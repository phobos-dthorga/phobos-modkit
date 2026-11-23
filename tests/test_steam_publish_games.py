"""Games as data for Workshop publishing (1.97.0): every game file loads, each metadata format reads, the game's ID file is
kept in step, and a catalogue can describe a game nobody has written a file for. Made-up mods only; nothing reaches Steam."""
import json
from pathlib import Path
import struct
import subprocess
import tempfile
import unittest

import support  # noqa: F401
from phobos_modkit.games import publish_adapters
from phobos_modkit.steam.publish import notes, stage
from phobos_modkit.steam.publish.game_data import DataAdapter, find, keyvalue_lines, png_size
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



def png(width, height, extra=0):
    """A made-up PNG header: enough for its size to be read."""
    return b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\rIHDR" + struct.pack(">II", width, height) + b"\x00" * (5 + extra)


class MoreGames(unittest.TestCase):
    """1.100.0: Project Zomboid, Kenshi and Workers & Resources as game files, and RimWorld's own Required items."""

    setUp, tearDown, write = GameFiles.setUp, GameFiles.tearDown, GameFiles.write

    def repo(self, config, notes_too=True):
        git(self.root, "init", "-q")
        git(self.root, "config", "core.fsmonitor", "false")
        self.write("config/workshop-publishing.json", json.dumps(config))
        project = Project.load(self.root, publish_adapters(), cache_folder=self.root / "cache")
        if notes_too:
            notes.run(project, None, None, True, None)
        return project

    def test_zomboid_one_mod_repository(self):
        self.write("mod.info", "name=Old\nid=Example\nmodversion=0.1.0\n")
        self.write("42.14/mod.info", "name=Example\nid=Example\nmodversion=1.0.0\n")
        self.write("42.15/mod.info", "name=Example Mod\nid=ExampleMod\nmodversion=1.1.0\n")
        self.write("common/media/lua/shared/a.lua", "return 1\n")
        self.write("42.15/media/scripts/bad.dll", "x")
        self.write("docs/notes.md", "not shipped")
        self.write(".gitignore", "x\n")
        self.write("workshop/preview.png", "")
        (self.root / "workshop/preview.png").write_bytes(png(300, 256))
        self.write("CHANGELOG.md", CHANGELOG.replace("1.0.0", "1.1.0"))
        self.write("workshop/page.bbcode", PAGE.format(title="Example Mod").replace("1.0.0", "1.1.0"))
        project = self.repo({"appId": "108600", "mods": {"ExampleMod": {"itemId": None, "requires": []}}})
        self.assertEqual(project.on_disk(), ["ExampleMod"])
        info = project.info("ExampleMod")
        self.assertEqual((info.title, info.version, info.tags), ("Example Mod", "1.1.0", ("Build 42",)))
        manifest, payload = stage.plan(project, "ExampleMod")[:2]
        self.assertIn("Contents/mods/ExampleMod/common/media/lua/shared/a.lua", payload)
        self.assertIn("preview.png", payload)
        self.assertFalse(any(name.startswith(("Contents/mods/ExampleMod/docs", "Contents/mods/ExampleMod/workshop",
                                              "Contents/mods/ExampleMod/.git")) for name in payload))
        blockers = " ".join(manifest["blockers"])
        self.assertIn("300 by 256 pixels; this game wants it square", blockers)
        self.assertIn("refuses Contents/mods/ExampleMod/42.15/media/scripts/bad.dll", blockers)
        self.assertEqual(manifest["footer"], ["Workshop ID: {itemId}", "Mod ID: ExampleMod"])
        page = stage.with_footer("Text\n", manifest)
        self.assertEqual(page, "Text\n\nMod ID: ExampleMod\n")            # no number yet: its line waits
        self.assertEqual(stage.with_footer("Text\n", manifest, "3900000001"),
                         "Text\n\nWorkshop ID: 3900000001\nMod ID: ExampleMod\n")

    def test_png_rules(self):
        self.assertEqual(png_size(png(512, 512)), (512, 512))
        self.assertIsNone(png_size(b"GIF89a"))
        adapter = publish_adapters()["108600"]
        self.assertEqual(adapter.blockers({"preview.png": png(512, 512)}, "preview.png"), [])
        self.assertIn("must be a PNG", adapter.blockers({"preview.png": b"JFIF"}, "preview.png")[0])
        self.assertIn("at most 1,024,000", adapter.blockers({"preview.png": png(512, 512, 1_100_000)}, "preview.png")[0])

    def test_kenshi_title_from_its_folder_and_the_info_file_kept(self):
        self.write("mods/Coil Rifle/Coil Rifle.mod", "binary")
        self.write("mods/Coil Rifle/_Coil Rifle.img", "x")
        self.write("mods/Coil Rifle/_Coil Rifle.info", "<?xml version=\"1.0\"?>\n<ModData>\n  <id>0</id>\n  "
                                                      "<title>Coil Rifle</title>\n</ModData>\n")
        self.write("mods/Coil Rifle/CHANGELOG.md", CHANGELOG)
        self.write("workshop/Coil Rifle/page.bbcode", PAGE.format(title="Coil Rifle"))
        self.write("mods/Not A Mod/readme.txt", "no .mod file here")
        project = self.repo({"appId": "233860", "mods": {"Coil Rifle": {"itemId": None, "requires": [], "version": "1.0.0"}}})
        info = project.info("Coil Rifle")
        self.assertEqual((info.title, info.version), ("Coil Rifle", "1.0.0"))
        self.assertIsNone(project.adapter.recorded_id(project, "Coil Rifle"))      # 0 is no item
        self.assertEqual(project.adapter.item_recorded(project, "Coil Rifle", "3900000005"), ["mods/Coil Rifle/_Coil Rifle.info"])
        self.assertIn("<id>3900000005</id>", (self.root / "mods/Coil Rifle/_Coil Rifle.info").read_text())
        self.assertIn("_Coil Rifle.img", stage.plan(project, "Coil Rifle")[0]["preview"])

    def test_wrsr_dollar_keys_quotes_and_end_line(self):
        self.write("mods/p01/workshopconfig.ini", '$OWNER_ID 0\n$ITEM_NAME "Heating Works"\n$END\n')
        self.write("mods/p01/previewimage.png", "x")
        self.write("mods/p01/CHANGELOG.md", CHANGELOG)
        self.write("workshop/p01/page.bbcode", PAGE.format(title="Heating Works"))
        project = self.repo({"appId": "784150", "mods": {"p01": {"itemId": None, "requires": [], "version": "1.0.0"}}})
        info = project.info("p01")
        self.assertEqual((info.title, info.version), ("Heating Works", "1.0.0"))
        project.adapter.item_recorded(project, "p01", "3900000006")
        self.assertEqual((self.root / "mods/p01/workshopconfig.ini").read_text(),
                         '$OWNER_ID 0\n$ITEM_NAME "Heating Works"\n$ITEM_ID 3900000006\n$END\n')
        self.assertEqual(project.adapter.recorded_id(project, "p01"), "3900000006")

    def test_rimworld_reads_each_mods_required_items(self):
        about = ("<ModMetaData><name>Thing</name><modVersion>1.0.0</modVersion><modDependencies>"
                 "<li><packageId>a.harmony</packageId><displayName>Harmony</displayName>"
                 "<steamWorkshopUrl>steam://url/CommunityFilePage/2009463077</steamWorkshopUrl></li>"
                 "<li><packageId>us.ours</packageId><displayName>Ours, unpublished</displayName></li>"
                 "<li><packageId>b.other</packageId><displayName>Other</displayName>"
                 "<steamWorkshopUrl>https://steamcommunity.com/sharedfiles/filedetails/?id=836308268</steamWorkshopUrl></li>"
                 "</modDependencies></ModMetaData>")
        self.write("mods/Thing/About/About.xml", about)
        self.write("mods/Thing/About/Preview.png", "x")
        self.write("mods/Thing/CHANGELOG.md", CHANGELOG)
        self.write("workshop/Thing/page.bbcode", PAGE.format(title="Thing"))
        project = self.repo({"appId": "294100", "mods": {"Thing": {"itemId": None, "requires": [],
                                                                   "requiredItems": ["1111111"]}},
                             "externalRequiredItemNames": {"1111111": "Named in the catalogue"}})
        manifest = stage.plan(project, "Thing")[0]
        self.assertEqual(manifest["requiredItemDetails"], [
            {"name": "Harmony", "itemId": "2009463077"}, {"name": "Other", "itemId": "836308268"},
            {"name": "Named in the catalogue", "itemId": "1111111"}])
        self.assertEqual(manifest["requiredItems"], ["2009463077", "836308268", "1111111"])


if __name__ == "__main__":
    unittest.main()
