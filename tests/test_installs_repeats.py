"""Repeated backups (1.40.0): a backup that repeats the one before it, file for file or only rebuilt, and removing them."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import support  # noqa: F401  (puts the package on the path)
from phobos_modkit import installs


def write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data if isinstance(data, bytes) else data.encode("utf-8"))


def backup(folder, name, dll, defs="<Defs/>", commit="c1", version="1.0.0"):
    root = folder / name
    write(root / "1.7" / "Assemblies" / "Boats.dll", dll)
    write(root / "Defs" / "Things.xml", defs)
    write(root / "InstallRecord.json", json.dumps({"format": 1, "mod": "Boats", "version": version, "commit": commit,
                                                   "uncommittedCount": 0, "installed": name}))
    copy = installs.Copy("backup", root, "Boats", version, None, json.loads((root / "InstallRecord.json").read_text()), name)
    copy.size = installs.size_of(root)
    return copy


class RepeatTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name)
        self.environ = {"PHOBOS_MODKIT_CACHE": str(self.folder / "cache")}

    def test_the_record_is_left_out_and_bytes_count(self):
        a = backup(self.folder, "Boats-20261101-100000", b"one")
        b = backup(self.folder, "Boats-20261102-100000", b"one", commit="c2")
        c = backup(self.folder, "Boats-20261103-100000", b"two", commit="c3")
        self.assertEqual(installs.content_digest(a.folder), installs.content_digest(b.folder))
        self.assertNotEqual(installs.content_digest(a.folder), installs.content_digest(c.folder))
        self.assertEqual(installs.content_digest(a.folder, True), installs.content_digest(c.folder, True))

    def test_only_a_run_repeats_and_the_oldest_is_kept(self):
        copies = [backup(self.folder, "Boats-20261101-100000", b"A"), backup(self.folder, "Boats-20261102-100000", b"A"),
                  backup(self.folder, "Boats-20261103-100000", b"B"), backup(self.folder, "Boats-20261104-100000", b"A")]
        digests = installs.backup_digests(copies, self.environ)
        repeats = installs.mark_duplicates(copies, digests)
        self.assertEqual([(c.backup, c.same_as, c.same_kind) for c in repeats],
                         [("Boats-20261102-100000", "Boats-20261101-100000", "identical")])

    def test_a_rebuild_counts_only_when_the_version_and_other_files_match_and_the_check_agrees(self):
        copies = [backup(self.folder, "Boats-20261101-100000", b"A", commit="c1"),
                  backup(self.folder, "Boats-20261102-100000", b"A2", commit="c2"),
                  backup(self.folder, "Boats-20261103-100000", b"A3", commit="c3", defs="<Defs><X/></Defs>"),
                  backup(self.folder, "Boats-20261104-100000", b"A4", commit="c4", defs="<Defs><X/></Defs>", version="1.1.0")]
        digests = installs.backup_digests(copies, self.environ)
        asked = []

        def check(older, newer):
            asked.append((older.backup, newer.backup))
            return True

        repeats = installs.mark_duplicates(copies, digests, check)
        self.assertEqual([(c.backup, c.same_kind) for c in repeats], [("Boats-20261102-100000", "rebuilt")])
        self.assertEqual(asked, [("Boats-20261101-100000", "Boats-20261102-100000")])
        self.assertEqual(installs.mark_duplicates(copies, digests, lambda older, newer: False), [])

    def test_digests_are_kept_and_read_once(self):
        copies = [backup(self.folder, "Boats-20261101-100000", b"A")]
        installs.backup_digests(copies, self.environ)
        with mock.patch.object(installs, "content_digest", side_effect=AssertionError("read again")):
            installs.backup_digests(copies, self.environ)

    def test_unchanged_sources_need_both_commits_and_no_difference(self):
        with mock.patch.object(installs.checks, "_git", return_value=""):
            self.assertTrue(installs.sources_unchanged(self.folder, "c1", "c2", ["src/Boats"]))
        with mock.patch.object(installs.checks, "_git", return_value="src/Boats/Boat.cs\n"):
            self.assertFalse(installs.sources_unchanged(self.folder, "c1", "c2", ["src/Boats"]))
        with mock.patch.object(installs.checks, "_git", return_value=None):
            self.assertFalse(installs.sources_unchanged(self.folder, "c1", "c2", ["src/Boats"]))
        self.assertFalse(installs.sources_unchanged(self.folder, None, "c2", ["src/Boats"]))


if __name__ == "__main__":
    unittest.main()
