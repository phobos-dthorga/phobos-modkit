"""installs: changelog comparison, the status survey, and backing up, going back and installing. Every file here is written by hand,
in temporary folders: a stand-in repository, a stand-in game folder and its backups. Nothing reads a real install."""
from datetime import datetime
import io
import json
import shutil
from pathlib import Path
import tempfile
import unittest

import support  # noqa: F401  (puts the package on the path)
from phobos_modkit import installs, installs_cli

OLD_LOG = """# Thing changelog

Free text before the log.

## [Unreleased]

- **Lamps glow.** A lamp now glows.

## [0.2.0] - 2026-11-02 - Draft

Second release

### Added

- **Boats float.** They float
  on water, mostly.

### Save compatibility

- Safe with a running save.

## [0.1.0] - 2026-11-01 - Draft

### Fixed

- **Wheels turn.** As they should.

## Old Thing history

- **Something merged in.** Never read as this mod's.
"""

NEW_LOG = """# Thing changelog

## [Unreleased]

## [0.3.0] - 2026-11-03 - Draft

Third release

### Added

- **Lamps glow.** A lamp now glows.
- **Sails.** Boats have sails.

### Save compatibility

- Not safe to remove: saves hold the sails.

## [0.2.0] - 2026-11-02 - Draft

Second release

### Added

- **Boats float.** They float on water, mostly.

### Save compatibility

- Safe with a running save.

## [0.1.0] - 2026-11-01 - Draft

### Fixed

- **Wheels turn.** As they should, now on ice too.
"""


def about(version, name="Thing"):
    return (f"<?xml version=\"1.0\" encoding=\"utf-8\"?>\n<ModMetaData><name>{name}</name><packageId>Test.Thing</packageId>"
            f"<modVersion>{version}</modVersion></ModMetaData>\n")


def write_mod(folder, version, log):
    folder = Path(folder)
    (folder / "About").mkdir(parents=True, exist_ok=True)
    (folder / "About" / "About.xml").write_text(about(version), encoding="utf-8")
    (folder / "CHANGELOG.md").write_text(log, encoding="utf-8")
    return folder


