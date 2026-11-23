"""Games as data for Workshop publishing (1.97.0): every game file loads, each metadata format reads, the game's ID file is
kept in step, and a catalogue can describe a game nobody has written a file for. Made-up mods only; nothing reaches Steam."""
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

import support  # noqa: F401
from phobos_modkit.games import publish_adapters
from phobos_modkit.steam.publish import notes, stage
from phobos_modkit.steam.publish.game_data import DataAdapter, find, keyvalue_lines
from phobos_modkit.steam.publish.project import Project, PublishError

CHANGELOG = "# Changelog\n\n## [Unreleased]\n\n## [1.0.0] - 2026-11-23 - Draft\n\n- First.\n"
PAGE = "[h1]{title}[/h1]\n[b]Version:[/b] 1.0.0\n[b]Publication status:[/b] Not published yet\n\nWhat it does.\n"


def git(root, *args):
    subprocess.run(["git", "-c", "core.fsmonitor=false", *args], cwd=root, check=True, capture_output=True)


class GameFiles(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, relative, text):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def test_every_game_file_loads(self):
        adapters = publish_adapters()
        self.assertIn("294100", adapters)
        self.assertIn("1022980", adapters)
        for app, adapter in adapters.items():
            self.assertEqual(adapter.app_id, app)
            self.assertTrue(adapter.spec.get("facts"), f"{adapter.name} states its format facts")

    def test_xml_any_letter_case_and_bare_ampersands(self):
        self.write("Mod/about/ABOUT.xml", "<ModMetaData><Name>Salt & Pepper</Name><modversion>1.2.3</modversion>"
                                         "<supportedVersions><li>1.6</li><li>1.7</li></supportedVersions></ModMetaData>")
        info = publish_adapters()["294100"].read(self.root / "Mod")
        self.assertEqual((info.title, info.version, info.tags), ("Salt & Pepper", "1.2.3", ("Mod", "1.6", "1.7")))

    def test_keyvalue_metadata_and_tags_from_the_catalogue(self):
        adapter = DataAdapter({"appId": "100", "metadata": {"file": "mod.info", "format": "keyvalue", "title": "name",
                                                              "version": "modversion"}, "tags": {"fixed": ["Build 1"]}})
        self.write("Mod/mod.info", "name=Example\nid=Example\nmodversion=2.0.1\n")
        info = adapter.read(self.root / "Mod", {"tags": ["Misc", "Build 1"]})
        self.assertEqual((info.title, info.version, info.tags), ("Example", "2.0.1", ("Build 1", "Misc")))
        self.assertEqual(keyvalue_lines("a=1\n\nb = two\nnoise\na=3"), [("a", "1"), ("b", "two"), ("a", "3")])

    def test_unknown_keys_and_formats_refused(self):
        with self.assertRaisesRegex(PublishError, "unknown keys"):
            DataAdapter({"appId": "100", "colour": "red"})
        with self.assertRaisesRegex(PublishError, "metadata format"):
            DataAdapter({"appId": "100", "metadata": {"file": "x", "format": "yaml"}})
        with self.assertRaisesRegex(PublishError, "appId"):
            DataAdapter({"appId": "0"})

    def test_find_matches_any_letter_case(self):
        self.write("A/About/About.xml", "<x/>")
        self.assertEqual(find(self.root, "a/ABOUT/about.XML"), self.root / "A" / "About" / "About.xml")

    def catalogue_project(self, game, mods, content=None):
        git(self.root, "init", "-q")
        git(self.root, "config", "core.fsmonitor", "false")   # the code under test runs plain git
        for mod, files in mods.items():
            for name, text in files.items():
                self.write(f"mods/{mod}/{name}", text)
            self.write(f"mods/{mod}/CHANGELOG.md", CHANGELOG)
        config = {"appId": game.get("appId", "100"), "game": {k: v for k, v in game.items() if k != "appId"},
                  "mods": {m: {"itemId": None, "requires": [], "hold": None, **(content or {}).get(m, {})} for m in mods}}
        self.write("config/workshop-publishing.json", json.dumps(config))
        return Project.load(self.root, {}, cache_folder=self.root / "cache")

    def test_a_catalogue_describes_its_own_game(self):
        project = self.catalogue_project({"metadata": {"format": "catalogue"}, "preview": "cover.png"},
                                         {"Plain": {"cover.png": "x", "data.txt": "y"}},
                                         {"Plain": {"title": "Plain Thing", "version": "1.0.0", "tags": ["Tools"]}})
        self.write("workshop/Plain/page.bbcode", PAGE.format(title="Plain Thing"))
        info = project.info("Plain")
        self.assertEqual((info.title, info.version, info.tags), ("Plain Thing", "1.0.0", ("Tools",)))
        notes.run(project, ["Plain"], None, True, None)
        manifest = stage.plan(project, "Plain")[0]
        self.assertEqual(manifest["tags"], ["Tools"])
        self.assertEqual(manifest["blockers"], [])

    def test_keyvalue_id_file_kept_in_step(self):
        game = {"metadata": {"file": "mod.info", "format": "keyvalue", "title": "name", "version": "modversion"},
                "idFile": {"file": "workshop.txt", "format": "keyvalue", "key": "id"}}
        project = self.catalogue_project(game, {"Kv": {"mod.info": "name=Kv\nmodversion=1.0.0\n",
                                                       "workshop.txt": "version=1\ntitle=Kv\n"}})
        written = project.adapter.item_recorded(project, "Kv", "3900000009")
        self.assertEqual(written, ["mods/Kv/workshop.txt"])
        self.assertEqual((self.root / "mods/Kv/workshop.txt").read_text(), "version=1\ntitle=Kv\nid=3900000009\n")
        self.assertEqual(project.adapter.recorded_id(project, "Kv"), "3900000009")
        self.assertIn("says 3900000009", project.adapter.check(project, "Kv", {"itemId": None})[0])
        self.assertEqual(project.adapter.check(project, "Kv", {"itemId": "3900000009"}), [])

    def test_game_layout_defaults_and_catalogue_wins(self):
        game = {"metadata": {"format": "catalogue"}, "layout": {"content": "mods/{mod}/Contents", "pageMaxBytes": 10}}
        project = self.catalogue_project(game, {"L": {"Contents/a.txt": "a"}}, {"L": {"title": "L", "version": "1.0.0"}})
        self.assertEqual(project.layout["content"], "mods/{mod}/Contents")
        self.assertEqual(project.layout["pageMaxBytes"], 10)


if __name__ == "__main__":
    unittest.main()
