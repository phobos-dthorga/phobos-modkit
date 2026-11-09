"""The rimworld-log command, run on fixtures copied into a temporary logs folder."""
import io
import json
from pathlib import Path
import shutil
import tempfile
import unittest

from support import FIXTURES
from phobos_modkit.__main__ import main as kit_main
from phobos_modkit.games.rimworld.cli import EXIT_NOT_FOUND, EXIT_OK, EXIT_USAGE, main


class Command(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.logs = Path(self.tmp.name) / "Logs"
        self.logs.mkdir()
        shutil.copy(FIXTURES / "rimworld" / "player-1.7.log", self.logs / "Player.log")
        shutil.copy(FIXTURES / "rimworld" / "player-prev-1.7.log", self.logs / "Player-prev.log")
        self.env = {}  # nothing from the real environment

    def tearDown(self):
        self.tmp.cleanup()

    def run_main(self, *args, settings=None):
        out = io.StringIO()
        code = main(list(args) + ["--no-mods"], settings_file=settings, environ=self.env, out=out)
        return code, out.getvalue()

    def test_default_reads_player_log_and_compares_with_the_previous_run(self):
        code, text = self.run_main("--logs", str(self.logs))
        self.assertEqual(code, EXIT_OK)
        self.assertIn("# Log triage: Player.log", text)
        self.assertIn("Compared with Player-prev.log.", text)
        self.assertIn("Installed mods were not read (--no-mods)", text)

    def test_logs_folder_from_the_environment_and_from_a_settings_file(self):
        self.env = {"RIMWORLD_LOGS_PATH": str(self.logs)}
        self.assertEqual(self.run_main()[0], EXIT_OK)
        self.env = {}
        settings = Path(self.tmp.name) / "install-settings.json"
        settings.write_text(json.dumps({"rimworldLogsPath": str(self.logs)}), encoding="utf-8")
        self.assertEqual(self.run_main(settings=settings)[0], EXIT_OK)

    def test_no_previous(self):
        code, text = self.run_main(str(self.logs / "Player.log"), "--no-previous")
        self.assertEqual(code, EXIT_OK)
        self.assertNotIn("Compared with", text)

    def test_show_one_signature(self):
        code, text = self.run_main(str(self.logs / "Player.log"), "--json", "-")
        some_id = json.loads(text)["data"]["groups"][0]["id"]
        code, text = self.run_main(str(self.logs / "Player.log"), "--show", some_id[:6])
        self.assertEqual(code, EXIT_OK)
        self.assertIn(f"# Signature {some_id}", text)

    def test_show_an_unknown_id(self):
        code, text = self.run_main(str(self.logs / "Player.log"), "--show", "zzzzzzzz")
        self.assertEqual((code, text), (EXIT_NOT_FOUND, ""))

    def test_json_to_a_file_and_markdown_to_the_screen(self):
        target = Path(self.tmp.name) / "report.json"
        code, text = self.run_main(str(self.logs / "Player.log"), "--json", str(target))
        self.assertEqual(code, EXIT_OK)
        self.assertIn("# Log triage", text)
        self.assertEqual(json.loads(target.read_text(encoding="utf-8"))["data"]["log"]["name"], "Player.log")

    def test_levels_option_can_include_info(self):
        code, text = self.run_main(str(self.logs / "Player.log"), "--levels", "info")
        self.assertIn("Engine starting.", text)

    def test_a_missing_log_is_a_usage_error(self):
        self.assertEqual(self.run_main(str(self.logs / "absent.log"))[0], EXIT_USAGE)
        self.assertEqual(self.run_main(str(self.logs / "Player.log"), "--previous", "absent.log")[0], EXIT_USAGE)


class Dispatch(unittest.TestCase):
    def test_unknown_commands_list_the_commands(self):
        self.assertEqual(kit_main(["no-such-command"]), 2)
        self.assertEqual(kit_main(["--help"]), 0)


if __name__ == "__main__":
    unittest.main()
