"""Workshop items Steam has not brought up to date (1.147.0): a synthetic record of Steam's and a stand-in Steam client."""
import io
import json
from pathlib import Path
import tempfile
import unittest

from phobos_modkit import mod_list_cli as cli
from phobos_modkit import workshop_updates as wu

from test_mod_list import FakeRimWorld, about
from test_steam_client import FakeSteam

RECORD = """"AppWorkshop"
{
	"appid"		"294100"
	"NeedsUpdate"		"1"
	"NeedsDownload"		"0"
	"WorkshopItemsInstalled"
	{
		"1000000001"	{ "size" "1" "timeupdated" "100" "manifest" "a" }
		"1000000002"	{ "size" "1" "timeupdated" "100" "manifest" "b" }
		"1000000003"	{ "size" "1" "timeupdated" "100" "manifest" "c" }
	}
	"WorkshopItemDetails"
	{
		"1000000001"	{ "manifest" "a" "timeupdated" "100" "subscribedby" "1" "latest_timeupdated" "100" "latest_manifest" "a" }
		"1000000002"	{ "manifest" "b" "timeupdated" "200" "subscribedby" "1" "latest_timeupdated" "200" "latest_manifest" "b2" }
		"1000000003"	{ "manifest" "c" "timeupdated" "300" "BytesDownloaded" "5" "BytesToDownload" "10" }
		"1000000004"	{ "manifest" "d" "timeupdated" "400" }
	}
}
"""


class States(unittest.TestCase):
    def test_waiting_downloading_and_missing_are_told_apart_and_up_to_date_left_out(self):
        from phobos_modkit.game_files import parse_vdf
        record = parse_vdf(RECORD)["AppWorkshop"]
        found = {i["workshop_id"]: i["state"] for i in wu.item_states(record)}
        self.assertEqual(found, {"1000000002": wu.WAITING, "1000000003": wu.DOWNLOADING, "1000000004": wu.MISSING})
        self.assertEqual(wu.flags(record), (True, False))
        self.assertNotIn("subscribedby", json.dumps(wu.item_states(record)))

    def test_no_record_is_nothing_waiting(self):
        self.assertEqual(wu.item_states({}), [])


class Command(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.fake = FakeRimWorld(self.tmp.name, ["ludeon.rimworld", "example.market"])
        self.environ = self.fake.environ(self.tmp.name)
        about(self.fake.workshop / "1000000002", "example.beds", "Beds")
        (Path(self.fake.workshop).parent.parent / "appworkshop_294100.acf").write_text(RECORD, encoding="utf-8")
        self.steam = FakeSteam(subscribed=["1000000002"])

    def tearDown(self):
        self.tmp.cleanup()

    def run_cli(self, *argv, running=lambda names: []):
        out = io.StringIO()
        code = cli.main(["updates", "--name", "RimWorld", *argv, "--json"], self.environ, out, running=running,
                        steam=lambda path: self.steam)
        return code, json.loads(out.getvalue())["data"]

    def test_items_are_named_and_fetched_again_only_with_apply(self):
        code, data = self.run_cli()
        self.assertEqual(code, 0)
        waiting = [i for i in data["items"] if i["state"] == "waiting"]
        self.assertEqual([(i["workshop_id"], i["name"]) for i in waiting], [("1000000002", "Beds")])
        self.assertTrue(data["needsUpdate"])
        code, data = self.run_cli("--item", "1000000002")
        self.assertEqual((data["applied"], self.steam.downloads), (False, []))
        code, data = self.run_cli("--item", "1000000002", "--apply")
        self.assertTrue(data["applied"])
        self.assertEqual(self.steam.downloads, [1000000002])
        self.assertTrue(data["results"][0]["asked"])

    def test_fetching_again_is_refused_while_the_game_runs(self):
        code, data = self.run_cli("--item", "1000000002", "--apply", running=lambda names: ["RimWorld.exe"])
        self.assertEqual(code, cli.EXIT_REFUSED)
        self.assertIn("close it", data["refusal"])
        self.assertEqual(self.steam.downloads, [])


if __name__ == "__main__":
    unittest.main()
