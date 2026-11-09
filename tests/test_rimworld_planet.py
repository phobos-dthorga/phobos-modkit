"""Pollution on the world map: the planet's shape, decoding the layer, and the report on the fixture save, whose values
fixtures/README.md lists. Tests that index a save need the xml-index program, as in test_rimworld_save."""
import base64
from contextlib import closing, redirect_stderr
import io
from pathlib import Path
import shutil
import struct
import tempfile
import unittest
import zlib

from support import FIXTURES
from test_rimworld_save import needs_indexer
from phobos_modkit.games.rimworld import planet, planet_reports
from phobos_modkit.games.rimworld import save as saves
from phobos_modkit.games.rimworld.save_cli import EXIT_OK, main
from phobos_modkit.report import render_markdown

FIXTURE = FIXTURES / "rimworld" / "Example.rws"
HOME, CAMP = 120, 130


def deflated(values):
    packer = zlib.compressobj(9, zlib.DEFLATED, -15)
    return base64.b64encode(packer.compress(struct.pack(f"<{len(values)}H", *values)) + packer.flush()).decode()


class Shape(unittest.TestCase):
    def test_tile_counts_name_their_subdivisions(self):
        self.assertEqual(planet.subdivisions_for(590492), 10)
        self.assertEqual(planet.subdivisions_for(32), 1)
        self.assertIsNone(planet.subdivisions_for(1000))

    def test_every_tile_has_five_or_six_mutual_neighbours(self):
        for subdivisions, tiles in ((1, 32), (2, 92), (3, 272)):
            shape = planet.build_shape(subdivisions)
            self.assertEqual(len(shape), tiles)
            counts = [len(shape.around(t)) for t in range(tiles)]
            self.assertEqual(counts.count(5), 12, "a sphere of hexagons needs exactly twelve pentagons")
            self.assertEqual(counts.count(6), tiles - 12)
            for tile in range(tiles):
                self.assertEqual(len(set(shape.around(tile))), counts[tile])
                for other in shape.around(tile):
                    self.assertIn(tile, shape.around(other))

    def test_neighbours_are_the_nearest_tiles(self):
        shape = planet.build_shape(3)
        for tile in range(len(shape)):
            def distance(other):
                return ((shape.xs[other] - shape.xs[tile]) ** 2 + (shape.ys[other] - shape.ys[tile]) ** 2
                        + (shape.zs[other] - shape.zs[tile]) ** 2)
            nearest = sorted((o for o in range(len(shape)) if o != tile), key=distance)[:len(shape.around(tile))]
            self.assertEqual(set(nearest), set(shape.around(tile)), tile)

    def test_rings_count_outwards(self):
        shape = planet.build_shape(3)
        rings = shape.rings(HOME, 2)
        self.assertEqual(rings[HOME], 0)
        self.assertEqual(sum(1 for d in rings.values() if d == 1), len(shape.around(HOME)))
        self.assertTrue(all(d <= 2 for d in rings.values()))

    def test_the_shape_is_cached_and_reloads_the_same(self):
        with tempfile.TemporaryDirectory() as folder:
            built = planet.load_shape(folder, 2)
            again = planet.load_shape(folder, 2)
            self.assertEqual(list(built.neighbours), list(again.neighbours))
            self.assertEqual(list(built.xs), list(again.xs))


class Decoding(unittest.TestCase):
    def test_deflated_and_plain(self):
        values = [0, 65535, 32768, 7]
        self.assertEqual(list(planet.decode(deflated(values), True)), values)
        plain = base64.b64encode(struct.pack("<4H", *values)).decode()
        self.assertEqual(list(planet.decode(plain, False)), values)

    def test_patches_are_touching_tiles_heaviest_first(self):
        shape = planet.build_shape(2)
        values = [0] * len(shape)
        first = shape.around(0)[0]
        values[0], values[first] = 65535, 32768
        rings = shape.rings(0, 99)
        far = max(rings, key=lambda t: (rings[t], t))
        values[far] = 100
        self.assertEqual([sorted(g) for g in planet.patches(values, shape)], [sorted([0, first]), [far]])

    def test_bands_follow_the_game(self):
        self.assertEqual([planet.band_of(int(f * planet.POLLUTION_FULL)) for f in (0.1, 0.3, 0.6, 1.0)],
                         ["light", "moderate", "heavy", "extreme"])

    def test_a_tiny_figure_is_not_shown_as_nothing(self):
        self.assertEqual(planet_reports.percent(0), "0.0%")
        self.assertEqual(planet_reports.percent(23), "0.035%")
        self.assertEqual(planet_reports.percent(32768), "50.0%")


