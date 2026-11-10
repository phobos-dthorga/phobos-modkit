"""The atlas: short hashes, each tile's ring and outline, the globe block, and the report on the fixture save, whose
values fixtures/README.md lists. Tests that index a save need the xml-index program, as in test_rimworld_save."""
from array import array
import base64
from contextlib import closing
import io
import json
import math
from pathlib import Path
import shutil
import sqlite3
import tempfile
import unittest

from support import FIXTURES
from phobos_modkit.games.rimworld import atlas, planet
from phobos_modkit.games.rimworld import save as saves
from phobos_modkit.games.rimworld.save_cli import EXIT_OK, main
from phobos_modkit.report import Globe, GlobeLayer, GlobePlace, Report, render_json, render_markdown

FIXTURE = FIXTURES / "rimworld" / "Example.rws"


def decoded(block):
    """An array from the JSON form of a globe array."""
    codes = {"u8": "B", "u16": "H", "i32": "i", "f32": "f"}
    values = array(codes[block["dtype"]])
    values.frombytes(base64.b64decode(block["data"]))
    return values


class ShortHashes(unittest.TestCase):
    def test_names_hash_as_a_real_save_holds_them(self):
        # Short hashes read from a RimWorld 1.7 save's biome layer (November 2026).
        self.assertEqual({atlas.short_hash(n) for n in ("Ocean", "Desert", "IceSheet", "Tundra")},
                         {27374, 11658, 43595, 520})

    def test_a_collision_moves_the_later_name_up(self):
        self.assertEqual(atlas.short_hash("Exampleaa"), atlas.short_hash("ExamplebB"))
        taken = atlas.short_hashes(["ExamplebB", "Exampleaa"])
        self.assertEqual(taken[6885], "Exampleaa")      # the first in name order keeps its hash
        self.assertEqual(taken[6886], "ExamplebB")

    def test_names_read_as_words(self):
        self.assertEqual(atlas.pretty("TemperateForest"), "temperate forest")
        self.assertEqual(atlas.pretty("DMSE_ImpactCraterBiome"), "DMSE impact crater biome")


