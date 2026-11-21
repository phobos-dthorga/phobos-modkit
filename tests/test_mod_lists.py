"""Saved lists of active mods (1.75.0), on a synthetic RimWorld install with saves, a log and RimSort's history. Nothing reads a real
one."""
from datetime import datetime, timedelta, timezone
import io
import json
import os
from pathlib import Path
import tempfile
import time
import unittest

from phobos_modkit import mod_list as core
from phobos_modkit import mod_list_cli as cli
from phobos_modkit import mod_lists
from phobos_modkit.games.rimworld.mod_list import RimWorld, read_list_file, read_save_meta, render_list_file

from test_mod_list import FakeRimWorld

SAVE = """﻿<?xml version="1.0" encoding="utf-8"?>
<savegame>
\t<meta>
\t\t<gameVersion>1.7.5014 rev1195</gameVersion>
\t\t<modIds>
\t\t\t<li>ludeon.rimworld</li>
\t\t\t<li>ludeon.rimworld.royalty</li>
\t\t\t<li>example.hostel</li>
\t\t\t<li>example.gone</li>
\t\t</modIds>
\t\t<modSteamIds>
\t\t\t<li>0</li>
\t\t\t<li>1149640</li>
\t\t\t<li>0</li>
\t\t\t<li>0</li>
\t\t</modSteamIds>
\t\t<modNames>
\t\t\t<li>Core</li>
\t\t\t<li>Royalty</li>
\t\t\t<li>Hostel</li>
\t\t\t<li>Gone &amp; Forgotten</li>
\t\t</modNames>
\t</meta>
\t<game>""" + "x" * 2000 + """</game>
</savegame>
"""


