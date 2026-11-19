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


def dds(path, width, height, fourcc=b"DX10", dxgi=98, mips=None, extra=b""):
    """A block-compressed DDS file written from the format's published layout, with a full mip chain unless told otherwise; each
    level's bytes are its level number, so a shortened file can be checked byte for byte."""
    mips = mips or max(width, height).bit_length()
    block = 8 if fourcc == b"DXT1" or dxgi in (70, 71, 72, 79, 80, 81) else 16
    header = bytearray(148 if fourcc == b"DX10" else 128)
    header[:4] = b"DDS "
    for at, value in ((4, 124), (8, 0x1 | 0x2 | 0x4 | 0x1000 | 0x20000), (12, height), (16, width), (28, mips), (76, 32), (80, 0x4)):
        header[at:at + 4] = value.to_bytes(4, "little")
    header[84:88] = fourcc
    if fourcc == b"DX10":
        for at, value in ((128, dxgi), (132, 3), (140, 1)):
            header[at:at + 4] = value.to_bytes(4, "little")
    levels = b"".join(bytes([level]) * (-(-max(1, width >> level) // 4) * -(-max(1, height >> level) // 4) * block)
                      for level in range(mips))
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(bytes(header) + levels + extra)
    return path


class MipTests(unittest.TestCase):
    def test_a_chain_waylith_would_unpack_is_cut_at_its_first_odd_height(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = dds(Path(tmp) / "Wide.dds", 8, 320)              # 320, 160, 80, 40, 20, then 10: not a multiple of four
            before = path.read_bytes()
            self.assertEqual(textures.trim_mips(path), textures.TRIMMED)
            after = path.read_bytes()
            layout = textures.read_layout(after[:148], len(after))
            self.assertEqual((layout.mips, layout.height, layout.width), (5, 320, 8))
            self.assertEqual(after[148:], before[148:148 + len(after) - 148])     # the kept levels, untouched
            self.assertEqual(after[148:], b"".join(bytes([n]) * layout.level_bytes(n) for n in range(5)))
            self.assertEqual(textures.trim_mips(path), textures.IN_STEP)          # a second run changes nothing
            self.assertEqual(path.read_bytes(), after)
            self.assertFalse(list(Path(tmp).glob("*.trimming")))

    def test_power_of_two_heights_and_dxt1_files_are_read_and_kept(self):
        with tempfile.TemporaryDirectory() as tmp:
            square = dds(Path(tmp) / "Square.dds", 512, 512)
            wide = dds(Path(tmp) / "Wide.dds", 1408, 512)                # width is not what Waylith checks
            self.assertEqual([textures.trim_mips(p) for p in (square, wide)], [textures.IN_STEP] * 2)
            bc1 = dds(Path(tmp) / "Opaque.dds", 16, 1152, fourcc=b"DXT1")   # 1152 ... 36, then 18
            self.assertEqual(textures.trim_mips(bc1), textures.TRIMMED)
            data = bc1.read_bytes()
            self.assertEqual(textures.read_layout(data[:148], len(data)).mips, 6)

    def test_a_chain_left_too_short_is_left_whole(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = dds(Path(tmp) / "Nacelle.dds", 228, 1156)        # 1156, then 578: only one level would remain
            before = path.read_bytes()
            self.assertEqual(textures.kept_mips(1156, 11), 1)
            self.assertEqual(textures.trim_mips(path), textures.LEFT_WHOLE)
            self.assertEqual(path.read_bytes(), before)
            self.assertEqual(textures.trim_mips(path, min_kept=1), textures.TRIMMED)

    def test_files_it_cannot_account_for_are_never_touched(self):
        with tempfile.TemporaryDirectory() as tmp:
            odd = dds(Path(tmp) / "Odd.dds", 8, 320, extra=b"more")       # a size the layout does not explain
            plain = dds(Path(tmp) / "Plain.dds", 8, 320, dxgi=28)          # plain pixels, not blocks
            for path in (odd, plain):
                before = path.read_bytes()
                self.assertEqual(textures.trim_mips(path), textures.NOT_COMPRESSED)
                self.assertEqual(path.read_bytes(), before)

    def test_a_folder_is_trimmed_only_under_textures(self):
        with tempfile.TemporaryDirectory() as tmp:
            dds(Path(tmp) / "Textures" / "Things" / "Truck.dds", 8, 1408)
            dds(Path(tmp) / "Textures" / "Fine.dds", 8, 1024)
            dds(Path(tmp) / "Textures" / "Nacelle.dds", 228, 1156)
            outside = dds(Path(tmp) / "About" / "Truck.dds", 8, 1408)
            before = outside.read_bytes()
            found = textures.trim_folder(tmp)
            self.assertEqual((found.checked, found.trimmed, found.left_whole, found.failed),
                             (3, ["Textures/Things/Truck.dds"], ["Textures/Nacelle.dds"], []))
            self.assertEqual(outside.read_bytes(), before)
            self.assertEqual(textures.trim_folder(tmp).trimmed, [])


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

            dds(Path(tmp) / "a" / "Textures" / "Truck.dds", 8, 1408)     # encoded earlier, so todds leaves it alone
            code, answer = self.run_cli(["encode", "--mod", "TEST.SAMPLE"], [installed(Path(tmp) / "a")], run=run)
            self.assertEqual((code, answer["data"]["ok"]), (0, True))
            self.assertEqual(calls[0][1:], [*textures.RIMSORT_OPTIMIZED, str(Path(tmp) / "a")])
            self.assertEqual(answer["data"]["mods"][0]["mipsShortened"], 1)

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
