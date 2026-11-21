"""Subscribing through the Steam client (1.77.0), against a stand-in library. Nothing here speaks to a real Steam."""
import io
import json
from pathlib import Path
import tempfile
import unittest

from phobos_modkit import mod_list_cli as cli
from phobos_modkit.games.rimworld.mod_list import RimWorld
from phobos_modkit.steam import client
from phobos_modkit.steam.client import DOWNLOADING, INSTALLED, SUBSCRIBED, Session, SteamError

from test_mod_list import FakeRimWorld


class FakeSteam:
    """Stands in for the flat Steamworks functions: items subscribe at once and download on the next pump."""

    def __init__(self, path=None, init_result=0, subscribed=(), refuse=()):
        self.init_result = init_result
        self.states = {int(i): SUBSCRIBED | INSTALLED for i in subscribed}
        self.refuse = {int(i) for i in refuse}
        self.calls = []
        self.shut = False
        self.downloads = []

    def init(self):
        return self.init_result, "" if self.init_result == 0 else "No Steam"

    def shutdown(self):
        self.shut = True

    def pump(self):
        for item, state in self.states.items():
            if state & DOWNLOADING:
                self.states[item] = SUBSCRIBED | INSTALLED

    def ugc(self):
        return 1

    def utils(self):
        return 2

    def subscribe(self, ugc, item):
        self.calls.append(("subscribe", item))
        if item not in self.refuse:
            self.states[item] = SUBSCRIBED | DOWNLOADING
        return 100 + item

    def unsubscribe(self, ugc, item):
        self.calls.append(("unsubscribe", item))
        self.states[item] = 0
        return 200 + item

    def state(self, ugc, item):
        return self.states.get(item, 0)

    def download(self, ugc, item):
        self.downloads.append(item)
        return True

    def progress(self, ugc, item):
        return 50, 100

    def completed(self, utils, call):
        return True, False


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


class Sessions(unittest.TestCase):
    def test_subscribing_asks_for_the_download_and_leaves_steam_after(self):
        steam, environ = FakeSteam(), {}
        with Session(steam, 294100, environ) as session:
            self.assertTrue(session.subscribe("3820401180"))
            self.assertEqual(session.progress(["3820401180"])[2], 1)
        self.assertEqual(environ["SteamAppId"], "294100")
        self.assertEqual(steam.downloads, [3820401180])
        self.assertTrue(steam.shut)

    def test_a_subscription_steam_refuses_says_so(self):
        steam = FakeSteam(refuse=["111111"])
        with Session(steam, 294100, {}) as session:
            self.assertFalse(session.subscribe("111111"))
        self.assertEqual(steam.downloads, [])

    def test_steam_not_running_is_said_in_words(self):
        with self.assertRaises(SteamError) as said:
            with Session(FakeSteam(init_result=1), 294100, {}):
                pass
        self.assertIn("running and signed in", str(said.exception))

    def test_state_words(self):
        self.assertEqual(client.state_words(SUBSCRIBED | INSTALLED), "installed")
        self.assertEqual(client.state_words(SUBSCRIBED | DOWNLOADING), "downloading")
        self.assertEqual(client.state_words(0), "not subscribed")

    def test_the_games_library_is_found_in_its_folder_or_below(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(client.library_path(tmp))
            nested = Path(tmp) / "Plugins" / "x86_64"
            nested.mkdir(parents=True)
            (nested / "steam_api64.dll").write_bytes(b"")
            self.assertEqual(client.library_path(tmp), nested / "steam_api64.dll")


class Command(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.fake = FakeRimWorld(self.tmp.name, ["ludeon.rimworld", "example.market", "example.hostel"])
        self.environ = self.fake.environ(self.tmp.name)
        (self.fake.game / "steam_api64.dll").write_bytes(b"")
        self.steam = FakeSteam(subscribed=["1000000001", "1000000002"])

    def tearDown(self):
        self.tmp.cleanup()

    def run_cli(self, *argv, running=None):
        out = io.StringIO()
        code = cli.main(list(argv) + ["--json"], self.environ, out, running=running or (lambda names: []),
                        steam=lambda path: self.steam)
        return code, json.loads(out.getvalue())["data"]

    def test_subscribe_previews_then_subscribes_and_says_what_is_installed(self):
        code, data = self.run_cli("subscribe", "--name", "RimWorld", "--item", "1000000004", "--item", "1000000099")
        self.assertFalse(data["applied"])
        self.assertEqual(self.steam.calls, [])
        code, data = self.run_cli("subscribe", "--name", "RimWorld", "--item", "1000000004", "--item", "1000000099",
                                  "--wait", "0", "--apply")
        self.assertEqual(code, 0)
        found = {r["workshop_id"]: r for r in data["results"]}
        self.assertTrue(found["1000000004"]["subscribed"])
        self.assertEqual(found["1000000004"]["id"], "example.library")
        self.assertTrue(found["1000000099"]["subscribed"])
        self.assertFalse(found["1000000099"]["installed"])

    def test_waiting_for_downloads_stops_when_all_are_installed(self):
        args = cli._parser().parse_args(["subscribe", "--name", "RimWorld", "--item", "1000000099", "--wait", "60", "--apply"])
        clock = Clock()
        said = []
        report, data = cli.subscribe_report(RimWorld(self.environ), args, self.environ, lambda path: self.steam,
                                            lambda *a, **k: said.append(a), clock, clock.sleep)
        self.assertLess(clock.now, 60)
        self.assertEqual(data["results"][0]["state"], "installed")

    def test_unsubscribe_switches_off_first_with_a_backup_then_unsubscribes(self):
        code, data = self.run_cli("unsubscribe", "--name", "RimWorld", "--list", "active", "--item", "1000000001", "--apply")
        self.assertEqual(code, 0)
        self.assertEqual(data["switched_off"], ["example.market"])
        self.assertTrue(data["backup"])
        self.assertEqual(RimWorld(self.environ).lists()[0].ids, ["ludeon.rimworld", "example.hostel"])
        self.assertEqual(self.steam.calls, [("unsubscribe", 1000000001)])
        self.assertTrue(data["results"][0]["unsubscribed"])

    def test_unsubscribe_waits_while_the_game_or_rimsort_runs_and_nonsense_is_refused(self):
        code, data = self.run_cli("unsubscribe", "--name", "RimWorld", "--list", "active", "--item", "1000000001", "--apply",
                                  running=lambda names: ["RimSort.exe"])
        self.assertEqual(code, cli.EXIT_REFUSED)
        self.assertEqual(self.steam.calls, [])
        code, data = self.run_cli("subscribe", "--name", "RimWorld", "--item", "12ab", "--apply")
        self.assertEqual(code, cli.EXIT_REFUSED)


if __name__ == "__main__":
    unittest.main()
