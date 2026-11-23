"""connections names: what every name in one C# file is, and where it is declared (the names reader, Roslyn).

The listing of a project's files is tested against MSBuild's answer as stand-in text; the reader itself is built and run on a
hand-written two-project fixture when the .NET SDK is installed, and the tests fail rather than skip when PHOBOS_REQUIRE_NATIVE is
set, as for the other native tools."""
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

import support  # noqa: F401  (puts the package on the path)

from phobos_modkit import code_names, connections_cli

HAVE_DOTNET = shutil.which("dotnet") is not None
REQUIRE = bool(os.environ.get("PHOBOS_REQUIRE_NATIVE"))
FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "dotnet" / "NamesFixture"


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


class Answered:
    def __init__(self, stdout, returncode=0, stderr=""):
        self.stdout, self.returncode, self.stderr = stdout, returncode, stderr


def msbuild_answer(root):
    return json.dumps({
        "Properties": {"AssemblyName": "Sample.Mod", "LangVersion": "latest", "Nullable": "enable",
                       "DefineConstants": "TRACE;DEBUG", "AllowUnsafeBlocks": "true"},
        "Items": {
            "Compile": [{"FullPath": str(root / "src" / "Mod" / "Sail.cs")},
                        {"FullPath": str(root / "src" / "Mod" / "Notes.txt")}],
            "ReferencePath": [
                {"FullPath": "C:/game/Assembly-CSharp.dll"},
                {"FullPath": str(root / "src" / "Core" / "bin" / "Core.dll"), "ReferenceSourceTarget": "ProjectReference",
                 "MSBuildSourceProjectFile": str(root / "src" / "Core" / "Core.csproj")}],
            "ProjectReference": [{"FullPath": str(root / "src" / "Core" / "Core.csproj")}]}})


