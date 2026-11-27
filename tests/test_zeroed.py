"""zeroed (1.81.0): files a crash left filled with zeros, on a made-up repository in a temporary folder. Nothing reads a real one."""
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import unittest

import support
from phobos_modkit import zeroed


def git(repository, *arguments):
    subprocess.run(["git", "-c", "core.fsmonitor=false", "-C", str(repository), *arguments], check=True, capture_output=True)


class Zeroed(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.repo = base / "repo"
        self.repo.mkdir()
        git(self.repo, "init", "-q")
        # In the repository too, as the code under test runs plain git: a system-wide fsmonitor started a daemon per test
        # repository, and once hung the gate's `git add` (28 Nov 2026).
        git(self.repo, "config", "core.fsmonitor", "false")
        git(self.repo, "config", "user.email", "test@example.invalid")
        git(self.repo, "config", "user.name", "Test")
        (self.repo / "good.txt").write_text("hello", encoding="utf-8")
        (self.repo / "Cargo.toml").write_text('[package]\nversion = "1.0.0"\n', encoding="utf-8")
        (self.repo / "zeros.bin").write_bytes(bytes(32))
        git(self.repo, "add", ".")
        git(self.repo, "commit", "-q", "-m", "first")
        # What a crash leaves: the file at its full size, every byte zero.
        (self.repo / "Cargo.toml").write_bytes(bytes(len('[package]\nversion = "1.0.0"\n')))
        (self.repo / "notes.txt").write_bytes(bytes(10))
        (self.repo / "empty.txt").write_bytes(b"")
        self.environ = support.isolated_environ(self.tmp.name, PHOBOS_MODKIT_BUILD=str(base / "build"))
        build = base / "build"
        build.mkdir()
        (build / "Tool.dll").write_bytes(bytes(100))
        self.build = build

    def tearDown(self):
        self.tmp.cleanup()

    def kinds(self, rows):
        return {Path(r["path"]).name: r["kind"] for r in rows}

    def test_each_zero_filled_file_is_found_and_said_what_it_is(self):
        rows = zeroed.survey([self.repo, self.build], self.environ)
        found = self.kinds(rows)
        self.assertEqual(found["Cargo.toml"], zeroed.TRACKED)
        self.assertEqual(found["zeros.bin"], zeroed.COMMITTED)
        self.assertEqual(found["notes.txt"], zeroed.UNTRACKED)
        self.assertNotIn("good.txt", found)
        self.assertNotIn("empty.txt", found)
        self.assertTrue(next(r for r in rows if r["kind"] == zeroed.TRACKED)["restorable"])

    def test_the_build_folder_and_gits_store_are_named_as_such(self):
        rows = zeroed.survey([self.build], self.environ)
        self.assertEqual(zeroed.native.build_dir(self.environ), self.build)
        self.assertEqual(self.kinds(rows)["Tool.dll"], zeroed.BUILT)
        head = self.repo / ".git" / "HEAD"
        head.write_bytes(bytes(head.stat().st_size))
        self.assertEqual(self.kinds(zeroed.survey([self.repo], self.environ))["HEAD"], zeroed.GIT_STORE)

    def test_only_recent_files_are_opened_unless_all_are_asked_for(self):
        old = time.time() - 10 * 86400
        os.utime(self.repo / "notes.txt", (old, old))
        recent = self.kinds(zeroed.survey([self.repo], self.environ, since=time.time() - 3 * 86400))
        self.assertNotIn("notes.txt", recent)
        self.assertIn("Cargo.toml", recent)
        self.assertIn("notes.txt", self.kinds(zeroed.survey([self.repo], self.environ, since=0)))

    def test_restore_writes_back_only_with_apply_and_only_tracked_files(self):
        out = io.StringIO()
        zeroed.main(["restore", "--root", str(self.repo), "--json"], self.environ, out)
        self.assertFalse(json.loads(out.getvalue())["data"]["applied"])
        self.assertTrue(zeroed.all_zero(self.repo / "Cargo.toml"))
        out = io.StringIO()
        zeroed.main(["restore", "--root", str(self.repo), "--apply", "--json"], self.environ, out)
        data = json.loads(out.getvalue())["data"]
        self.assertEqual([Path(p).name for p in data["restored"]], ["Cargo.toml"])
        self.assertIn("1.0.0", (self.repo / "Cargo.toml").read_text(encoding="utf-8"))
        self.assertTrue(zeroed.all_zero(self.repo / "notes.txt"))

    def test_the_check_says_when_nothing_is_found(self):
        out = io.StringIO()
        zeroed.main(["check", "--root", str(self.repo / ".git"), "--days", "1"], self.environ, out)
        self.assertIn("none in 1 folders", out.getvalue())


if __name__ == "__main__":
    unittest.main()
