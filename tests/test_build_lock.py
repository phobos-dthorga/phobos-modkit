"""One build at a time in a repository (1.103.0): the lock itself, and the gate's lanes that hold it."""
import json
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest

import support  # noqa: F401  (the package on the import path)
from phobos_modkit import build_lock
from phobos_modkit.gate.runner import load, run


class Lock(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.repo = self.base / "my repo"
        self.repo.mkdir()
        self.locks = self.base / "locks"

    def tearDown(self):
        self.tmp.cleanup()

    def test_one_file_per_repository_and_name_in_the_folder_given(self):
        other = self.base / "other"
        other.mkdir()
        a = build_lock.lock_path(self.repo, folder=self.locks)
        self.assertEqual(a.parent, self.locks)
        self.assertTrue(a.name.startswith("my-repo-") and a.name.endswith("-build.lock"), a.name)
        self.assertEqual(a, build_lock.lock_path(self.repo / ".", folder=self.locks))
        self.assertNotEqual(a, build_lock.lock_path(other, folder=self.locks))
        self.assertNotEqual(a, build_lock.lock_path(self.repo, name="pack", folder=self.locks))

    def test_the_holder_says_who_and_the_lock_goes_after(self):
        path = build_lock.lock_path(self.repo, folder=self.locks)
        with build_lock.held(self.repo, "an install", folder=self.locks) as taken:
            holder = build_lock.read_holder(path)
            self.assertEqual(holder["purpose"], "an install")
            self.assertEqual(holder["pid"], os.getpid())
            self.assertLess(taken.waited_s, 1)
            self.assertIsNone(taken.waited_for)
        self.assertFalse(path.exists())

    def test_a_second_build_waits_says_so_and_goes_on(self):
        said = []
        released = threading.Event()

        def first():
            with build_lock.held(self.repo, "a gate (dotnet)", folder=self.locks, pid=4242):
                time.sleep(0.3)
            released.set()

        thread = threading.Thread(target=first)
        thread.start()
        time.sleep(0.1)
        with build_lock.held(self.repo, "an install", folder=self.locks, wait_s=10, log=said.append) as taken:
            self.assertTrue(released.is_set(), "the second build ran only after the first let go")
        thread.join()
        self.assertEqual(taken.waited_for["purpose"], "a gate (dotnet)")
        self.assertIn("a gate (dotnet) (process 4242) since", said[0])
        self.assertTrue(said[0].startswith("Waiting for"))
        self.assertTrue(said[-1].startswith("Went on after waiting"))

    def test_a_build_held_past_the_wait_gives_up_naming_the_holder(self):
        with build_lock.held(self.repo, "a gate (dotnet)", folder=self.locks, pid=7):
            with self.assertRaises(build_lock.BuildBusy) as caught:
                with build_lock.held(self.repo, "an install", folder=self.locks, wait_s=0.1):
                    self.fail("must not run")
        self.assertIn("a gate (dotnet) (process 7)", str(caught.exception))
        self.assertIn("try again once it has finished", str(caught.exception))

    def test_a_lock_left_by_a_build_that_stopped_is_broken(self):
        path = build_lock.lock_path(self.repo, folder=self.locks)
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({"purpose": "a crashed gate"}), encoding="utf-8")
        old = time.time() - build_lock.DEFAULT_STALE_S - 60
        os.utime(path, (old, old))
        with build_lock.held(self.repo, "an install", folder=self.locks, wait_s=0) as taken:
            self.assertIsNone(taken.waited_for)

    def test_describe_reads_what_it_can(self):
        self.assertEqual(build_lock.describe({}), "another build")
        self.assertEqual(build_lock.describe({"purpose": "an install", "since": "not a time"}), "an install")


class GateLanes(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "repo"
        self.root.mkdir()
        self.locks = Path(self.tmp.name) / "locks"
        self.env = {k: v for k, v in os.environ.items() if k.upper() in ("SYSTEMROOT", "WINDIR", "TEMP", "TMP")}
        self.env["PATH"] = ""
        (self.root / "config").mkdir()
        (self.root / "config" / "gate.json").write_text(json.dumps({"schemaVersion": 1, "stages": [
            {"name": "Build", "steps": [
                {"name": "build a", "lane": "dotnet", "holds": "build", "run": ["{python}", "-c", "pass"]},
                {"name": "build b", "lane": "dotnet", "holds": "build", "run": ["{python}", "-c", "pass"]},
                {"name": "docs", "run": ["{python}", "-c", "pass"]}]}]}), encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def test_a_step_says_which_lock_it_holds(self):
        (_, steps), = load(self.root, environ=self.env)
        self.assertEqual({s.name: s.holds for s in steps}, {"build a": "build", "build b": "build", "docs": ""})

    def test_a_lane_that_holds_the_lock_fails_with_the_holder_named_when_it_cannot_have_it(self):
        with build_lock.held(self.root, "an install", folder=self.locks, pid=99):
            results = run(load(self.root, environ=self.env), self.root, self.env,
                          lock_options={"folder": self.locks, "wait_s": 0.1})
        states = {r.step.name: r.state for r in results}
        self.assertEqual(states, {"build a": "failed", "build b": "failed", "docs": "passed"})
        failed = [r for r in results if r.step.name == "build a"][0]
        self.assertIn("an install (process 99)", failed.parsed.problems[0])

    def test_a_lane_that_waited_says_so_as_a_warning(self):
        def hold_briefly():
            with build_lock.held(self.root, "an install", folder=self.locks, pid=5):
                time.sleep(0.3)

        thread = threading.Thread(target=hold_briefly)
        thread.start()
        time.sleep(0.1)
        results = run(load(self.root, environ=self.env), self.root, self.env, lock_options={"folder": self.locks, "wait_s": 10})
        thread.join()
        self.assertEqual({r.state for r in results}, {"passed"})
        first = [r for r in results if r.step.name == "build a"][0]
        self.assertTrue(any("an install (process 5)" in w for w in first.parsed.warnings), first.parsed.warnings)
        self.assertFalse(build_lock.lock_path(self.root, folder=self.locks).exists())


if __name__ == "__main__":
    unittest.main()