class ChangelogTests(unittest.TestCase):
    def test_entries_sections_and_summaries(self):
        log = installs.parse_changelog(OLD_LOG)
        self.assertEqual(log.title, "Thing changelog")
        self.assertEqual([(e.version, e.section, e.lead) for e in log.entries], [
            ("Unreleased", "", "Lamps glow."), ("0.2.0", "Added", "Boats float."), ("0.2.0", "Save compatibility", "Safe with a running save."),
            ("0.1.0", "Fixed", "Wheels turn.")])
        self.assertEqual(log.summaries, {"0.2.0": "Second release"})
        self.assertEqual(log.entries[1].text, "**Boats float.** They float on water, mostly.")

    def test_history_closes_the_log(self):
        log = installs.parse_changelog(OLD_LOG)
        self.assertNotIn("Something merged in.", [e.lead for e in log.entries])

    def test_an_entry_that_gained_a_version_is_neither_gained_nor_lost(self):
        delta = installs.compare(installs.parse_changelog(OLD_LOG), installs.parse_changelog(NEW_LOG))
        self.assertEqual([e.lead for e in delta.gain], ["Sails.", "Not safe to remove: saves hold the sails."])
        self.assertEqual(delta.lose, [])
        self.assertEqual([(a.lead, b.version) for a, b in delta.reworded], [("Wheels turn.", "0.1.0")])
        self.assertEqual([e.lead for e in delta.save_notes], ["Not safe to remove: saves hold the sails."])

    def test_going_back_loses_what_going_forward_gains(self):
        delta = installs.compare(installs.parse_changelog(NEW_LOG), installs.parse_changelog(OLD_LOG))
        self.assertEqual([e.lead for e in delta.lose], ["Sails.", "Not safe to remove: saves hold the sails."])
        self.assertEqual(delta.gain, [])

    def test_a_version_number_used_twice_is_set_aside_not_lost(self):
        # The owner's screen note of 20 Nov 2026: one session's 0.3.0 was installed, another session then took 0.3.0 for other work.
        installed = installs.parse_changelog(NEW_LOG)
        other = installs.parse_changelog(NEW_LOG.replace("- **Lamps glow.** A lamp now glows.\n- **Sails.** Boats have sails.",
                                                         "- **Oars.** Boats have oars.").replace(
                                                             "Not safe to remove: saves hold the sails.", "Safe to remove."))
        delta = installs.set_aside(installs.compare(installed, other), installed, other)
        self.assertEqual(delta.lose, [])
        self.assertEqual([e.lead for e in delta.unlisted], ["Lamps glow.", "Sails.", "Not safe to remove: saves hold the sails."])
        self.assertEqual(delta.unlisted_why, {"0.3.0": installs.REUSED})
        self.assertEqual([e.lead for e in delta.gain], ["Oars.", "Safe to remove."])

    def test_an_entry_dropped_from_a_version_both_share_is_still_lost(self):
        installed = installs.parse_changelog(NEW_LOG)
        other = installs.parse_changelog(NEW_LOG.replace("- **Sails.** Boats have sails.\n", ""))
        delta = installs.set_aside(installs.compare(installed, other), installed, other, {"uncommittedCount": 4})
        self.assertEqual([e.lead for e in delta.lose], ["Sails."])
        self.assertEqual(delta.unlisted, [])

    def test_uncommitted_work_the_repository_no_longer_lists_is_set_aside(self):
        installed, other = installs.parse_changelog(NEW_LOG), installs.parse_changelog(OLD_LOG)
        delta = installs.set_aside(installs.compare(installed, other), installed, other, {"uncommittedCount": 4})
        self.assertEqual(delta.lose, [])
        self.assertEqual([e.lead for e in delta.unlisted], ["Sails.", "Not safe to remove: saves hold the sails."])
        self.assertEqual(delta.unlisted_why, {"0.3.0": installs.UNCOMMITTED})

    def test_a_committed_install_ahead_of_the_repository_still_loses(self):
        installed, other = installs.parse_changelog(NEW_LOG), installs.parse_changelog(OLD_LOG)
        for record in (None, {"uncommittedCount": 0}):
            delta = installs.set_aside(installs.compare(installed, other), installed, other, record)
            self.assertEqual([e.lead for e in delta.lose], ["Sails.", "Not safe to remove: saves hold the sails."])
            self.assertEqual(delta.unlisted, [])

    def test_no_changelog_knows_nothing(self):
        self.assertEqual(installs.compare(None, installs.parse_changelog(NEW_LOG)).gain, [])

    def test_direction(self):
        self.assertEqual(installs.direction("0.9.0", "0.10.0"), "newer")
        self.assertEqual(installs.direction("0.10.0", "0.9.0"), "older")
        self.assertEqual(installs.direction("1.0", "1.0"), "same")
        self.assertEqual(installs.direction("", "1.0"), "unknown")


class Fixture:
    """A stand-in repository with one mod, a game folder with it installed, and one backup."""

    def __init__(self, tmp):
        self.tmp = Path(tmp)
        self.repo, self.game = self.tmp / "repo", self.tmp / "Game"
        write_mod(self.repo / "mods" / "Thing", "0.3.0", NEW_LOG)
        (self.repo / "config").mkdir(parents=True)
        (self.repo / ".local").mkdir()
        (self.repo / ".local" / "settings.json").write_text(json.dumps({"rimworldPath": str(self.game)}), encoding="utf-8")
        (self.repo / "config" / "installs.json").write_text(json.dumps({
            "schemaVersion": 1, "game": "rimworld", "mods": "mods", "backups": ".local/backups",
            "settings": ".local/settings.json", "install": ["{python}", "scripts/deploy.py", "--apply", "{mod}"]}), encoding="utf-8")
        write_mod(self.game / "Mods" / "Thing", "0.2.0", OLD_LOG)
        installs.write_record(self.game / "Mods" / "Thing", {"format": 1, "mod": "Thing", "version": "0.2.0", "commit": None})
        write_mod(self.repo / ".local" / "backups" / "Thing-20261101-120000", "0.1.0", "# Thing changelog\n\n## [Unreleased]\n\n"
                  "## [0.1.0] - 2026-11-01 - Draft\n\n### Fixed\n\n- **Wheels turn.** As they should.\n")
        self.where = installs.place(self.repo, environ=support.isolated_environ(tmp))

    def run(self, *argv, running=lambda names: [], run=None):
        out = io.StringIO()
        code = installs_cli.main([*argv, "--root", str(self.repo), "--json", "--no-redact"], environ=support.isolated_environ(self.tmp),
                                 out=out,
                                 now=datetime(2026, 11, 18, 21, 0, 0), running=running, run=run)
        return code, json.loads(out.getvalue())


