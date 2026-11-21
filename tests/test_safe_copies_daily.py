"""safe-copies run-all and schedule (1.71.0): every list on the games list, and the daily run as a scheduled task. Task Scheduler
is a stand-in here; nothing is scheduled for real."""
from datetime import datetime
import json
from pathlib import Path
import subprocess
import sys
import unittest

from test_safe_copies import NOW, Fixture
from phobos_modkit import safe_copies as sc
from phobos_modkit import safe_copies_daily as daily

WINDOWS = sys.platform == "win32"


class RunAllTests(Fixture):
    def setUp(self):
        super().setUp()
        (self.repo / "config" / "safe-copies").mkdir()
        (self.base / "game-data").mkdir()
        (self.base / "game-data" / "options.ini").write_text("x", encoding="utf-8")
        (self.repo / "config" / "safe-copies" / "spacegame.json").write_text(json.dumps(
            {"game": "spacegame", "sets": [{"name": "settings", "root": "@repository", "folder": "plans", "kind": "own"}]}),
            encoding="utf-8")
        self.games = self.base / "games.json"
        self.games.write_text(json.dumps({"schema_version": 1, "root": str(self.base), "games": [
            {"id": "testgame", "name": "Test", "repositories": ["repo", "gone-repo"]},
            {"id": "tools", "name": "Tools", "repositories": [str(self.repo)]}]}), encoding="utf-8")

    def test_the_games_list_gives_each_repository_once(self):
        self.assertEqual(daily.repositories(self.games), [self.repo, self.base / "gone-repo"])

    def test_a_repository_keeps_its_own_list_and_its_games_lists(self):
        self.assertEqual(daily.lists_in(self.repo), [(self.repo, None), (self.repo, "spacegame")])

    def test_every_list_runs_and_a_missing_repository_is_a_row_not_a_stop(self):
        summary = daily.run_all(self.environ, str(self.games), verify=True, push=False, now=NOW)
        rows = {(r["repository"], r["game"]): r for r in summary["lists"]}
        self.assertTrue(rows[("repo", "testgame")]["ok"] and rows[("repo", "spacegame")]["ok"])
        self.assertGreater(rows[("repo", "testgame")]["copied"], 0)
        self.assertEqual(rows[("gone-repo", None)]["problem"], "not on this PC")
        self.assertFalse(summary["ok"])
        self.assertTrue(summary["checked"] and not summary["checked"][0]["problems"])
        self.assertEqual(daily.last_run_all(self.environ)["time"], summary["time"], "kept for the Companion")

    def test_the_command_says_what_each_list_did(self):
        out = __import__("io").StringIO()
        code = sc.main(["run-all", "--games", str(self.games), "--no-push", "--json"], out=out, environ=self.environ)
        answer = json.loads(out.getvalue())
        self.assertEqual(code, sc.EXIT_PROBLEMS, "the missing repository is a problem")
        self.assertEqual(len(answer["data"]["lists"]), 3)


class TaskTests(unittest.TestCase):
    def test_the_task_runs_this_kit_daily_catching_up_and_never_twice(self):
        xml = daily.task_xml("04:00", "C:/Games/games.json", python="C:/Python/python.exe", folder="C:/kit/python",
                             user="owner", today=datetime(2026, 11, 22).date())
        self.assertIn("<StartBoundary>2026-11-22T04:00:00</StartBoundary>", xml)
        self.assertIn("<StartWhenAvailable>true</StartWhenAvailable>", xml)
        self.assertIn("<MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>", xml)
        self.assertIn("<LogonType>InteractiveToken</LogonType>", xml)
        self.assertIn("run-all --settle --verify --games &quot;C:/Games/games.json&quot;", xml)
        self.assertIn(f"<WorkingDirectory>{Path('C:/kit/python')}</WorkingDirectory>", xml)

    def test_a_time_must_be_a_time_of_day(self):
        for bad in ("4am", "24:00", "04:60", "", None):
            with self.assertRaises(daily.DailyError):
                daily.task_xml(bad, "g.json")

    def test_the_next_run_is_today_or_tomorrow(self):
        self.assertEqual(daily.next_run("04:00", datetime(2026, 11, 22, 3, 0)), datetime(2026, 11, 22, 4, 0))
        self.assertEqual(daily.next_run("04:00", datetime(2026, 11, 22, 5, 0)), datetime(2026, 11, 23, 4, 0))


class SchedulerStandIn:
    """Answers schtasks as Task Scheduler would, keeping one task."""

    def __init__(self):
        self.task, self.calls = None, []

    def __call__(self, command, **kwargs):
        self.calls.append(command)
        verb = command[1]
        if verb == "/Create":
            self.task = Path(command[command.index("/XML") + 1]).read_text(encoding="utf-16")
            return subprocess.CompletedProcess(command, 0, "SUCCESS", "")
        if verb == "/Query":
            if self.task is None:
                return subprocess.CompletedProcess(command, 1, "", "ERROR: The system cannot find the file specified.")
            return subprocess.CompletedProcess(command, 0, self.task, "")
        if verb == "/Delete":
            self.task = None
            return subprocess.CompletedProcess(command, 0, "SUCCESS", "")
        raise AssertionError(command)


@unittest.skipUnless(WINDOWS, "the daily run is a Windows scheduled task")
class ScheduleTests(unittest.TestCase):
    def test_set_read_move_and_remove(self):
        scheduler = SchedulerStandIn()
        self.assertEqual(daily.schedule_read(scheduler), {"set": False, "supported": True})
        found = daily.schedule_set("04:00", "C:/Games/games.json", scheduler)
        self.assertEqual((found["set"], found["at"]), (True, "04:00"))
        self.assertIn("run-all", found["arguments"])
        self.assertEqual(daily.schedule_set("19:30", "C:/Games/games.json", scheduler)["at"], "19:30")
        self.assertFalse(daily.schedule_off(scheduler)["set"])
        self.assertEqual([c[1] for c in scheduler.calls].count("/Create"), 2)

    def test_a_refusal_says_task_schedulers_words(self):
        def refusing(command, **kwargs):
            return subprocess.CompletedProcess(command, 1, "", "ERROR: Access is denied.")
        with self.assertRaises(daily.DailyError) as refused:
            daily.schedule_set("04:00", "g.json", refusing)
        self.assertIn("Access is denied", str(refused.exception))


if __name__ == "__main__":
    unittest.main()
