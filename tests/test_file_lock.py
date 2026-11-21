"""The shared lock file (1.70.2), and the C# tools built under it: two runs starting together build a tool once."""
import os
from pathlib import Path
import subprocess
import tempfile
import threading
import time
import unittest

from phobos_modkit import __version__, dotnet_tools, file_lock, native


class Held(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.lock = Path(self.tmp.name) / "deep" / "x.lock"

    def tearDown(self):
        self.tmp.cleanup()

    def test_the_lock_is_there_while_held_and_gone_after(self):
        with file_lock.held(self.lock, 0, 60):
            self.assertTrue(self.lock.is_file())
        self.assertFalse(self.lock.exists())

    def test_a_lock_another_run_holds_is_busy_once_the_wait_is_over(self):
        with file_lock.held(self.lock, 0, 60):
            with self.assertRaises(file_lock.LockBusy):
                with file_lock.held(self.lock, 0.1, 60, poll_s=0.01):
                    pass
            self.assertTrue(self.lock.is_file(), "a run that gave up leaves the holder's lock alone")

    def test_a_lock_left_by_a_run_that_stopped_is_broken(self):
        self.lock.parent.mkdir(parents=True)
        self.lock.write_text("")
        old = time.time() - 120
        os.utime(self.lock, (old, old))
        with file_lock.held(self.lock, 0, 60):
            pass
        self.assertFalse(self.lock.exists())

    def test_a_run_waits_for_another_to_let_go(self):
        order = []

        def first():
            with file_lock.held(self.lock, 5, 60):
                order.append("first in")
                time.sleep(0.2)
                order.append("first out")

        thread = threading.Thread(target=first)
        thread.start()
        while not self.lock.exists():
            time.sleep(0.01)
        with file_lock.held(self.lock, 5, 60, poll_s=0.01):
            order.append("second in")
        thread.join()
        self.assertEqual(order, ["first in", "first out", "second in"])


class ToolBuilds(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        (base / "bundled").mkdir()
        self.environ = {native.BUILD_ENV: str(base / "build"), native.BUNDLED_ENV: str(base / "bundled")}
        self.tool = dotnet_tools.DotnetTool("Sample.Tool", "sample", "test the lock")
        self.builds = []

    def tearDown(self):
        self.tmp.cleanup()

    def run_build(self, command, **kwargs):
        self.builds.append(command)
        time.sleep(0.3)     # long enough for a second run to arrive while this one builds
        folder = Path(command[command.index("-o") + 1])
        folder.mkdir(parents=True, exist_ok=True)
        (folder / native.program_name("Sample.Tool")).write_bytes(b"")
        return subprocess.CompletedProcess(command, 0, "", "")

    def test_two_runs_after_an_update_build_once(self):
        found = []
        threads = [threading.Thread(target=lambda: found.append(self.tool.ensure(self.environ, self.run_build)))
                   for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(len(self.builds), 1)
        self.assertEqual(found, [self.tool.built_path(self.environ)] * 2)
        self.assertEqual((self.tool.build_folder(self.environ) / dotnet_tools.STAMP).read_text(encoding="utf-8"), __version__)

    def test_a_current_build_is_not_built_again_and_takes_no_lock(self):
        self.tool.ensure(self.environ, self.run_build)
        self.tool.ensure(self.environ, self.run_build)
        self.assertEqual(len(self.builds), 1)
        folder = self.tool.build_folder(self.environ)
        self.assertFalse(folder.with_name(folder.name + ".lock").exists())

    def test_another_versions_build_is_built_again(self):
        self.tool.ensure(self.environ, self.run_build)
        (self.tool.build_folder(self.environ) / dotnet_tools.STAMP).write_text("0.0.1", encoding="utf-8")
        self.tool.ensure(self.environ, self.run_build)
        self.assertEqual(len(self.builds), 2)


if __name__ == "__main__":
    unittest.main()