class ListingTests(unittest.TestCase):
    def test_the_project_holding_a_file_most_closely_is_found(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write(root / "src" / "All.csproj", "<Project/>")
            write(root / "src" / "Mod" / "Mod.csproj", "<Project/>")
            self.assertEqual(code_names.project_for(root, "src/Mod/Deep/Sail.cs").name, "Mod.csproj")
            self.assertEqual(code_names.project_for(root, "src/Other/Thing.cs").name, "All.csproj")
            self.assertIsNone(code_names.project_for(root, "docs/Thing.cs"))

    def test_msbuilds_list_becomes_the_readers_request(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            asked = []

            def run(command, **_):
                asked.append(command)
                return Answered("MSBuild says hello\n" + msbuild_answer(root))

            found = code_names.describe(root / "src" / "Mod" / "Mod.csproj", run)
            self.assertEqual(found["name"], "Sample.Mod")
            self.assertEqual(found["sources"], [str(root / "src" / "Mod" / "Sail.cs")])
            self.assertEqual(found["references"][0], {"path": "C:/game/Assembly-CSharp.dll", "project": None})
            self.assertEqual(found["references"][1]["project"], str(root / "src" / "Core" / "Core.csproj"))
            self.assertTrue(found["allowUnsafe"])
            self.assertIn("-p:BuildProjectReferences=false", asked[0])
            self.assertNotIn("-restore", asked[0])

    def test_a_project_never_restored_is_restored_then_listed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            answers = [Answered("error NETSDK1004: Assets file not found", 1), Answered(msbuild_answer(root))]
            asked = []

            def run(command, **_):
                asked.append(command)
                return answers.pop(0)

            code_names.describe(root / "Mod.csproj", run)
            self.assertEqual(len(asked), 2)
            self.assertIn("-restore", asked[1])

    def test_what_is_not_c_sharp_or_outside_the_repository_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for file, words in (("src/Defs.xml", "is not C#"), ("../elsewhere/A.cs", "not inside the repository"),
                                ("src/Loose.cs", "No C# project")):
                with self.assertRaises(code_names.NamesError) as caught:
                    code_names.read(root, file, run=lambda *a, **k: Answered(""))
                self.assertIn(words, str(caught.exception))

    def test_a_commit_that_is_not_one_is_refused(self):
        out = io.StringIO()
        code = connections_cli.main(["names", "--root", ".", "--file", "A.cs", "--commit=--all", "--json"], {}, out)
        self.assertEqual(code, 1)
        self.assertFalse(json.loads(out.getvalue())["data"]["ok"])


@unittest.skipUnless(HAVE_DOTNET or REQUIRE, "the .NET SDK is not installed")
class ReaderTests(unittest.TestCase):
    def repository(self, tmp):
        root = Path(tmp) / "repo"
        shutil.copytree(FIXTURE, root / "src")
        return root

    def names(self, found):
        return {(n["text"], n["line"]): n for n in found["names"]}

    def test_every_name_is_read_and_a_name_from_the_other_project_is_placed_in_its_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self.repository(tmp)
            found = code_names.read(root, "src/Mod/Sail.cs")
            self.assertEqual((found["file"], found["errors"]), ("src/Mod/Sail.cs", 0))
            self.assertEqual(found["projects"], ["NamesFixture.Mod", "NamesFixture.Core"])
            names = self.names(found)
            boat = names[("Boat", 7)]
            self.assertEqual((boat["kind"], boat["declared"]["file"], boat["declared"]["line"]), ("class", "src/Core/Boat.cs", 3))
            self.assertEqual(names[("Float", 10)]["kind"], "method")
            self.assertEqual(names[("Float", 10)]["display"], "Boat.Float(int)")
            self.assertEqual(names[("Float", 10)]["id"], "M:NamesFixture.Core.Boat.Float(System.Int32)")
            self.assertEqual(names[("load", 10)]["declared"]["line"], 9)
            self.assertEqual(names[("crew", 7)]["kind"], "parameter")
            self.assertTrue(names[("Ready", 7)]["here"])
            self.assertEqual(names[("Length", 10)]["declared"]["assembly"], "System.Runtime")
            # A declaration of this repository comes with its lines, its comment above it included; one inside a method needs none.
            snippet = found["snippets"]["src/Core/Boat.cs:10"]
            self.assertEqual(snippet["lines"][0].strip(), "/// <summary>Whether it floats.</summary>")
            self.assertFalse(any(key.endswith(":9") for key in found["snippets"]))

    def test_at_a_commit_the_file_is_read_as_it_stood(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self.repository(tmp)
            git = ["git", "-c", "user.email=fixture@example.invalid", "-c", "user.name=Fixture", "-c", "core.fsmonitor=false",
                   "-c", "core.autocrlf=false"]
            subprocess.run(git + ["init", "-q"], cwd=root, check=True)
            subprocess.run(git + ["add", "."], cwd=root, check=True)
            subprocess.run(git + ["commit", "-q", "-m", "first"], cwd=root, check=True)
            first = subprocess.run(git + ["rev-parse", "HEAD"], cwd=root, check=True, capture_output=True, text=True).stdout.strip()
            sail = root / "src" / "Mod" / "Sail.cs"
            sail.write_text(sail.read_text(encoding="utf-8").replace("Ready", "Afloat"), encoding="utf-8")
            then = self.names(code_names.read(root, "src/Mod/Sail.cs", first))
            now = self.names(code_names.read(root, "src/Mod/Sail.cs"))
            self.assertIn(("Ready", 7), then)
            self.assertIn(("Afloat", 7), now)

    def test_the_command_says_it_in_words_and_in_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self.repository(tmp)
            out = io.StringIO()
            code = connections_cli.main(["names", "--root", str(root), "--file", "src/Mod/Sail.cs", "--json"], {}, out)
            self.assertEqual(code, 0)
            found = json.loads(out.getvalue())
            self.assertIn("declared in this repository", found["report"]["title"])
            self.assertEqual(found["data"]["file"], "src/Mod/Sail.cs")


if __name__ == "__main__":
    unittest.main()
