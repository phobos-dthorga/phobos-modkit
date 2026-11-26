"""Declared effects: what a repository's data declares a thing does, and whether anything reads it. Stand-in repositories, their
data, code and table, are written by hand in temporary folders, in the shape of a game's XML Defs and C# (no game's own files)."""
import io
import json
from pathlib import Path
import tempfile
import unittest

import support  # noqa: F401  (puts the package on the path)
from phobos_modkit import effects, effects_cli

TABLE = {
    "data": ["data/**/*.xml"],
    "code": ["code/**/*.cs"],
    "kinds": [
        {"element": "FittingDef", "id": "defName", "label": "fitting",
         "effects": [
             {"what": "grant", "path": "grants/li", "readers": {"tags": ["needsGrant"], "code": True}},
             {"what": "figure", "path": "factors/li/parameter", "readers": {"tags": ["parameter", "factorParameter"]},
              "definedBy": {"tagNamed": True}},
             {"what": "mount", "path": "roles/li", "readers": {"tags": ["role"], "built": "Engine[1-4]"}},
         ]},
        {"element": "TreeDef", "id": "defName", "label": "node",
         "effects": [{"what": "node", "path": "nodes/li/key", "unless": "upgrades", "readers": {"tagEndings": ["Node"]}}]},
    ],
}

FITTINGS = """<Defs>
  <FittingDef>
    <defName>Fitting_Read</defName>
    <grants><li>Heater</li></grants>
    <factors><li><parameter>batteryAmpHours</parameter></li></factors>
    <roles><li>Battery</li><li>Engine3</li></roles>
  </FittingDef>
  <FittingDef>
    <defName>Fitting_Unread</defName>
    <grants><li>Heater</li><li>Nothing</li></grants>
    <factors><li><parameter>noSuchFigure</parameter></li></factors>
    <roles><li>Engine9</li></roles>
  </FittingDef>
</Defs>
"""

SYSTEMS = """<Defs>
  <SystemDef>
    <needsGrant>Heater</needsGrant>
    <parameters><batteryAmpHours>45</batteryAmpHours></parameters>
    <flow><factorParameter>batteryAmpHours</factorParameter></flow>
  </SystemDef>
  <LoadoutDef><partRoles><li><role>Battery</role></li></partRoles></LoadoutDef>
  <TreeDef>
    <defName>Tree</defName>
    <nodes>
      <li><key>Plain</key></li>
      <li><key>Chopper</key></li>
      <li><key>WithUpgrades</key><upgrades><li>x</li></upgrades></li>
      <li><key>Other</key><prerequisiteNodes><li>Plain</li></prerequisiteNodes></li>
    </nodes>
  </TreeDef>
  <HarvesterProps><strawChopperNode>Chopper</strawChopperNode></HarvesterProps>
</Defs>
"""


def stand_in(tmp, table=None, accepted=None, code='class A { const string G = "Nothing2"; }'):
    root = Path(tmp)
    (root / "data").mkdir()
    (root / "code").mkdir()
    (root / "config").mkdir()
    (root / "data" / "Fittings.xml").write_text(FITTINGS, encoding="utf-8")
    (root / "data" / "Systems.xml").write_text(SYSTEMS, encoding="utf-8")
    (root / "code" / "A.cs").write_text(code, encoding="utf-8")
    table = dict(table or TABLE)
    if accepted is not None:
        table["accepted"] = accepted
    (root / "config" / "effects.json").write_text(json.dumps(table), encoding="utf-8")
    return root


def unread(result):
    return sorted((f.entry, f.value, f.problem) for f in result.findings)


