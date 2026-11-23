"""doc-tables: generated tables of projects, Harmony patches and mod requirements, from hand-written files in a temp folder."""
import io
import json
from pathlib import Path
import tempfile
import unittest

import support  # noqa: F401  (puts the package on the path)
from phobos_modkit import command_docs, doc_tables, dotnet_projects, generated_blocks
from phobos_modkit.code import harmony

PATCHES = '''using HarmonyLib;
using Verse;

namespace Example
{
    // [HarmonyPatch(typeof(Commented), "Out")] is a comment, never a patch
    [HarmonyPatch(typeof(Pawn), "Kill")]
    static class KillPatch
    {
        static void Prefix() { }
        static void Postfix() { }
    }

    [HarmonyPatch(typeof(Pawn), nameof(Pawn.Drafted), MethodType.Getter)]
    static class DraftedPatch
    {
        [HarmonyPostfix]
        static void After() { }
    }

    [HarmonyPatch(typeof(Thing))]
    static class SplitPatch
    {
        [HarmonyPatch("TakeDamage", new[] { typeof(DamageInfo) })]
        static bool Prefix() => true;

        [HarmonyPatch(nameof(Thing.Destroy), typeof(DestroyMode))]
        static void Finalizer() { }
    }

    [HarmonyPatch(typeof(Building), MethodType.Constructor)]
    static class BuildingMade { static void Postfix() { } }

    [HarmonyPatch]
    static class ByName
    {
        static System.Reflection.MethodBase TargetMethod() => AccessTools.Method("Other.Mod:Hidden");
        static void Postfix() { }
    }

    [HarmonyPatch(typeof(Pawn), Names.Tick)]
    static class Unknown { static void Prefix() { } }

    static class Manual
    {
        static void Apply(Harmony harmony)
        {
            harmony.Patch(AccessTools.Method("A:B"), prefix: new HarmonyMethod(typeof(Manual), "P"));
            harmony.CreateClassProcessor(typeof(Manual)).Patch();
        }
    }

    static class NotAPatch { static void Prefix() { } }
}
'''

PROJECT = '''<Project Sdk="Microsoft.NET.Sdk">
  <PropertyGroup>
    <ModFolder>{mod}</ModFolder>
    {tie_in}
  </PropertyGroup>
  <ItemGroup>
    {refs}
    <Reference Include="Other, Version=1.0.0.0, Culture=neutral">
      <HintPath>$(OtherAssemblies)\\Other.dll</HintPath>
    </Reference>
  </ItemGroup>
</Project>
'''

TESTS = '''<Project Sdk="Microsoft.NET.Sdk">
  <ItemGroup>
    <Compile Include="../../src/Core/Rules/*.cs" Link="Rules/%(Filename)%(Extension)" />
    <ProjectReference Include="..\\..\\src\\TieIn\\TieIn.csproj" />
  </ItemGroup>
</Project>
'''

ABOUT = '''<?xml version="1.0" encoding="utf-8"?>
<ModMetaData>
  <packageId>Example.Core</packageId>
  <name>Example Core</name>
  <supportedVersions><li>1.6</li><li>1.7</li></supportedVersions>
  <modDependencies>
    <li><packageId>brrainz.harmony</packageId><displayName>Harmony</displayName></li>
  </modDependencies>
  <loadAfter><li>Old.Mod</li></loadAfter>
  <loadAfterByVersion><v1.7><li>brrainz.harmony</li><li>Some.Author.Thing</li></v1.7></loadAfterByVersion>
  <loadBefore><li>Example.Extra</li></loadBefore>
</ModMetaData>
'''

LOAD_FOLDERS = '''<loadFolders>
  <v1.6><li>/</li><li IfModActive="Old.Mod">Mods/Old</li></v1.6>
  <v1.7>
    <li>/</li>
    <li IfModActive="Some.Author.Thing">Mods/Thing</li>
    <li IfModActive="Some.Author.Thing">Mods/Thing/1.7</li>
    <li IfModActiveAll="Some.Author.Thing,brrainz.harmony">Mods/Both</li>
    <li IfModActive="A.One,B.Two">Mods/Either</li>
    <li IfModNotActive="Some.Author.Thing">Mods/Without</li>
  </v1.7>
</loadFolders>
'''


def write(path, text, newline="\n"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.replace("\n", newline).encode("utf-8"))