@needs_indexer
class OnTheFixture(unittest.TestCase):
    def setUp(self):
        self.folder = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.folder, ignore_errors=True)
        self.saves = self.folder / "Saves"
        self.saves.mkdir()
        shutil.copy(FIXTURE, self.saves / "Example.rws")
        self.cache = self.folder / "cache"
        self.index, _ = saves.ensure(self.saves / "Example.rws", self.cache)

    def common(self):
        return ["--saves", str(self.saves), "--cache", str(self.cache)]

    def run_cli(self, *args):
        out = io.StringIO()
        code = main(["planet", *self.common(), *args], out=out)
        self.assertEqual(code, EXIT_OK, out.getvalue())
        return out.getvalue()

    def refused(self, *args):
        errors = io.StringIO()
        with redirect_stderr(errors):
            code = main(["planet", *self.common(), *args], out=io.StringIO())
        self.assertNotEqual(code, EXIT_OK)
        return errors.getvalue()

    def test_the_layer_reads_from_the_index(self):
        with closing(saves.open_read_only(self.index)) as conn:
            values = planet.from_index(conn)
        self.assertEqual(len(values), 272)
        self.assertEqual((values[HOME], values[CAMP]), (6554, 65535))

    def test_the_report_counts_bands_and_patches(self):
        text = self.run_cli()
        self.assertIn("3 of 272 surface tiles are polluted", text)
        self.assertIn("| light | 0% to 25% | 1 |", text)
        self.assertIn("| extreme | 75% to 100% | 1 |", text)
        self.assertIn("Raider Camp", text)

    def test_near_a_named_place_reads_the_rings_around_it(self):
        text = self.run_cli("--near", "Raider Camp", "--hops", "2")
        self.assertIn("tile 130 is 100.0% polluted", text)
        self.assertIn("Rings around it, out to 2 steps", text)

    def test_near_a_tile_number(self):
        self.assertIn("Around tile 120: tile 120 is 10.0% polluted", self.run_cli("--near", "120", "--hops", "1"))

    def test_a_place_that_does_not_exist_says_so(self):
        self.assertIn("No world object is named Nowhere", self.refused("--near", "Nowhere"))

    def test_compare_finds_no_change_against_itself(self):
        self.assertIn("0 tiles changed", self.run_cli("--compare", "Example"))

    def test_history_reads_each_save(self):
        text = self.run_cli("--near", "Raider Camp", "--hops", "1", "--history")
        self.assertIn("Example.rws", text)
        self.assertIn("100.0%", text)

    def test_history_needs_a_place(self):
        self.assertIn("--history needs --near", self.refused("--history"))

    def test_a_save_changed_while_read_is_refused(self):
        original = planet.derived.file_stamp
        stamps = iter([{"source_size": "1"}, {"source_size": "2"}])
        planet.derived.file_stamp = lambda path: next(stamps)
        try:
            with self.assertRaises(planet.PlanetError):
                planet.read_save(self.saves / "Example.rws")
        finally:
            planet.derived.file_stamp = original

    def test_the_report_goes_through_the_shared_renderer(self):
        with closing(saves.open_read_only(self.index)) as conn:
            report = planet_reports.report_planet(conn, self.cache)
        self.assertIn("# Planet", render_markdown(report))


if __name__ == "__main__":
    unittest.main()
