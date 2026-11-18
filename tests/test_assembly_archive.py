"""The assembly archive: keeping each distinct version once, unpacking it intact, and choosing what RimWorld to watch.

Files here are made-up bytes, never real assemblies: the archive keeps files without reading them as .NET.
"""
import io
import os
from pathlib import Path
import tempfile
import unittest

import support  # noqa: F401  (the package on the import path)
from phobos_modkit.assembly_archive import Archive, ArchiveError, Source, default_archive, history, pick
from phobos_modkit.games.rimworld.archive_cli import EXIT_OK, main, tied_mods

ABOUT = "<ModMetaData><name>{name}</name><packageId>{pid}</packageId>{extra}</ModMetaData>"


def write(path, content):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, bytes):
        path.write_bytes(content)
    else:
        path.write_text(content, encoding="utf-8")
    return path


def make_mod(folder, name, pid, extra="", dll=None, load_folders=None):
    write(folder / "About" / "About.xml", ABOUT.format(name=name, pid=pid, extra=extra))
    if load_folders:
        write(folder / "LoadFolders.xml", load_folders)
    if dll is not None:
        write(folder / "1.7" / "Assemblies" / dll[0], dll[1])


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.archive = Archive(self.root / "archive")
        self.dll = write(self.root / "game" / "Thing.dll", b"first build" * 100)

    def tearDown(self):
        self.tmp.cleanup()

    def source(self, version="1"):
        return Source("owner.one", "Owner One", version, self.dll)

    def test_nothing_is_written_until_something_is_kept(self):
        self.assertEqual(self.archive.versions(), [])
        self.assertFalse((self.root / "archive").exists())

    def test_a_version_is_kept_once_and_a_change_is_kept_again(self):
        self.assertEqual(self.archive.add([self.source()], "t1")[0][1], "first")
        self.assertEqual(self.archive.add([self.source()], "t2")[0][1], "same")
        write(self.dll, b"second build" * 100)
        self.assertEqual(self.archive.add([self.source("2")], "t3")[0][1], "new")
        chain = history(self.archive.versions(), "thing.dll")
        self.assertEqual([v.version for v in chain], ["1", "2"])
        self.assertEqual([v.seen_at for v in chain], ["t1", "t3"])

    def test_going_back_to_an_older_build_is_a_new_version_but_stores_nothing_new(self):
        self.archive.add([self.source("1")], "t1")
        original = self.dll.read_bytes()
        write(self.dll, b"second build" * 100)
        self.archive.add([self.source("2")], "t2")
        write(self.dll, original)
        self.archive.add([self.source("1")], "t3")
        self.assertEqual(len(self.archive.versions()), 3)
        self.assertEqual(len(list((self.root / "archive" / "objects").rglob("*.gz"))), 2)

    def test_an_older_version_unpacks_to_exactly_what_was_kept(self):
        original = self.dll.read_bytes()
        self.archive.add([self.source("1")], "t1")
        write(self.dll, b"second build" * 100)
        self.archive.add([self.source("2")], "t2")
        older = self.archive.extract(pick(history(self.archive.versions(), "Thing.dll"), 1))
        self.assertEqual(older.read_bytes(), original)
        self.assertEqual(older.name, "Thing.dll")

    def test_a_damaged_copy_is_refused_rather_than_handed_out(self):
        self.archive.add([self.source()], "t1")
        stored = next((self.root / "archive" / "objects").rglob("*.gz"))
        import gzip
        with gzip.open(stored, "wb") as out:
            out.write(b"something else")
        with self.assertRaises(ArchiveError):
            self.archive.extract(self.archive.versions()[0])

    def test_a_file_two_owners_ship_needs_an_owner(self):
        self.archive.add([self.source(), Source("owner.two", "Owner Two", "1", self.dll)], "t1")
        with self.assertRaises(ArchiveError):
            history(self.archive.versions(), "Thing.dll")
        self.assertEqual(len(history(self.archive.versions(), "Thing.dll", "OWNER.TWO")), 1)

    def test_going_back_further_than_the_archive_reaches_is_refused(self):
        self.archive.add([self.source()], "t1")
        chain = history(self.archive.versions(), "Thing.dll")
        self.assertIs(pick(chain, 0), chain[0])
        with self.assertRaises(ArchiveError):
            pick(chain, 1)

    def test_the_default_place_is_not_a_temp_folder(self):
        self.assertEqual(default_archive("win32", {"LOCALAPPDATA": r"C:\Users\x\AppData\Local"}),
                         Path(r"C:\Users\x\AppData\Local") / "phobos-modkit" / "assembly-archive")
        self.assertEqual(default_archive("linux", {}, home="/home/x"), Path("/home/x/.local/share/phobos-modkit/assembly-archive"))


class RimWorldTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.project = root / "project"
        make_mod(self.project / "mods" / "Ours", "Ours", "Our.Mod",
                 extra="<modDependencies><li><packageId>tied.dependency</packageId></li></modDependencies>"
                       "<loadAfter><li>tied.after_steam</li><li>our.other</li></loadAfter>",
                 load_folders='<loadFolders><v1.7><li IfModActive="Tied.Folder, tied.dependency">Mods/X</li></v1.7></loadFolders>')
        make_mod(self.project / "mods" / "OursToo", "Ours Too", "our.other")
        self.game = root / "steamapps" / "common" / "RimWorld"
        write(self.game / "Assembly-CSharp.dll", b"game build one")
        write(self.game / "Version.txt", "1.7.5011 rev24\n")
        workshop = root / "steamapps" / "workshop" / "content" / "294100"
        make_mod(workshop / "1", "Tied Dependency", "tied.dependency", "<modVersion>2.0</modVersion>", ("Dep.dll", b"dep one"))
        make_mod(workshop / "2", "Tied Folder", "tied.folder", dll=("Folder.dll", b"folder one"))
        make_mod(workshop / "3", "Untied", "untied.mod", dll=("Untied.dll", b"untied"))
        make_mod(workshop / "4", "Tied After", "tied.after", dll=("After.dll", b"after"))
        self.config = root / "Config"
        write(self.config / "ModsConfig.xml", "<ModsConfigData><version>1.7.5011 rev24</version><activeMods>"
                                              "<li>ludeon.rimworld</li><li>tied.dependency</li><li>tied.folder</li>"
                                              "<li>untied.mod</li></activeMods></ModsConfigData>")
        self.common = ["--archive", str(root / "archive"), "--no-redact"]
        self.snapshot = ["snapshot", "--root", str(self.project), "--game", str(self.game), "--workshop", str(workshop),
                         "--config", str(self.config)] + self.common

    def tearDown(self):
        self.tmp.cleanup()

    def run_main(self, argv, now="t"):
        out = io.StringIO()
        code = main(argv, environ={}, out=out, now=now)
        return code, out.getvalue()

    def test_tie_ins_come_from_about_and_load_folders_and_leave_our_own_out(self):
        own, tied = tied_mods(self.project)
        self.assertEqual(own, {"our.mod", "our.other"})
        self.assertEqual(tied, {"tied.dependency", "tied.after", "tied.folder"})

    def test_a_snapshot_keeps_the_game_and_active_tied_mods_only(self):
        code, text = self.run_main(self.snapshot)
        self.assertEqual(code, EXIT_OK, text)
        self.assertIn("3 kept now", text)
        for kept in ("Assembly-CSharp.dll", "Dep.dll", "Folder.dll"):
            self.assertIn(kept, text)
        self.assertNotIn("Untied.dll", text)   # active but not tied
        self.assertNotIn("After.dll", text)    # tied but switched off
        self.assertIn("1.7.5011 rev24", text)
        self.assertIn("2.0", text)

    def test_a_second_snapshot_keeps_only_what_changed_and_list_shows_the_history(self):
        self.run_main(self.snapshot, now="day one")
        write(self.game / "Assembly-CSharp.dll", b"game build two")
        write(self.game / "Version.txt", "1.7.5013 rev95\n")
        code, text = self.run_main(self.snapshot, now="day two")
        self.assertIn("1 kept now, 2 unchanged", text)
        code, text = self.run_main(["list", "--file", "assembly-csharp.dll"] + self.common)
        self.assertEqual(code, EXIT_OK, text)
        self.assertIn("1.7.5011 rev24", text)
        self.assertIn("day two", text)
        code, text = self.run_main(["get", "Assembly-CSharp.dll", "--back", "1"] + self.common)
        self.assertEqual(Path(text.strip()).read_bytes(), b"game build one")

    def test_asking_for_a_file_the_archive_never_kept_says_so(self):
        self.run_main(self.snapshot)
        code, text = self.run_main(["compare", "Nothing.dll"] + self.common)
        self.assertNotEqual(code, EXIT_OK)
        self.assertIn("holds no Nothing.dll", text)

    def test_with_no_game_on_the_machine_it_can_pass_quietly(self):
        argv = ["snapshot", "--root", str(self.project), "--game", os.path.join(self.tmp.name, "nowhere"), "--if-installed"] + self.common
        code, text = self.run_main(argv)
        self.assertEqual(code, EXIT_OK)
        self.assertIn("skipped", text)


if __name__ == "__main__":
    unittest.main()
