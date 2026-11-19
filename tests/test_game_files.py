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
                        "PHOBOS_SETTINGS": str(base / "none.json"), "PHOBOS_MODKIT_CACHE": str(base / "cache")}

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

    def test_guesses_find_a_moved_documents_folder_and_names_that_differ(self):
        # The owner's PC (20 Nov 2026): Documents lives in SynologyDrive; Farming Simulator 25 writes FarmingSimulator2025;
        # Project Zomboid writes Zomboid beside a folder of the person's own mods; Vortex keeps folders named for games.
        documents = Path(self.temp.name) / "elsewhere" / "Documents"
        farm = documents / "My Games" / "FarmingSimulator2025"
        farm.mkdir(parents=True)
        (documents / "My Games" / "Project Zomboid (mods)").mkdir()
        (self.home / "Zomboid").mkdir()
        (self.home / "AppData" / "Roaming" / "Vortex" / "farmingsimulator25").mkdir(parents=True)
        (self.home / "AppData" / "Local" / "AutomationGame").mkdir(parents=True)
        (self.home / "AppData" / "Local" / "Projects").mkdir(parents=True)
        (self.home / "AppData" / "Local" / "Unreal Engine" / "Engine").mkdir(parents=True)
        environ = {**self.environ, game_files.DOCUMENTS: str(documents)}
        self.assertIsNone(game_files.guess_data("Farming Simulator 25", self.environ))
        found = game_files.guess_candidates("Farming Simulator 25", environ)
        self.assertEqual([(c["path"], c["score"]) for c in found], [(str(farm), 80)])
        zomboid = game_files.guess_candidates("Project Zomboid", environ)
        self.assertEqual(zomboid[0]["path"], str(self.home / "Zomboid"))
        self.assertEqual(zomboid[1]["reason"], "named for the game's mods")
        self.assertEqual(game_files.guess_data("Automation - The Car Company Tycoon Game", environ),
                         self.home / "AppData" / "Local" / "AutomationGame")
        self.assertEqual(game_files.guess_candidates("Wallpaper Engine", environ), [])

    def test_screenshots_alone_are_listed_quickly_from_the_same_folders(self):
        out = io.StringIO()
        self.assertEqual(game_files.main(["screenshots", "--name", "Sample Colony", "--json"], out, self.environ), 0)
        found = json.loads(out.getvalue())["data"]
        self.assertEqual(found["count"], 2)
        self.assertEqual(sorted(s["name"] for s in found["list"]), ["own.png", "steam-shot.jpg"])
        self.assertEqual(len(found["folders"]), 2)
        self.assertNotIn("space", found)
        out = io.StringIO()
        game_files.main(["screenshots", "--name", "Nowhere Game"], out, self.environ)
        self.assertIn("No screenshots folder found", out.getvalue())

    def test_steam_games_carry_their_guesses(self):
        out = io.StringIO()
        game_files.main(["steam-games", "--json"], out, self.environ)
        guesses = json.loads(out.getvalue())["data"]["games"][0]["dataGuesses"]
        self.assertEqual(guesses[0]["reason"], "named for the game, with more after, inside Sample Studio")

    def test_the_report_holds_what_changed_saves_screenshots_and_space(self):
        found = game_files.report("Sample Colony", environ=self.environ)
        self.assertTrue(found["changed"]["gameUpdated"])
        self.assertEqual([i["title"] for i in found["changed"]["workshop"]], ["Better Lamps"])
        self.assertEqual([s["name"] for s in found["saves"]["list"]], ["Colony One", "Autosave-1"])
        self.assertEqual(found["saves"]["autosaves"], 1)
        self.assertEqual(found["screenshots"]["count"], 2)
        self.assertEqual(found["space"]["data"][0]["name"], "Cache")
        self.assertEqual(found["space"]["install"], 1048576)

    def test_since_previous_falls_back_to_the_last_launch_until_one_before_is_seen(self):
        found = game_files.report("Sample Colony", since=game_files.PREVIOUS, environ=self.environ)
        self.assertFalse(found["changed"]["sincePrevious"])
        self.assertEqual(found["changed"]["launchesSeen"], 1)
        self.assertEqual(found["changed"]["since"], found["game"]["lastPlayedAt"])

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


class Launches(unittest.TestCase):
    """Launches remembered (1.51.0): Steam keeps only the latest, so while a game runs the kit compares with the one before."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.environ = {"PHOBOS_MODKIT_CACHE": self.temp.name, "PHOBOS_SETTINGS": str(Path(self.temp.name) / "none.json")}

    def tearDown(self):
        self.temp.cleanup()

    def test_each_launch_is_kept_once_and_the_one_before_is_known(self):
        self.assertEqual(game_files.remember_launch(9, 100, self.environ), [100])
        self.assertEqual(game_files.remember_launch(9, 100, self.environ), [100])
        seen = game_files.remember_launch(9, 300, self.environ)
        self.assertEqual(seen, [100, 300])
        self.assertEqual(game_files.previous_launch(seen, 300), 100)
        self.assertIsNone(game_files.previous_launch([300], 300))
        self.assertEqual(game_files.remember_launch(10, 50, self.environ), [50])

    def test_only_the_newest_launches_are_kept(self):
        for when in range(1, game_files.LAUNCHES_KEPT + 6):
            seen = game_files.remember_launch(9, when, self.environ)
        self.assertEqual(len(seen), game_files.LAUNCHES_KEPT)
        self.assertEqual(seen[-1], game_files.LAUNCHES_KEPT + 5)


if __name__ == "__main__":
    unittest.main()
