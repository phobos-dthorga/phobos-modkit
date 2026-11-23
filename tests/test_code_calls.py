"""connections calls: what a commit did to its C# methods' calls, and the rings of calls it made or cut (1.116.0).

The comparison and the ring finder are tested on methods written by hand, shaped as the names reader gives them; the reader
itself is run on a hand-written repository of two commits when the .NET SDK is installed, and the tests fail rather than skip
when PHOBOS_REQUIRE_NATIVE is set, as for the other native tools."""
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

import support  # noqa: F401  (puts the package on the path)

from phobos_modkit import code_calls, connections_cli

HAVE_DOTNET = shutil.which("dotnet") is not None
REQUIRE = bool(os.environ.get("PHOBOS_REQUIRE_NATIVE"))
FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "dotnet" / "NamesFixture"


def call(display, type_, name, file=None, assembly=None, via_base=False, virtual=False, on_this=False):
    found = {"id": f"M:{type_}.{name}", "display": display, "type": type_, "name": name, "viaBase": via_base,
             "virtual": virtual, "onThis": on_this}
    if file:
        found.update(file=file, line=1)
    else:
        found["assembly"] = assembly
    return found


def method(display, type_, name, calls, overrides=None, base=False):
    return {"id": f"M:{type_}.{name}", "display": display, "file": "src/Worker.cs", "line": 1, "end": 2, "type": type_,
            "name": name, "overrides": overrides, "calls": calls, "base": base}


# The shape of phobos-rimworld's crash of 23 November 2026, by hand: AvailableOnNow asks AvailableReport, which hands on to the
# game's AvailableReport, whose body asks AvailableOnNow on the same object: an override of ours.
GAME = "Verse.RecipeWorker"
OURS = "Phobos.NeedsNode"
ON_GAME = call("RecipeWorker.AvailableOnNow", GAME, "AvailableOnNow", assembly="Assembly-CSharp", virtual=True)
REPORT_GAME = call("RecipeWorker.AvailableReport", GAME, "AvailableReport", assembly="Assembly-CSharp", virtual=True)
REPORT_OURS = call("NeedsNode.AvailableReport", OURS, "AvailableReport", file="src/Worker.cs", virtual=True, on_this=True)
CHECK = call("NeedsNode.Check", OURS, "Check", file="src/Worker.cs", on_this=True)
UNLOCKED = call("Upgrades.Unlocked", "Phobos.Upgrades", "Unlocked", file="src/Upgrades.cs")
BEFORE = [
    method("NeedsNode.AvailableOnNow", OURS, "AvailableOnNow", [REPORT_OURS], overrides=ON_GAME),
    method("NeedsNode.AvailableReport", OURS, "AvailableReport", [dict(REPORT_GAME, viaBase=True, onThis=True), UNLOCKED],
           overrides=REPORT_GAME),
]
AFTER = [
    method("NeedsNode.AvailableOnNow", OURS, "AvailableOnNow", [CHECK], overrides=ON_GAME),
    method("NeedsNode.AvailableReport", OURS, "AvailableReport", [CHECK], overrides=REPORT_GAME),
    method("NeedsNode.Check", OURS, "Check", [UNLOCKED]),
]
BODIES = {(GAME, "AvailableReport"): [(GAME, "AvailableOnNow")]}


def ring_names(edges, holding):
    return [[step.split(".")[-1] for step in ring] for ring in code_calls.rings(edges, holding)]


class CompareTests(unittest.TestCase):
    def test_calls_gone_new_and_kept_and_a_method_added(self):
        found = {m["display"]: m for m in code_calls.compare(BEFORE, AFTER)}
        report = found["NeedsNode.AvailableReport"]
        self.assertEqual(report["status"], "changed")
        self.assertEqual(sorted(c["display"] for c in report["gone"]), ["RecipeWorker.AvailableReport", "Upgrades.Unlocked"])
        self.assertEqual([c["display"] for c in report["new"]], ["NeedsNode.Check"])
        self.assertTrue(next(c for c in report["gone"] if c["display"] == "RecipeWorker.AvailableReport")["viaBase"])
        self.assertEqual(found["NeedsNode.Check"]["status"], "added")
        self.assertEqual(found["NeedsNode.Check"]["node"], "cs:Phobos.NeedsNode.Check")

    def test_calls_that_moved_whole_into_another_method_say_so(self):
        found = {m["display"]: m for m in code_calls.compare(BEFORE, AFTER)}
        self.assertEqual(found["NeedsNode.AvailableReport"]["movedTo"][0]["display"], "NeedsNode.Check")
        self.assertEqual(found["NeedsNode.Check"]["movedFrom"][0]["calls"], ["M:Phobos.Upgrades.Unlocked"])

    def test_a_method_read_only_for_its_calls_is_never_a_change(self):
        shown = code_calls.compare([], [method("Worker.Report", "Core.Worker", "Report", [], base=True)])
        self.assertEqual(shown, [])

    def test_a_documentation_id_becomes_a_connections_id(self):
        self.assertEqual(code_calls.node_of({"id": "M:A.B.C(System.Int32)"}), "cs:A.B.C")
        self.assertEqual(code_calls.node_of({"id": "M:A.Boat.#ctor"}), "cs:A.Boat.Boat")
        self.assertEqual(code_calls.node_of({"id": "M:A.B.Make``1(``0)"}), "cs:A.B.Make")
        self.assertIsNone(code_calls.node_of({"id": None}))


