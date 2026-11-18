"""rimworld-upstream: our targets read from C#, commits in a throwaway "upstream" repository that touch them, and an archived
update's changes matched against them through a stand-in for the code compare."""
import io
import json
from datetime import datetime, timezone
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock

import support  # noqa: F401  (the package on the import path)
from phobos_modkit.assembly_archive import Version
from phobos_modkit.code import compare as code_compare
from phobos_modkit.games.rimworld import upstream_cli as up

HAVE_GIT = shutil.which("git") is not None
OURS = """using HarmonyLib;
namespace Ours {
  [HarmonyPatch(typeof(Vehicles.CompUpgradeTree), "PrerequisitesMet")]
  static class Patch { static void Postfix() {} }
  static class Other { static object m = AccessTools.Method("Vehicles.VehiclePawn:Tick"); }
}
"""
UPSTREAM_V1 = """namespace Vehicles {
  public class CompUpgradeTree {
    public bool PrerequisitesMet(int node) {
      return true;
    }
    public void Unrelated() { }
  }
}
"""
UPSTREAM_V2 = UPSTREAM_V1.replace("return true;", "return node > 0;")
UPSTREAM_V3 = UPSTREAM_V2.replace("public void Unrelated() { }", "public void Unrelated() { int x = 1; }")


def git(root, *args):
    return subprocess.run(["git", "-c", "core.fsmonitor=false", *args], cwd=root, check=True, capture_output=True, text=True)


class WantedTests(unittest.TestCase):
    def test_targets_by_type_and_member(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "src" / "A").mkdir(parents=True)
            (Path(tmp) / "src" / "A" / "Patch.cs").write_text(OURS, encoding="utf-8")
            wanted = up.wanted_members(tmp)
        self.assertIn(("CompUpgradeTree", "PrerequisitesMet"), wanted)
        self.assertIn(("VehiclePawn", "Tick"), wanted)
        self.assertTrue(wanted[("CompUpgradeTree", "PrerequisitesMet")].where.endswith("Patch.cs:3"))

    def test_a_declaration_matches_by_type_and_member(self):
        wanted = {("CompUpgradeTree", "PrerequisitesMet"): up.Wanted("CompUpgradeTree", "PrerequisitesMet", "x:1")}
        self.assertIsNotNone(up._matches("Vehicles.CompUpgradeTree.PrerequisitesMet", wanted))
        self.assertIsNone(up._matches("Vehicles.CompUpgradeTree.Unrelated", wanted))


@unittest.skipUnless(HAVE_GIT, "git is not installed")
class PendingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.clones = Path(self.tmp.name) / "clones"
        repo = self.clones / "VehicleFramework-src"
        (repo / "Source").mkdir(parents=True)
        git(repo, "init", "-q", "-b", "main")
        for key, value in (("core.fsmonitor", "false"), ("user.email", "t@example.com"), ("user.name", "T")):
            git(repo, "config", key, value)
        for text, message in ((UPSTREAM_V1, "start"), (UPSTREAM_V2, "VF-412: research check"), (UPSTREAM_V3, "tidy")):
            (repo / "Source" / "CompUpgradeTree.cs").write_text(text, encoding="utf-8")
            git(repo, "add", "-A")
            git(repo, "commit", "-q", "-m", message)
        self.register = [{"name": "Vehicle Framework", "repository": "https://example.com/vf", "confirmed": "About/About.xml"},
                         {"name": "Not Cloned", "repository": "https://example.com/x", "confirmed": "About/About.xml"}]
        self.wanted = {("CompUpgradeTree", "PrerequisitesMet"): up.Wanted("CompUpgradeTree", "PrerequisitesMet", "src/A/Patch.cs:3")}

    def test_commits_that_touch_a_member_we_name(self):
        rows, fresh, skipped = up.pending_rows(self.register, self.clones, self.wanted, 30, subprocess.run)
        subjects = [r[3] for r in rows]
        self.assertIn("VF-412: research check", subjects)
        self.assertNotIn("tidy", subjects)                 # the change to Unrelated names no member of ours
        self.assertEqual("CompUpgradeTree.PrerequisitesMet", rows[0][4])
        self.assertEqual("src/A/Patch.cs:3", rows[0][5])
        self.assertEqual(["Vehicle Framework"], [name for name, _ in fresh])
        self.assertEqual([], skipped)

    def test_a_file_that_declares_none_of_our_types_is_not_read(self):
        other = {("SomethingElse", "Run"): up.Wanted("SomethingElse", "Run", "x:1")}
        rows, fresh, _ = up.pending_rows(self.register, self.clones, other, 30, subprocess.run)
        self.assertEqual([], rows)
        self.assertEqual(1, len(fresh))


