"""rimworld-update-check: the window, temporary patches against stand-in compares, update sizes, and our XML patches against a
small hand-made Def index and mod folders (no game, archive or decompiler)."""
from contextlib import closing
from datetime import datetime, timezone
import io
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from xml.etree import ElementTree as ET

import support  # noqa: F401  (the package on the import path)
from phobos_modkit.assembly_archive import Version
from phobos_modkit.code import compare as code_compare
from phobos_modkit.games.rimworld import defs, patched_defs
from phobos_modkit.games.rimworld import update_check_cli as uc

SINCE = "2026-11-19 00:00"


def item(full, kind="method"):
    return code_compare.Item(kind, full.split(".")[-1], full, "", "x.cs", 1, 2)


def version(id_, file, seen, owner="vf", name="Vehicle Framework", text=""):
    return Version(id_, owner, name, file, f"{id_:064x}", 1, text, seen)


class WindowTests(unittest.TestCase):
    def test_since_wins_over_days_and_is_read_as_utc(self):
        now = datetime(2026, 11, 20, 12, 0, tzinfo=timezone.utc)
        self.assertEqual("2026-11-19 10:00", uc.window_start("2026-11-19T10:00:00Z", 7, now))
        self.assertEqual("2026-11-19 10:00", uc.window_start("2026-11-19T21:00:00+11:00", 7, now))
        self.assertEqual("2026-11-13 12:00", uc.window_start(None, 7, now))

    def test_a_bad_moment_is_refused(self):
        with self.assertRaises(uc.UpdateCheckError):
            uc.window_start("yesterday", 7, datetime.now(timezone.utc))

    def test_unknown_parts_are_refused(self):
        self.assertEqual(uc.PARTS, uc._parts(None))
        self.assertEqual(("names", "xml"), uc._parts("names, xml"))
        with self.assertRaises(uc.UpdateCheckError):
            uc._parts("names,colour")


class TemporaryTests(unittest.TestCase):
    def setUp(self):
        self.versions = {
            ("vf", "Vehicles.dll"): [version(1, "Vehicles.dll", "2026-11-10 10:00"), version(2, "Vehicles.dll", "2026-11-19 09:00")],
            ("rp", "RimPacts.dll"): [version(3, "RimPacts.dll", "2026-11-01 10:00", "rp", "RimPacts"),
                                     version(4, "RimPacts.dll", "2026-11-02 10:00", "rp", "RimPacts")],
            ("ir", "IRBM.dll"): [version(5, "IRBM.dll", "2026-11-18 10:00", "ir", "IRBM")],
        }
        self.asked = []

    def compare(self, result):
        def run(older, newer, patterns):
            self.asked.append(patterns)
            return result
        return run

    def entry(self, file="Vehicles.dll", members=("VehiclePawn.DeSpawn",), mod="Vehicle Framework"):
        return {"row": 2, "patch": "VehicleFires", "mod": mod, "file": file, "members": list(members)}

    def test_a_changed_member_says_to_read_the_fault(self):
        change = code_compare.Change(item("Vehicles.VehiclePawn.DeSpawn"), item("Vehicles.VehiclePawn.DeSpawn"), False, "code")
        rows = uc.temporary_rows([self.entry()], self.versions, SINCE, self.compare(([change], [], [])))
        self.assertEqual("changed", rows[0]["status"])
        self.assertEqual(["VehiclePawn.DeSpawn"], rows[0]["changed"])
        self.assertIn("*.vehiclepawn.despawn", self.asked[0])

    def test_an_added_member_counts_as_a_change(self):
        rows = uc.temporary_rows([self.entry(members=["LordJob_ScorpionRaid.*"])], self.versions, SINCE,
                                 self.compare(([], [], [item("VFEC.LordJob_ScorpionRaid.LordJob_ScorpionRaid")])))
        self.assertEqual("changed", rows[0]["status"])

    def test_a_removed_member_says_the_patch_cannot_reach_it(self):
        rows = uc.temporary_rows([self.entry()], self.versions, SINCE, self.compare(([], [item("Vehicles.VehiclePawn.DeSpawn")], [])))
        self.assertEqual("removed", rows[0]["status"])

    def test_untouched_old_and_single_builds(self):
        rows = uc.temporary_rows([self.entry(), self.entry("RimPacts.dll", mod="RimPacts"), self.entry("IRBM.dll", mod="")],
                                 self.versions, SINCE, self.compare(([], [], [])))
        self.assertEqual(["unchanged", "no-update", "one-build"], [r["status"] for r in rows])
        self.assertEqual(1, len(self.asked))          # only the build inside the window is compared

    def test_a_named_mod_must_match_the_archive(self):
        rows = uc.temporary_rows([self.entry(mod="Someone Else")], self.versions, SINCE, self.compare(([], [], [])))
        self.assertEqual("one-build", rows[0]["status"])


