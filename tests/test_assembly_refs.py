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


class LibraryCopies(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.fake = FakeRimWorld(self.tmp.name, ["ludeon.rimworld", "example.hostel", "example.market", "example.library"])
        self.environ = self.fake.environ(self.tmp.name)
        self.environ["PHOBOS_MODKIT_CACHE"] = str(Path(self.tmp.name) / "cache")
        for folder in ("1000000002/Assemblies", "1000000001/Assemblies", "1000000004/Assemblies"):
            (self.fake.workshop / folder).mkdir(parents=True, exist_ok=True)
        (self.fake.workshop / "1000000002/Assemblies/Shared.dll").write_bytes(b"MZ old")
        (self.fake.workshop / "1000000001/Assemblies/Shared.dll").write_bytes(b"MZ new copy")
        (self.fake.workshop / "1000000004/Assemblies/Library.dll").write_bytes(b"MZ")
        self.versions = {"1000000002": "1.0.0.0", "1000000001": "2.0.0.0"}

    def tearDown(self):
        self.tmp.cleanup()

    def run_reader(self, command, capture_output=True, check=False):
        listing = Path(command[2][1:]).read_text(encoding="utf-8").splitlines()
        lines = []
        for path in listing:
            item = Path(path).parent.parent.name
            name = Path(path).stem
            lines.append(json.dumps({"path": path, "assembly": name, "version": self.versions.get(item, "1.0.0.0"),
                                     "references": [], "inherits": []}))
        return subprocess.CompletedProcess(command, 0, "\n".join(lines).encode("utf-8"), b"")

    def copies(self):
        from phobos_modkit import assembly_refs as refs
        original = refs.read_references
        try:
            refs.read_references = lambda paths, environ=None, run=None, reader=None: original(paths, environ, self.run_reader,
                                                                                               "reader")
            return RimWorld(self.environ).library_copies()
        finally:
            refs.read_references = original

    def test_an_older_copy_loading_first_is_found_and_noted(self):
        found = self.copies()
        self.assertEqual(len(found), 1)
        self.assertEqual((found[0]["first"]["name"], found[0]["newest"]["name"]), ("Hostel", "Market"))
        adapter = RimWorld(self.environ)
        problems = core.check(adapter, adapter.lists()[0], core.Installed(adapter, adapter.installed()), {},
                              library_copies=found)
        noted = [p for p in problems if p.kind == "library"]
        self.assertEqual(noted[0].severity, core.NOTE)
        self.assertIn("older Shared (1.0.0.0)", noted[0].title)

    def test_the_newest_loading_first_is_no_clash(self):
        self.versions = {"1000000002": "3.0.0.0", "1000000001": "2.0.0.0"}
        self.assertEqual(self.copies(), [])


class Groups(unittest.TestCase):
    """Groups as RimSort's tiers (1.86.0): frameworks lead and take in what they must load after; top means the group."""

    def setUp(self):
        from test_mod_sort import Plain
        Plain.known_frameworks = ("vef",)
        self.addCleanup(lambda: delattr(Plain, "known_frameworks"))

    def test_a_framework_leads_a_full_resort_and_takes_what_it_must_follow_along(self):
        mods = [mod("core", source="game", name="Core"), mod("apple", needs=["vef"], name="Apple"),
                mod("vef", name="Vanilla Expanded Framework"), mod("bg", before=["vef"], name="Backgrounds"),
                mod("zed", name="Zed")]
        found = sort(["apple", "zed", "core", "bg", "vef"], mods, how=mod_sort.FULL)
        self.assertEqual(found["ids"], ["core", "bg", "vef", "apple", "zed"])

    def test_each_group_move_names_its_own_reason(self):
        mods = [mod("core", source="game", name="Core"), mod("apple", name="Apple"), mod("mid", name="Mid"),
                mod("zed", name="Zed"), mod("vef", name="Vanilla Expanded Framework"), mod("bg", before=["vef"], name="Backgrounds")]
        found = sort(["core", "apple", "mid", "zed", "bg", "vef"], mods, how=mod_sort.FULL)
        self.assertEqual(found["ids"], ["core", "bg", "vef", "apple", "mid", "zed"])
        why = {m["key"]: m["why"][0] for m in found["moves"] if m["kind"] == mod_sort.GROUP_MOVE}
        self.assertIn("Vanilla Expanded Framework: it is a known framework, so it goes in the frameworks' group", why["vef"])
        self.assertIn("Backgrounds: Vanilla Expanded Framework loads after it (Vanilla Expanded Framework: it is a known "
                      "framework)", why["bg"])

    def test_a_reason_follows_the_links_back_to_the_framework(self):
        mods = [mod("core", source="game", name="Core"), mod("apple", name="Apple"), mod("mid", name="Mid"),
                mod("zed", name="Zed"), mod("des", before=["ce"], name="Deserters"),
                mod("ce", before=["vef"], name="Combat Extended"), mod("vef", name="Vanilla Expanded Framework")]
        found = sort(["core", "apple", "mid", "zed", "des", "ce", "vef"], mods, how=mod_sort.FULL)
        self.assertEqual(found["ids"], ["core", "des", "ce", "vef", "apple", "mid", "zed"])
        why = {m["key"]: m["why"][0] for m in found["moves"]}
        self.assertIn("Deserters: Combat Extended loads after it, and Vanilla Expanded Framework after Combat Extended "
                      "(Vanilla Expanded Framework: it is a known framework)", why["des"])

    def test_mods_already_in_their_group_keep_their_order_inside_it(self):
        # 1.141.0: they used to change places by name; now nothing moves a mod no rule places.
        from test_mod_sort import Plain
        Plain.known_frameworks = ("vef", "hugs")
        mods = [mod("core", source="game", name="Core"), mod("vef", name="Vanilla Expanded Framework"),
                mod("hugs", name="HugsLib"), mod("apple", name="Apple")]
        found = sort(["core", "vef", "hugs", "apple"], mods, how=mod_sort.FULL)
        self.assertEqual(found["ids"], ["core", "vef", "hugs", "apple"])
        self.assertEqual([], found["moves"])

    def test_a_mod_others_code_builds_on_is_not_pulled_up_with_the_frameworks(self):
        code = mod_sort.RuleSet(mod_sort.CODE, "Code", "here",
                                {"addon": {"after": [("bigmod", "")], "before": [], "top": None, "bottom": None}})
        mods = [mod("core", source="game", name="Core"), mod("apple", name="Apple"), mod("bigmod", name="Big Mod"),
                mod("addon", name="Addon")]
        found = sort(["core", "apple", "bigmod", "addon"], mods, [code], how=mod_sort.FULL)
        self.assertEqual(found["ids"], ["core", "apple", "bigmod", "addon"])
        self.assertEqual(found["moves"], [])

    def test_a_frameworks_needs_make_no_order_rule(self):
        mods = [mod("vef", needs=["apple"], name="Vanilla Expanded Framework"), mod("apple", name="Apple")]
        found = sort(["vef", "apple"], mods)
        self.assertEqual(found["moves"], [])
        self.assertEqual(found["rules"]["needs"], 0)

    def test_top_means_the_group_so_a_top_mod_among_frameworks_stays(self):
        top = mod_sort.RuleSet(mod_sort.YOURS, "Your rules", "here",
                               {"fast": {"after": [], "before": [], "top": "", "bottom": None}})
        mods = [mod("core", source="game"), mod("vef", name="Vanilla Expanded Framework"), mod("fast"), mod("x")]
        found = sort(["core", "vef", "fast", "x"], mods, [top])
        self.assertEqual(found["moves"], [])

    def test_workshop_requirements_give_way_even_to_the_community(self):
        community = mod_sort.RuleSet(mod_sort.COMMUNITY, "Community", "here",
                                     {"a": {"after": [("b", "")], "before": [], "top": None, "bottom": None}})
        workshop = mod_sort.RuleSet(mod_sort.WORKSHOP, "Workshop", "here",
                                    {"b": {"after": [("a", "")], "before": [], "top": None, "bottom": None}})
        found = sort(["a", "b"], [mod("a"), mod("b")], [community, workshop])
        self.assertEqual(found["ids"], ["b", "a"])
        self.assertEqual(found["set_aside"][0]["source"], "workshop")


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
