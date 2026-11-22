"""What the game's runs say about the list (1.85.0): judging a run once, the verdict on the last change, the newest list that ran
clean, and mods that ran without an error. A stand-in adapter gives the runs; one test reads real-shaped log headers."""
from datetime import datetime, timedelta, timezone
import io
import json
import os
from pathlib import Path
import tempfile
import unittest

from phobos_modkit import mod_list as core
from phobos_modkit import mod_list_cli as cli
from phobos_modkit import mod_lists, mod_runs
from phobos_modkit.games.rimworld.mod_list import RimWorld, _save_loaded

from test_mod_list import FakeRimWorld

T0 = datetime(2026, 11, 23, 1, 0, tzinfo=timezone.utc)


class Fixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.fake = FakeRimWorld(self.tmp.name, ["ludeon.rimworld", "example.market", "example.hostel"])
        self.environ = self.fake.environ(self.tmp.name)
        self.adapter = RimWorld(self.environ)
        self.adapter.running = lambda names: []
        self.installed = core.Installed(self.adapter, self.adapter.installed())
        self.reports = {}
        self.runs = []
        self.adapter.runs = lambda: self.runs
        self.adapter.run_report = lambda path, previous=None: self.reports[str(path)]

    def tearDown(self):
        self.tmp.cleanup()

    def run_at(self, started, minutes=30, name="Player.log"):
        return {"path": Path(name), "started": started, "ended": started + timedelta(minutes=minutes)}

    def report(self, name, new=(), error_mods=(), loaded="Colony", previous_loaded="Colony"):
        self.reports[name] = {"errors": len(new), "error_mods": list(error_mods), "loaded": loaded,
                              "previous_loaded": previous_loaded,
                              "new": [{"id": f"id{n}", "level": "ERROR", "count": 1, "message": m, "mods": []}
                                      for n, m in enumerate(new)]}

    def change(self, at):
        """A change made here at `at`, as apply_fix leaves it."""
        mod_list = self.adapter.lists()[0]
        return core.apply_fix(self.adapter, mod_list, None, core.MOVE, "example.hostel", lambda names: [], self.environ,
                              now=at, place=2)

    def judge(self, running=False):
        return mod_runs.judge_latest(self.adapter, self.installed, self.environ, running=running)


class Verdicts(Fixture):
    def test_new_errors_after_a_change_are_named_and_a_clean_run_says_so(self):
        self.change(T0)
        self.runs = [self.run_at(T0 + timedelta(hours=1)), self.run_at(T0 - timedelta(hours=2), name="Player-prev.log")]
        self.report("Player.log", new=["Could not find type IAmMother.Compat"])
        latest = self.judge()
        since = mod_runs.since_change(self.adapter, "active", latest, self.environ)
        self.assertEqual(since["verdict"], mod_runs.NEW_ERRORS)
        self.assertEqual(since["new"][0]["message"], "Could not find type IAmMother.Compat")
        self.assertIn("move example.hostel", since["change"]["why"])

    def test_not_run_since_too_late_and_running(self):
        self.change(T0)
        self.runs = [self.run_at(T0 - timedelta(hours=1))]
        self.assertEqual(mod_runs.since_change(self.adapter, "active", None, self.environ)["verdict"], mod_runs.NOT_RUN)
        self.runs = [self.run_at(T0 + timedelta(hours=3)), self.run_at(T0 + timedelta(hours=1), name="Player-prev.log")]
        self.assertEqual(mod_runs.since_change(self.adapter, "active", None, self.environ)["verdict"], mod_runs.TOO_LATE)
        self.assertEqual(mod_runs.since_change(self.adapter, "active", None, self.environ, running=True)["verdict"],
                         mod_runs.RUNNING)
        self.assertIsNone(self.judge(running=True))

    def test_a_list_changed_outside_the_tools_is_said_so(self):
        self.change(T0)
        path = self.adapter.lists()[0].path
        path.write_bytes(path.read_bytes().replace(b"example.market", b"example.marketx"))
        self.assertEqual(mod_runs.since_change(self.adapter, "active", None, self.environ)["verdict"], mod_runs.CHANGED)

    def test_runs_that_did_not_both_load_a_save_are_not_compared(self):
        self.change(T0)
        self.runs = [self.run_at(T0 + timedelta(hours=1)), self.run_at(T0 - timedelta(hours=2), name="Player-prev.log")]
        self.report("Player.log", new=["Exception loading a save"], previous_loaded="")
        latest = self.judge()
        self.assertFalse(latest["compared"])
        self.assertIsNone(latest["clean"])
        self.assertEqual(mod_runs.since_change(self.adapter, "active", latest, self.environ)["verdict"], mod_runs.UNKNOWN)

    def test_a_run_is_judged_once(self):
        self.runs = [self.run_at(T0), self.run_at(T0 - timedelta(hours=2), name="Player-prev.log")]
        self.report("Player.log")
        first = self.judge()
        self.reports["Player.log"]["new"] = [{"id": "x", "level": "ERROR", "count": 1, "message": "later", "mods": []}]
        self.assertEqual(self.judge(), first)