class RingTests(unittest.TestCase):
    def test_the_crash_ring_runs_through_the_games_method_and_back(self):
        edges, words, outside = code_calls.graph(BEFORE, BODIES)
        holding = {"M:Phobos.NeedsNode.AvailableOnNow", "M:Phobos.NeedsNode.AvailableReport"}
        self.assertEqual(ring_names(edges, holding), [["AvailableOnNow", "AvailableReport", "AvailableReport"]])
        self.assertIn(f"M:{GAME}.AvailableReport", outside)

    def test_the_fix_leaves_no_ring(self):
        edges, _, _ = code_calls.graph(AFTER, BODIES)
        self.assertEqual(code_calls.rings(edges, {"M:Phobos.NeedsNode.Check"}), [])

    def test_without_the_games_code_the_ring_is_not_seen(self):
        edges, _, _ = code_calls.graph(BEFORE, {})
        self.assertEqual(code_calls.rings(edges, {"M:Phobos.NeedsNode.AvailableOnNow"}), [])

    def test_a_call_through_base_never_lands_back_in_its_own_override(self):
        only = [method("NeedsNode.AvailableReport", OURS, "AvailableReport", [dict(REPORT_GAME, viaBase=True, onThis=True)],
                       overrides=REPORT_GAME)]
        edges, _, _ = code_calls.graph(only, {})
        self.assertEqual(code_calls.rings(edges, {"M:Phobos.NeedsNode.AvailableReport"}), [])

    def test_only_rings_holding_a_changed_method_are_given(self):
        edges = {"a": {"b"}, "b": {"a"}, "c": {"d"}, "d": {"c"}}
        self.assertEqual(code_calls.rings(edges, {"c"}), [("c", "d")])


class CommandTests(unittest.TestCase):
    def test_a_commit_that_is_not_one_is_refused(self):
        out = io.StringIO()
        code = connections_cli.main(["calls", "--root", ".", "--commit=--all", "--json"], {}, out)
        self.assertEqual(code, 1)
        self.assertFalse(json.loads(out.getvalue())["data"]["ok"])


WORKER = """namespace NamesFixture.Core;

public class Worker
{
    public virtual bool On() => true;

    public virtual bool Report() => On();
}
"""
MINE_RING = """using NamesFixture.Core;

namespace NamesFixture.Mod;

public class MyWorker : Worker
{
    public override bool On() => Report();

    public override bool Report() => base.Report();
}
"""


@unittest.skipUnless(HAVE_DOTNET or REQUIRE, "the .NET SDK is not installed")
class ReaderTests(unittest.TestCase):
    def test_a_ring_through_our_own_base_class_is_made_then_cut(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "repo"
            shutil.copytree(FIXTURE, root / "src")
            (root / "src" / "Core" / "Worker.cs").write_text(WORKER, encoding="utf-8")
            git = ["git", "-c", "user.email=fixture@example.invalid", "-c", "user.name=Fixture", "-c", "core.fsmonitor=false",
                   "-c", "core.autocrlf=false"]

            def commit(message):
                subprocess.run(git + ["add", "."], cwd=root, check=True)
                subprocess.run(git + ["commit", "-q", "-m", message], cwd=root, check=True)
                return subprocess.run(git + ["rev-parse", "HEAD"], cwd=root, check=True, capture_output=True,
                                      text=True).stdout.strip()

            subprocess.run(git + ["init", "-q"], cwd=root, check=True)
            commit("first")
            mine = root / "src" / "Mod" / "MyWorker.cs"
            mine.write_text(MINE_RING, encoding="utf-8")
            made = commit("a ring")
            mine.write_text(MINE_RING.replace("public override bool On() => Report();", "public override bool On() => true;"),
                            encoding="utf-8")
            fixed = commit("the ring cut")

            first = code_calls.read(root, made)
            self.assertEqual(len(first["rings"]["made"]), 1, first["rings"])
            ring = [step["display"] for step in first["rings"]["made"][0]]
            self.assertEqual(ring, ["MyWorker.On()", "MyWorker.Report()", "Worker.Report()"])
            second = code_calls.read(root, fixed)
            self.assertEqual(len(second["rings"]["cut"]), 1, second["rings"])
            self.assertEqual(second["rings"]["made"], [])
            on = next(m for m in second["methods"] if m["display"] == "MyWorker.On()")
            self.assertEqual([c["display"] for c in on["gone"]], ["MyWorker.Report()"])


if __name__ == "__main__":
    unittest.main()