class Lists(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.fake = FakeRimWorld(self.tmp.name, ["ludeon.rimworld", "example.market", "example.hostel"])
        self.environ = self.fake.environ(self.tmp.name)
        self.saves = Path(self.environ["RIMWORLD_SAVES_PATH"])
        self.saves.mkdir()
        (self.saves / "Colony.rws").write_text(SAVE, encoding="utf-8")
        history = Path(self.environ["PHOBOS_RIMSORT"]) / "modlists" / "history" / "Default"
        history.mkdir(parents=True)
        (history / "2026-11-20T01-00-00__abc.json").write_text(
            json.dumps({"version": "1.7", "activeMods": ["ludeon.rimworld", "example.hostel", "example.market"]}),
            encoding="utf-8")
        self.adapter = RimWorld(self.environ)
        self.installed = core.Installed(self.adapter, self.adapter.installed())

    def tearDown(self):
        self.tmp.cleanup()

    def active(self):
        return RimWorld(self.environ).lists()[0]

    def test_a_saves_header_is_read_with_names_and_no_workshop_number_for_the_expansions(self):
        version, ids, steam, names = read_save_meta(self.saves / "Colony.rws")
        self.assertEqual(version, "1.7.5014 rev1195")
        self.assertEqual(ids[2:], ["example.hostel", "example.gone"])
        self.assertEqual(names[3], "Gone & Forgotten")
        saved = self.adapter.save_lists()[0]
        self.assertEqual(saved.workshop, {})
        self.assertEqual(saved.names["example.gone"], "Gone & Forgotten")

    def test_every_source_is_offered(self):
        found = mod_lists.every_list(self.adapter, self.environ)
        self.assertEqual([s.ref for s in found["save"]], ["Colony.rws"])
        self.assertEqual(found["manager"][0].ref, "Default/2026-11-20T01-00-00__abc.json")
        self.assertTrue(found["manager"][0].label.startswith("RimSort, "))

    def test_compare_names_what_changes_and_leaves_out_mods_not_here(self):
        chosen = mod_lists.find_list(self.adapter, "save", "Colony.rws", self.environ)
        found = mod_lists.compare(self.adapter, self.active(), chosen, self.installed, None, self.environ)
        self.assertEqual([m["key"] for m in found["off"]], ["example.market"])
        self.assertEqual([m["name"] for m in found["missing"]], ["Royalty", "Gone & Forgotten"])
        self.assertIn("by its name", found["missing"][1]["why"])
        self.assertEqual(found["ids"], ["ludeon.rimworld", "example.hostel"])

    def test_loading_keeps_a_backup_and_undo_takes_it_back(self):
        chosen = mod_lists.find_list(self.adapter, "manager", "Default/2026-11-20T01-00-00__abc.json", self.environ)
        found, backup = mod_lists.load(self.adapter, self.active(), chosen, self.installed, lambda names: [], self.environ)
        self.assertTrue(backup.exists())
        self.assertEqual(self.active().ids, ["ludeon.rimworld", "example.hostel", "example.market"])
        self.assertEqual(found["moved"], 1)
        core.undo(self.adapter, self.active(), lambda names: [], self.environ)
        self.assertEqual(self.active().ids, ["ludeon.rimworld", "example.market", "example.hostel"])
        with self.assertRaises(core.FixError):
            mod_lists.load(self.adapter, self.active(), chosen, self.installed, lambda names: ["RimSort.exe"], self.environ)

    def test_saved_by_name_refuses_a_name_in_use_unless_replaced_and_can_be_taken_away(self):
        saved = mod_lists.save_named(self.adapter, self.active(), self.installed, "Before the war: v2", environ=self.environ)
        self.assertEqual(saved.ref, "Before the war- v2")
        self.assertEqual(saved.names["example.hostel"], "Hostel")
        with self.assertRaises(core.FixError):
            mod_lists.save_named(self.adapter, self.active(), self.installed, "Before the war: v2", environ=self.environ)
        mod_lists.save_named(self.adapter, self.active(), self.installed, "Before the war: v2", True, self.environ)
        self.assertEqual([s.label for s in mod_lists.named_lists("rimworld", self.environ)], ["Before the war: v2"])
        mod_lists.forget_named("rimworld", saved.ref, self.environ)
        self.assertEqual(mod_lists.named_lists("rimworld", self.environ), [])

    def test_the_games_own_list_file_goes_out_and_back_unchanged(self):
        chosen = mod_lists.find_list(self.adapter, "save", "Colony.rws", self.environ)
        target = Path(self.tmp.name) / "out.rml"
        target.write_bytes(render_list_file(chosen).encode("utf-8"))
        text = target.read_text(encoding="utf-8")
        self.assertIn("<savedModList>", text)
        self.assertIn("<li>Gone &amp; Forgotten</li>", text)
        again = read_list_file(target)
        self.assertEqual(again.ids, chosen.ids)
        self.assertEqual(again.names["example.gone"], "Gone & Forgotten")

    def test_an_exported_rimsort_list_and_nonsense_files(self):
        exported = Path(self.tmp.name) / "list.xml"
        exported.write_text("<ModsConfigData><version>1.7</version><activeMods><li>a.b</li></activeMods></ModsConfigData>",
                            encoding="utf-8")
        self.assertEqual(read_list_file(exported).ids, ["a.b"])
        nonsense = Path(self.tmp.name) / "nonsense.xml"
        nonsense.write_text("<html/>", encoding="utf-8")
        self.assertIsNone(read_list_file(nonsense))


class KeptAtStart(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.fake = FakeRimWorld(self.tmp.name, ["ludeon.rimworld", "example.hostel"])
        self.environ = self.fake.environ(self.tmp.name)
        self.logs = Path(self.environ["RIMWORLD_LOGS_PATH"])
        self.logs.mkdir()
        self.config = self.fake.config / "ModsConfig.xml"

    def tearDown(self):
        self.tmp.cleanup()

    def log(self, started, ended):
        log = self.logs / "Player.log"
        log.write_text(f"=== log ===\nStarted:   {started.astimezone().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]} "
                       f"{started.astimezone().strftime('%z')[:3]}:{started.astimezone().strftime('%z')[3:]}\n", encoding="utf-8")
        os.utime(log, (ended.timestamp(), ended.timestamp()))

    def keep(self):
        adapter = RimWorld(self.environ)
        adapter.running = lambda names: []      # the owner's own game may be running while the tests run
        return mod_lists.keep_at_start(adapter, adapter.lists()[0], core.Installed(adapter, adapter.installed()), self.environ)

    def test_a_start_with_a_new_list_is_kept_once(self):
        now = datetime.now(timezone.utc)
        os.utime(self.config, ((now - timedelta(minutes=50)).timestamp(),) * 2)
        self.log(now - timedelta(minutes=40), now - timedelta(minutes=5))
        kept = self.keep()
        self.assertIsNotNone(kept)
        self.assertTrue(kept.label.startswith("Game start, "))
        self.assertIsNone(self.keep())
        self.assertEqual(len(mod_lists.kept_lists("rimworld", self.environ)), 1)

    def test_a_list_changed_after_the_game_closed_is_not_what_it_started_with(self):
        now = datetime.now(timezone.utc)
        self.log(now - timedelta(minutes=40), now - timedelta(minutes=30))
        os.utime(self.config, (time.time(), time.time()))
        self.assertIsNone(self.keep())

    def test_without_a_log_nothing_is_kept(self):
        self.assertIsNone(self.keep())


class Command(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.fake = FakeRimWorld(self.tmp.name, ["ludeon.rimworld", "example.market", "example.hostel"])
        self.environ = self.fake.environ(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def run_cli(self, *argv):
        out = io.StringIO()
        code = cli.main(list(argv) + ["--json"], self.environ, out, running=lambda names: [])
        return code, json.loads(out.getvalue())["data"]

    def test_save_list_compare_load_and_export_from_the_command(self):
        code, data = self.run_cli("save", "--name", "RimWorld", "--list", "active", "--as", "Quiet", "--apply")
        self.assertTrue(data["applied"])
        code, data = self.run_cli("lists", "--name", "RimWorld")
        self.assertEqual([s["ref"] for s in data["sources"]["saved"]], ["Quiet"])
        self.run_cli("fix", "--name", "RimWorld", "--list", "active", "--remove", "example.market", "--apply")
        code, data = self.run_cli("compare", "--name", "RimWorld", "--list", "active", "--from", "saved:Quiet")
        self.assertEqual([m["key"] for m in data["on"]], ["example.market"])
        code, data = self.run_cli("load", "--name", "RimWorld", "--list", "active", "--from", "saved:Quiet", "--apply")
        self.assertTrue(data["applied"])
        self.assertEqual(RimWorld(self.environ).lists()[0].ids, ["ludeon.rimworld", "example.market", "example.hostel"])
        target = Path(self.tmp.name) / "shared"
        code, data = self.run_cli("export", "--name", "RimWorld", "--from", "saved:Quiet", "--to", str(target), "--apply")
        self.assertTrue(Path(data["file"]).name.endswith(".rml"))
        self.assertEqual(read_list_file(target.with_name("shared.rml")).ids, ["ludeon.rimworld", "example.market", "example.hostel"])
        code, data = self.run_cli("forget", "--name", "RimWorld", "--saved", "Quiet", "--apply")
        self.assertTrue(data["applied"])

    def test_a_list_named_wrongly_is_refused_in_words(self):
        out = io.StringIO()
        code = cli.main(["compare", "--name", "RimWorld", "--list", "active", "--from", "nowhere", "--json"], self.environ, out)
        self.assertEqual(code, cli.EXIT_REFUSED)
        self.assertFalse(json.loads(out.getvalue())["data"]["ok"])


if __name__ == "__main__":
    unittest.main()
