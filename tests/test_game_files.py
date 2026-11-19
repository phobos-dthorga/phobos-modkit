"""game-files: Steam's records and a game's own files, for any Steam game (1.46.0)."""
import io
import json
import os
from pathlib import Path
import tempfile
import unittest

import support  # noqa: F401  (puts the package on the path)
from phobos_modkit import game_files

MANIFEST = '''"AppState"
{
\t"appid"\t\t"4242"
\t"name"\t\t"Sample Colony"
\t"installdir"\t\t"Sample Colony"
\t"LastUpdated"\t\t"2000"
\t"LastPlayed"\t\t"1500"
\t"SizeOnDisk"\t\t"1048576"
\t"buildid"\t\t"77"
}
'''
WORKSHOP = '''"AppWorkshop"
{
\t"appid"\t\t"4242"
\t"WorkshopItemsInstalled"
\t{
\t\t"111"
\t\t{
\t\t\t"size"\t\t"10"
\t\t\t"timeupdated"\t\t"1000"
\t\t}
\t\t"222"
\t\t{
\t\t\t"size"\t\t"20"
\t\t\t"timeupdated"\t\t"1800"
\t\t}
\t}
}
'''


class GameFilesTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        base = Path(self.temp.name)
        self.steam = base / "Steam"
        apps = self.steam / "steamapps"
        (apps / "workshop" / "content" / "4242" / "222" / "About").mkdir(parents=True)
        (apps / "libraryfolders.vdf").write_text('"libraryfolders"\n{\n\t"0"\n\t{\n\t\t"path"\t\t"%s"\n\t}\n}\n'
                                                 % str(self.steam).replace("\\", "\\\\"), encoding="utf-8")
        (apps / "appmanifest_4242.acf").write_text(MANIFEST, encoding="utf-8")
        (apps / "workshop" / "appworkshop_4242.acf").write_text(WORKSHOP, encoding="utf-8")
        (apps / "workshop" / "content" / "4242" / "222" / "About" / "About.xml").write_text(
            "<ModMetaData><name>Better Lamps</name></ModMetaData>", encoding="utf-8")
        shots = self.steam / "userdata" / "99" / "760" / "remote" / "4242" / "screenshots"
        shots.mkdir(parents=True)
        (shots / "steam-shot.jpg").write_bytes(b"x" * 30)
        self.home = base / "home"
        data = self.home / "AppData" / "LocalLow" / "Sample Studio" / "Sample Colony by Sample Studio"
        (data / "Saves").mkdir(parents=True)
        (data / "Saves" / "Colony One.rws").write_bytes(b"x" * 100)
        (data / "Saves" / "Autosave-1.rws").write_bytes(b"x" * 50)
        os.utime(data / "Saves" / "Colony One.rws", (3000, 3000))
        os.utime(data / "Saves" / "Autosave-1.rws", (2000, 2000))
        (data / "Screenshots").mkdir()
        (data / "Screenshots" / "own.png").write_bytes(b"x" * 40)
        (data / "Cache").mkdir()
        (data / "Cache" / "big.bin").write_bytes(b"x" * 500)
        self.data = data
        self.environ = {"PHOBOS_STEAM": str(self.steam), "USERPROFILE": str(self.home), "HOME": str(self.home),
                        "PHOBOS_SETTINGS": str(base / "none.json")}

    def tearDown(self):
        self.temp.cleanup()

    def test_valves_text_reads_as_nested_dicts(self):
        parsed = game_files.parse_vdf(MANIFEST)
        self.assertEqual(parsed["AppState"]["buildid"], "77")

    def test_the_game_is_found_by_name_or_id(self):
        self.assertEqual(game_files.find_game(self.steam, "sample colony")["appId"], 4242)
        self.assertEqual(game_files.find_game(self.steam, app_id=4242)["name"], "Sample Colony")
        self.assertIsNone(game_files.find_game(self.steam, "No Such Game"))

    def test_the_data_folder_is_guessed_through_its_makers_folder(self):
        self.assertEqual(game_files.guess_data("Sample Colony", self.environ), self.data)

    def test_the_report_holds_what_changed_saves_screenshots_and_space(self):
        found = game_files.report("Sample Colony", environ=self.environ)
        self.assertTrue(found["changed"]["gameUpdated"])
        self.assertEqual([i["title"] for i in found["changed"]["workshop"]], ["Better Lamps"])
        self.assertEqual([s["name"] for s in found["saves"]["list"]], ["Colony One", "Autosave-1"])
        self.assertEqual(found["saves"]["autosaves"], 1)
        self.assertEqual(found["screenshots"]["count"], 2)
        self.assertEqual(found["space"]["data"][0]["name"], "Cache")
        self.assertEqual(found["space"]["install"], 1048576)

    def test_since_moves_the_line(self):
        found = game_files.report("Sample Colony", since=500, environ=self.environ)
        self.assertEqual(found["changed"]["workshopCount"], 2)
        self.assertFalse(found["changed"]["sinceLastPlayed"])

    def test_a_folder_of_save_folders_is_opened_up(self):
        group = self.data / "Saves" / "Sandbox" / "Phobos-1"
        group.mkdir(parents=True)
        (group / "map.bin").write_bytes(b"x")
        names = [s["name"] for s in game_files.saves(self.data / "Saves")]
        self.assertIn("Sandbox / Phobos-1", names)

    def test_a_game_steam_lacks_is_said_in_words(self):
        out = io.StringIO()
        game_files.main(["report", "--name", "Nowhere Game"], out, self.environ)
        self.assertIn("Steam has no installed game", out.getvalue())
        self.assertIn("No data folder found", out.getvalue())

    def test_command_line_json_and_steam_games(self):
        out = io.StringIO()
        self.assertEqual(game_files.main(["report", "--name", "Sample Colony", "--json"], out, self.environ), 0)
        self.assertEqual(json.loads(out.getvalue())["data"]["game"]["buildId"], "77")
        out = io.StringIO()
        game_files.main(["steam-games", "--json"], out, self.environ)
        self.assertEqual(json.loads(out.getvalue())["data"]["games"][0]["appId"], 4242)


if __name__ == "__main__":
    unittest.main()
