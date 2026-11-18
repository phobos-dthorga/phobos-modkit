"""test-pass code: where the code notes each test row's keys, and in which method (1.36.0)."""
import io
import json
from pathlib import Path
import tempfile
import unittest

import support  # noqa: F401  (puts the package on the path)
from phobos_modkit import testpass_cli

EVIDENCE = {
    "doc": "docs/tests.md",
    "rows": {"1": ["boats.float"], "2": ["boats.stage.sink"], "3": ["boats.stage.capsize"], "4": ["boats.never"]},
    "prefixes": {"boats.stage.": "a stage, by its name"},
}

BOAT = """namespace Sample.Boats
{
    public class Boat
    {
        public void Float()
        {
            Seen.Note("boats.float", this);
        }

        public void Stage(string name)
        {
            if (Seen.Wants("boats.stage." + name, this)) Seen.On("boats.stage." + name, this);
        }
    }
}
"""

TEST = 'KEYS = ["boats.float"]\n'


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def run(root, tmp):
    out = io.StringIO()
    environ = support.isolated_environ(tmp, PHOBOS_MODKIT_CACHE=str(Path(tmp) / "cache"))
    code = testpass_cli.main(["code", "--root", str(root), "--json"], environ=environ, out=out)
    return code, json.loads(out.getvalue())["data"]


class CodePlacesTests(unittest.TestCase):
    def test_each_key_is_placed_in_its_method_with_its_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "repo"
            write(root / "config" / "test-evidence.json", json.dumps(EVIDENCE))
            write(root / "docs" / "tests.md", "| # | What |\n| --- | --- |\n| 1 | Floats |\n")
            write(root / "src" / "Boat.cs", BOAT)
            write(root / "tests" / "test_keys.py", TEST)
            code, data = run(root, tmp)
            self.assertEqual(code, 0)
            places = {(p["key"], p["line"]): p for p in data["places"]}
            self.assertEqual(sorted(places), [("boats.float", 7), ("boats.stage.", 12)])
            self.assertEqual(places[("boats.float", 7)]["thing"]["id"], "cs:Sample.Boats.Boat.Float")
            self.assertEqual(places[("boats.float", 7)]["rows"], ["1"])
            stage = places[("boats.stage.", 12)]
            self.assertTrue(stage["prefix"])
            self.assertEqual(stage["rows"], ["2", "3"])
            self.assertEqual(stage["thing"]["id"], "cs:Sample.Boats.Boat.Stage")
            self.assertTrue(all(p["file"] == "src/Boat.cs" for p in data["places"]))
            self.assertEqual(data["unplaced"], ["boats.never"])


if __name__ == "__main__":
    unittest.main()
