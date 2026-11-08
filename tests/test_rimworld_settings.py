"""rimworld-settings on a made-up install: file names to mods, active or left behind, values, defaults and snapshots."""
import io
import json
from pathlib import Path
import tempfile
import unittest

import support  # noqa: F401  (the package on the import path)
from phobos_modkit.games.rimworld.settings import compare, flatten, split_name
from phobos_modkit.games.rimworld.settings_cli import EXIT_FAILED, EXIT_OK, main
import xml.etree.ElementTree as ET

ABOUT = "<ModMetaData><name>{name}</name><packageId>{pid}</packageId></ModMetaData>"
MODS_CONFIG = ("<ModsConfigData><version>1.7.4000 rev1</version><activeMods><li>ludeon.rimworld</li>"
               "<li>phobos.example</li></activeMods></ModsConfigData>")
EXAMPLE = """<?xml version="1.0" encoding="utf-8"?>
<SettingsBlock>
  <ModSettings Class="Phobos.Example.ExampleSettings">
    <PhobosEx_Mode>Engineer</PhobosEx_Mode>
    <PhobosEx_Strip>True</PhobosEx_Strip>
    <PhobosEx_Old>3</PhobosEx_Old>
    <PhobosEx_Off><li>a.one</li><li>b.two</li></PhobosEx_Off>
  </ModSettings>
</SettingsBlock>"""
SIMPLE = '<SettingsBlock><ModSettings Class="Other.Settings"><x>1</x></ModSettings></SettingsBlock>'


class Model(unittest.TestCase):
    def test_file_names_split_at_the_installed_folder_even_when_the_class_has_underscores(self):
        self.assertEqual(split_name("Mod_2023507013_AnimalBehaviours_Mod.xml", {"2023507013"}), ("2023507013", "AnimalBehaviours_Mod"))
        self.assertEqual(split_name("Mod_Gone_GoneMod.xml", set()), ("Gone", "GoneMod"))
        self.assertEqual(split_name("Mod_My_Mod_Folder_MyMod.xml", {"My_Mod_Folder", "My"}), ("My_Mod_Folder", "MyMod"))
        self.assertIsNone(split_name("KeyPrefs.xml", set()))

    def test_flatten_lists_and_nested_values(self):
        root = ET.fromstring("<s><a>1</a><b><li>x</li><li>y</li></b><c><li><k>p</k><v>q</v></li></c><d/></s>")
        self.assertEqual(flatten(root), {"a": "1", "b": "[2] x; y", "c[0]/k": "p", "c[0]/v": "q", "d": "(empty)"})

    def test_compare_names_changes_and_files_that_came_or_went(self):
        before = {"files": {"A.xml": {"mod": "A", "values": {"k": "1", "gone": "x"}}, "B.xml": {"mod": "B", "values": {}}}}
        after = {"files": {"A.xml": {"mod": "A", "values": {"k": "2", "new": "y"}}, "C.xml": {"mod": "C", "values": {"z": "1"}}}}
        self.assertEqual(compare(before, after), [
            ("A.xml", "A", "k", "1", "2"), ("A.xml", "A", "gone", "x", "(default)"), ("A.xml", "A", "new", "(default)", "y"),
            ("B.xml", "B", "(the whole file)", "0 values", "(gone)"), ("C.xml", "C", "(the whole file)", "(none)", "1 values")])


