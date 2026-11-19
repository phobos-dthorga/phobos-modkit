"""makeup: what a repository is made of, how it grew, where the work goes, and what each product holds (1.39.0)."""
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

import support  # noqa: F401  (puts the package on the path)
from phobos_modkit import makeup, makeup_cli

BOAT = "namespace Boats\n{\n    public class Boat\n    {\n    }\n}\n"
DEFS = """<Defs>
  <ThingDef><defName>Boat</defName></ThingDef>
  <ThingDef><defName>Raft</defName></ThingDef>
  <ThingDef Name="BaseBoat" Abstract="True"></ThingDef>
  <RecipeDef><defName>MakeBoat</defName></RecipeDef>
</Defs>
"""
KEYED = "<?xml version=\"1.0\"?>\n<LanguageData>\n  <BoatsFloat>Floats.</BoatsFloat>\n  <BoatsSink>Sinks.</BoatsSink>\n</LanguageData>\n"


def git(root, *args, when=None):
    environ = dict(os.environ)
    if when:
        environ.update(GIT_AUTHOR_DATE=when, GIT_COMMITTER_DATE=when)
    return subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True, env=environ).stdout


def write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data if isinstance(data, bytes) else data.encode("utf-8"))


def repository(tmp):
    root = Path(tmp) / "repo"
    root.mkdir()
    git(root, "init", "-q")
    git(root, "config", "core.fsmonitor", "false")
    git(root, "config", "user.email", "test@example.com")
    git(root, "config", "user.name", "Test")
    write(root / "mods" / "Boats" / "CHANGELOG.md", "# Sample Boats changelog\n\n## [Unreleased]\n")
    write(root / "mods" / "Boats" / "Defs" / "Things.xml", DEFS)
    write(root / "src" / "Boats" / "Boats.csproj", "<Project>\n  <PropertyGroup>\n    <ModFolder>Boats</ModFolder>\n"
                                                   "  </PropertyGroup>\n</Project>\n")
    write(root / "src" / "Boats" / "Boat.cs", BOAT)
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "first", when="2026-11-01T10:00:00+00:00")
    write(root / "mods" / "Boats" / "Textures" / "boat.png", b"\x89PNG\r\n\x1a\n\0\0\0binary")
    write(root / "mods" / "Boats" / "Languages" / "English" / "Keyed" / "Boats.xml", KEYED)
    write(root / "docs" / "guide.md", "# Guide\n\nRow boats.\n")
    write(root / "tests" / "test_boats.py", "def test_floats():\n    assert True\n")
    write(root / "README.md", "# Boats\n")
    write(root / "src" / "Boats" / "Boat.cs", BOAT + "// more\n")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "second", when="2026-11-03T10:00:00+00:00")
    return root


class MakeupTests(unittest.TestCase):
    def test_kinds_come_from_extensions_and_folders(self):
        self.assertEqual(makeup.classify("src/Boats/Boat.cs"), ("code", "C#"))
        self.assertEqual(makeup.classify("tests/test_boats.py"), ("tests", "Python"))
        self.assertEqual(makeup.classify("mods/Boats/Defs/Things.xml"), ("data", "XML"))
        self.assertEqual(makeup.classify("mods/Boats/Languages/English/Keyed/Boats.xml"), ("words", "XML"))
        self.assertEqual(makeup.classify("mods/Boats/Textures/boat.png"), ("pictures", "PNG"))
        self.assertEqual(makeup.classify("src/Boats/Boats.csproj"), ("build", "csproj"))
        self.assertEqual(makeup.classify("docs/guide.md"), ("words", "Markdown"))

    def test_each_file_has_its_product_kind_and_lines(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = repository(tmp)
            environ = support.isolated_environ(tmp, PHOBOS_MODKIT_CACHE=str(Path(tmp) / "cache"))
            data = makeup.now(root, environ)
            files = {f["path"]: f for f in data["files"]}
            self.assertEqual(data["products"], ["Sample Boats"])
            self.assertEqual(files["src/Boats/Boat.cs"]["product"], "Sample Boats")
            self.assertEqual(files["src/Boats/Boat.cs"]["lines"], 7)
            self.assertEqual(files["mods/Boats/Textures/boat.png"]["lines"], 0)
            self.assertEqual(files["mods/Boats/Textures/boat.png"]["bytes"], 17)
            self.assertEqual((files["docs/guide.md"]["product"], files["docs/guide.md"]["group"]), (None, "docs"))
            self.assertEqual(files["README.md"]["group"], "")

    def test_growth_has_a_point_a_day_and_churn_counts_commits(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = repository(tmp)
            environ = support.isolated_environ(tmp, PHOBOS_MODKIT_CACHE=str(Path(tmp) / "cache"))
            points = makeup.growth(root, environ)["points"]
            self.assertEqual([p["day"] for p in points], ["2026-11-01", "2026-11-03"])
            self.assertEqual(points[0]["kinds"]["code"][0], 6)
            self.assertEqual(points[1]["kinds"]["code"][0], 7)
            self.assertNotIn("pictures", points[0]["kinds"])
            # changelog 3, Defs 6, project 5, Boat.cs 7, keys 5; the picture has no lines
            self.assertEqual(points[1]["products"]["Sample Boats"][0], 3 + 6 + 5 + 7 + 5)
            found = makeup.churn(root, 0)
            self.assertEqual(found["src/Boats/Boat.cs"]["commits"], 2)
            self.assertEqual(found["src/Boats/Boat.cs"]["last"], "2026-11-03")

    def test_the_census_counts_defs_pictures_and_text_keys(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = repository(tmp)
            out = io.StringIO()
            environ = support.isolated_environ(tmp, PHOBOS_MODKIT_CACHE=str(Path(tmp) / "cache"))
            code = makeup_cli.main(["census", "--root", str(root), "--json"], environ=environ, out=out)
            self.assertEqual(code, 0)
            boats = json.loads(out.getvalue())["data"]["products"]["Sample Boats"]
            self.assertEqual(boats["defs"], {"ThingDef": 2, "RecipeDef": 1})
            self.assertEqual((boats["pictures"], boats["sounds"], boats["keys"]), (1, 0, 2))


if __name__ == "__main__":
    unittest.main()
