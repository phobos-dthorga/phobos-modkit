"""packed: files kept compressed with zstd, checked before anything is let go (1.149.0)."""
from pathlib import Path
import tempfile
import unittest

import support  # noqa: F401  (puts the package on the path)
from phobos_modkit import packed

TEXT = b"a line of a trace that repeats\n" * 4000


class PackInPlaceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.folder = Path(self.temp.name)
        self.plain = self.folder / "trace.nettrace"
        self.plain.write_bytes(TEXT)

    def tearDown(self):
        self.temp.cleanup()

    def test_pack_keeps_the_bytes_and_removes_the_plain_file(self):
        target = packed.pack(self.plain)
        self.assertEqual(target, packed.packed_of(self.plain))
        self.assertFalse(self.plain.exists())
        self.assertLess(target.stat().st_size, len(TEXT) // 10)
        self.assertEqual(packed.read_bytes(self.plain), TEXT)
        self.assertEqual(packed.present(self.plain), target)
        self.assertEqual(list(self.folder.glob("*.partial")), [])

    def test_pack_again_is_harmless_and_nothing_there_is_refused(self):
        target = packed.pack(self.plain)
        self.assertEqual(packed.pack(self.plain), target)
        with self.assertRaises(packed.PackError):
            packed.pack(self.folder / "missing")

    def test_unpack_gives_the_plain_file_back_and_never_writes_over_one(self):
        target = packed.pack(self.plain)
        self.assertEqual(packed.unpack(target), self.plain)
        self.assertEqual(self.plain.read_bytes(), TEXT)
        self.assertTrue(target.is_file())
        with self.assertRaises(packed.PackError):
            packed.unpack(target)
        self.plain.unlink()
        packed.unpack(target, keep=False)
        self.assertFalse(target.exists())
        with self.assertRaises(packed.PackError):
            packed.unpack(self.plain)


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.folder = Path(self.temp.name)
        self.store = packed.Store(self.folder / "store")

    def tearDown(self):
        self.temp.cleanup()

    def _file(self, name, data):
        path = self.folder / name
        path.write_bytes(data)
        return path

    def test_the_same_bytes_are_kept_once(self):
        first = self.store.put(self._file("a.txt", TEXT))
        second = self.store.put(self._file("b.txt", TEXT))
        self.assertEqual(first, second)
        self.assertEqual(first[1], len(TEXT))
        self.assertEqual(len(self.store.kept()), 1)
        self.assertEqual(list((self.folder / "store").rglob("*.partial")), [])

    def test_get_writes_a_kept_file_out_and_checks_it(self):
        sha, _ = self.store.put(self._file("a.txt", TEXT))
        out = self.store.get(sha, self.folder / "out" / "a.txt")
        self.assertEqual(out.read_bytes(), TEXT)
        with self.assertRaises(packed.PackError):
            self.store.get(sha, out)
        with self.assertRaises(packed.PackError):
            self.store.get("0" * 64, self.folder / "none.txt")

    def test_a_damaged_kept_file_fails_its_check(self):
        sha, _ = self.store.put(self._file("a.txt", TEXT))
        self.assertTrue(self.store.check(sha))
        self.store.path_of(sha).write_bytes(b"not zstd")
        self.assertFalse(self.store.check(sha))

    def test_let_go_removes_only_what_is_named(self):
        keep, _ = self.store.put(self._file("a.txt", TEXT))
        drop, _ = self.store.put(self._file("b.txt", b"other"))
        self.assertEqual(self.store.let_go([drop])[0], 1)
        self.assertEqual(set(self.store.kept()), {keep})


if __name__ == "__main__":
    unittest.main()