class Command(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.game, self.workshop, self.config = root / "RimWorld", root / "workshop", root / "Config"
        for folder, name, pid in ((self.game / "Mods" / "PhobosExample", "Example", "phobos.example"),
                                  (self.workshop / "123", "Workshop Thing", "author.thing")):
            (folder / "About").mkdir(parents=True)
            (folder / "About" / "About.xml").write_text(ABOUT.format(name=name, pid=pid), encoding="utf-8")
        self.config.mkdir()
        (self.config / "ModsConfig.xml").write_text(MODS_CONFIG, encoding="utf-8")
        (self.config / "Mod_PhobosExample_ExampleMod.xml").write_text(EXAMPLE, encoding="utf-8")
        (self.config / "Mod_123_Thing_Mod.xml").write_text(SIMPLE, encoding="utf-8")
        (self.config / "Mod_PhobosOldName_OldMod.xml").write_text(SIMPLE, encoding="utf-8")
        (self.config / "KeyPrefs.xml").write_text("<KeyPrefs/>", encoding="utf-8")
        self.root = root

    def tearDown(self):
        self.tmp.cleanup()

    def run_main(self, *args):
        out = io.StringIO()
        code = main(list(args) + ["--config", str(self.config), "--game", str(self.game), "--workshop", str(self.workshop),
                                  "--no-redact"], environ={}, out=out)
        return code, out.getvalue()

    def test_summary_sorts_files_into_active_inactive_and_gone(self):
        code, text = self.run_main()
        self.assertEqual(code, EXIT_OK)
        self.assertIn("3 mod settings files: 1 for active mods, 1 for installed mods that are not active, 1 for mods not installed.", text)
        self.assertIn("| 1 | Example | phobos.example | 4 |", text)
        self.assertIn("| Mod_123_Thing_Mod.xml | installed, not active |", text)
        self.assertIn("| Mod_PhobosOldName_OldMod.xml | no installed mod has this folder |", text)
        self.assertIn("2 other files in Config are not mod settings in this format (KeyPrefs.xml, ModsConfig.xml)", text)

    def test_one_mods_values_with_its_defaults(self):
        defaults = self.root / "defaults.json"
        defaults.write_text(json.dumps({"schemaVersion": 1, "classes": {"Phobos.Example.ExampleSettings": {
            "PhobosEx_Mode": {"default": "Operator"}, "PhobosEx_Strip": {"default": "false", "initial": "true"},
            "PhobosEx_Off": {"default": ""}, "PhobosEx_Rate": {"default": "1.5"}}}}), encoding="utf-8")
        code, text = self.run_main("--mod", "phobos.*", "--defaults", str(defaults))
        self.assertEqual(code, EXIT_OK)
        self.assertNotIn("## Active mods with settings", text)
        self.assertIn("## Example (active; Mod_PhobosExample_ExampleMod.xml)", text)
        self.assertIn("| PhobosEx_Mode | Engineer | Operator |", text)
        self.assertIn("| PhobosEx_Old | 3 | not read by this version |", text)
        self.assertIn("| PhobosEx_Off | [2] a.one; b.two |", text)
        self.assertIn("At default, so not in the file: PhobosEx_Rate = 1.5", text)
        self.assertIn("PhobosEx_Strip: field starts at true, but a missing key loads as false", text)
        code, text = self.run_main("--mod", "nothing.like.this")
        self.assertIn("No settings file matches nothing.like.this", text)

    def test_snapshot_then_compare(self):
        snap = self.root / "before.json"
        self.assertEqual(self.run_main("snapshot", str(snap))[0], EXIT_OK)
        (self.config / "Mod_PhobosExample_ExampleMod.xml").write_text(EXAMPLE.replace("Engineer", "Plain"), encoding="utf-8")
        code, text = self.run_main("compare", str(snap))
        self.assertEqual(code, EXIT_OK)
        self.assertIn("1 differences between", text)
        self.assertIn("| Mod_PhobosExample_ExampleMod.xml | Example | PhobosEx_Mode | Engineer | Plain |", text)

    def test_a_missing_config_folder_is_an_error(self):
        out = io.StringIO()
        code = main(["--config", str(self.root / "nowhere"), "--game", str(self.game)], environ={}, out=out)
        self.assertEqual(code, EXIT_FAILED)
        self.assertIn("No Config folder", out.getvalue())


if __name__ == "__main__":
    unittest.main()