class UpdateTests(unittest.TestCase):
    def test_sizes_and_new_types_largest_first(self):
        versions = {("vf", "Vehicles.dll"): [version(1, "Vehicles.dll", "2026-11-10 10:00", text="1.0"),
                                             version(2, "Vehicles.dll", "2026-11-19 09:00", text="1.1")],
                    ("h", "AV8BHarrier.dll"): [version(3, "AV8BHarrier.dll", "2026-11-10 10:00", "h", "Harrier"),
                                               version(4, "AV8BHarrier.dll", "2026-11-20 09:00", "h", "Harrier")],
                    ("o", "Old.dll"): [version(5, "Old.dll", "2026-01-01 10:00", "o", "Old"),
                                       version(6, "Old.dll", "2026-02-01 10:00", "o", "Old")]}
        added = [item("AV8BHarrier.PilotLoss", "class"), item("AV8BHarrier.PilotLoss.Tick"), item("AV8BHarrier.CompHarrier.crashDust", "field")]
        body = code_compare.Change(item("V.A.B"), item("V.A.B"), False, "code")

        def compare_all(older, newer):
            return ([], [], added) if newer.file == "AV8BHarrier.dll" else ([body], [], [])
        rows = uc.update_rows(versions, SINCE, compare_all)
        self.assertEqual(["AV8BHarrier.dll", "Vehicles.dll"], [r["file"] for r in rows])
        self.assertEqual(["PilotLoss"], rows[0]["newTypes"])     # the new type, not each member inside it
        self.assertEqual(3, rows[0]["added"])
        self.assertEqual(1, rows[1]["bodies"])
        self.assertEqual("1.0 to 1.1", rows[1]["versions"])


DEFS_XML = """<Defs>
  <ThingDef><defName>Harrier_Jet</defName><comps><li><compClass>A</compClass></li></comps></ThingDef>
  <RecipeDef><defName>MakeRocket</defName></RecipeDef>
</Defs>"""
OUR_PATCHES = """<Patch>
  <Operation Class="PatchOperationAdd"><xpath>Defs/ThingDef[defName="Harrier_Jet"]/comps</xpath><value><li/></value></Operation>
  <Operation Class="PatchOperationAdd"><xpath>Defs/RecipeDef[defName="MakeRocket"]/recipeUsers</xpath><value><li>X</li></value></Operation>
  <Operation Class="PatchOperationReplace"><xpath>Defs/ThingDef[defName="Gone_Thing"]/label</xpath><value><label>x</label></value></Operation>
  <Operation Class="PatchOperationAdd"><xpath>Defs</xpath><value><ThingDef><defName>OurBombCase</defName></ThingDef></value></Operation>
  <Operation Class="PatchOperationAdd"><xpath>Defs/ThingDef[defName="OurBombCase"]/recipeUsers</xpath><value><li>X</li></value></Operation>
  <Operation Class="PatchOperationConditional"><xpath>Defs/ThingDef[defName="Absent"]</xpath></Operation>
  <Operation Class="PatchOperationFindMod"><mods><li>Not Here</li></mods>
    <match Class="PatchOperationAdd"><xpath>Defs/ThingDef[defName="Elsewhere"]/comps</xpath><value><li/></value></match>
  </Operation>
</Patch>"""
THEIR_PATCHES = """<Patch>
  <Operation Class="PatchOperationAdd"><xpath>Defs/RecipeDef[defName="MakeRocket"]</xpath><value><recipeUsers/></value></Operation>
</Patch>"""


class XmlTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        theirs, ours = root / "Theirs", root / "Ours"
        (theirs / "Defs").mkdir(parents=True)
        (theirs / "Patches").mkdir()
        (ours / "Patches").mkdir(parents=True)
        (theirs / "Defs" / "Things.xml").write_text(DEFS_XML, encoding="utf-8")
        (theirs / "Patches" / "Theirs.xml").write_text(THEIR_PATCHES, encoding="utf-8")
        (ours / "Patches" / "Ours.xml").write_text(OUR_PATCHES, encoding="utf-8")
        self.conn = sqlite3.connect(":memory:")
        self.addCleanup(self.conn.close)
        self.conn.executescript(defs.TABLES)
        self.conn.execute("INSERT INTO mod (position, listed_id, package_id, name, folder, installed) VALUES "
                          "(0, 'them.mod', 'Them.Mod', 'Their Mod', ?, 1), (1, 'phobosdthorga.patches', "
                          "'PhobosDthorga.Patches', 'D''thorga Patches', ?, 1)", (str(theirs), str(ours)))
        for index, (kind, name) in enumerate([("ThingDef", "Harrier_Jet"), ("RecipeDef", "MakeRocket")]):
            self.conn.execute("INSERT INTO def (mod_position, def_type, def_name, abstract, loads, registers, load_folder, file, "
                              "element_index) VALUES (0, ?, ?, 0, 1, 0, '', 'Defs/Things.xml', ?)", (kind, name, index))
        for position, folder, file in ((0, theirs, "Patches/Theirs.xml"), (1, ours, "Patches/Ours.xml")):
            for operation, xpath, find_mods, may_require in defs.patch_operations(ET.parse(folder / file).getroot()):
                match = defs.DEF_TYPE_IN_XPATH.match(xpath)
                cursor = self.conn.execute("INSERT INTO patch (mod_position, operation, xpath, def_type, find_mods, may_require, "
                                           "load_folder, file) VALUES (?, ?, ?, ?, ?, ?, '', ?)",
                                           (position, operation, xpath, match.group(1) if match else None, find_mods or None,
                                            may_require or None, file))
                self.conn.executemany("INSERT INTO patch_target VALUES (?, ?)",
                                      [(cursor.lastrowid, n) for n in dict.fromkeys(defs.DEF_NAME_IN_XPATH.findall(xpath))])

    def statuses(self, result):
        return {r["def"]: r["status"] for r in result["rows"]}

    def test_each_kind_of_answer(self):
        result = uc.xml_rows(self.conn, ["PhobosDthorga.*"])
        self.assertEqual({"Harrier_Jet": "found", "MakeRocket": "node-missing", "Gone_Thing": "missing", "OurBombCase": "found"},
                         self.statuses(result))
        self.assertEqual(4, result["checked"])     # Harrier_Jet, MakeRocket, Gone_Thing, OurBombCase
        rocket = next(r for r in result["rows"] if r["def"] == "MakeRocket")
        self.assertEqual(1, rocket["earlierPatches"])
        self.assertIn("1 earlier patch names this Def", rocket["detail"])
        self.assertEqual(1, result["skipped"]["a question (Conditional, Test, FindMod): finding nothing is an answer"])
        self.assertEqual(1, result["skipped"]["for a mod that is not active"])
        self.assertEqual("missing", result["rows"][0]["status"])      # problems first

    def test_only_our_package_ids_are_read(self):
        self.assertEqual([], uc.xml_rows(self.conn, ["Someone.*"])["rows"])

    def test_the_patched_defs_file_confirms_a_node_an_earlier_patch_adds(self):
        patched = sqlite3.connect(":memory:")
        with closing(patched):
            patched.executescript(patched_defs.SCHEMA)
            patched.execute("INSERT INTO pdef (def_type, def_name, abstract, xml) VALUES ('RecipeDef', 'MakeRocket', 0, "
                            "'<RecipeDef><defName>MakeRocket</defName><recipeUsers /></RecipeDef>')")
            result = uc.xml_rows(self.conn, ["PhobosDthorga.*"], patched)
        self.assertEqual("patched", self.statuses(result)["MakeRocket"])


class CommandTests(unittest.TestCase):
    def test_bad_parts_and_bad_config_are_errors(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = io.StringIO()
            self.assertEqual(uc.EXIT_FAILED, uc.main(["--root", tmp, "--only", "colour", "--json"], environ={}, out=out))
            self.assertEqual("rimworld-update-check", json.loads(out.getvalue())["tool"])
            (Path(tmp) / "config").mkdir()
            (Path(tmp) / "config" / "update-check.json").write_text("{", encoding="utf-8")
            out = io.StringIO()
            self.assertEqual(uc.EXIT_FAILED, uc.main(["--root", tmp, "--only", "xml"], environ={}, out=out))
            self.assertIn("not valid JSON", out.getvalue())

    def test_a_temporary_row_without_members_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "t.json").write_text(json.dumps({"patches": [{"row": 1, "file": "A.dll"}]}), encoding="utf-8")
            with self.assertRaises(uc.UpdateCheckError):
                uc.read_temporary(tmp, {"temporaryPatches": "t.json"})
            self.assertEqual([], uc.read_temporary(tmp, {}))


if __name__ == "__main__":
    unittest.main()
