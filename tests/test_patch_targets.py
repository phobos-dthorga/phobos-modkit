"""rimworld-patches targets: each method a repository patches, the other mods on it, and what its last update changed (1.37.0)."""
from contextlib import closing
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import support  # noqa: F401  (puts the package on the path)
from phobos_modkit.games.rimworld import patch_targets


def graph():
    conn = sqlite3.connect(":memory:")
    conn.executescript("""
        CREATE TABLE nodes (id TEXT PRIMARY KEY, name TEXT, kind TEXT, language TEXT, file TEXT, line INTEGER, "end" INTEGER,
                            owner TEXT, external INTEGER, assembly TEXT);
        CREATE TABLE edges (source TEXT, target TEXT, kind TEXT, exact INTEGER);
    """)
    conn.executemany("INSERT INTO nodes VALUES (?, ?, 'method', 'csharp', NULL, NULL, NULL, NULL, 1, ?)", [
        ("cs:Verse.Pawn.Tick", "Pawn.Tick", "Assembly-CSharp"),
        ("cs:Verse.Pawn.Label", "Pawn.Label", "Assembly-CSharp"),
    ])
    conn.executemany("INSERT INTO edges VALUES (?, ?, ?, 1)", [
        ("cs:Boats.Patches.TickPrefix", "cs:Verse.Pawn.Tick", "patches"),
        ("cs:Boats.Patches.TickPostfix", "cs:Verse.Pawn.Tick", "patches"),
        ("cs:Boats.Patches.LabelPostfix", "cs:Verse.Pawn.Label", "patches"),
        ("cs:Boats.Patches.TickPrefix", "cs:Verse.Pawn.Destroy", "calls"),
    ])
    return conn


def index():
    conn = sqlite3.connect(":memory:")
    conn.executescript("""
        CREATE TABLE patches (path TEXT, source TEXT, kind TEXT, target_type TEXT, target_member TEXT, method_type TEXT,
                              argument_types TEXT, patch_class TEXT, patch_method TEXT, can_skip INTEGER, priority INTEGER,
                              note TEXT);
        CREATE TABLE owners (path TEXT, position INTEGER, package_id TEXT, mod TEXT);
    """)
    conn.executemany("INSERT INTO owners VALUES (?, ?, ?, ?)", [
        ("C:/Mods/Boats/Assemblies/Boats.dll", 1, "sample.boats", "Sample Boats"),
        ("C:/Mods/Sails/Assemblies/Sails.dll", 2, "sample.sails", "Sample Sails"),
        ("C:/Mods/Oars/Assemblies/Oars.dll", 3, "sample.oars", "Sample Oars"),
    ])
    conn.executemany("INSERT INTO patches VALUES (?, 'attribute', ?, 'Verse.Pawn', ?, 'Normal', '', 'P', 'M', ?, -1, '')", [
        ("C:/Mods/Boats/Assemblies/Boats.dll", "Prefix", "Tick", 1),
        ("C:/Mods/Sails/Assemblies/Sails.dll", "Prefix", "Tick", 1),
        ("C:/Mods/Oars/Assemblies/Oars.dll", "Postfix", "Tick", 0),
        ("C:/Mods/Oars/Assemblies/Oars.dll", "Postfix", "Label", 0),
    ])
    return conn


class TargetTests(unittest.TestCase):
    def test_each_patched_method_names_the_other_mods_on_it(self):
        with tempfile.TemporaryDirectory() as tmp, closing(graph()) as g, closing(index()) as i, \
                mock.patch.object(patch_targets.csharp, "assembly_names", return_value=["Boats"]):
            found = {t["target"]: t for t in patch_targets.targets(g, i, Path(tmp))}
        self.assertEqual(sorted(found), ["Verse.Pawn.Label", "Verse.Pawn.Tick"])
        tick = found["Verse.Pawn.Tick"]
        self.assertEqual(tick["node"], "cs:Verse.Pawn.Tick")
        self.assertEqual(tick["ours"], ["cs:Boats.Patches.TickPostfix", "cs:Boats.Patches.TickPrefix"])
        self.assertEqual(tick["mods"], ["Sample Oars", "Sample Sails"])
        self.assertEqual(tick["skippers"], 1)
        self.assertEqual(found["Verse.Pawn.Label"]["mods"], ["Sample Oars"])

    def test_an_update_row_is_joined_by_type_and_member(self):
        found = [{"target": "Verse.Pawn.Tick", "changed": []}, {"target": "Verse.Pawn.Label", "changed": []}]
        patch_targets.join_updates(found, [
            ("RimWorld", "Assembly-CSharp.dll", "1.7.1 to 1.7.2", "Pawn.Tick", "new body (+3 -1)", "src/x.cs:1"),
            ("Other", "Other.dll", "1 to 2", "Thing.Tick", "**removed**", "src/y.cs:2"),
        ])
        self.assertEqual(found[0]["changed"], [{"mod": "RimWorld", "file": "Assembly-CSharp.dll", "versions": "1.7.1 to 1.7.2",
                                                "change": "new body (+3 -1)", "newestKept": ""}])
        self.assertEqual(found[1]["changed"], [])

    def test_when_the_newer_build_was_kept_comes_as_a_time(self):
        found = [{"target": "Verse.Pawn.Tick", "changed": []}]
        patch_targets.join_updates(found, [("RimWorld", "Assembly-CSharp.dll", "a to b", "Pawn.Tick", "new body", "x")],
                                   {("RimWorld", "Assembly-CSharp.dll"): "2026-11-19 09:08 UTC"})
        self.assertEqual(found[0]["changed"][0]["newestKept"], "2026-11-19T09:08:00+00:00")
        self.assertEqual(patch_targets.kept_at("not a time"), "")

    def test_a_members_id_splits_into_type_and_member(self):
        self.assertEqual(patch_targets.split_target("cs:Verse.AI.Pawn_PathFollower.TryEnterNextPathCell"),
                         ("Verse.AI.Pawn_PathFollower", "TryEnterNextPathCell"))


if __name__ == "__main__":
    unittest.main()