class Repo:
    """A made-up repository: two projects, a test project, a mod, two docs and a config."""

    def __init__(self, root):
        self.root = Path(root)
        write(self.root / "src/Core/Core.csproj", PROJECT.format(mod="Core", tie_in="", refs=""))
        write(self.root / "src/Core/Rules/Rule.cs", "namespace Example { static class Rule { } }\n")
        write(self.root / "src/Core/Patches.cs", PATCHES)
        write(self.root / "src/TieIn/TieIn.csproj", PROJECT.format(
            mod="Core", tie_in="<TieInFolder>Mods/Thing/</TieInFolder>",
            refs='<ProjectReference Include="../Core/Core.csproj" Private="false" />'))
        write(self.root / "src/TieIn/Plain.cs", "namespace Example { class Plain { } }\n")
        write(self.root / "tests/Core.Tests/Core.Tests.csproj", TESTS)
        write(self.root / "mods/Core/About/About.xml", ABOUT)
        write(self.root / "mods/Core/LoadFolders.xml", LOAD_FOLDERS)
        write(self.root / "mods/NotAMod/readme.txt", "no About.xml here\n")
        write(self.root / "docs/building.md", "# Building\n\n<!-- generated: table dotnet-projects -->\nold\n<!-- end generated -->\n\nAfter.\n",
              "\r\n")
        write(self.root / "docs/players.md", "# Players\n\nWords of its own.\n")
        self.config({"schemaVersion": 1, "run": "python scripts/doc-tables.py --write", "tables": [
            {"doc": "docs/building.md", "kind": "dotnet-projects",
             "options": {"folders": ["src"], "testFolders": ["tests"], "output": "mods/{ModFolder}/{TieInFolder}"}},
            {"doc": "docs/building.md", "kind": "harmony-patches", "options": {"folders": ["src"]}},
            {"doc": "docs/players.md", "kind": "mod-requirements",
             "options": {"game": "rimworld", "folders": ["mods"], "names": {"some.author.thing": "Some Thing"}}}]})

    def config(self, data):
        write(self.root / "config/doc-tables.json", json.dumps(data))

    def run(self, *argv):
        out = io.StringIO()
        code = doc_tables.main(["--root", str(self.root), "--json", *argv], out=out)
        return code, json.loads(out.getvalue())

    def text(self, path):
        return (self.root / path).read_bytes().decode("utf-8")


class Blocks(unittest.TestCase):
    def test_command_docs_uses_the_shared_mechanism(self):
        self.assertIs(command_docs.replace_block, generated_blocks.replace_block)
        self.assertIs(command_docs.write, generated_blocks.write_changed)
        self.assertEqual(command_docs.start("x"), generated_blocks.start("x"))

    def test_replace_keeps_the_rest(self):
        text = "a\n<!-- generated: k -->\nold\n<!-- end generated -->\nb\n"
        self.assertEqual(generated_blocks.replace_block(text, "k", ["new", "lines"]),
                         ("a\n<!-- generated: k -->\nnew\nlines\n<!-- end generated -->\nb\n", True))
        self.assertEqual(generated_blocks.replace_block(text, "other", ["x"]), (text, False))
        self.assertEqual(generated_blocks.keys(text), ["k"])


class HarmonyReader(unittest.TestCase):
    def setUp(self):
        self.found = harmony.read_source(PATCHES, "Patches.cs")
        self.targets = {p.target: p.kinds for p in self.found.patches}

    def test_class_attributes_name_the_target_and_method_names_the_kinds(self):
        self.assertEqual(self.targets["Pawn.Kill"], ("prefix", "postfix"))

    def test_getters_and_marked_methods(self):
        self.assertEqual(self.targets["Pawn.Drafted (getter)"], ("postfix",))

    def test_class_and_method_attributes_combine_and_argument_types_are_ignored(self):
        self.assertEqual(self.targets["Thing.TakeDamage"], ("prefix",))
        self.assertEqual(self.targets["Thing.Destroy"], ("finalizer",))

    def test_constructors(self):
        self.assertEqual(self.targets["Building (constructor)"], ("postfix",))

    def test_target_method_is_by_name(self):
        self.assertEqual(self.targets["by name in TargetMethod"], ("postfix",))

    def test_comments_and_plain_classes_are_not_patches(self):
        self.assertNotIn("Commented.Out", self.targets)
        self.assertEqual(len(self.found.patches), 6)

    def test_an_unknown_form_is_listed_with_its_line(self):
        self.assertEqual(len(self.found.unread), 1)
        unread = self.found.unread[0]
        self.assertEqual((unread.file, unread.line), ("Patches.cs", PATCHES.split("\n").index(
            "    [HarmonyPatch(typeof(Pawn), Names.Tick)]") + 1))
        self.assertIn("Names.Tick", unread.text)

    def test_manual_patch_calls_are_counted_but_not_class_processors(self):
        self.assertEqual(len(self.found.manual), 1)

    def test_uses_harmony(self):
        self.assertTrue(harmony.uses_harmony("using HarmonyLib;\nclass A { }"))
        self.assertFalse(harmony.uses_harmony("// using HarmonyLib;\nclass A { }"))


