"""The terrain report on the fixture save, whose made-up terrain fixtures/README.md gives: elevation tile x 10 - 500 m and hilliness
tile mod 6, on a planet of 272 tiles. Tests that index a save need the xml-index program, as in test_rimworld_save."""
from contextlib import closing
import io
import json
from pathlib import Path
import shutil
import tempfile
import unittest

from support import FIXTURES
from phobos_modkit.games.rimworld import terrain_reports
from phobos_modkit.games.rimworld import save as saves
from phobos_modkit.games.rimworld.save_cli import EXIT_OK, main
from phobos_modkit.report import render_markdown

FIXTURE = FIXTURES / "rimworld" / "Example.rws"


class Rules(unittest.TestCase):
    def test_land_is_above_the_sea_with_a_hilliness(self):
        elevation, hills = [-5, 10, 10, 10], [1, 0, 3, 9]
        self.assertEqual([terrain_reports.is_land(elevation, hills, t) for t in range(4)], [False, False, True, False])

    def test_a_percentile_is_the_nearest_rank(self):
        values = list(range(1, 11))
        self.assertEqual((terrain_reports.percentile(values, 0), terrain_reports.percentile(values, 0.5),
                          terrain_reports.percentile(values, 1)), (1, 6, 10))
        self.assertIsNone(terrain_reports.percentile([], 0.5))


class OnTheFixture(unittest.TestCase):
    def setUp(self):
        self.folder = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.folder, ignore_errors=True)
        self.saves = self.folder / "Saves"
        self.saves.mkdir()
        shutil.copy(FIXTURE, self.saves / "Example.rws")
        self.cache = self.folder / "cache"
        self.index, _ = saves.ensure(self.saves / "Example.rws", self.cache)

    def report(self, near=None, hops=2):
        with closing(saves.open_read_only(self.index)) as conn:
            return render_markdown(terrain_reports.report_terrain(conn, self.cache / "planet", near, hops))

    def test_land_and_its_heights(self):
        text = self.report()
        # Land: tiles 51 to 271 (above the sea) without a hilliness of 0 (every sixth): 184 of 272.
        self.assertIn("184 of 272 surface tiles are land", text)
        # The tenth land tile from the bottom is tile 73 (230 m); the highest is tile 271 (2,210 m).
        self.assertIn("| 230 m | 1,110 m | 1,990 m | 2,210 m |", text)
        self.assertIn("| flat | 37 |", text)

    def test_the_players_places_stand_at_their_tiles_height(self):
        self.assertIn("| Example Home | Settlement | 120 | 700 m | undefined |", self.report())

    def test_steps_between_neighbours_are_measured(self):
        text = self.report()
        self.assertIn("## Steps between neighbouring land tiles", text)
        self.assertIn("not a slope", text)

    def test_rings_around_a_place(self):
        text = self.report("Example Home", 2)
        self.assertIn("Around Example Home", text)
        self.assertIn("tile 120 stands at 700 m, undefined.", text)
        self.assertIn("| Steps | Tiles | Land | Lowest | Median | Highest |", text)
        self.assertIn("| 0 | 1 | 0 | - | - | - |", text)

    def test_the_command_answers_with_one_envelope(self):
        out = io.StringIO()
        code = main(["terrain", "--saves", str(self.saves), "--cache", str(self.cache), "--json"], out=out)
        self.assertEqual(code, EXIT_OK)
        self.assertIn("Terrain", json.loads(out.getvalue())["report"]["title"])


if __name__ == "__main__":
    unittest.main()
