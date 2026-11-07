"""The derived-data cache: provenance, staleness, frozen copies and the cache folder."""
import os
from pathlib import Path
import shutil
import sqlite3
import stat
import tempfile
import time
import unittest
from contextlib import closing

import support  # noqa: F401
from phobos_modkit import cache


class Provenance(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.source = self.root / "source.xml"
        self.source.write_text("<a/>", encoding="utf-8")
        self.derived = self.root / "derived.sqlite"
        with closing(sqlite3.connect(self.derived)) as conn:
            cache.write_meta(conn, {**cache.file_stamp(self.source), "schema_sha": "abc"})
            conn.commit()

    def tearDown(self):
        for path in self.root.rglob("*"):
            if path.is_file():
                os.chmod(path, stat.S_IREAD | stat.S_IWRITE)
        self.tmp.cleanup()

    def test_current_until_the_source_or_the_schema_changes(self):
        expected = {**cache.file_stamp(self.source), "schema_sha": "abc"}
        self.assertTrue(cache.is_current(self.derived, expected))
        self.assertFalse(cache.is_current(self.derived, {**expected, "schema_sha": "def"}))
        later = time.time() + 5
        os.utime(self.source, (later, later))
        self.assertFalse(cache.is_current(self.derived, {**cache.file_stamp(self.source), "schema_sha": "abc"}))

    def test_missing_or_unreadable_files_are_never_current(self):
        self.assertEqual(cache.read_meta(self.root / "absent.sqlite"), {})
        broken = self.root / "broken.sqlite"
        broken.write_bytes(b"not a database")
        self.assertEqual(cache.read_meta(broken), {})
        self.assertFalse(cache.is_current(broken, {}))

    def test_meta_is_rewritten_not_duplicated(self):
        with closing(sqlite3.connect(self.derived)) as conn:
            cache.write_meta(conn, {"schema_sha": "new"})
            conn.commit()
        self.assertEqual(cache.read_meta(self.derived)["schema_sha"], "new")

    def test_read_only_connections_cannot_write(self):
        with closing(cache.open_read_only(self.derived)) as conn:
            with self.assertRaises(sqlite3.OperationalError):
                conn.execute("DELETE FROM meta")

    def test_digests_are_short_and_follow_the_bytes(self):
        first = cache.digest(self.source)
        self.assertEqual(len(first), cache.DIGEST_LENGTH)
        self.source.write_text("<b/>", encoding="utf-8")
        self.assertNotEqual(cache.digest(self.source), first)


class FrozenCopies(Provenance):
    def test_the_copy_exists_inside_the_block_and_is_gone_after(self):
        into = self.root / "cache"
        with cache.frozen_copy(self.source, into) as (copy, stamp):
            self.assertEqual(copy.read_text(encoding="utf-8"), "<a/>")
            self.assertEqual(copy.name, "source.frozen.xml")
            self.assertEqual(stamp, cache.file_stamp(self.source))
        self.assertFalse(copy.exists())

    def test_a_read_only_source_leaves_no_undeletable_copy(self):
        os.chmod(self.source, stat.S_IREAD)
        with cache.frozen_copy(self.source, self.root / "cache") as (copy, _):
            pass
        self.assertFalse(copy.exists())

    def test_a_source_that_changes_while_copied_is_refused_and_cleaned_up(self):
        def copy_while_writing(source, target):
            shutil.copyfile(source, target)
            later = time.time() + 10
            os.utime(source, (later, later))  # the other program writes during the copy

        with self.assertRaisesRegex(cache.CacheError, "changed while it was being copied"):
            with cache.frozen_copy(self.source, self.root / "cache", copy=copy_while_writing):
                self.fail("the block must not run")
        self.assertEqual(list((self.root / "cache").iterdir()), [])

    def test_remove_handles_read_only_and_missing_files(self):
        target = self.root / "locked.txt"
        target.write_text("x", encoding="utf-8")
        os.chmod(target, stat.S_IREAD)
        cache.remove(target)
        self.assertFalse(target.exists())
        cache.remove(target)  # already gone: no error


class Folders(unittest.TestCase):
    def test_each_tool_has_a_folder_in_the_cache_root(self):
        self.assertEqual(cache.folder("rimworld-saves", "root"), Path("root") / "rimworld-saves")
        self.assertEqual(cache.folder("x", environ={"PHOBOS_MODKIT_CACHE": "env"}), Path("env") / "x")


if __name__ == "__main__":
    unittest.main()
