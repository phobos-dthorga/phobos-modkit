"""connections: a made-up repository in every language the tool reads, and the made-up C# assembly built and read exactly. Every
file is written by hand in temporary folders; the cache points there too. Without the .NET SDK the exact C# tests are skipped,
unless PHOBOS_REQUIRE_NATIVE is set, as for the other native tools."""
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

import support  # noqa: F401  (puts the package on the path)
from phobos_modkit import connections, connections_cli, native

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "dotnet" / "ConnectionsFixture"
HAVE_DOTNET = shutil.which("dotnet") is not None
REQUIRE = bool(os.environ.get("PHOBOS_REQUIRE_NATIVE"))

DEFS = """<?xml version="1.0" encoding="utf-8"?>
<Defs>
  <ThingDef Name="BaseLamp" Abstract="True">
    <thingClass>Sample.Lamps.LampThing</thingClass>
  </ThingDef>
  <ThingDef ParentName="BaseLamp">
    <defName>Lamp</defName>
    <comps>
      <li Class="Sample.Lamps.CompGlow" />
    </comps>
  </ThingDef>
  <RecipeDef>
    <defName>MakeLamp</defName>
    <products>
      <li>Lamp</li>
    </products>
  </RecipeDef>
</Defs>
"""
LUA = """Lamps = {}

-- a comment that names Lamps.shine() is not a call
function Lamps.light()
    Lamps.shine()
end

local function dim()
    return 1
end

function Lamps.shine()
    print("shine()")
end

require "Sample/Other"
"""
PYTHON = """import json


class Keeper:
    def run(self):
        return tidy()


def tidy():
    return json.dumps({})
"""
LAMPS_LOG_FIRST = """# Lamps changelog

## [Unreleased]

## [0.1.0] - 2026-11-01 - Draft

- **Lamps.** They shine.
"""
LAMPS_LOG_SECOND = """# Lamps changelog

## [Unreleased]

## [0.2.0] - 2026-11-02 - Draft

- **Brighter.** Lamps shine brighter.

## [0.1.0] - 2026-11-01 - Draft

- **Lamps.** They shine.
"""
CSHARP = """namespace Sample.Text
{
    public class Reader
    {
        public void Run() { Writer.Go(); }
    }

    public static class Writer
    {
        public static void Go() { }
    }
}
"""


def git(root, *args):
    subprocess.run(["git", "-c", "core.fsmonitor=false", *args], cwd=root, check=True, capture_output=True)


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def repository(tmp):
    root = Path(tmp) / "repo"
    write(root / "Defs" / "Lamps.xml", DEFS)
    write(root / "lua" / "lamps.lua", LUA)
    write(root / "tools" / "keeper.py", PYTHON)
    write(root / "src" / "Reader.cs", CSHARP)
    write(root / ".local" / "Decompiled.cs", "class NotOurs { void X() { } }\n")
    return root


def environ(tmp):
    return support.isolated_environ(tmp, PHOBOS_MODKIT_CACHE=str(Path(tmp) / "cache"))


def run(argv, tmp):
    out = io.StringIO()
    code = connections_cli.main([*argv, "--json"], environ=environ(tmp), out=out)
    return code, json.loads(out.getvalue())["data"]


def relations(found):
    return {g["relation"]: sorted(n["id"] for n in g["nodes"]) for g in found["groups"]}


