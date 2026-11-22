"""What each mod's code builds on (1.84.0): the reader's `refs`, its cache, the RimWorld rules made from it, the check that flags
them, and libraries first in a full re-sort. Nothing reads a real install."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

import support
from phobos_modkit import assembly_refs, assemblies
from phobos_modkit import mod_list as core
from phobos_modkit import mod_sort
from phobos_modkit.games.rimworld.mod_list import RimWorld

from test_mod_list import FakeRimWorld, about
from test_mod_sort import mod, sort


class FakeRun:
    """Stands in for the reader: answers `refs` from a table of {file name: (assembly, references, inherits)}."""

    def __init__(self, table):
        self.table = table
        self.calls = 0

    def __call__(self, command, capture_output=True, check=False):
        self.calls += 1
        listing = Path(command[2][1:]).read_text(encoding="utf-8").splitlines()
        lines = []
        for path in listing:
            name = Path(path).name
            if name in self.table:
                assembly, references, inherits = self.table[name]
                lines.append(json.dumps({"path": path, "assembly": assembly, "references": references, "inherits": inherits}))
            else:
                lines.append(json.dumps({"path": path, "error": "no .NET metadata (a native DLL)"}))
        return subprocess.CompletedProcess(command, 0, "\n".join(lines).encode("utf-8"), b"")


class Reading(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.environ = support.isolated_environ(self.tmp.name, PHOBOS_MODKIT_CACHE=str(Path(self.tmp.name) / "cache"))
        self.dll = Path(self.tmp.name) / "Mine.dll"
        self.dll.write_bytes(b"MZ not really")
        (Path(self.tmp.name) / "Native.dll").write_bytes(b"MZ")

    def tearDown(self):
        self.tmp.cleanup()

    def test_answers_are_kept_per_file_version_and_native_files_left_out(self):
        run = FakeRun({"Mine.dll": ("Mine", ["PipeSystem", "System.Runtime"], ["PipeSystem"])})
        files = [self.dll, Path(self.tmp.name) / "Native.dll"]
        found = assembly_refs.read_references(files, self.environ, run, reader="reader")
        self.assertEqual(list(found), [str(self.dll)])
        self.assertEqual(found[str(self.dll)]["inherits"], ["PipeSystem"])
        assembly_refs.read_references(files, self.environ, run, reader="reader")
        self.assertEqual(run.calls, 1)
        self.dll.write_bytes(b"MZ changed and longer")
        assembly_refs.read_references(files, self.environ, run, reader="reader")
        self.assertEqual(run.calls, 2)


class RimWorldRules(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.fake = FakeRimWorld(self.tmp.name, ["ludeon.rimworld", "example.hostel", "example.market", "example.library"])
        self.environ = self.fake.environ(self.tmp.name)
        self.environ["PHOBOS_MODKIT_CACHE"] = str(Path(self.tmp.name) / "cache")
        workshop = self.fake.workshop
        # Market's compat folder loads only while Library is active; its class builds on Library's.
        (workshop / "1000000001" / "LoadFolders.xml").write_text(
            '<loadFolders><v1.7><li>/</li><li IfModActive="example.library">Compat/Library</li></v1.7></loadFolders>',
            encoding="utf-8")
        for folder, name in (("1000000001/Compat/Library/Assemblies", "MarketCompat.dll"),
                             ("1000000004/Assemblies", "Library.dll"), ("1000000002/Assemblies", "Hostel.dll")):
            (workshop / folder).mkdir(parents=True, exist_ok=True)
            (workshop / folder / name).write_bytes(b"MZ")
        self.run = FakeRun({"MarketCompat.dll": ("MarketCompat", ["Library", "Hostel"], ["Library"]),
                            "Library.dll": ("Library", [], []), "Hostel.dll": ("Hostel", [], [])})

    def tearDown(self):
        self.tmp.cleanup()

    def adapter(self):
        adapter = RimWorld(self.environ)
        return adapter

    def rules(self):
        from phobos_modkit import assembly_refs as refs
        original = refs.read_references
        try:
            refs.read_references = lambda paths, environ=None, run=None, reader=None: original(paths, environ, self.run, "reader")
            return self.adapter().code_rules()
        finally:
            refs.read_references = original

    def test_a_class_built_on_another_mods_class_makes_a_rule_and_a_call_inside_a_method_does_not(self):
        rules = self.rules()
        self.assertEqual([other for other, _ in rules["example.market"]["after"]], ["example.library"])
        self.assertIn("builds on classes from Library", rules["example.market"]["after"][0][1])
        self.assertNotIn("example.hostel", [other for other, _ in rules["example.market"]["after"]])

    def test_the_check_calls_it_a_problem_when_the_order_is_wrong(self):
        rules = self.rules()
        adapter = self.adapter()
        installed = core.Installed(adapter, adapter.installed())
        problems = core.check(adapter, adapter.lists()[0], installed, {}, code_rules=rules)
        found = [p for p in problems if "whose classes its code builds on" in p.title]
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].severity, core.PROBLEM)
        self.assertIn("Neither mod says so", found[0].why)


class LibrariesFirst(unittest.TestCase):
    def test_a_full_resort_puts_the_most_used_library_first_after_the_game(self):
        mods = [mod("core", source="game", name="Core"), mod("apple", needs=["zlib"], name="Apple"),
                mod("berry", needs=["zlib", "ylib"], name="Berry"), mod("zlib", name="Zlib"), mod("ylib", name="Ylib"),
                mod("cherry", name="Cherry")]
        found = sort(["apple", "berry", "cherry", "core", "ylib", "zlib"], mods, how=mod_sort.FULL)
        self.assertEqual(found["ids"], ["core", "zlib", "ylib", "apple", "berry", "cherry"])


@unittest.skipUnless(shutil.which("dotnet"), "the .NET SDK builds the reader")
class TheRealReader(unittest.TestCase):
    def test_refs_names_the_assembly_what_it_references_and_what_its_types_inherit_from(self):
        from test_rimworld_patches import fixture_dll
        dll = fixture_dll()
        tool = assemblies.ensure_reader()
        result = subprocess.run([str(tool), "refs", str(dll)], capture_output=True, check=False)
        record = json.loads(result.stdout.decode("utf-8").splitlines()[0])
        self.assertEqual(record["assembly"], "PatchFixture")
        self.assertTrue(record["references"])
        self.assertTrue(set(record["inherits"]) <= set(record["references"]))
        self.assertTrue(record["inherits"], "every class inherits from something in another assembly")


if __name__ == "__main__":
    unittest.main()
