"""rimworld-textures: stale, missing and left-over encoded textures, and encoding with RimSort's preset. Folders written by hand; todds is
a stand-in, so nothing is encoded and no real install is read."""
import io
import json
import os
from pathlib import Path
import tempfile
import time
import unittest

import support  # noqa: F401  (puts the package on the path)
from phobos_modkit.games.rimworld import textures, textures_cli
from phobos_modkit.games.rimworld.mods import InstalledMod


def write(path, when):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x")
    os.utime(path, (when, when))


def sample_mod(folder):
    now = time.time()
    write(folder / "Textures" / "Fresh.png", now - 3600)
    write(folder / "Textures" / "Fresh.dds", now - 600)
    write(folder / "Textures" / "Changed.png", now - 60)               # updated after it was encoded
    write(folder / "Textures" / "Changed.dds", now - 86_400)
    write(folder / "Textures" / "Close.png", now - 30)                 # written a moment after its .dds by a download
    write(folder / "Textures" / "Close.dds", now - 60)
    write(folder / "1.7" / "Textures" / "Things" / "New.png", now)     # never encoded
    write(folder / "Textures" / "Gone.dds", now)                       # its picture was removed
    write(folder / "About" / "Preview.png", now)                       # not under Textures: never read


class CheckTests(unittest.TestCase):
    def test_stale_missing_and_left_over_are_told_apart(self):
        with tempfile.TemporaryDirectory() as tmp:
            sample_mod(Path(tmp))
            found = textures.check_folder(tmp)
            self.assertEqual(found.pictures, 4)
            self.assertEqual(found.stale, ["Textures/Changed.png"])
            self.assertEqual(found.missing, ["1.7/Textures/Things/New.png"])
            self.assertEqual(found.left_over, ["Textures/Gone.dds"])
            self.assertTrue(found.needs_encoding)

    def test_letter_case_does_not_split_a_picture_from_its_encoding(self):
        with tempfile.TemporaryDirectory() as tmp:
            write(Path(tmp) / "Textures" / "Boat.PNG", time.time() - 600)
            write(Path(tmp) / "Textures" / "boat.dds", time.time())
            found = textures.check_folder(tmp)
            self.assertEqual((found.stale, found.missing, found.left_over), ([], [], []))


def installed(folder, name="Sample Mod", package="test.sample", source="Workshop"):
    return InstalledMod(package, name, source, Path(folder))


class CliTests(unittest.TestCase):
    def run_cli(self, argv, mods, running=lambda names: [], run=None):
        out = io.StringIO()
        code = textures_cli.main([*argv, "--json", "--todds", __file__], environ=support.isolated_environ(), out=out, running=running,
                                 run=run, mods=mods)
        return code, json.loads(out.getvalue())

    def test_status_names_the_mods_that_would_show_old_pictures(self):
        with tempfile.TemporaryDirectory() as tmp:
            sample_mod(Path(tmp) / "a")
            write(Path(tmp) / "b" / "Textures" / "Ok.png", time.time() - 600)
            write(Path(tmp) / "b" / "Textures" / "Ok.dds", time.time())
            code, answer = self.run_cli(["status"], [installed(Path(tmp) / "a"), installed(Path(tmp) / "b", "In Step", "test.ok")])
            self.assertEqual(code, 0)
            self.assertEqual(answer["data"]["totals"]["staleMods"], 1)
            self.assertEqual([m["name"] for m in answer["data"]["mods"]], ["Sample Mod"])
            self.assertIn("would show old pictures", answer["report"]["title"])

    def test_encode_runs_rimsorts_preset_on_each_named_mod(self):
        with tempfile.TemporaryDirectory() as tmp:
            sample_mod(Path(tmp) / "a")
            calls = []

            def run(command, **kwargs):
                calls.append(command)

                class Result:
                    returncode, stdout, stderr = 0, "done", ""
                return Result()

            code, answer = self.run_cli(["encode", "--mod", "TEST.SAMPLE"], [installed(Path(tmp) / "a")], run=run)
            self.assertEqual((code, answer["data"]["ok"]), (0, True))
            self.assertEqual(calls[0][1:], [*textures.RIMSORT_OPTIMIZED, str(Path(tmp) / "a")])

    def test_encode_refuses_while_the_game_runs_and_for_a_mod_not_active(self):
        with tempfile.TemporaryDirectory() as tmp:
            sample_mod(Path(tmp) / "a")
            mods = [installed(Path(tmp) / "a")]
            never = lambda *a, **k: self.fail("encoded")
            code, answer = self.run_cli(["encode", "--mod", "test.sample"], mods, running=lambda names: ["rimworld.exe"], run=never)
            self.assertEqual((code, answer["data"]["ok"]), (1, False))
            self.assertIn("running", answer["data"]["refusal"])
            code, answer = self.run_cli(["encode", "--mod", "someone.else"], mods, run=never)
            self.assertIn("Not an active mod", answer["data"]["refusal"])

    def test_the_preset_is_rimsorts_optimized_one(self):
        self.assertEqual(textures.RIMSORT_OPTIMIZED, ("-f", "BC1", "-af", "BC7", "-on", "-vf", "-fs", "-ss", "Textures", "-t", "-p"))


if __name__ == "__main__":
    unittest.main()