class Item:
    def __init__(self, full):
        self.full = full


class UpdateTests(unittest.TestCase):
    def test_a_changed_and_a_removed_member_are_reported(self):
        archive = mock.Mock()
        archive.versions.return_value = [
            Version(1, "vf", "Vehicle Framework", "Vehicles.dll", "a" * 64, 1, "1.0", "2026-11-01 10:00 UTC"),
            Version(2, "vf", "Vehicle Framework", "Vehicles.dll", "b" * 64, 1, "1.1", "2026-11-15 10:00 UTC"),
            Version(3, "old", "Old Mod", "Old.dll", "c" * 64, 1, "1", "2026-01-01 10:00 UTC"),
            Version(4, "old", "Old Mod", "Old.dll", "d" * 64, 1, "2", "2026-02-01 10:00 UTC"),
        ]
        wanted = {("CompUpgradeTree", "PrerequisitesMet"): up.Wanted("CompUpgradeTree", "PrerequisitesMet", "src/A.cs:3"),
                  ("VehiclePawn", "Tick"): up.Wanted("VehiclePawn", "Tick", "src/B.cs:9")}
        change = code_compare.Change(Item("Vehicles.CompUpgradeTree.PrerequisitesMet"), Item("Vehicles.CompUpgradeTree.PrerequisitesMet"),
                                     False, "code", 3, 1)
        with mock.patch.object(code_compare, "decompile", return_value=(Path("x"), False)), \
                mock.patch.object(up.code_index, "ensure", return_value=(Path("x"), False)), \
                mock.patch.object(code_compare, "Source"), \
                mock.patch.object(code_compare, "compare", return_value=([change], [Item("Vehicles.VehiclePawn.Tick")], [], 0, 0, 0)):
            rows, skipped, compared = up.update_rows(archive, wanted, 30, datetime(2026, 11, 18, tzinfo=timezone.utc),
                                                     Path("d"), Path("c"), lambda: "ilspycmd")
        self.assertEqual(["Vehicles.dll"], compared)       # Old.dll's update is outside the 30 days
        self.assertIn(("Vehicle Framework", "Vehicles.dll", "1.0 to 1.1", "CompUpgradeTree.PrerequisitesMet",
                       "new body (code, +3 -1)", "src/A.cs:3"), rows)
        self.assertIn(("Vehicle Framework", "Vehicles.dll", "1.0 to 1.1", "VehiclePawn.Tick", "**removed**", "src/B.cs:9"), rows)
        self.assertEqual([], skipped)


class CommandTests(unittest.TestCase):
    def test_no_targets_is_an_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = io.StringIO()
            code = up.main(["pending", "--root", tmp], environ={}, out=out)
        self.assertEqual(up.EXIT_FAILED, code)
        self.assertIn("No member on another assembly's type", out.getvalue())

    def test_pending_without_clones_says_so(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "src").mkdir()
            (Path(tmp) / "src" / "Patch.cs").write_text(OURS, encoding="utf-8")
            (Path(tmp) / "config").mkdir()
            (Path(tmp) / "config" / "source-repos.json").write_text(json.dumps({"mods": {}}), encoding="utf-8")
            out = io.StringIO()
            code = up.main(["pending", "--root", tmp], environ={}, out=out)
        self.assertEqual(up.EXIT_OK, code, out.getvalue())
        self.assertIn("name the clones folder with --clones", out.getvalue())


if __name__ == "__main__":
    unittest.main()