class Projects(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.repo = Repo(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_reads_properties_references_and_tests(self):
        found = {p.name: p for p in dotnet_projects.read_projects(self.repo.root, ["src"])}
        tests = dotnet_projects.read_projects(self.repo.root, ["tests"])
        self.assertEqual(list(found), ["Core", "TieIn"])
        self.assertEqual(found["TieIn"].project_refs, ["src/Core/Core.csproj"])
        self.assertEqual(found["Core"].references, ["Other"])
        self.assertTrue(found["Core"].harmony)
        self.assertFalse(found["TieIn"].harmony)
        self.assertEqual(dotnet_projects.fill("mods/{ModFolder}/{TieInFolder}", found["TieIn"].properties), "mods/Core/Mods/Thing/")
        self.assertEqual(dotnet_projects.tests_of(found["Core"], tests), ["Core.Tests"])
        self.assertEqual(dotnet_projects.tests_of(found["TieIn"], tests), ["Core.Tests"])
        self.assertIsNone(dotnet_projects.fill("{Missing}/x", {}))


class Command(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.repo = Repo(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_check_fails_then_write_fills_then_check_passes(self):
        code, data = self.repo.run()
        self.assertEqual(code, doc_tables.EXIT_FAILED)
        states = {d["path"]: d["state"] for d in data["data"]["docs"]}
        self.assertEqual(states, {"docs/building.md": "block missing", "docs/players.md": "block missing"})
        self.assertEqual(self.repo.text("docs/players.md"), "# Players\n\nWords of its own.\n")
        code, data = self.repo.run("--write")
        self.assertEqual(code, doc_tables.EXIT_OK)
        self.assertEqual(sorted(data["data"]["written"]), ["docs/building.md", "docs/players.md"])
        self.assertEqual(self.repo.run()[0], doc_tables.EXIT_OK)

    def test_projects_table_in_place_keeping_line_endings(self):
        self.repo.run("--write")
        text = self.repo.text("docs/building.md")
        self.assertIn("\r\n", text)
        self.assertNotIn("\nold\r\n", text.replace("\r\n", "\n"))
        lines = text.replace("\r\n", "\n").split("\n")
        self.assertIn("| `Core` | `mods/Core/` | none | `Other` | yes | `Core.Tests` |", lines)
        self.assertIn("| `TieIn` | `mods/Core/Mods/Thing/` | `Core` | `Other` | no | `Core.Tests` |", lines)
        self.assertLess(text.index("table dotnet-projects"), text.index("After."))
        self.assertGreater(text.index("table harmony-patches"), text.index("After."))
        self.assertIn("`python scripts/doc-tables.py --write`", text)

    def test_patch_list(self):
        code, data = self.repo.run("--write")
        text = self.repo.text("docs/building.md").replace("\r\n", "\n")
        self.assertIn("| `Core` | 5 | 1 | 1 | 1 |", text)
        self.assertIn("| `Pawn.Kill` | prefix, postfix | `Patches.cs` |", text)
        self.assertIn("- `src/Core/Patches.cs:", text)
        unread = [t for t in data["data"]["tables"] if t["kind"] == "harmony-patches"][0]["found"]["unread"]
        self.assertEqual(len(unread), 1)
        self.assertIn("Harmony attributes not read", [s["heading"] for s in data["report"]["sections"]])

    def test_requirements_through_the_adapter(self):
        self.repo.run("--write")
        text = self.repo.text("docs/players.md")
        self.assertTrue(text.startswith("# Players\n\nWords of its own.\n\n## What each mod needs\n"))
        row = next(line for line in text.split("\n") if line.startswith("| Example Core"))
        cells = [c.strip() for c in row.strip("|").split("|")]
        self.assertEqual(cells[:4], ["Example Core", "`Example.Core`", "Harmony", "Harmony, Some Thing"])  # 1.7's list replaces
        self.assertEqual(cells[4:6], ["`Example.Extra`", "1.6, 1.7"])
        self.assertEqual(cells[6], "`A.One` or `B.Two`, not Some Thing, Some Thing, Some Thing and Harmony")

    def test_a_game_without_an_adapter_says_so(self):
        config = json.loads(self.repo.text("config/doc-tables.json"))
        config["tables"][2]["options"]["game"] = "project-zomboid"
        self.repo.config(config)
        code, data = self.repo.run("--write")
        self.assertEqual(code, doc_tables.EXIT_OK)
        self.assertIn("No game adapter reads project-zomboid's mod requirements yet", self.repo.text("docs/players.md"))
        self.assertIn("Tables that say they cannot be made", [s["heading"] for s in data["report"]["sections"]])

    def test_config_problems_fail(self):
        self.repo.config({"schemaVersion": 1, "tables": [{"doc": "docs/players.md", "kind": "no-such-kind"},
                                                         {"doc": "docs/gone.md", "kind": "harmony-patches"}]})
        code, data = self.repo.run("--write")
        self.assertEqual(code, doc_tables.EXIT_FAILED)
        self.assertEqual(len(data["data"]["problems"]), 2)
        self.repo.config({"schemaVersion": 2, "tables": []})
        self.assertEqual(self.repo.run()[0], doc_tables.EXIT_FAILED)


if __name__ == "__main__":
    unittest.main()
