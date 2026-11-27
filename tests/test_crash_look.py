"""When to look after a crash (1.138.0): zeroed's status from Windows' last unexpected shutdown and the last check, WebView2's cache
left out, and crash-dump's quick list. Windows' log and the dumps folder are stood in for; nothing reads the real ones."""
from datetime import datetime, timezone
import io
import json
import os
from pathlib import Path
import tempfile
import unittest

import support
from phobos_modkit import crashdump_cli, zeroed

NOW = datetime(2026, 11, 27, 9, 0, tzinfo=timezone.utc)
EVENTS = ("<Event><System><EventID>41</EventID><TimeCreated SystemTime='2026-11-22T15:24:15.4205752Z'/></System></Event>"
          "<Event><System><EventID>6008</EventID><TimeCreated SystemTime='2026-11-18T15:33:52.0316666Z'/></System></Event>")


class Ran:
    def __init__(self, stdout):
        self.stdout = stdout


class StatusTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        # The build folder too: a check of the usual folders reads it.
        self.environ = support.isolated_environ(self.tmp.name, PHOBOS_MODKIT_BUILD=str(Path(self.tmp.name) / "build"))

    def test_windows_last_unexpected_shutdown_is_read_from_its_log(self):
        if os.name != "nt":
            self.skipTest("Windows' log only")
        self.assertEqual("2026-11-22T15:24:15+00:00", zeroed.last_unexpected_shutdown(lambda *a, **k: Ran(EVENTS.encode())))
        self.assertIsNone(zeroed.last_unexpected_shutdown(lambda *a, **k: Ran(b"")))

    def test_a_check_is_due_once_after_each_shutdown_reaching_back_to_it(self):
        shutdown = "2026-11-22T15:24:15+00:00"
        found = zeroed.status(self.environ, NOW, shutdown)
        self.assertEqual((True, None, 6), (found["due"], found["lastCheck"], found["days"]))
        zeroed.remember_check(self.environ, datetime(2026, 11, 23, tzinfo=timezone.utc))
        self.assertFalse(zeroed.status(self.environ, NOW, shutdown)["due"])
        self.assertTrue(zeroed.status(self.environ, NOW, "2026-11-26T01:00:00+00:00")["due"])     # a newer shutdown
        self.assertFalse(zeroed.status(self.environ, NOW, "")["due"])                              # none recorded
        self.assertEqual(zeroed.MAX_DAYS, zeroed.status(self.environ, NOW, "2025-01-01T00:00:00+00:00")["days"])

    def test_a_check_of_the_usual_folders_is_remembered_and_one_of_named_folders_is_not(self):
        named = Path(self.tmp.name) / "named"
        named.mkdir()
        zeroed.main(["check", "--root", str(named), "--json"], self.environ, io.StringIO())
        self.assertIsNone(zeroed.status(self.environ, NOW, "2026-11-22T15:24:15+00:00")["lastCheck"])
        zeroed.main(["check", "--json"], self.environ, io.StringIO())
        self.assertIsNotNone(zeroed.status(self.environ, NOW, "2026-11-22T15:24:15+00:00")["lastCheck"])

    def test_webview2s_cache_in_the_companions_folder_is_left_out(self):
        data = zeroed.companion_data(self.environ)
        (data / "EBWebView").mkdir(parents=True)
        (data / "EBWebView" / "BrowserMetrics-spare.pma").write_bytes(bytes(4096))
        (data / "picks").mkdir()
        (data / "picks" / "repo.jsonl").write_bytes(bytes(64))
        rows = zeroed.survey([data], self.environ)
        self.assertEqual(["repo.jsonl"], [Path(r["path"]).name for r in rows])


class CrashListTests(unittest.TestCase):
    def test_dumps_are_listed_newest_first_by_program_without_opening_one(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            for name, when in (("RimWorld.exe.70556.dmp", 1_795_000_000), ("GNSSsdFwD.exe(1).18572.dmp", 1_794_000_000),
                               ("odd.dmp", 1_793_000_000)):
                (folder / name).write_bytes(b"not a real dump")
                os.utime(folder / name, (when, when))
            out = io.StringIO()
            code = crashdump_cli.main(["--list", "--folder", tmp, "--json"], {}, out)
            data = json.loads(out.getvalue())["data"]
            self.assertEqual(0, code)
            self.assertEqual(["RimWorld", "GNSSsdFwD", "odd"], [d["program"] for d in data["dumps"]])
            self.assertEqual(["RimWorld.exe.70556.dmp"],
                             [d["file"] for d in crashdump_cli.listed(folder, "rimworld")])


if __name__ == "__main__":
    unittest.main()
