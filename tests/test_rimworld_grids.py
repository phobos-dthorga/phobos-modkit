"""Map grids and save comparison, on the fixture save (whose grid values fixtures/README.md lists) and on
synthetic bytes. Tests that index a save need the xml-index program, as in test_rimworld_save."""
import base64
from contextlib import closing
import ctypes
import io
from pathlib import Path
import shutil
import sqlite3
import struct
import tempfile
import unittest
import zlib

from support import FIXTURES
from test_rimworld_save import HAVE_INDEXER, ONLY_INDEXER, needs_indexer  # noqa: F401
from phobos_modkit.games.rimworld import grids, save_diff, save_maps
from phobos_modkit.games.rimworld import save as saves
from phobos_modkit.games.rimworld.save_cli import EXIT_OK, EXIT_USAGE, main
from phobos_modkit.report import render_markdown

FIXTURE = FIXTURES / "rimworld" / "Example.rws"


def reference_hash(text):
    """The same sum in explicitly signed 32-bit arithmetic, as C# does it."""
    value = ctypes.c_int32(23)
    for unit in struct.unpack(f"<{len(text.encode('utf-16-le')) // 2}H", text.encode("utf-16-le")):
        value = ctypes.c_int32(value.value * 31 + unit)
    return value.value


def fake_names():
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE def (def_type TEXT, def_name TEXT, wins INTEGER)")
    conn.executemany("INSERT INTO def VALUES (?, ?, 1)", [("TerrainDef", "Soil"), ("TerrainDef", "Sand"),
                                                           ("RoofDef", "RoofConstructed"), ("ThingDef", "Steel")])
    return grids.Names(conn)


class Hashes(unittest.TestCase):
    def test_stable_string_hash_is_signed_32_bit_arithmetic(self):
        for text in ("", "a", "Soil", "WaterOceanShallow", "x" * 200, "Ünïcødé_Def"):
            self.assertEqual(grids.stable_string_hash(text), reference_hash(text), text)

    def test_values_that_named_a_real_save_correctly(self):
        # These numbers decoded the owner's PG2 (7 Nov 2026) into the expected terrain, roofs and deep resources.
        self.assertEqual([grids.base_short_hash(n) for n in ("Soil", "Sand", "RoofConstructed", "Steel")],
                         [34465, 21158, 5133, 33787])

    def test_negative_hashes_keep_the_dividends_sign(self):
        # Long enough names overflow 32 bits, so about half of them come out negative.
        name = next(n for n in (f"LongEnoughDefName{i}" for i in range(1000)) if grids.stable_string_hash(n) < 0)
        value = grids.stable_string_hash(name)
        self.assertEqual(grids.base_short_hash(name), (-((-value) % 65535)) & 0xFFFF)

    def test_a_shared_number_moves_the_later_name_up(self):
        seen = {}
        for i in range(100000):
            name = f"Thing{i}"
            number = grids.base_short_hash(name)
            if number in seen:
                first, second = sorted((seen[number], name), key=lambda n: (n.lower(), n))
                break
            seen[number] = name
        table, uncertain = grids.short_hashes([second, first])
        self.assertEqual(table[number], first)
        self.assertEqual(table[number + 1], second)
        self.assertEqual(set(uncertain), {first, second})


class Decoding(unittest.TestCase):
    def test_deflated_and_plain_bytes(self):
        raw = bytes(range(20))
        packed = zlib.compressobj(9, zlib.DEFLATED, -15)
        deflated = base64.b64encode(packed.compress(raw) + packed.flush()).decode()
        self.assertEqual(grids.raw_bytes(deflated, True), raw)
        self.assertEqual(grids.raw_bytes(base64.b64encode(raw).decode(), False), raw)

    def test_each_layout(self):
        kind = lambda key: grids.KINDS[key]
        self.assertEqual(grids.cells(kind("terrain"), struct.pack("<3H", 1, 2, 65535), 3), [1, 2, 65535])
        self.assertEqual(grids.cells(kind("fog"), bytes([0b00000101]), 3), [1, 0, 1])
        gas = grids.cells(kind("gas"), struct.pack("<I", (200 << 8) | 7), 1)[0]
        self.assertEqual([grids.gas_density(gas, o) for _, o in grids.GAS_TYPES], [7, 200, 0, 0])
        with self.assertRaises(grids.GridError):
            grids.cells(kind("roof"), b"\x00", 4)

    def test_kinds_come_from_owner_and_element(self):
        self.assertEqual(grids.kind_of("terrainGrid", "topGridDeflate"), (grids.KINDS["terrain"], True))
        self.assertEqual(grids.kind_of("grid", "arr"), (grids.KINDS["pollution"], False))
        self.assertEqual(grids.kind_of("colorGrid", "x")[0], None)


