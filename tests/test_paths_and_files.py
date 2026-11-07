"""Path precedence and reading files another program may be writing."""
import json
from pathlib import Path
import tempfile
import unittest

import support  # noqa: F401
from phobos_modkit.games.rimworld import paths as rimworld_paths
from phobos_modkit.paths import resolve
from phobos_modkit.textfile import read_text_shared


class Precedence(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.settings = Path(self.tmp.name) / "settings.json"
        self.settings.write_text(json.dumps({"key": "from-settings"}), encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def test_argument_then_environment_then_settings_then_default(self):
        env = {"VAR": "from-env"}
        self.assertEqual(resolve("key", "VAR", "dflt", "explicit", env, self.settings), Path("explicit"))
        self.assertEqual(resolve("key", "VAR", "dflt", None, env, self.settings), Path("from-env"))
        self.assertEqual(resolve("key", "VAR", "dflt", None, {}, self.settings), Path("from-settings"))
        self.assertEqual(resolve("other", "VAR", "dflt", None, {}, self.settings), Path("dflt"))
        self.assertEqual(resolve("key", "VAR", "dflt", None, {}, Path(self.tmp.name) / "absent.json"), Path("dflt"))
        self.assertIsNone(resolve("other", "VAR", None, None, {}, None))

    def test_rimworld_places_per_system(self):
        home = Path("home")
        self.assertEqual(rimworld_paths.default_user_data("win32", home),
                         home / "AppData" / "LocalLow" / "Ludeon Studios" / "RimWorld by Ludeon Studios")
        self.assertEqual(rimworld_paths.default_user_data("linux", home),
                         home / ".config" / "unity3d" / "Ludeon Studios" / "RimWorld by Ludeon Studios")


class SharedReading(unittest.TestCase):
    def test_byte_order_mark_and_broken_bytes(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "log.txt"
            path.write_bytes(b"\xef\xbb\xbfline one\nline two \xe2\x82")  # a character cut off at the end
            text = read_text_shared(path)
        self.assertTrue(text.startswith("line one\n"))
        self.assertTrue(text.endswith("line two �"))


if __name__ == "__main__":
    unittest.main()