class RanClean(Fixture):
    def test_the_kept_copy_is_marked_and_the_newest_clean_one_found(self):
        start = datetime.now(timezone.utc) - timedelta(minutes=30)
        os.utime(self.fake.config / "ModsConfig.xml", ((start - timedelta(minutes=5)).timestamp(),) * 2)
        self.runs = [self.run_at(start), self.run_at(start - timedelta(hours=2), name="Player-prev.log")]
        kept = mod_lists.keep_at_start(self.adapter, self.adapter.lists()[0], self.installed, self.environ)
        self.assertIsNotNone(kept)
        self.report("Player.log", error_mods=["Hostel"])
        record = self.judge()
        self.assertTrue(record["clean"])
        self.assertEqual(record["error_mods"], ["example.hostel"])
        clean = mod_runs.last_clean(self.adapter, self.environ)
        self.assertEqual(clean.ref, kept.ref)
        self.assertTrue(clean.ran["clean"])

    def test_mods_that_ran_without_an_error_are_likely_to_work(self):
        record = {"started": "2026-11-22T17:01:21+00:00", "active": ["example.market", "example.hostel"],
                  "error_mods": ["example.hostel"]}
        self.adapter.version_misfit = lambda mod, version: "does not say" if mod.id in ("example.market", "example.hostel") \
            else ""
        self.adapter.game_version = lambda: "1.7"
        problems = core.check(self.adapter, self.adapter.lists()[0], self.installed, {}, last_run=record)
        likely = [p for p in problems if p.kind == "version-likely"]
        day = core._local_day(record["started"])
        self.assertIn(f"ran without an error in your game of {day}", likely[0].why)
        self.assertRegex(day, r"^\d{1,2} [A-Z][a-z]{2} 2026$")
        self.assertIn("Market", likely[0].why)
        self.assertEqual([p.name for p in problems if p.kind == "version"], ["Hostel"])


class Logs(unittest.TestCase):
    def test_a_log_header_gives_the_start_and_the_save_loaded(self):
        with tempfile.TemporaryDirectory() as tmp:
            logs = Path(tmp) / "Logs"
            logs.mkdir()
            (logs / "Player.log").write_text("=== Waylith log ===\nStarted:   2026-11-23 04:01:21.727 +11:00\n", encoding="utf-8")
            (logs / "Player-prev.log").write_text("no header here\n", encoding="utf-8")
            adapter = RimWorld({"RIMWORLD_LOGS_PATH": str(logs), "RIMWORLD_PATH": str(Path(tmp) / "game")})
            found = adapter.runs()
            self.assertEqual(found[0]["started"], datetime(2026, 11, 22, 17, 1, 21, 727000, tzinfo=timezone.utc))
            self.assertIsNone(found[1]["started"])
            self.assertIsNotNone(found[1]["ended"])
        self.assertEqual(_save_loaded("x\n2026  INFO [Verse] Loading game from file PG19 with mods:\n"), "PG19")
        self.assertEqual(_save_loaded("nothing loaded"), "")


class Command(Fixture):
    def test_load_last_clean_refuses_in_words_when_none_ran_clean(self):
        out = io.StringIO()
        code = cli.main(["compare", "--name", "RimWorld", "--list", "active", "--last-clean", "--json"], self.environ, out)
        self.assertEqual(code, cli.EXIT_REFUSED)
        self.assertIn("No list kept at a game start has run clean yet", json.loads(out.getvalue())["data"]["refusal"])


if __name__ == "__main__":
    unittest.main()
