"""mod-list start (1.146.0): the game started through Steam, refused while it runs. A stand-in opener; nothing is started."""
import io
import json
import tempfile
import unittest

from phobos_modkit import mod_list_cli as cli

from test_mod_list import FakeRimWorld


class Start(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.fake = FakeRimWorld(self.tmp.name, ["ludeon.rimworld"])
        self.environ = self.fake.environ(self.tmp.name)
        self.opened = []

    def tearDown(self):
        self.tmp.cleanup()

    def run_cli(self, *argv, running=lambda names: []):
        out = io.StringIO()
        code = cli.main(["start", "--name", "RimWorld", *argv, "--json"], self.environ, out, running=running,
                        opener=self.opened.append)
        return code, json.loads(out.getvalue())["data"]

    def test_a_preview_starts_nothing_and_apply_hands_steam_the_game(self):
        code, data = self.run_cli()
        self.assertEqual((code, data["started"], self.opened), (0, False, []))
        code, data = self.run_cli("--apply")
        self.assertEqual(code, 0)
        self.assertTrue(data["started"])
        self.assertEqual(self.opened, ["steam://rungameid/294100"])

    def test_refused_while_the_game_runs(self):
        code, data = self.run_cli("--apply", running=lambda names: ["RimWorld.exe"] if "RimWorld.exe" in names else [])
        self.assertEqual(code, cli.EXIT_REFUSED)
        self.assertIn("running already", data["refusal"])
        self.assertEqual(self.opened, [])


if __name__ == "__main__":
    unittest.main()
