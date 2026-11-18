"""The gate's commit guard on throwaway repositories: a full pass notes what it checked, and --verify-staged lets a commit through
only when one pass saw every staged file exactly as staged."""
import io
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

import support  # noqa: F401  (the package on the import path)
from phobos_modkit.gate import cli, stamp

HAVE_GIT = shutil.which("git") is not None


def git(root, *args):
    return subprocess.run(["git", "-c", "core.fsmonitor=false", *args], cwd=root, check=True, capture_output=True, text=True)


GATE = {"schemaVersion": 1, "stages": [{"name": "Checks", "steps": [
    {"name": "check", "run": ["{python}", "-c", "import pathlib,sys; sys.exit(1 if 'BROKEN' in pathlib.Path('a.txt').read_text() else 0)"]}]}]}


@unittest.skipUnless(HAVE_GIT, "git is not installed")
class GuardTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "repo"
        self.root.mkdir()
        git(self.root, "init", "-q", "-b", "main")
        for key, value in (("core.fsmonitor", "false"), ("user.email", "test@example.com"), ("user.name", "Test"), ("core.autocrlf", "false")):
            git(self.root, "config", key, value)
        (self.root / "config").mkdir()
        (self.root / "config" / "gate.json").write_text(json.dumps(GATE), encoding="utf-8")
        (self.root / "a.txt").write_text("one\n", encoding="utf-8")
        git(self.root, "add", "-A")
        git(self.root, "commit", "-q", "-m", "start")

    def gate(self, *argv):
        out = io.StringIO()
        code = cli.main(["--root", str(self.root), *argv], out=out)
        return code, out.getvalue()

    def edit(self, text, name="a.txt"):
        (self.root / name).write_text(text, encoding="utf-8")

    def test_a_pass_covers_what_it_saw(self):
        self.edit("two\n")
        code, text = self.gate()
        self.assertEqual(cli.EXIT_OK, code, text)
        self.assertIn("Noted for the commit guard: 1 changed files", text)
        git(self.root, "add", "a.txt")
        self.assertEqual(cli.EXIT_OK, self.gate("--verify-staged")[0])

    def test_an_edit_after_the_pass_is_refused(self):
        self.edit("two\n")
        self.gate()
        self.edit("three\n")
        git(self.root, "add", "a.txt")
        code, text = self.gate("--verify-staged")
        self.assertEqual(cli.EXIT_FAILED, code)
        self.assertIn("Commit refused", text)
        self.assertIn("a.txt", text)

    def test_a_failed_gate_notes_nothing(self):
        self.edit("BROKEN\n")
        self.assertEqual(cli.EXIT_FAILED, self.gate()[0])
        git(self.root, "add", "a.txt")
        code, text = self.gate("--verify-staged")
        self.assertEqual(cli.EXIT_FAILED, code)
        self.assertIn("No passing run is noted", text)

    def test_a_narrowed_run_does_not_count(self):
        self.edit("two\n")
        self.assertEqual(cli.EXIT_OK, self.gate("--only", "check")[0])
        git(self.root, "add", "a.txt")
        self.assertEqual(cli.EXIT_FAILED, self.gate("--verify-staged")[0])

    def test_another_sessions_failing_run_leaves_an_earlier_pass_standing(self):
        self.edit("two\n")
        self.gate()
        self.edit("x\n", "b.txt")
        self.edit("BROKEN\n")                      # someone else breaks a.txt after our pass, then restores it
        self.gate()
        self.edit("two\n")
        git(self.root, "add", "a.txt")
        self.assertEqual(cli.EXIT_OK, self.gate("--verify-staged")[0])

    def test_new_and_deleted_files(self):
        self.edit("new\n", "c.txt")
        git(self.root, "rm", "-q", "--cached", "a.txt")
        (self.root / "a.txt").unlink()
        self.assertEqual(cli.EXIT_FAILED, self.gate()[0])   # the check reads a.txt, so it fails without it
        (self.root / "a.txt").write_text("one\n", encoding="utf-8")
        git(self.root, "add", "a.txt")
        self.assertEqual(cli.EXIT_OK, self.gate()[0])
        git(self.root, "add", "c.txt")
        self.assertEqual(cli.EXIT_OK, self.gate("--verify-staged")[0])

    def test_nothing_staged_is_covered(self):
        self.assertEqual(cli.EXIT_OK, self.gate("--verify-staged")[0])

    def test_a_folder_inside_a_repository_notes_nothing(self):
        inner = self.root / "inner"
        (inner / "config").mkdir(parents=True)
        (inner / "config" / "gate.json").write_text(json.dumps(GATE), encoding="utf-8")
        (inner / "a.txt").write_text("one\n", encoding="utf-8")
        out = io.StringIO()
        self.assertEqual(cli.EXIT_OK, cli.main(["--root", str(inner)], out=out))
        self.assertNotIn("Noted", out.getvalue())
        self.assertFalse((stamp.git_dir(self.root) / stamp.FOLDER).exists())


if __name__ == "__main__":
    unittest.main()