class Rings(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.shape = planet.build_shape(3)

    def test_each_ring_is_the_neighbours_in_order_round_the_tile(self):
        shape = self.shape
        for tile in range(len(shape)):
            ring = list(shape.ring[shape.start[tile]:shape.start[tile + 1]])
            self.assertEqual(sorted(ring), sorted(shape.around(tile)))
            for k, a in enumerate(ring):
                self.assertIn(ring[(k + 1) % len(ring)], shape.around(a))

    def test_neighbours_come_in_the_games_order_round_the_tile(self):
        # The game numbers a tile's neighbours round it, starting from its lowest-numbered triangle. Saves name a road's
        # other end by that number, so an order that merely holds the right tiles scatters roads into scraps.
        shape = self.shape
        for tile in range(len(shape)):
            around = list(shape.around(tile))
            for k, a in enumerate(around):
                self.assertIn(around[(k + 1) % len(around)], shape.around(a), tile)
        # Traced by hand from the game's code for one subdivision: tile 0's first triangles are (0, 16, 12),
        # (0, 12, 13), (0, 13, 14), (0, 14, 15) and (0, 15, 16), so its neighbours run 16, 15, 14, 13, 12.
        self.assertEqual(list(planet.build_shape(1).around(0)), [16, 15, 14, 13, 12])

    def test_every_outline_turns_the_same_way_seen_from_outside(self):
        shape = self.shape
        for tile in range(len(shape)):
            corners = shape.corners(tile)
            (ax, ay, az), (bx, by, bz), (cx, cy, cz) = corners[0], corners[1], corners[2]
            ux, uy, uz, vx, vy, vz = bx - ax, by - ay, bz - az, cx - ax, cy - ay, cz - az
            normal = (uy * vz - uz * vy, uz * vx - ux * vz, ux * vy - uy * vx)
            outward = normal[0] * shape.xs[tile] + normal[1] * shape.ys[tile] + normal[2] * shape.zs[tile]
            self.assertGreater(outward, 0, tile)

    def test_longitude_and_latitude_follow_the_games_formula(self):
        shape = self.shape
        for tile in (0, 50, 271):
            longitude, latitude = shape.long_lat(tile)
            self.assertLessEqual(abs(latitude), 90)
            corners = shape.corners(tile)
            x = sum(c[0] for c in corners) / len(corners)
            z = sum(c[2] for c in corners) / len(corners)
            self.assertAlmostEqual(longitude, math.degrees(math.atan2(x, -z)), places=4)

    def test_where_writes_it_as_the_game_does(self):
        self.assertRegex(atlas.where(self.shape, 0), r"^\d+\.\d\d°[NS] \d+\.\d\d°[EW]$")


class GlobeBlock(unittest.TestCase):
    def small(self, **changes):
        positions = array("f", [0, 1, 0, 0, -1, 0])
        values = dict(title="Tiny", description="Two tiles.", positions=positions, ring_start=array("i", [0, 1, 2]),
                      ring=array("i", [1, 0]),
                      layers=[GlobeLayer("a", "A", "Some values.", array("H", [3, 4]))],
                      places=[GlobePlace(0, "Home", "Settlement", "Yours", "accent")])
        values.update(changes)
        return Globe(**values)

    def test_arrays_travel_as_base64_and_come_back_the_same(self):
        report = Report("Globe")
        report.blocks.append(self.small())
        block = render_json(report)["blocks"][0]
        self.assertEqual(block["type"], "globe")
        self.assertEqual(block["tiles"], 2)
        self.assertEqual(list(decoded(block["layers"][0]["values"])), [3, 4])
        self.assertEqual(list(decoded(block["positions"])), [0, 1, 0, 0, -1, 0])
        self.assertEqual(block["places"][0]["role"], "accent")

    def test_markdown_says_what_the_globe_holds(self):
        report = Report("Globe")
        report.blocks.append(self.small())
        text = render_markdown(report)
        self.assertIn("A globe for a program to draw (2 tiles; views: A; 1 places)", text)

    def test_a_layer_of_the_wrong_length_is_refused(self):
        with self.assertRaisesRegex(ValueError, "has 1 values for 2 tiles"):
            self.small(layers=[GlobeLayer("a", "A", "Short.", array("H", [3]))])

    def test_an_unknown_role_is_refused(self):
        with self.assertRaisesRegex(ValueError, "role"):
            self.small(places=[GlobePlace(0, "Home", "Settlement", "Yours", "crimson")])


def fake_defs():
    """A Def index holding only what the atlas asks of one: a modded biome and a mutator, with labels."""
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE def (def_type TEXT, def_name TEXT, label TEXT, loads INTEGER, wins INTEGER, "
                 "abstract INTEGER)")
    rows = [("BiomeDef", name, None) for name in ("Ocean", "TemperateForest", "IceSheet")]
    rows += [("BiomeDef", "Example_ModBiome", "example meadow"), ("TileMutatorDef", "Caves", "caves"),
             ("RoadDef", "DirtRoad", "dirt road"), ("RiverDef", "River", "river")]
    conn.executemany("INSERT INTO def VALUES (?, ?, ?, 1, 1, 0)", rows)
    return conn


class OnTheFixture(unittest.TestCase):
    def setUp(self):
        self.folder = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.folder, ignore_errors=True)
        self.saves = self.folder / "Saves"
        self.saves.mkdir()
        shutil.copy(FIXTURE, self.saves / "Example.rws")
        self.cache = self.folder / "cache"
        self.index, _ = saves.ensure(self.saves / "Example.rws", self.cache)

    def report(self, written=None):
        if written is not None:
            self.addCleanup(written.close)
        with closing(saves.open_read_only(self.index)) as conn:
            return atlas.atlas(conn, self.cache / "planet", written)

    def globe(self, written=None):
        report = Report("Atlas")
        report.blocks = self.report(written).blocks
        return render_json(report)["blocks"][0]

    def test_biomes_are_counted_and_an_unknown_one_is_named_as_such(self):
        text = render_markdown(self.report())
        self.assertIn("| Ocean | 100 | 36.8% |", text)
        self.assertIn("| Temperate forest | 99 |", text)
        self.assertIn("| Ice sheet | 72 |", text)
        self.assertIn("1 biome short hashes match no loaded BiomeDef", text)

    def test_a_modded_biome_named_by_the_defs_is_coloured_from_its_climate(self):
        text = render_markdown(self.report(fake_defs()))
        self.assertIn("| Example meadow | 1 |", text)
        self.assertIn("No colour is set for example meadow", text)

    def test_places_are_grouped_by_how_their_faction_stands_with_the_player(self):
        text = render_markdown(self.report())
        self.assertIn("| Example Home | Settlement | Example Colony | Your colonies and camps | 120 |", text)
        self.assertIn("| Raider Camp | Settlement | Example Raiders | Hostile | 130 |", text)

    def test_roads_rivers_and_regions_are_listed(self):
        text = render_markdown(self.report())
        self.assertIn("| Road | Dirt road | 1 |", text)
        self.assertIn("| River | River | 1 |", text)
        self.assertIn("| Example Ocean | Ocean | 100 |", text)
        self.assertIn("| Example Isle | Island | 20 |", text)

    def test_the_globe_carries_every_layer_with_water_left_out_where_it_means_nothing(self):
        globe = self.globe()
        self.assertEqual(globe["tiles"], 272)
        layers = {layer["key"]: layer for layer in globe["layers"]}
        self.assertEqual(list(layers), ["biome", "elevation", "temperature", "rainfall", "hilliness", "swampiness",
                                        "pollution", "region"])
        rainfall = decoded(layers["rainfall"]["values"])
        self.assertEqual(sum(1 for v in rainfall if v == atlas.MISSING_U16), 100)    # the ocean tiles
        self.assertEqual(rainfall[150], 750)
        temperature = decoded(layers["temperature"]["values"])
        shown = temperature[10] * layers["temperature"]["scale"] + layers["temperature"]["offset"]
        self.assertAlmostEqual(shown, 19.0, places=3)
        self.assertTrue(layers["pollution"]["overlay"])
        self.assertEqual([b["label"] for b in layers["pollution"]["bands"]], ["Light", "Moderate", "Heavy", "Extreme"])
        region = decoded(layers["region"]["values"])
        self.assertEqual(layers["region"]["categories"][region[110]]["label"], "Example Isle")

    def test_roads_and_rivers_join_the_tiles_the_save_names(self):
        lines = {lines["key"]: lines for lines in self.globe()["lines"]}
        self.assertEqual(list(decoded(lines["roads"]["pairs"])), [120, 154])
        self.assertEqual(list(decoded(lines["rivers"]["pairs"])), [130, 168])
        self.assertEqual(lines["rivers"]["style"], "river")

    def test_labels_sit_where_the_game_draws_them(self):
        labels = {label["label"]: label for label in self.globe()["labels"]}
        self.assertEqual(labels["Example Ocean"]["position"], [0.0, 0.6, -0.8])
        self.assertEqual(labels["Example Isle"]["size"], 4.0)

    def test_mutators_become_tags_when_the_defs_name_them(self):
        self.assertEqual(self.globe()["tags"], [])
        tags = self.globe(fake_defs())["tags"][0]
        self.assertEqual(tags["names"], ["Caves"])
        self.assertEqual(list(decoded(tags["tiles"])), [120])

    def test_the_command_prints_one_envelope(self):
        out = io.StringIO()
        code = main(["atlas", "--saves", str(self.saves), "--cache", str(self.cache), "--no-defs", "--json"], out=out)
        self.assertEqual(code, EXIT_OK)
        answer = json.loads(out.getvalue())
        self.assertEqual(answer["tool"], "rimworld-save")
        self.assertEqual(answer["report"]["blocks"][0]["type"], "globe")


if __name__ == "__main__":
    unittest.main()
