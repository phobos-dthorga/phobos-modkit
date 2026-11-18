"""Lean clones of public source: only source files checked out, updates that never discard work, and a refusal (never a
deletion) when the drive is short of space. A made-up repository on disk stands in for GitHub."""
import io
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

import support  # noqa: F401  (the package on the import path)
from phobos_modkit import source_clones
from phobos_modkit.source_clones import ensure, existing, folder_name

HAVE_GIT = shutil.which("git") is not None
PLENTY = lambda path: (500 * 10 ** 9, 1000 * 10 ** 9)   # noqa: E731
SHORT = lambda path: (5 * 10 ** 9, 1000 * 10 ** 9)      # noqa: E731


def git(root, *args):
    return subprocess.run(["git", "-c", "core.fsmonitor=false", *args], cwd=root, check=True, capture_output=True, text=True)


def make_upstream(root):
    """A repository with source, an About.xml and a texture, served to clones by file:// so partial clones work."""
    root.mkdir(parents=True)
    git(root, "init", "-q", "-b", "main")
    for key, value in (("core.fsmonitor", "false"), ("user.email", "test@example.com"), ("user.name", "Test"),
                       ("uploadpack.allowFilter", "true"), ("uploadpack.allowAnySHA1InWant", "true")):
        git(root, "config", key, value)
    (root / "Source").mkdir()
    (root / "Source" / "Thing.cs").write_text("class Thing {}\n", encoding="utf-8")
    (root / "About").mkdir()
    (root / "About" / "About.xml").write_text("<ModMetaData><packageId>a.b</packageId></ModMetaData>", encoding="utf-8")
    (root / "Textures").mkdir()
    (root / "Textures" / "Big.png").write_bytes(b"\x89PNG" + b"0" * 4096)
    git(root, "add", "-A", "-f")
    git(root, "commit", "-q", "-m", "one")
    return root.as_uri()


class NameTests(unittest.TestCase):
    def test_folder_names_drop_tags_and_join_words(self):
        self.assertEqual(folder_name("[sbz] Fridge"), "Fridge-src")
        self.assertEqual(folder_name("Vehicle Framework"), "VehicleFramework-src")
        self.assertEqual(folder_name("Hospitality (Continued)"), "HospitalityContinued-src")


@unittest.skipUnless(HAVE_GIT, "git is not installed")
class CloneTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.upstream = root / "upstream"
        self.url = make_upstream(self.upstream)
        self.into = root / "project" / ".local" / "decompiled"

    def tearDown(self):
        self.tmp.cleanup()

    def test_a_clone_checks_out_source_but_not_textures(self):
        [outcome] = ensure([("Some Mod", self.url)], self.into, space=PLENTY)
        self.assertEqual(outcome.action, "cloned", outcome.detail)
        folder = self.into / "SomeMod-src"
        self.assertTrue((folder / "Source" / "Thing.cs").is_file())
        self.assertTrue((folder / "About" / "About.xml").is_file())
        self.assertFalse((folder / "Textures" / "Big.png").exists())
        self.assertEqual(git(folder, "config", "core.fsmonitor").stdout.strip(), "false")
        self.assertGreater(outcome.size, 0)
        self.assertEqual([name for name, _ in existing(self.into)], ["SomeMod-src"])

    def test_an_update_moves_forward_and_a_second_finds_nothing_new(self):
        ensure([("Some Mod", self.url)], self.into, space=PLENTY)
        (self.upstream / "Source" / "Other.cs").write_text("class Other {}\n", encoding="utf-8")
        git(self.upstream, "add", "-A")
        git(self.upstream, "commit", "-q", "-m", "two")
        self.assertEqual(ensure([("Some Mod", self.url)], self.into, refresh=True, space=PLENTY)[0].action, "updated")
        self.assertTrue((self.into / "SomeMod-src" / "Source" / "Other.cs").is_file())
        self.assertEqual(ensure([("Some Mod", self.url)], self.into, refresh=True, space=PLENTY)[0].action, "unchanged")
        self.assertEqual(ensure([("Some Mod", self.url)], self.into, space=PLENTY)[0].action, "kept")

    def test_no_new_clone_while_the_drive_is_short_and_nothing_is_removed(self):
        ensure([("Some Mod", self.url)], self.into, space=PLENTY)
        outcomes = ensure([("Some Mod", self.url), ("Another Mod", self.url)], self.into, space=SHORT)
        self.assertEqual([o.action for o in outcomes], ["kept", "refused"])
        self.assertTrue((self.into / "SomeMod-src" / "Source" / "Thing.cs").is_file())
        self.assertFalse((self.into / "AnotherMod-src").exists())

    def test_a_folder_that_is_not_a_clone_is_left_alone(self):
        (self.into / "SomeMod-src").mkdir(parents=True)
        (self.into / "SomeMod-src" / "mine.txt").write_text("keep me", encoding="utf-8")
        [outcome] = ensure([("Some Mod", self.url)], self.into, space=PLENTY)
        self.assertEqual(outcome.action, "failed")
        self.assertEqual((self.into / "SomeMod-src" / "mine.txt").read_text(encoding="utf-8"), "keep me")