class SaveIndex(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.saves = Path(self.tmp.name) / "Saves"
        self.saves.mkdir()
        self.cache = Path(self.tmp.name) / "cache"

    def tearDown(self):
        self.tmp.cleanup()

    def index(self, name, text=None):
        save = self.saves / name
        if text is None:
            shutil.copyfile(FIXTURE, save)
        else:
            save.write_text(text, encoding="utf-8")
        index, _ = saves.ensure(save, self.cache)
        return index


@needs_indexer
class Grids(SaveIndex):
    def setUp(self):
        super().setUp()
        self.conn = saves.open_read_only(self.index("Example.rws"))

    def tearDown(self):
        self.conn.close()
        super().tearDown()

    def test_the_fixtures_grids_decode_to_their_values(self):
        m = grids.load_map(self.conn, 0)
        self.assertEqual((m.width, m.height), (8, 8))
        self.assertEqual(m.values["terrain"][:32], [34465] * 32)
        self.assertEqual(m.values["roof"][m.index(1, 5)], 5133)
        self.assertEqual(grids.gas_density(m.values["gas"][m.index(3, 3)], 8), 128)
        self.assertEqual(sum(m.values["fog"]), 16)
        self.assertEqual(m.values["snow"][0], 32768)
        self.assertEqual(m.values["pollution"].index(1), 5)
        self.assertEqual((m.values["deep resource"][10], m.values["deep resource count"][10]), (33787, 300))

    def test_the_summary_names_layers_from_the_def_index(self):
        report = save_maps.grid(self.conn, 0, names=fake_names())
        text = render_markdown(report)
        self.assertIn("| Soil | 32 | 50.0% |", text)
        self.assertIn("| RoofConstructed | 16 | 25.0% |", text)
        self.assertIn("| toxic gas | 1 | highest 128 of 255, mean 128 |", text)
        self.assertIn("| fog | 16 | 25.0% of the cells |", text)
        self.assertIn("| Steel | 1 | 300 |", text)

    def test_without_names_defs_are_numbers(self):
        text = render_markdown(save_maps.grid(self.conn, 0))
        self.assertIn("| #34465 | 32 |", text)
        self.assertIn("No Def index was available", text)

    def test_an_area_limits_the_counts(self):
        text = render_markdown(save_maps.grid(self.conn, 0, names=fake_names(), area=(0, 0, 1, 1)))
        self.assertIn("(4 cells)", text)
        self.assertIn("| RoofConstructed | 4 | 100.0% |", text)

    def test_one_cell(self):
        text = render_markdown(save_maps.grid(self.conn, 0, names=fake_names(), at=(4, 4)))
        self.assertIn("| gas | blind smoke 255 |", text)
        self.assertIn("| terrain | Sand |", text)

    def test_a_picture_of_one_layer(self):
        report = save_maps.grid(self.conn, 0, kind="roof", names=fake_names(), render=True)
        picture = next(b for s in report.sections if s.heading == "Picture" for b in s.blocks
                       if hasattr(b, "lines"))
        self.assertEqual(picture.lines[0], "aa......")  # north row first; roofs where x is 0 or 1
        self.assertEqual(len(picture.lines), 8)

    def test_unknown_maps_and_layers_are_explained(self):
        with self.assertRaisesRegex(grids.GridError, "No map 5"):
            save_maps.grid(self.conn, 5)
        with self.assertRaisesRegex(grids.GridError, "No under-terrain grid"):
            save_maps.grid(self.conn, 0, kind="under-terrain")


@needs_indexer
class Diff(SaveIndex):
    def test_what_changed_between_two_saves(self):
        before = self.index("Before.rws")
        text = FIXTURE.read_text(encoding="utf-8")
        text = text.replace("<ticksGame>3720000</ticksGame>", "<ticksGame>3840000</ticksGame>")
        text = text.replace("<stackCount>75</stackCount>", "<stackCount>60</stackCount>")
        meal_start = text.index('<li Class="ThingWithComps">\n                    <def>MealSimple</def>')
        meal_end = text.index("</li>", meal_start) + len("</li>")
        text = text[:meal_start] + text[meal_end:]
        text = text.replace("<severity>4.5</severity>", "<severity>2</severity>")
        text = text.replace("<def>Example_Addiction</def>", "<def>Example_Bruise</def>")
        text = text.replace("<faction>Faction_2</faction>\n            <nameInt>Raider Camp",
                            "<faction>Faction_1</faction>\n            <nameInt>Raider Camp")
        text = text.replace("<warActive>True</warActive>", "<warActive>False</warActive>")
        text = text.replace("<li>\n              <tick>200</tick>\n            </li>",
                            "<li>\n              <tick>200</tick>\n            </li>\n            <li>\n"
                            "              <tick>300</tick>\n            </li>")
        site_start = text.index('<li Class="Example.Site">')
        text = text[:site_start] + text[text.index("</li>", site_start) + len("</li>"):]
        after = self.index("After.rws", text)
        with closing(saves.open_read_only(after)) as conn:
            report = save_diff.diff(conn, Path(before).resolve().as_uri() + "?mode=ro", "Before", "After")
            alarm_only = save_diff.diff(conn, Path(before).resolve().as_uri() + "?mode=ro", "Before", "After",
                                        component="*Alarm")
        self.assertIn("After is 2.0 in-game days after Before.", report.lines[0])
        tables = {s.heading: s.table.rows for s in report.sections}
        self.assertEqual(tables["Things that went, by def"], [("MealSimple", 1)])
        self.assertEqual(tables["Stacks that grew or shrank, by def"], [("Steel", "-15", 1)])
        hediffs = sorted((r[1], r[2]) for r in tables["Hediffs of the player's pawns gained, lost or changed"])
        self.assertEqual(hediffs, [("better", "Gunshot"), ("gained", "Example_Bruise"), ("lost", "Example_Addiction")])
        self.assertEqual(tables["World objects whose faction changed"],
                         [(2, "Settlement", "Raider Camp", "Example Raiders", "Example Colony")])
        self.assertEqual(tables["World objects that appeared or went"],
                         [("went", 3, "Example_Site", None, "Example Raiders")])
        self.assertEqual(tables["Component values that changed"],
                         [("Example.WorldComponent_Wars", None, "warActive", "True", "False")])
        self.assertEqual(tables["Component lists that grew or shrank"],
                         [("Example.WorldComponent_Wars", None, "history/li/tick", 2, 3, "+1")])
        narrowed = {s.heading: s.table.rows for s in alarm_only.sections}
        self.assertEqual(narrowed["Component values that changed"], [])


@needs_indexer
class Command(SaveIndex):
    def run_main(self, *args):
        out = io.StringIO()
        code = main([*args, "--saves", str(self.saves), "--cache", str(self.cache)], environ=ONLY_INDEXER, out=out)
        return code, out.getvalue()

    def test_grid_and_diff_from_the_command_line(self):
        shutil.copyfile(FIXTURE, self.saves / "Older.rws")
        shutil.copyfile(FIXTURE, self.saves / "Example.rws")
        code, text = self.run_main("grid", "--at", "3,3", "--no-names", "--save", "Example")
        self.assertEqual(code, EXIT_OK)
        self.assertIn("toxic gas 128", text)
        code, text = self.run_main("grid", "--kind", "gas", "--render", "--no-names", "--save", "Example")
        self.assertIn("## Picture", text)
        code, text = self.run_main("diff", "Older", "--save", "Example")
        self.assertEqual(code, EXIT_OK)
        self.assertIn("| things | 10 | 10 | +0 |", text)

    def test_bad_cells_are_usage_errors(self):
        shutil.copyfile(FIXTURE, self.saves / "Example.rws")
        self.assertEqual(self.run_main("grid", "--at", "3", "--no-names")[0], EXIT_USAGE)
        self.assertEqual(self.run_main("grid", "--at", "30,3", "--no-names")[0], EXIT_USAGE)


if __name__ == "__main__":
    unittest.main()