class StatusTests(unittest.TestCase):
    def test_status_compares_the_install_with_the_repository_and_each_backup(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = Fixture(tmp)
            code, answer = f.run("status")
            self.assertEqual(code, 0)
            mod = answer["data"]["mods"][0]
            self.assertEqual((mod["state"], mod["installed"]["version"], mod["repository"]["version"]), ("behind", "0.2.0", "0.3.0"))
            self.assertEqual(mod["installed"]["record"]["version"], "0.2.0")
            # 1.82.0: each copy names its folder, so a program can show a changed picture from both copies.
            self.assertTrue(all(Path(c["folder"]).is_dir() for c in [mod["installed"], mod["repository"], *mod["backups"]]))
            self.assertEqual(mod["changelog"], "mods/Thing/CHANGELOG.md")
            self.assertEqual([e["lead"] for e in mod["update"]["gain"]], ["Sails.", "Not safe to remove: saves hold the sails."])
            self.assertEqual(mod["update"]["summaries"], {"0.3.0": "Third release"})
            backup = mod["backups"][0]
            self.assertEqual((backup["backup"], backup["version"], backup["direction"]), ("Thing-20261101-120000", "0.1.0", "older"))
            self.assertEqual(backup["taken"], "2026-11-01T12:00:00")
            self.assertIn("Boats float.", [e["lead"] for e in backup["delta"]["lose"]])
            self.assertEqual(answer["data"]["gameRunning"], [])

    def test_an_install_of_uncommitted_work_the_repository_no_longer_lists_is_not_called_a_loss(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = Fixture(tmp)
            write_mod(f.game / "Mods" / "Thing", "0.3.0", NEW_LOG)
            installs.write_record(f.game / "Mods" / "Thing", {"format": 1, "mod": "Thing", "version": "0.3.0", "commit": None,
                                                              "uncommittedCount": 2})
            write_mod(f.repo / "mods" / "Thing", "0.2.0", OLD_LOG)
            code, answer = f.run("status")
            mod = answer["data"]["mods"][0]
            self.assertEqual((code, mod["state"]), (0, "unlisted"))
            self.assertEqual(mod["update"]["lose"], [])
            self.assertEqual([e["lead"] for e in mod["update"]["unlisted"]], ["Sails.", "Not safe to remove: saves hold the sails."])
            self.assertEqual(mod["update"]["unlistedWhy"], {"0.3.0": "uncommitted"})
            self.assertEqual(mod["update"]["summaries"], {"0.3.0": "Third release"})
            # Going back to a backup is what its changelog says: never set aside.
            self.assertIn("Sails.", [e["lead"] for e in mod["backups"][0]["delta"]["lose"]])

    def test_an_unknown_mod_is_refused_in_the_envelope(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, answer = Fixture(tmp).run("status", "--mod", "Other")
            self.assertEqual((code, answer["data"]["ok"]), (1, False))
            self.assertIn("not one of this repository's mods", answer["data"]["refusal"])

    def test_a_repository_without_the_config_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(installs.InstallsError):
                installs.place(Path(tmp), environ={})


class MovingTests(unittest.TestCase):
    def test_backup_copies_the_install(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = Fixture(tmp)
            code, answer = f.run("backup", "--mod", "Thing")
            self.assertEqual((code, answer["data"]["backup"]), (0, "Thing-20261118-210000"))
            # 1.96.0: a backup is one zip, read back like a folder.
            self.assertTrue((f.repo / ".local" / "backups" / "Thing-20261118-210000.zip").is_file())
            copied = installs.read_backup(f.where, "Thing-20261118-210000")
            self.assertEqual((copied.record["version"], copied.version), ("0.2.0", "0.2.0"))
            self.assertEqual(installs.content_digest(copied.archive), installs.content_digest(f.game / "Mods" / "Thing"))
            self.assertTrue((f.game / "Mods" / "Thing" / "CHANGELOG.md").is_file())

    def test_restore_swaps_and_keeps_both(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = Fixture(tmp)
            code, answer = f.run("restore", "--mod", "Thing", "--backup", "Thing-20261101-120000")
            self.assertEqual((code, answer["data"]["replacedBy"]), (0, "Thing-20261118-210000"))
            self.assertEqual(f.where.game.identity(f.game / "Mods" / "Thing")[1], "0.1.0")
            backups = f.repo / ".local" / "backups"
            # Both kept, packed as zips by the tidying that follows a go-back (1.96.0).
            self.assertEqual(sorted(p.name for p in backups.iterdir()), ["Thing-20261101-120000.zip", "Thing-20261118-210000.zip"])
            self.assertEqual(installs.read_backup(f.where, "Thing-20261118-210000").version, "0.2.0")
            self.assertEqual(sorted(p["backup"] for p in answer["data"]["packed"]), ["Thing-20261101-120000", "Thing-20261118-210000"])
            self.assertEqual(sorted(p.name for p in f.game.iterdir()), ["Mods"])

    def test_restore_removes_the_repeated_backup_it_makes_and_keeps_the_older_twin(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = Fixture(tmp)
            backups = f.repo / ".local" / "backups"
            shutil.copytree(f.game / "Mods" / "Thing", backups / "Thing-20261110-120000")
            code, answer = f.run("restore", "--mod", "Thing", "--backup", "Thing-20261101-120000")
            self.assertEqual(code, 0)
            self.assertEqual([(r["backup"], r["sameAs"], r["kind"]) for r in answer["data"]["removedRepeats"]],
                             [("Thing-20261118-210000", "Thing-20261110-120000", "identical")])
            self.assertIsNone(answer["data"]["tidyProblem"])
            self.assertEqual(sorted(p.name for p in backups.iterdir()), ["Thing-20261101-120000.zip", "Thing-20261110-120000.zip"])
            self.assertEqual(f.where.game.identity(f.game / "Mods" / "Thing")[1], "0.1.0")

    def test_tidy_reports_a_problem_instead_of_raising(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = Fixture(tmp)
            removed, problem = installs.tidy(f.where, ["NoSuchMod"])
            self.assertEqual(removed, [])
            self.assertIn("NoSuchMod", problem)
            self.assertIn("can do it later", installs.tidy_lines(removed, problem)[0])

    def test_restore_refuses_while_the_game_runs_and_changes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = Fixture(tmp)
            code, answer = f.run("restore", "--mod", "Thing", "--backup", "Thing-20261101-120000", running=lambda names: ["rimworld.exe"])
            self.assertEqual((code, answer["data"]["ok"]), (1, False))
            self.assertIn("running", answer["data"]["refusal"])
            self.assertEqual(f.where.game.identity(f.game / "Mods" / "Thing")[1], "0.2.0")

    def test_restore_refuses_a_name_that_is_not_a_backup(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = Fixture(tmp)
            for name in ("..", "Thing-20261101-120000/../..", "Other-20261101-120000"):
                code, answer = f.run("restore", "--mod", "Thing", "--backup", name)
                self.assertEqual(code, 1, name)
            self.assertEqual(f.where.game.identity(f.game / "Mods" / "Thing")[1], "0.2.0")

    def test_install_runs_the_repository_command(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = Fixture(tmp)
            seen = {}

            def run(command, **kwargs):
                seen["command"], seen["cwd"] = command, kwargs["cwd"]

                class Result:
                    returncode, stdout, stderr = 0, "Thing: 4 files\n  copied 4 files\n", ""
                return Result()

            code, answer = f.run("install", "--mod", "Thing", run=run)
            self.assertEqual((code, answer["data"]["ok"]), (0, True))
            self.assertEqual(seen["command"][1:], ["scripts/deploy.py", "--apply", "Thing"])
            self.assertEqual(Path(seen["cwd"]), f.repo.resolve())
            self.assertEqual(answer["data"]["output"][-1], "  copied 4 files")

    def test_install_refuses_while_the_game_runs(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, answer = Fixture(tmp).run("install", "--mod", "Thing", running=lambda names: ["rimworld.exe"],
                                            run=lambda *a, **k: self.fail("ran while the game was running"))
            self.assertEqual(code, 1)

    def test_the_game_is_found_in_a_process_listing(self):
        listing = '"RimWorld.exe","1234","Console","1","2,000,000 K"\n"explorer.exe","1","Console","1","1 K"\n'
        self.assertEqual(installs.game_running(("RimWorld.exe",), listing), ["rimworld.exe"])


if __name__ == "__main__":
    unittest.main()


class RepeatsAndSettingsTests(unittest.TestCase):
    def test_dedupe_removes_a_backup_repeating_the_one_before_and_keeps_the_oldest(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = Fixture(tmp)
            backups = f.repo / ".local" / "backups"
            shutil.copytree(backups / "Thing-20261101-120000", backups / "Thing-20261102-120000")
            code, answer = f.run("status")
            thing = answer["data"]["mods"][0]
            self.assertEqual([(b["backup"], b["sameAs"], b["sameKind"]) for b in thing["backups"]],
                             [("Thing-20261102-120000", "Thing-20261101-120000", "identical"),
                              ("Thing-20261101-120000", None, None)])
            self.assertEqual(answer["data"]["space"]["duplicates"], 1)
            code, answer = f.run("dedupe")
            self.assertEqual((code, [r["backup"] for r in answer["data"]["removed"]]), (0, ["Thing-20261102-120000"]))
            self.assertEqual(sorted(p.name for p in backups.iterdir()), ["Thing-20261101-120000"])
            code, answer = f.run("dedupe")
            self.assertEqual(answer["data"]["removed"], [])

    def test_settings_reads_the_repositorys_own_history_newest_first(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = Fixture(tmp)
            config = json.loads((f.repo / "config" / "installs.json").read_text(encoding="utf-8"))
            script = f.repo / "history.py"
            script.write_text("import json\nprint(json.dumps([\n"
                              " {'time': '2026-11-01T10:00:00+11:00', 'commit': 'a1', 'subject': 's', 'mod': 'Thing', 'key': 'K1',"
                              " 'label': 'One', 'what': 'added', 'before': None, 'after': 'True'},\n"
                              " {'time': '2026-11-02T10:00:00+11:00', 'commit': 'b2', 'subject': 's', 'mod': 'Thing', 'key': 'K2',"
                              " 'label': None, 'what': 'removed', 'before': '3', 'after': None}]))\n", encoding="utf-8")
            config["settingsHistory"] = ["{python}", "history.py"]
            (f.repo / "config" / "installs.json").write_text(json.dumps(config), encoding="utf-8")
            code, answer = f.run("settings")
            self.assertEqual(code, 0)
            self.assertEqual([(c["key"], c["product"]) for c in answer["data"]["settings"]], [("K2", "Thing"), ("K1", "Thing")])
            from phobos_modkit import history
            facts = history.settings_facts(f.repo)
            self.assertEqual([(x["kind"], x["product"], x["time"]) for x in facts],
                             [("setting-added", "Thing", "2026-10-31T23:00:00+00:00"),
                              ("setting-removed", "Thing", "2026-11-01T23:00:00+00:00")])

    def test_a_repository_without_a_settings_history_says_so(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = Fixture(tmp)
            code, answer = f.run("settings")
            self.assertEqual((code, answer["data"]["ok"]), (1, False))
            self.assertIn("settings' history", answer["data"]["refusal"])