@unittest.skipUnless(HAVE_GIT, "git is not installed")
class CommandTests(unittest.TestCase):
    """The clone section of rimworld-sources, from a register that already confirms one mod."""

    def setUp(self):
        from test_rimworld_sources import ABOUT, FakeGitHub, steam, write
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        url = make_upstream(root / "upstream")
        self.project = root / "project"
        write(self.project / "mods" / "Ours" / "About" / "About.xml",
              ABOUT.format(name="Ours", pid="our.mod", extra="<loadAfter><li>a.b</li></loadAfter>"))
        write(self.project / "config" / "source-repos.json", json.dumps({"format": 1, "mods": {"a.b": {
            "name": "Some Mod", "package_id": "a.b", "repository": url, "confirmed": "About/About.xml", "candidates": []}}}))
        game = root / "steamapps" / "common" / "RimWorld"
        write(game / "Assembly-CSharp.dll", "x")
        shop = root / "steamapps" / "workshop" / "content" / "294100"
        write(shop / "1" / "About" / "About.xml", ABOUT.format(name="Some Mod", pid="a.b", extra=""))
        write(root / "Config" / "ModsConfig.xml", "<ModsConfigData><version>1.7.5013 rev95</version><activeMods>"
              "<li>ludeon.rimworld</li><li>a.b</li></activeMods></ModsConfigData>")
        self.argv = ["--root", str(self.project), "--game", str(game), "--workshop", str(shop), "--config", str(root / "Config"),
                     "--cache", str(root / "cache"), "--no-redact", "--clone-into", ".local/decompiled"]
        self.fake, self.post = FakeGitHub(), steam({})

    def tearDown(self):
        self.tmp.cleanup()

    def run_main(self, disk):
        from phobos_modkit.games.rimworld.sources_cli import main
        out = io.StringIO()
        code = main(self.argv, environ={}, out=out, get=self.fake, post=self.post, sleep=lambda s: None,
                    clock=lambda: 1_800_000_000, disk=disk)
        return code, out.getvalue()

    def test_a_clone_is_made_and_its_cost_reported(self):
        code, text = self.run_main(PLENTY)
        self.assertEqual(code, 0, text)
        self.assertIn("SomeMod-src", text)
        self.assertIn("1 clones in", text)
        self.assertNotIn("needs a decision", text)

    def test_a_drive_short_of_space_asks_the_owner_and_deletes_nothing(self):
        code, text = self.run_main(SHORT)
        self.assertIn("Storage needs a decision: nothing was deleted", text)
        self.assertIn("refused", text)
        self.assertIn("Choices for the owner", text)
        self.assertFalse((self.project / ".local" / "decompiled" / "SomeMod-src").exists())


if __name__ == "__main__":
    unittest.main()
