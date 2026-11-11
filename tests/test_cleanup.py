"""cleanup on made-up folders in a temporary directory. Nothing here touches the real cache, build folder or processes."""
import io
import json
import os
from pathlib import Path
import sqlite3
import stat
import tempfile
import time
import unittest

import support  # noqa: F401  (the package on the import path)
from phobos_modkit import cleanup
from phobos_modkit.cleanup_cli import EXIT_OK, EXIT_USAGE, build_report
from phobos_modkit.report import render_markdown

NOW = 1_800_000_000.0
DAY = cleanup.DAY


def touch(path, age_days=0.0, data=b"x"):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    os.utime(path, (NOW - age_days * DAY, NOW - age_days * DAY))
    return path


def folder(path, age_days=0.0):
    path = Path(path)
    path.mkdir(parents=True, exist_ok=True)
    touch(path / "inside.bin", age_days)
    os.utime(path, (NOW - age_days * DAY, NOW - age_days * DAY))
    return path


def write_rules(root, rules):
    config = Path(root) / "config" / "cleanup.json"
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text(json.dumps({"schemaVersion": 1, "rules": rules}), encoding="utf-8")
    return config


class Rules(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def items(self, rule, environ=None):
        items, notes = cleanup.rule_items(rule, self.root, environ or {}, NOW)
        return sorted(i.path.name for i in items), notes

    def test_keeps_the_newest_of_each_live_group_and_none_of_a_group_gone(self):
        backups = self.root / "backups"
        for name in ("ModA-20261107-130954", "ModA-20261108-145928", "ModA-20261101-090000", "Merged-20261107-131000",
                     "notes", "My-Mod-20261108-100000"):
            folder(backups / name)
        for live in ("ModA", "My-Mod"):
            touch(self.root / "mods" / live / "About" / "About.xml")
        rule = {"name": "Backups", "folder": "backups", "match": ["*-*-*"], "kinds": "folders", "order": "name",
                "group": r"^(?P<group>.+)-\d{8}-\d{6}$", "keepNewest": 1, "liveGroups": "mods/{group}/About/About.xml",
                "why": "old installs"}
        names, _ = self.items(rule)
        self.assertEqual(["Merged-20261107-131000", "ModA-20261101-090000", "ModA-20261107-130954"], names)
        names, _ = self.items({**rule, "keepNewest": 2})
        self.assertEqual(["Merged-20261107-131000", "ModA-20261101-090000"], names)

    def test_patterns_kinds_and_minimum_age(self):
        temp = self.root / "temp"
        folder(temp / "archive-test-abc")
        touch(temp / "archive-test-file.txt")
        folder(temp / "someone-elses")
        touch(temp / "Build_1.log", age_days=3)
        touch(temp / "Build_2.log", age_days=0.1)
        environ = {"SCRATCH": str(temp)}
        names, _ = self.items({"name": "Repos", "folder": "{env:SCRATCH}", "match": ["archive-test-*"], "kinds": "folders",
                               "why": "test repositories"}, environ)
        self.assertEqual(["archive-test-abc"], names)
        names, _ = self.items({"name": "Logs", "folder": "{env:SCRATCH}", "match": ["Build_*.log"], "olderThanDays": 1,
                               "why": "build logs"}, environ)
        self.assertEqual(["Build_1.log"], names)

    def test_keep_newest_by_time(self):
        dumps = self.root / "dumps"
        for age, name in ((5, "Game.1.dmp"), (1, "Game.2.dmp"), (9, "Game.3.dmp"), (9, "Other.dmp")):
            touch(dumps / name, age)
        names, _ = self.items({"name": "Dumps", "folder": "dumps", "match": ["Game.*.dmp"], "keepNewest": 1, "why": "old dumps"})
        self.assertEqual(["Game.1.dmp", "Game.3.dmp"], names)

    def test_an_unset_variable_skips_the_rule(self):
        names, notes = self.items({"name": "X", "folder": "{env:NOPE}/x", "match": ["a*"], "why": "w"})
        self.assertEqual([], names)
        self.assertIn("unset", notes[0])

    def test_bad_rules_are_refused(self):
        for rule in ({"name": "All", "folder": "x", "match": ["*"], "why": "w"},
                     {"name": "No why", "folder": "x", "match": ["a*"]},
                     {"name": "Group", "folder": "x", "match": ["a*"], "why": "w", "group": "^(.+)$"}):
            write_rules(self.root, [rule])
            with self.assertRaises(cleanup.CleanupError):
                cleanup.load_rules(self.root)

    def test_no_config_means_no_rules(self):
        self.assertEqual([], cleanup.load_rules(self.root))


class Cache(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.cache = Path(self.temp.name) / "cache"

    def tearDown(self):
        self.temp.cleanup()

    def test_age_stale_frozen_and_kept(self):
        touch(self.cache / "tool-a" / "old.sqlite", age_days=20)
        touch(self.cache / "tool-a" / "new.sqlite", age_days=1)
        touch(self.cache / "tool-a" / "Save.frozen.rws", age_days=0.5)
        touch(self.cache / "tool-b" / "gone.sqlite", age_days=1)
        touch(self.cache / "fetched" / "pages.sqlite", age_days=90)
        policies = {"tool-b": {"folder": "tool-b", "stale": lambda path, environ, settings: "its source has gone"},
                    "fetched": {"folder": "fetched", "keep": "slow to fetch"}}
        items, notes = cleanup.cache_items(self.cache, policies, 14, NOW)
        found = {i.path.name: i.why for i in items}
        self.assertEqual({"old.sqlite", "Save.frozen.rws", "gone.sqlite"}, set(found))
        self.assertEqual("its source has gone", found["gone.sqlite"])
        self.assertIn("unchanged for 20 days", found["old.sqlite"])
        self.assertEqual(["Kept the fetched cache: slow to fetch."], notes)

    def test_a_save_index_is_stale_once_its_save_changes(self):
        from phobos_modkit.games.rimworld import save as saves
        saves_folder = Path(self.temp.name) / "Saves"
        save = touch(saves_folder / "Colony.rws", data=b"<savegame/>")
        index = self.cache / "rimworld-saves" / "Colony.sqlite"
        index.parent.mkdir(parents=True)
        with sqlite3.connect(index) as conn:
            from phobos_modkit import cache as derived
            derived.write_meta(conn, {**saves.provenance(save), "source": "Colony.rws"})
        conn.close()
        environ = {"RIMWORLD_SAVES_PATH": str(saves_folder)}
        self.assertIsNone(saves.stale_index(index, environ))
        touch(save, data=b"<savegame>longer</savegame>")
        self.assertIn("saved again", saves.stale_index(index, environ))
        save.unlink()
        self.assertIn("no longer in the Saves folder", saves.stale_index(index, environ))

    def test_every_declared_policy_names_a_folder(self):
        policies = cleanup.cache_policies()
        self.assertIn("rimworld-saves", policies)
        self.assertTrue(policies["steam-workshop"]["keep"])


class Build(unittest.TestCase):
    def test_only_development_profiles_and_never_under_a_running_build(self):
        with tempfile.TemporaryDirectory() as temp:
            folder(Path(temp) / "debug")
            folder(Path(temp) / "release")
            items, notes = cleanup.build_items(temp, [])
            self.assertEqual(["debug"], [i.path.name for i in items])
            items, notes = cleanup.build_items(temp, ["cargo"])
            self.assertEqual([], items)
            self.assertIn("cargo is running", notes[0])

    def test_reads_builders_from_a_process_listing(self):
        listing = '"cargo.exe","123","Console","1","10 K"\n"Code.exe","4","Console","1","9 K"\n"rustc.exe","5","x","1","1 K"\n'
        self.assertEqual(["cargo", "rustc"], cleanup.running_builders(listing))
        self.assertEqual([], cleanup.running_builders('"python.exe","1"\n'))


class Apply(unittest.TestCase):
    def test_deletes_read_only_trees_and_reports(self):
        with tempfile.TemporaryDirectory() as temp:
            objects = Path(temp) / "repo" / ".git" / "objects" / "ab"
            objects.mkdir(parents=True)
            locked = objects / "cdef"
            locked.write_bytes(b"\0")
            os.chmod(locked, stat.S_IREAD)
            found = cleanup.Found(items=[cleanup.Item("Repos", Path(temp) / "repo", 1, "test repositories")], daemons=[7])
            deleted, failed, stopped = cleanup.apply(found, stop=lambda pids: len(pids))
            self.assertFalse((Path(temp) / "repo").exists())
            self.assertEqual((1, [], 1), (len(deleted), failed, stopped))
            text = render_markdown(build_report(found, (deleted, failed, stopped)))
            self.assertIn("deleted 1", text)
            self.assertIn("stopped: 1 of 1", text)

    def test_preview_says_so(self):
        found = cleanup.Found(items=[cleanup.Item("Logs", Path("a.log"), 2048, "build logs")])
        self.assertIn("Preview only", render_markdown(build_report(found)))


class Command(unittest.TestCase):
    def test_a_bad_config_is_a_usage_error(self):
        from phobos_modkit.cleanup_cli import main
        with tempfile.TemporaryDirectory() as temp:
            config = Path(temp) / "rules.json"
            config.write_text('{"schemaVersion": 99}', encoding="utf-8")
            self.assertEqual(EXIT_USAGE, main(["--root", temp, "--config", str(config)], environ={}, out=io.StringIO()))

    def test_json_lists_items(self):
        from phobos_modkit import cleanup_cli
        found = cleanup.Found(items=[cleanup.Item("Logs", Path("a.log"), 10, "build logs")])
        original = cleanup_cli.survey
        cleanup_cli.survey = lambda *a, **k: found
        try:
            out = io.StringIO()
            self.assertEqual(EXIT_OK, cleanup_cli.main(["--json"], environ={}, out=out))
        finally:
            cleanup_cli.survey = original
        data = json.loads(out.getvalue())
        self.assertEqual("a.log", data["data"]["items"][0]["path"])
        self.assertFalse(data["data"]["applied"])


if __name__ == "__main__":
    unittest.main()