class Readers(unittest.TestCase):
    def test_what_is_read_passes_and_what_is_not_is_found(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = stand_in(tmp)
            result = effects.audit(root, effects.load_config(root))
        self.assertEqual(unread(result), [
            ("Fitting_Unread", "Engine9", "read by nothing"),
            ("Fitting_Unread", "Nothing", "read by nothing"),
            ("Fitting_Unread", "noSuchFigure", "defined nowhere"),
            ("Fitting_Unread", "noSuchFigure", "read by nothing"),
            ("Tree", "Other", "read by nothing"),
            ("Tree", "Plain", "read by nothing"),
        ])

    def test_a_declaration_never_reads_another(self):
        # Both fittings grant Heater; only the system's needsGrant reads it. Without it, two declarations do not read each other.
        with tempfile.TemporaryDirectory() as tmp:
            root = stand_in(tmp)
            (root / "data" / "Systems.xml").write_text(SYSTEMS.replace("<needsGrant>Heater</needsGrant>", ""), encoding="utf-8")
            result = effects.audit(root, effects.load_config(root))
        self.assertIn(("Fitting_Read", "Heater", "read by nothing"), unread(result))
        self.assertIn(("Fitting_Unread", "Heater", "read by nothing"), unread(result))

    def test_a_quoted_string_in_code_reads_a_name_and_a_part_of_one_does_not(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = stand_in(tmp, code='class A { const string G = "Nothing"; string H = "Engine" + 9; }')
            result = effects.audit(root, effects.load_config(root))
        self.assertNotIn(("Fitting_Unread", "Nothing", "read by nothing"), unread(result))
        self.assertIn(("Fitting_Unread", "Engine9", "read by nothing"), unread(result))

    def test_a_built_name_counts_only_within_its_pattern(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = stand_in(tmp)
            result = effects.audit(root, effects.load_config(root))
        self.assertNotIn("Engine3", [f.value for f in result.findings])

    def test_a_node_with_upgrades_declares_there_and_a_tag_ending_reads_a_node(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = stand_in(tmp)
            result = effects.audit(root, effects.load_config(root))
        values = [f.value for f in result.findings]
        self.assertNotIn("WithUpgrades", values)
        self.assertNotIn("Chopper", values)
        # A prerequisite list item is not a reader of what the node does.
        self.assertIn("Plain", values)


class Accepted(unittest.TestCase):
    def test_an_accepted_finding_passes_with_its_reason_and_a_stale_one_fails(self):
        accepted = [{"entry": "Fitting_Unread", "value": "Nothing", "why": "a marker"},
                    {"entry": "Fitting_Gone", "value": "Old", "why": "no longer there"}]
        with tempfile.TemporaryDirectory() as tmp:
            root = stand_in(tmp, accepted=accepted)
            result = effects.audit(root, effects.load_config(root))
        self.assertEqual([(f.value, f.why) for f in result.accepted], [("Nothing", "a marker")])
        self.assertEqual(result.stale, [accepted[1]])


class Command(unittest.TestCase):
    def run_cli(self, *args):
        out = io.StringIO()
        code = effects_cli.main(list(args), environ={}, out=out)
        return code, out.getvalue()

    def test_check_fails_on_a_new_finding_and_passes_once_all_are_accepted(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = stand_in(tmp)
            code, text = self.run_cli("check", "--root", str(root))
            self.assertEqual(code, 1)
            self.assertIn("Read by nothing", text)
            accepted = [{"entry": "Fitting_Unread", "value": v, "why": "known"} for v in ("Engine9", "Nothing", "noSuchFigure")]
            accepted += [{"entry": "Tree", "value": v, "why": "known"} for v in ("Plain", "Other")]
            table = dict(TABLE, accepted=accepted)
            (root / "config" / "effects.json").write_text(json.dumps(table), encoding="utf-8")
            code, text = self.run_cli("check", "--root", str(root))
            self.assertEqual(code, 0, text)

    def test_json_counts_what_waits(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = stand_in(tmp)
            code, text = self.run_cli("list", "--root", str(root), "--json")
        data = json.loads(text)["data"]
        self.assertEqual(data["waiting"], 6)
        self.assertEqual(len(data["unread"]), 6)

    def test_a_repository_without_a_table_is_told_how_to_opt_in(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, text = self.run_cli("check", "--root", tmp)
        self.assertEqual(code, 1)
        self.assertIn("opts in", text)


if __name__ == "__main__":
    unittest.main()
