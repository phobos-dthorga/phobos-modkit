"""backup_archive and the install helper's zipped backups (1.96.0): packing a folder backup, reading one back, comparing it with a
folder, going back to one, and refusing an archive that would unpack outside its folder. Every file is written in temporary
folders."""
from pathlib import Path
import tempfile
import unittest
import zipfile

import support  # noqa: F401  (puts the package on the path)
from phobos_modkit import backup_archive as archives
from phobos_modkit import installs
from test_installs import Fixture, write_mod


def _picture(folder, data=b"\x89PNG sample picture"):
    path = Path(folder) / "Textures" / "Boat.png"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


class ArchiveTests(unittest.TestCase):
    def test_a_folder_and_its_zip_hold_the_same_files_and_hash_the_same(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = write_mod(Path(tmp) / "Thing", "0.1.0", "# Thing changelog\n")
            _picture(folder)
            archive = Path(tmp) / "Thing.zip"
            size = archives.write(folder, archive)
            self.assertEqual(size, archive.stat().st_size)
            self.assertEqual([r for r, _ in archives.members(archive)], [r for r, _ in archives.files_of(folder)])
            self.assertEqual(installs.content_digests(archive), installs.content_digests(folder))
            self.assertFalse((Path(tmp) / "Thing.zip.partial").exists())

    def test_writing_over_an_existing_zip_is_refused_and_leaves_nothing_behind(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = write_mod(Path(tmp) / "Thing", "0.1.0", "# Thing changelog\n")
            archive = Path(tmp) / "Thing.zip"
            archive.write_bytes(b"something else")
            with self.assertRaises(archives.ArchiveError):
                archives.write(folder, archive)
            self.assertEqual(archive.read_bytes(), b"something else")

    def test_an_archive_that_would_unpack_outside_its_folder_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive = Path(tmp) / "Bad.zip"
            with zipfile.ZipFile(archive, "w") as out:
                out.writestr("../outside.txt", "no")
            with self.assertRaises(archives.ArchiveError):
                archives.unpack(archive, Path(tmp) / "into")
            self.assertFalse((Path(tmp) / "outside.txt").exists())

    def test_backup_names_count_folders_and_zips_once_and_skip_half_written_ones(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "Thing-20261101-120000").mkdir()
            (Path(tmp) / "Thing-20261102-120000.zip").write_bytes(b"")
            (Path(tmp) / "Thing-20261103-120000.zip.partial").write_bytes(b"")
            self.assertEqual(archives.names(tmp), ["Thing-20261101-120000", "Thing-20261102-120000"])


class PackingTests(unittest.TestCase):
    def test_pack_turns_a_folder_backup_into_a_zip_read_back_as_before(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = Fixture(tmp)
            backups = f.repo / ".local" / "backups"
            name = "Thing-20261101-120000"
            before = installs.read_backup(f.where, name)
            digests = installs.content_digests(backups / name)
            packed, left = installs.pack(f.where)
            self.assertEqual(([p["backup"] for p in packed], left), ([name], []))
            self.assertEqual(sorted(p.name for p in backups.iterdir()), [f"{name}.zip"])
            after = installs.read_backup(f.where, name, measure=True)
            self.assertEqual((after.name, after.version, after.backup), (before.name, before.version, name))
            self.assertEqual(after.size, (backups / f"{name}.zip").stat().st_size)
            self.assertEqual(installs.content_digests(after.archive), digests)
            # Packed already: a second pass has nothing to do.
            self.assertEqual(installs.pack(f.where), ([], []))

    def test_status_reads_a_zipped_backup_and_copies_out_a_changed_picture_to_compare(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = Fixture(tmp)
            name = "Thing-20261101-120000"
            _picture(f.repo / ".local" / "backups" / name, b"old picture")
            _picture(f.game / "Mods" / "Thing", b"installed picture")
            _picture(f.repo / "mods" / "Thing", b"repository picture")
            installs.pack(f.where)
            code, answer = f.run("status")
            mod = answer["data"]["mods"][0]
            backup = mod["backups"][0]
            self.assertEqual((code, backup["backup"], backup["version"]), (0, name, "0.1.0"))
            self.assertEqual((Path(backup["folder"]) / "Textures" / "Boat.png").read_bytes(), b"old picture")

    def test_going_back_to_a_zipped_backup_unpacks_it_in_place(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = Fixture(tmp)
            installs.pack(f.where)
            code, answer = f.run("restore", "--mod", "Thing", "--backup", "Thing-20261101-120000")
            self.assertEqual(code, 0)
            self.assertEqual(f.where.game.identity(f.game / "Mods" / "Thing")[1], "0.1.0")
            self.assertTrue((f.repo / ".local" / "backups" / "Thing-20261101-120000.zip").is_file())

    def test_a_repeated_zipped_backup_is_removed_like_a_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = Fixture(tmp)
            backups = f.repo / ".local" / "backups"
            for stamp in ("20261110-120000", "20261111-120000"):
                code, _ = f.run("backup", "--mod", "Thing")
                (backups / "Thing-20261118-210000.zip").rename(backups / f"Thing-{stamp}.zip")
            removed = installs.dedupe(f.where, ["Thing"])
            self.assertEqual([(r["backup"], r["sameAs"]) for r in removed], [("Thing-20261111-120000", "Thing-20261110-120000")])
            self.assertEqual(sorted(p.name for p in backups.iterdir()),
                             ["Thing-20261101-120000", "Thing-20261110-120000.zip"])

    def test_tidy_says_what_packing_saved(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = Fixture(tmp)
            done, problem = installs.tidy(f.where, ["Thing"])
            self.assertIsNone(problem)
            self.assertEqual([d["kind"] for d in done], [installs.PACKED])
            self.assertIn("Packed 1 backup as zips", installs.tidy_lines(done, problem)[0])


if __name__ == "__main__":
    unittest.main()
