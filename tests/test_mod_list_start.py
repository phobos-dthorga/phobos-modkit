"""mod-list start and launch (1.146.0, 1.150.0): the game's own program started with the arguments line kept for it, refused while
the game runs. A stand-in launcher; nothing is started."""
import io
import json
from pathlib import Path
import sys
import tempfile
import time
import unittest

import support  # noqa: F401  (puts the package on the path)
from phobos_modkit import mod_list as core
from phobos_modkit import mod_list_cli as cli
from phobos_modkit.games.rimworld import mod_list as rimworld

from test_mod_list import FakeRimWorld

STEAM_UP = lambda names: ["steam.exe"] if "steam.exe" in names else []   # noqa: E731


class Start(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.fake = FakeRimWorld(self.tmp.name, ["ludeon.rimworld"])
        self.environ = self.fake.environ(self.tmp.name)
        self.program = self.fake.game / rimworld.PROGRAMS.get(sys.platform, ("RimWorldLinux",))[0]
        self.program.write_bytes(b"")
        self.started = []

    def tearDown(self):
        self.tmp.cleanup()

    def run_cli(self, report, *argv, running=STEAM_UP):
        out = io.StringIO()
        code = cli.main([report, "--name", "RimWorld", *argv, "--json"], self.environ, out, running=running,
                        launcher=lambda program, arguments, folder: self.started.append((program, arguments, folder)))
        return code, json.loads(out.getvalue())["data"]

    def test_a_preview_starts_nothing_and_apply_runs_the_games_own_program(self):
        code, data = self.run_cli("start")
        self.assertEqual((code, data["started"], self.started), (0, False, []))
        code, data = self.run_cli("start", "--apply")
        self.assertEqual((code, data["started"]), (0, True))
        self.assertEqual(self.started, [(self.program, "", self.fake.game)])

    def test_the_kept_arguments_line_goes_with_it_and_one_given_wins_this_once(self):
        # The owner's choice by card (28 Nov 2026): one line per game, the game's own program always.
        code, data = self.run_cli("launch", "--set=-harmony-detours -logfile")
        self.assertEqual((code, data["arguments"], data["applied"]), (0, "", False))
        code, data = self.run_cli("launch", "--set=-harmony-detours -logfile", "--apply")
        self.assertEqual((data["arguments"], data["applied"]), ("-harmony-detours -logfile", True))
        self.run_cli("start", "--apply")
        self.run_cli("start", "--arguments=-quicktest", "--apply")
        self.assertEqual([a for _, a, _ in self.started], ["-harmony-detours -logfile", "-quicktest"])
        self.assertEqual(self.run_cli("launch")[1]["arguments"], "-harmony-detours -logfile")
        self.run_cli("launch", "--clear", "--apply")
        self.assertEqual(self.run_cli("launch")[1]["arguments"], "")

    def test_a_line_break_or_too_long_a_line_is_refused(self):
        for text in ("-one\n-two", "x" * (core.MAX_ARGUMENTS + 1)):
            code, data = self.run_cli("launch", f"--set={text}", "--apply")
            self.assertEqual(code, cli.EXIT_REFUSED)
        self.assertEqual(self.run_cli("launch")[1]["arguments"], "")

    def test_says_when_steam_is_not_running(self):
        code, data = self.run_cli("start", running=lambda names: [])
        self.assertEqual(code, 0)
        self.assertFalse(data["steamRunning"])

    def test_refused_while_the_game_runs_or_without_its_program(self):
        code, data = self.run_cli("start", "--apply", running=lambda names: ["RimWorld.exe"] if "RimWorld.exe" in names else [])
        self.assertEqual(code, cli.EXIT_REFUSED)
        self.assertIn("running already", data["refusal"])
        self.program.unlink()
        code, data = self.run_cli("start", "--apply")
        self.assertEqual(code, cli.EXIT_REFUSED)
        self.assertIn("not found", data["refusal"])
        self.assertEqual(self.started, [])


class LaunchProgram(unittest.TestCase):
    def test_the_program_runs_on_its_own_with_the_line_as_written(self):
        # A real start, of Python itself, never a game: the arguments line must arrive whole, quotes and dashes included.
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "got.txt"
            script = Path(tmp) / "echo.py"
            script.write_text("import sys, pathlib\npathlib.Path(sys.argv[1]).write_text('|'.join(sys.argv[2:]))\n",
                              encoding="utf-8")
            cli.launch_program(Path(sys.executable), f'"{script}" "{out}" -harmony-detours "two words"', Path(tmp))
            deadline = time.monotonic() + 20
            while not out.is_file() and time.monotonic() < deadline:
                time.sleep(0.1)
            time.sleep(0.2)
            self.assertEqual(out.read_text(encoding="utf-8"), "-harmony-detours|two words")


if __name__ == "__main__":
    unittest.main()
