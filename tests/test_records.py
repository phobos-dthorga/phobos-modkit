"""records: the Companion's records copied to a folder of the owner's choosing (1.43.0)."""
from datetime import datetime, timedelta, timezone
import io
import json
from pathlib import Path
import tempfile
import unittest

import support  # noqa: F401  (puts the package on the path)
from phobos_modkit import records

NOW = datetime(2026, 11, 19, 10, 0, tzinfo=timezone.utc)


class RecordsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        base = Path(self.temp.name)
        self.local = base / "local"
        self.environ = {"LOCALAPPDATA": str(self.local), "XDG_DATA_HOME": str(self.local), "HOME": str(base),
                        "PHOBOS_SETTINGS": str(base / "settings-not-here.json")}
        self.data = records.companion_data(self.environ)
        (self.data / "test-verdicts").mkdir(parents=True)
        (self.data / "test-verdicts" / "sample.jsonl").write_text('{"row": 1}\n', encoding="utf-8")
        (self.data / "shortcuts.json").write_text("{}", encoding="utf-8")
        (self.data / "EBWebView" / "Cache").mkdir(parents=True)
        (self.data / "EBWebView" / "Cache" / "big").write_bytes(b"x" * 5000)
        (self.data / "screen-notes" / "20261119-090000.partial").mkdir(parents=True)
        self.target = base / "nas" / "companion-records"

    def tearDown(self):
        self.temp.cleanup()

    def test_every_record_but_the_browser_cache_is_a_source(self):
        names = [name for name, _ in records.sources(self.environ)]
        self.assertIn("test-verdicts", names)
        self.assertIn("shortcuts.json", names)
        self.assertNotIn("EBWebView", names)

    def test_a_record_kept_elsewhere_by_a_setting_is_copied_too(self):
        elsewhere = Path(self.temp.name) / "my-history"
        elsewhere.mkdir()
        (elsewhere / "sample.jsonl").write_text("{}\n", encoding="utf-8")
        self.environ["PHOBOS_HISTORY"] = str(elsewhere)
        names = [name for name, _ in records.sources(self.environ)]
        self.assertIn("elsewhere-history", names)

    def test_no_folder_chosen_is_refused_and_status_says_never(self):
        with self.assertRaises(records.RecordsError):
            records.backup(None, self.environ)
        found = records.status(None, self.environ, NOW)
        self.assertIsNone(found["folder"])
        self.assertTrue(found["stale"])

    def test_a_copy_is_dated_whole_and_never_replaces_another(self):
        first = records.backup(str(self.target), self.environ, NOW)
        second = records.backup(str(self.target), self.environ, NOW)
        self.assertNotEqual(first["name"], second["name"])
        copy = Path(first["path"])
        self.assertTrue((copy / "test-verdicts" / "sample.jsonl").is_file())
        self.assertFalse((copy / "EBWebView").exists())
        self.assertFalse((copy / "screen-notes" / "20261119-090000.partial").exists())
        made = json.loads((copy / records.MANIFEST_FILE).read_text(encoding="utf-8"))
        self.assertEqual(made["files"], 2)
        self.assertEqual(list(self.target.glob("*.partial")), [])

    def test_status_reads_the_newest_copy_and_its_age(self):
        records.backup(str(self.target), self.environ, NOW - timedelta(days=9))
        found = records.status(str(self.target), self.environ, NOW)
        self.assertEqual(found["ageDays"], 9)
        self.assertTrue(found["stale"])
        records.backup(str(self.target), self.environ, NOW)
        found = records.status(str(self.target), self.environ, NOW)
        self.assertEqual(found["ageDays"], 0)
        self.assertFalse(found["stale"])
        self.assertEqual(len(found["copies"]), 2)

    def test_a_copy_is_due_when_none_is_made_or_the_newest_is_old_enough(self):
        # The owner's choice (20 Nov 2026): every few hours while the Companion is open, a missed one made at the next chance.
        self.assertFalse(records.status(None, self.environ, NOW, every_hours=6)["due"])          # no folder: nothing to do
        self.assertTrue(records.status(str(self.target), self.environ, NOW, every_hours=6)["due"])
        records.backup(str(self.target), self.environ, NOW - timedelta(hours=5), automatic=True)
        found = records.status(str(self.target), self.environ, NOW, every_hours=6)
        self.assertEqual((found["ageHours"], found["due"]), (5.0, False))
        self.assertTrue(found["newest"]["automatic"])
        self.assertTrue(records.status(str(self.target), self.environ, NOW + timedelta(hours=1), every_hours=6)["due"])
        self.assertNotIn("due", records.status(str(self.target), self.environ, NOW))

    def test_a_folder_that_cannot_be_reached_is_refused_in_words(self):
        blocker = Path(self.temp.name) / "a-file"
        blocker.write_text("not a folder", encoding="utf-8")
        with self.assertRaises(records.RecordsError) as refused:
            records.backup(str(blocker / "copies"), self.environ, NOW)
        self.assertIn("cannot be reached", str(refused.exception))
        out = io.StringIO()
        self.assertEqual(records.main(["backup", "--to", str(blocker / "copies"), "--json"], out, self.environ),
                         records.EXIT_REFUSED)
        self.assertFalse(json.loads(out.getvalue())["data"]["ok"])

    def test_a_folder_inside_the_records_is_refused(self):
        with self.assertRaises(records.RecordsError):
            records.backup(str(self.data / "backups"), self.environ, NOW)

    def test_command_line(self):
        out = io.StringIO()
        self.assertEqual(records.main(["status"], out, self.environ), 0)
        self.assertIn("never copied", out.getvalue())
        out = io.StringIO()
        self.assertEqual(records.main(["backup"], out, self.environ), records.EXIT_REFUSED)
        out = io.StringIO()
        self.assertEqual(records.main(["backup", "--to", str(self.target), "--json"], out, self.environ), 0)
        self.assertEqual(json.loads(out.getvalue())["data"]["copy"]["files"], 2)


if __name__ == "__main__":
    unittest.main()
