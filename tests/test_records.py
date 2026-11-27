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
        (self.data / "answers" / "test_lists").mkdir(parents=True)
        (self.data / "answers" / "test_lists" / "rimworld.json").write_text("{}", encoding="utf-8")
        (self.data / "screen-notes" / "20261119-090000.partial").mkdir(parents=True)
        self.target = base / "nas" / "companion-records"

    def tearDown(self):
        self.temp.cleanup()

    def test_every_record_but_the_browser_cache_is_a_source(self):
        names = [name for name, _ in records.sources(self.environ)]
        self.assertIn("test-verdicts", names)
        self.assertIn("shortcuts.json", names)
        self.assertNotIn("EBWebView", names)
        self.assertNotIn("answers", names)     # the Companion's kept answers (1.147.2)

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
        made = json.loads(Path(first["path"]).read_text(encoding="utf-8"))
        self.assertEqual(made["format"], records.STORE_FORMAT)
        self.assertEqual(sorted(e["path"] for e in made["entries"]), ["shortcuts.json", "test-verdicts/sample.jsonl"])
        self.assertEqual(made["files"], 2)
        self.assertEqual(list(self.target.glob("*.partial")), [])

    def test_each_file_is_kept_once_however_many_copies_name_it(self):
        # The owner's choice by card (28 Nov 2026): "Store-once".
        records.backup(str(self.target), self.environ, NOW)
        records.backup(str(self.target), self.environ, NOW)
        self.assertEqual(records.store_size(self.target)[0], 2)
        (self.data / "shortcuts.json").write_text('{"changed": true}', encoding="utf-8")
        records.backup(str(self.target), self.environ, NOW)
        self.assertEqual(records.store_size(self.target)[0], 3)
        self.assertEqual([c["form"] for c in records.status(str(self.target), self.environ, NOW)["copies"]], ["store"] * 3)

    def test_restore_writes_a_copy_out_as_it_was(self):
        made = records.backup(str(self.target), self.environ, NOW)
        (self.data / "shortcuts.json").write_text('{"later": 1}', encoding="utf-8")
        into = Path(self.temp.name) / "restored"
        done = records.restore(made["name"], str(into), str(self.target), self.environ)
        self.assertEqual(done["files"], 2)
        self.assertEqual((into / "shortcuts.json").read_text(encoding="utf-8"), "{}")
        self.assertEqual((into / "test-verdicts" / "sample.jsonl").read_text(encoding="utf-8"), '{"row": 1}\n')

    def test_restore_never_writes_over_anything(self):
        made = records.backup(str(self.target), self.environ, NOW)
        busy = Path(self.temp.name) / "busy"
        busy.mkdir()
        (busy / "mine.txt").write_text("keep", encoding="utf-8")
        for into in (busy, self.data / "put-back", self.target / "inside"):
            with self.assertRaises(records.RecordsError):
                records.restore(made["name"], str(into), str(self.target), self.environ)
        self.assertEqual((busy / "mine.txt").read_text(encoding="utf-8"), "keep")
        with self.assertRaises(records.RecordsError):
            records.restore("20990101-000000", str(Path(self.temp.name) / "fresh"), str(self.target), self.environ)

    def _folder_copy(self, name):
        """A copy as kit 1.148.0 and earlier made it: a plain folder with a backup.json."""
        copy = self.target / name
        (copy / "test-verdicts").mkdir(parents=True)
        (copy / "test-verdicts" / "sample.jsonl").write_text('{"row": 1}\n', encoding="utf-8")
        (copy / "shortcuts.json").write_text("{}", encoding="utf-8")
        (copy / records.MANIFEST_FILE).write_text(json.dumps(
            {"format": records.FOLDER_FORMAT, "time": "2026-11-20T00:00:00+00:00", "files": 2, "bytes": 13, "automatic": True,
             "records": []}), encoding="utf-8")
        return copy

    def test_pack_turns_folder_copies_into_store_copies_and_only_then_removes_them(self):
        # The owner's choice by card (28 Nov 2026): "Convert, checked first".
        old = self._folder_copy("20261120-000000")
        preview = records.pack(str(self.target), self.environ)
        self.assertEqual([c["packed"] for c in preview["copies"]], [False])
        self.assertTrue(old.is_dir())
        done = records.pack(str(self.target), self.environ, apply=True)
        self.assertEqual([c["packed"] for c in done["copies"]], [True])
        self.assertFalse(old.exists())
        listed = records.copies(self.target)
        self.assertEqual([(c["name"], c["form"], c["automatic"]) for c in listed], [("20261120-000000", "store", True)])
        into = Path(self.temp.name) / "back"
        records.restore("20261120-000000", str(into), str(self.target), self.environ)
        self.assertEqual((into / "test-verdicts" / "sample.jsonl").read_text(encoding="utf-8"), '{"row": 1}\n')
        self.assertFalse((into / records.MANIFEST_FILE).exists())

    def test_pack_leaves_a_folder_whose_name_is_already_a_store_copy(self):
        made = records.backup(str(self.target), self.environ, NOW)
        old = self._folder_copy(made["name"])
        done = records.pack(str(self.target), self.environ, apply=True)
        self.assertFalse(done["copies"][0]["packed"])
        self.assertTrue(old.is_dir())

    def test_tidy_lets_go_only_of_files_no_copy_names_and_not_new_ones(self):
        first = records.backup(str(self.target), self.environ, NOW)
        (self.data / "shortcuts.json").write_text('{"changed": true}', encoding="utf-8")
        records.backup(str(self.target), self.environ, NOW)
        Path(first["path"]).unlink()                                     # the owner prunes a copy by hand
        fresh = records.tidy(str(self.target), self.environ, apply=True)
        self.assertEqual((fresh["loose"], fresh["removed"]), (0, 0))      # kept in the last day: a backup may be writing
        later = NOW.timestamp() + 10 ** 9
        preview = records.tidy(str(self.target), self.environ, now=later)
        self.assertEqual((preview["loose"], preview["removed"]), (1, 0))
        done = records.tidy(str(self.target), self.environ, apply=True, now=later)
        self.assertEqual(done["removed"], 1)
        self.assertEqual(records.store_size(self.target)[0], 2)

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
        for argv in (["pack"], ["tidy"], ["status"]):
            out = io.StringIO()
            self.assertEqual(records.main([*argv, "--to", str(self.target)], out, self.environ), 0)
        self.assertIn("store holds 2 files", out.getvalue())
        out = io.StringIO()
        self.assertEqual(records.main(["restore", "--copy", "nope", "--into", str(Path(self.temp.name) / "x"), "--to",
                                       str(self.target)], out, self.environ), records.EXIT_REFUSED)


if __name__ == "__main__":
    unittest.main()