class ByNameTests(unittest.TestCase):
    def test_each_language_reads_its_shape(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = repository(tmp)
            code, found = run(["summary", "--root", str(root)], tmp)
            self.assertEqual(code, 0)
            self.assertEqual([r["language"] for r in found["readers"]], ["C#", "XML Defs", "Lua", "Python"])
            self.assertIn("by name", found["readers"][0]["how"])

    def test_defs_build_on_their_parent_and_use_classes_and_other_defs(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, found = run(["around", "--root", str(repository(tmp)), "--node", "def:ThingDef/Lamp"], tmp)
            self.assertEqual(code, 0)
            groups = relations(found)
            self.assertEqual(groups["builds-on"], ["def:ThingDef/BaseLamp"])
            self.assertEqual(groups["uses"], ["cs:Sample.Lamps.CompGlow"])
            self.assertEqual(groups["used-by"], ["def:RecipeDef/MakeLamp"])
            self.assertEqual((found["centre"]["file"], found["centre"]["line"]), ("Defs/Lamps.xml", 7))

    def test_lua_calls_by_name_and_skips_comments_and_strings(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = repository(tmp)
            _, light = run(["around", "--root", str(root), "--node", "lua:Lamps.light"], tmp)
            self.assertEqual(relations(light)["calls"], ["lua:Lamps.shine"])
            self.assertFalse(next(g for g in light["groups"] if g["relation"] == "calls")["exact"])
            _, shine = run(["around", "--root", str(root), "--node", "lua:Lamps.shine"], tmp)
            self.assertEqual(relations(shine)["called-by"], ["lua:Lamps.light"])
            _, module = run(["around", "--root", str(root), "--node", "lua:file:lua/lamps.lua"], tmp)
            self.assertIn("lua:lua/lamps.lua:dim", relations(module)["holds"])
            self.assertEqual(relations(module)["imports"], ["lua:module:Sample/Other"])

    def test_python_and_csharp_source_connect_by_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = repository(tmp)
            _, run_method = run(["around", "--root", str(root), "--node", "py:tools.keeper.Keeper.run"], tmp)
            self.assertEqual(relations(run_method)["calls"], ["py:tools.keeper.tidy"])
            _, reader = run(["around", "--root", str(root), "--node", "cs:Sample.Text.Reader.Run"], tmp)
            self.assertEqual(relations(reader)["calls"], ["cs:Sample.Text.Writer.Go"])
            code, found = run(["find", "--root", str(root), "--name", "NotOurs"], tmp)
            self.assertEqual(found["things"], [])

    def test_the_flow_runs_from_callers_to_callees(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, found = run(["flow", "--root", str(repository(tmp)), "--node", "lua:Lamps.shine"], tmp)
            self.assertEqual([(c["step"], [n["id"] for n in c["nodes"]]) for c in found["columns"]],
                             [(-1, ["lua:Lamps.light"]), (0, ["lua:Lamps.shine"])])

    def test_a_commit_names_what_its_lines_changed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = repository(tmp)
            git(root, "init", "-q")
            git(root, "config", "core.fsmonitor", "false")
            git(root, "config", "user.email", "test@example.com")
            git(root, "config", "user.name", "Test")
            git(root, "add", "-A")
            git(root, "commit", "-q", "-m", "first")
            write(root / "lua" / "lamps.lua", LUA.replace('print("shine()")', 'print("brighter")'))
            write(root / "Defs" / "Lamps.xml", DEFS.replace("<li>Lamp</li>", "<li>Lamp</li>\n      <li>Lamp</li>"))
            git(root, "commit", "-q", "-am", "brighter")
            commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True).stdout.strip()
            code, found = run(["changed", "--root", str(root), "--commit", commit[:10]], tmp)
            self.assertEqual(code, 0)
            self.assertEqual(sorted(t["id"] for t in found["things"]), ["def:RecipeDef/MakeLamp", "lua:Lamps.shine"])
            self.assertTrue(all(t["inGraph"] for t in found["things"]))

    def test_a_things_history_is_its_commits_with_the_entries_they_wrote(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = repository(tmp)
            write(root / "CHANGELOG.md", LAMPS_LOG_FIRST)
            git(root, "init", "-q")
            git(root, "config", "core.fsmonitor", "false")
            git(root, "config", "user.email", "test@example.com")
            git(root, "config", "user.name", "Test")
            git(root, "add", "-A")
            git(root, "commit", "-q", "-m", "Lamps 0.1.0")
            write(root / "lua" / "lamps.lua", LUA.replace('print("shine()")', 'print("brighter")'))
            write(root / "CHANGELOG.md", LAMPS_LOG_SECOND)
            git(root, "commit", "-q", "-am", "Lamps 0.2.0: brighter")
            code, found = run(["history", "--root", str(root), "--node", "lua:Lamps.shine"], tmp)
            self.assertEqual(code, 0)
            self.assertEqual([c["subject"] for c in found["commits"]], ["Lamps 0.2.0: brighter", "Lamps 0.1.0"])
            self.assertEqual(found["commits"][0]["entries"], [
                {"changelog": "CHANGELOG.md", "product": "Lamps", "text": "**Brighter.** Lamps shine brighter."}])
            code, found = run(["history", "--root", str(root), "--node", "cs:Sample.Lamps.CompGlow"], tmp)
            self.assertEqual((code, found["ok"]), (1, False))

    def test_what_is_not_a_thing_or_a_commit_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = repository(tmp)
            code, found = run(["around", "--root", str(root), "--node", "cs:Nothing.Here"], tmp)
            self.assertEqual((code, found["ok"]), (1, False))
            code, found = run(["around", "--root", str(root), "--node=--all"], tmp)
            self.assertEqual(code, 1)
            code, found = run(["changed", "--root", str(root), "--commit", "HEAD~1"], tmp)
            self.assertEqual(code, 1)


@unittest.skipUnless(HAVE_DOTNET or REQUIRE, "the .NET SDK is not installed")
class ExactTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        out = native.build_dir() / "dotnet" / "fixtures" / "ConnectionsFixture"
        result = subprocess.run(["dotnet", "build", str(FIXTURE / "ConnectionsFixture.csproj"), "-c", "Release", "-o", str(out),
                                 "--nologo", "-v", "q"], capture_output=True, text=True, check=False)
        if result.returncode != 0:
            raise AssertionError("the fixture did not build:\n" + result.stdout[-2000:])
        cls.dll = out / "ConnectionsFixture.dll"

    def repository(self, tmp):
        root = Path(tmp) / "repo"
        write(root / "src" / "ConnectionsFixture.csproj", (FIXTURE / "ConnectionsFixture.csproj").read_text(encoding="utf-8"))
        write(root / "src" / "Fixture.cs", (FIXTURE / "Fixture.cs").read_text(encoding="utf-8"))
        (root / "mods" / "Sample" / "Assemblies").mkdir(parents=True)
        shutil.copy(self.dll, root / "mods" / "Sample" / "Assemblies" / "ConnectionsFixture.dll")
        return root

    def test_calls_are_read_exactly_and_placed_in_the_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self.repository(tmp)
            code, summary = run(["summary", "--root", str(root)], tmp)
            self.assertIn("exact", summary["readers"][0]["how"])
            _, tick = run(["around", "--root", str(root), "--node", "cs:Sample.Boats.Boat.Tick"], tmp)
            groups = relations(tick)
            self.assertEqual(groups["calls"], ["cs:Sample.Boats.Harbour.Count", "cs:Sample.Boats.Harbour.Moor"])
            self.assertEqual(groups["overrides"], ["cs:Sample.Boats.Vessel.Tick"])
            self.assertEqual(groups["uses"], ["cs:Sample.Boats.Boat.crew", "cs:Sample.Boats.Boat.oars"])
            self.assertEqual(groups["belongs-to"], ["cs:Sample.Boats.Boat"])
            self.assertEqual(tick["centre"]["file"], "src/Fixture.cs")
            self.assertTrue(all(g["exact"] for g in tick["groups"]))

    def test_an_iterator_and_a_property_count_as_their_own(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self.repository(tmp)
            _, gather = run(["around", "--root", str(root), "--node", "cs:Sample.Boats.Boat.Gather"], tmp)
            self.assertEqual(relations(gather)["calls"], ["cs:Sample.Boats.Harbour.Count"])
            _, moor = run(["around", "--root", str(root), "--node", "cs:Sample.Boats.Harbour.Moor"], tmp)
            self.assertEqual(relations(moor)["calls"], ["cs:Sample.Boats.Boat.Label"])
            self.assertEqual(relations(moor)["called-by"], ["cs:Sample.Boats.Boat.Tick"])
            _, boat = run(["around", "--root", str(root), "--node", "cs:Sample.Boats.Boat"], tmp)
            self.assertEqual(relations(boat)["builds-on"], ["cs:Sample.Boats.Vessel"])


if __name__ == "__main__":
    unittest.main()
