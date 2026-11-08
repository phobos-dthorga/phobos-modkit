"""The constants updater: every copy checked before any write, in-place edits, read-back and rollback."""
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import support  # noqa: F401
from phobos_modkit.release import constants
from phobos_modkit.release.cli import main
from phobos_modkit.release.constants import UpdateError, apply, plan

ABOUT = '<?xml version="1.0" encoding="utf-8"?>\n<ModMetaData>\n  <modVersion>0.4.0</modVersion>\n</ModMetaData>\n'
README = "﻿| **Example** | 0.4.0 |\r\nUnrelated text, été.\r\n"
DATA = '{\n  "version": "0.4.0",\n  "tuning": {"rate": 2, "list": [1, 2.50]}\n}\n'
CODE = "const float Rate = 2;\n"


class Constants(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        files = {"mods/Example/About/About.xml": ABOUT, "README.md": README, "mods/Example/data.json": DATA,
                 "src/Example/Rules.cs": CODE}
        for name, text in files.items():
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(text.encode("utf-8"))
        self.catalogue = {"schemaVersion": 1, "targetsUnder": ["mods/", "src/", "README.md"], "constants": {
            "Example.version": {"type": "version", "parts": 3, "value": "0.4.0", "description": "The mod's version",
                                "targets": [{"path": "mods/Example/About/About.xml",
                                             "pattern": r"<modVersion>(?P<value>[0-9.]+)</modVersion>"},
                                            {"path": "README.md", "pattern": r"\| \*\*Example\*\* \| (?P<value>[0-9.]+) \|"},
                                            {"path": "mods/Example/data.json", "pointer": "/version"}],
                                "review": ["Write the changelog entry."]},
            "Example.rate": {"type": "number", "min": 0, "max": 10, "value": "2", "description": "Rate",
                             "targets": [{"path": "src/Example/Rules.cs", "pattern": r"Rate = (?P<value>[0-9.]+)",
                                          "literal": "csharp-float"},
                                         {"path": "mods/Example/data.json", "pointer": "/tuning/rate"}]}}}
        self.write_catalogue()

    def tearDown(self):
        self.tmp.cleanup()

    def write_catalogue(self):
        path = self.root / constants.CATALOGUE
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.catalogue, indent=2), encoding="utf-8")

    def snapshot(self):
        return {p: p.read_bytes() for p in self.root.rglob("*") if p.is_file()}

    def test_preview_writes_nothing(self):
        before = self.snapshot()
        _, proposed, summary = plan(self.root, {"Example.version": "0.5.0"}, {})
        self.assertEqual(len(summary["changes"]), 3)
        self.assertEqual(self.snapshot(), before)
        self.assertIn(constants.CATALOGUE, proposed)

    def test_apply_keeps_formatting_and_repeats_cleanly(self):
        original, proposed, _ = plan(self.root, {"Example.version": "0.5.0", "Example.rate": "2.5"},
                                     {"Example.version": "0.4.0"})
        apply(self.root, original, proposed)
        self.assertIn("<modVersion>0.5.0</modVersion>", (self.root / "mods/Example/About/About.xml").read_text())
        readme = (self.root / "README.md").read_bytes()
        self.assertTrue(readme.startswith(b"\xef\xbb\xbf") and b"\r\n" in readme and "été".encode() in readme)
        self.assertEqual((self.root / "src/Example/Rules.cs").read_text(), "const float Rate = 2.5f;\n")
        data = (self.root / "mods/Example/data.json").read_text()
        self.assertIn('"version": "0.5.0"', data)
        self.assertIn('{"rate": 2.5, "list": [1, 2.50]}', data)
        self.assertEqual(plan(self.root, {"Example.version": "0.5.0"}, {})[1], {})

    def test_drift_anywhere_blocks_everything(self):
        (self.root / "src/Example/Rules.cs").write_text("const float Rate = 3;\n")
        with self.assertRaisesRegex(UpdateError, "Drift: Example.rate"):
            plan(self.root, {"Example.version": "0.5.0"}, {})

    def test_bad_values_targets_and_paths(self):
        cases = [({"Example.version": "0.5"}, {}, "3-part"), ({"Example.rate": "11"}, {}, "outside"),
                 ({"Example.version": "0.5.0"}, {"Example.version": "0.3.0"}, "expected"),
                 ({"Missing.key": "1"}, {}, "Unknown")]
        for updates, expected, message in cases:
            with self.subTest(message), self.assertRaisesRegex(UpdateError, message):
                plan(self.root, updates, expected)
        for target, message in (({"path": "README.md", "pattern": r"(?P<value>\d)\.", "count": 1}, "shape changed"),
                                ({"path": "../outside.txt", "pattern": "(?P<value>x)"}, "Unsafe"),
                                ({"path": ".git/config", "pattern": "(?P<value>x)"}, "targetsUnder"),
                                ({"path": "docs/x.md", "pattern": "(?P<value>x)"}, "targetsUnder"),
                                ({"path": "mods/Example/missing.txt", "pattern": "(?P<value>x)"}, "Missing target")):
            self.catalogue["constants"]["Example.version"]["targets"] = [target]
            self.write_catalogue()
            with self.subTest(message), self.assertRaisesRegex(UpdateError, message):
                plan(self.root, {}, {})

    def test_overlapping_targets_refused(self):
        self.catalogue["constants"]["Example.version"]["targets"].append(
            {"path": "README.md", "pattern": r"\*\* \| (?P<value>[0-9.]+)"})
        self.write_catalogue()
        with self.assertRaisesRegex(UpdateError, "Overlapping"):
            plan(self.root, {}, {})

    def test_concurrent_edit_and_rollback(self):
        original, proposed, _ = plan(self.root, {"Example.version": "0.5.0"}, {})
        (self.root / "README.md").write_bytes(b"| **Example** | 0.4.0 |\n")
        with self.assertRaisesRegex(UpdateError, "Edited while planning"):
            apply(self.root, original, proposed)
        (self.root / "README.md").write_bytes(README.encode("utf-8"))
        original, proposed, _ = plan(self.root, {"Example.version": "0.5.0"}, {})
        before = self.snapshot()
        real = constants.atomic_write
        calls = []

        def failing(path, data):
            calls.append(path)
            if len(calls) == 3:
                raise OSError("disk full")
            real(path, data)
        with mock.patch.object(constants, "atomic_write", failing), self.assertRaisesRegex(UpdateError, "restored"):
            apply(self.root, original, proposed)
        self.assertEqual(self.snapshot(), before)

    def test_broken_xml_is_refused(self):
        self.catalogue["constants"]["Example.version"]["targets"][0]["pattern"] = r"<modVersion>(?P<value>[0-9.]+)<"
        self.write_catalogue()
        with self.assertRaises(Exception):
            plan(self.root, {"Example.version": "0.5.0<x"}, {})

    def test_command_line(self):
        out = io.StringIO()
        self.assertEqual(main(["constants", "--list", "--root", str(self.root)], out=out), 0)
        self.assertIn("| Example.version | 0.4.0 | version | 3 | The mod's version |", out.getvalue())
        out = io.StringIO()
        self.assertEqual(main(["constants", "--set", "Example.version=0.5.0", "--root", str(self.root)], out=out), 0)
        self.assertIn("# Constants: preview", out.getvalue())
        self.assertIn("Write the changelog entry.", out.getvalue())
        out = io.StringIO()
        self.assertEqual(main(["constants", "--check", "--set", "Example.version=1.0.0", "--root", str(self.root)],
                              out=out), 1)
        self.assertEqual(main(["constants", "--set", "Example.version=0.5.0", "--apply", "--root", str(self.root)],
                              out=io.StringIO()), 0)
        self.assertIn("0.5.0", (self.root / "README.md").read_text(encoding="utf-8-sig"))


if __name__ == "__main__":
    unittest.main()
