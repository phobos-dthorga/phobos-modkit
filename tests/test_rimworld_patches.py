"""rimworld-patches: choosing the assemblies the game loads, and (with the .NET SDK) reading a made-up mod's patches.

The reader and its fixture assembly are built from source in the kit's build folder. Without the .NET SDK the reading
tests are skipped, unless PHOBOS_REQUIRE_NATIVE is set, as for the Rust tools.
"""
import io
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from support import FIXTURES
from phobos_modkit import native
from phobos_modkit.games.rimworld import loading
from phobos_modkit.games.rimworld.mods import ModIndex
from phobos_modkit.games.rimworld.patches import build_reader, mod_assemblies, read_assemblies, reader_path
from phobos_modkit.games.rimworld.patches_cli import EXIT_OK, main

ABOUT = "<ModMetaData><name>{name}</name><packageId>{pid}</packageId></ModMetaData>"
HAVE_DOTNET = shutil.which("dotnet") is not None
REQUIRE = bool(os.environ.get("PHOBOS_REQUIRE_NATIVE"))
FIXTURE_PROJECT = FIXTURES / "dotnet" / "PatchFixture" / "PatchFixture.csproj"


def fixture_dll():
    """Build the fixture assembly (once per run) and return its path."""
    out = native.build_dir() / "dotnet" / "fixtures" / "PatchFixture"
    dll = out / "PatchFixture.dll"
    if not getattr(fixture_dll, "built", False):
        result = subprocess.run(["dotnet", "build", str(FIXTURE_PROJECT), "-c", "Release", "-o", str(out), "--nologo",
                                 "-v", "q"], capture_output=True, text=True, check=False)
        if result.returncode != 0:
            raise AssertionError("the fixture did not build:\n" + result.stdout[-2000:])
        fixture_dll.built = True
    return dll


def make_mod(root, folder, name, pid, dlls=(), load_folders=None):
    mod = root / folder
    (mod / "About").mkdir(parents=True)
    (mod / "About" / "About.xml").write_text(ABOUT.format(name=name, pid=pid), encoding="utf-8")
    if load_folders:
        (mod / "LoadFolders.xml").write_text(load_folders, encoding="utf-8")
    for relative, source in dlls:
        target = mod / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if source is None:
            target.write_bytes(b"not a real assembly")
        else:
            shutil.copyfile(source, target)
    return mod


class Choosing(unittest.TestCase):
    def test_the_assemblies_the_game_loads_for_its_version(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "Mods"
            make_mod(root, "A", "Mod A", "a.mod", [("1.7/Assemblies/A.dll", None), ("1.6/Assemblies/Old.dll", None),
                                                   ("1.7/Assemblies/0Harmony.dll", None)])
            make_mod(root, "B", "Mod B", "b.mod", [("Common/Assemblies/B.dll", None), ("Mods/CE/Assemblies/BCe.dll", None)],
                     load_folders="<loadFolders><v1.7><li>Common</li><li IfModActive=\"ceteam.combatextended\">Mods/CE</li>"
                                  "</v1.7></loadFolders>")
            index = ModIndex.scan([("Local", root)])
            active = loading.resolve_active(index.mods, ["a.mod", "b.mod"])
            found = [(entry.mod.package_id, dll.name) for entry, dll in mod_assemblies(active, "1.7")]
        self.assertEqual(found, [("a.mod", "A.dll"), ("b.mod", "B.dll")])


@unittest.skipUnless(HAVE_DOTNET or REQUIRE, "needs the .NET SDK")
class Reading(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not reader_path().is_file():
            build_reader()
        cls.dll = fixture_dll()

    def test_every_kind_of_patch_in_the_fixture(self):
        record, = read_assemblies(reader_path(), [str(self.dll)])
        found = {(p["patchClass"].split(".")[-1], p["patchMethod"]): p for p in record["patches"]}
        kill = found[("KillPatch", "Prefix")]
        self.assertEqual((kill["kind"], kill["targetType"], kill["targetMember"], kill["canSkip"], kill["priority"]),
                         ("prefix", "Game.Pawn", "Kill", True, 800))
        self.assertFalse(found[("KillPatch", "Postfix")]["canSkip"])
        self.assertEqual(found[("DownedPatch", "Postfix")]["methodType"], "Getter")
        heal = found[("HealPatch", "Before")]
        self.assertEqual((heal["kind"], heal["argumentTypes"]), ("prefix", ["System.Collections.Generic.List<System.Int32>", "System.Single"]))
        self.assertEqual(found[("HealPatch", "After")]["kind"], "postfix")
        tick = found[("TickPatch", "Postfix")]
        self.assertEqual((tick["targetType"], tick["targetMember"], tick["note"]), ("Game.Map", "Tick", "target read from TargetMethod's code"))
        install = found[("Manual", "AfterInstall")]
        self.assertEqual((install["source"], install["targetType"], install["targetMember"]), ("call", "Other.Bridge", "Install"))
        downed = found[("Manual", "DownedPrefix")]
        self.assertEqual((downed["kind"], downed["targetType"], downed["methodType"]), ("prefix", "Game.Pawn", "Getter"))
        self.assertNotIn(("NotAPatch", "Postfix"), found)

    def test_a_file_that_is_not_an_assembly_is_an_error_not_a_stop(self):
        with tempfile.TemporaryDirectory() as tmp:
            junk = Path(tmp) / "junk.dll"
            junk.write_bytes(b"MZ but nothing else")
            records = read_assemblies(reader_path(), [str(junk), str(self.dll)])
        self.assertIn("error", records[0])
        self.assertTrue(records[1]["patches"])

    def test_the_command_on_a_made_up_install(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            game = root / "RimWorld"
            make_mod(game / "Mods", "Fixture", "Fixture Mod", "fixture.mod", [("1.7/Assemblies/PatchFixture.dll", self.dll)])
            config = root / "Config"
            config.mkdir()
            (config / "ModsConfig.xml").write_text("<ModsConfigData><version>1.7.1 rev1</version><activeMods>"
                                                   "<li>fixture.mod</li></activeMods></ModsConfigData>", encoding="utf-8")
            common = ["--game", str(game), "--workshop", str(root / "none"), "--config", str(config), "--cache", str(root / "cache"),
                      "--no-redact"]
            out = io.StringIO()
            self.assertEqual(main(["who", "Pawn.Kill"] + common, environ={}, out=out), EXIT_OK)
            text = out.getvalue()
            self.assertIn("2 patches from 1 mods.", text)
            self.assertIn("may skip the original; priority 800", text)
            out = io.StringIO()
            main(["summary"] + common, environ={}, out=out)
            self.assertIn("Read now: 0 assemblies; 1 unchanged", out.getvalue())


if __name__ == "__main__":
    unittest.main()
