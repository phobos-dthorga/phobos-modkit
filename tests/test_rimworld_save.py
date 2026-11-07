"""RimWorld save indexes and reports, on the hand-written fixture save in temporary folders.

Tests that need the compiled xml-index program skip when it is not built; CI builds it and sets
PHOBOS_REQUIRE_NATIVE=1, which turns those skips into failures.
"""
import io
import json
import os
from pathlib import Path
import shutil
import sqlite3
import stat
import tempfile
import time
import unittest
from contextlib import closing
from types import SimpleNamespace

from support import FIXTURES
from phobos_modkit import native
from phobos_modkit.games.rimworld import save as saves
from phobos_modkit.games.rimworld import save_reports as reports
from phobos_modkit.games.rimworld.save_cli import EXIT_OK, EXIT_USAGE, main
from phobos_modkit.report import render_markdown

FIXTURE = FIXTURES / "rimworld" / "Example.rws"
INDEXER = native.tool_path("xml-index")
HAVE_INDEXER = INDEXER.is_file()
if not HAVE_INDEXER and os.environ.get("PHOBOS_REQUIRE_NATIVE") == "1":
    raise RuntimeError(f"PHOBOS_REQUIRE_NATIVE=1 but {INDEXER} is not built")
needs_indexer = unittest.skipUnless(HAVE_INDEXER, "xml-index is not built (cargo build --release)")
# Command tests see no real environment, only the indexer the tests found.
ONLY_INDEXER = {"PHOBOS_XML_INDEX": str(INDEXER)}


class Folders(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.saves = Path(self.tmp.name) / "Saves"
        self.cache = Path(self.tmp.name) / "cache"
        self.saves.mkdir()
        self.older = self.saves / "Older.rws"
        shutil.copyfile(FIXTURE, self.older)
        os.utime(self.older, (time.time() - 3600, time.time() - 3600))
        self.save = self.saves / "Example.rws"
        shutil.copyfile(FIXTURE, self.save)

    def tearDown(self):
        for path in Path(self.tmp.name).rglob("*"):
            if path.is_file():
                os.chmod(path, stat.S_IREAD | stat.S_IWRITE)
        self.tmp.cleanup()


class ChoosingSaves(Folders):
    def test_the_newest_save_by_default_and_any_save_by_name(self):
        self.assertEqual(saves.find_save(self.saves), self.save)
        self.assertEqual(saves.find_save(self.saves, "older"), self.older)
        self.assertEqual(saves.find_save(self.saves, "Older.rws"), self.older)
        self.assertEqual(saves.find_save(self.saves, str(self.older)), self.older)

    def test_missing_saves_say_where_they_looked(self):
        with self.assertRaisesRegex(saves.SaveError, "No save named Nope"):
            saves.find_save(self.saves, "Nope")
        with self.assertRaisesRegex(saves.SaveError, "No saves"):
            saves.find_save(Path(self.tmp.name) / "empty")

    def test_no_index_is_never_current(self):
        self.assertFalse(saves.is_current(self.cache / "Example.sqlite", self.save))


class Patterns(unittest.TestCase):
    def test_underscores_and_percent_signs_are_literal_and_star_and_question_mark_are_wildcards(self):
        self.assertEqual(saves.like("Gun_Revolver"), "Gun\\_Revolver")
        self.assertEqual(saves.like("*Chunk?"), "%Chunk_")
        self.assertEqual(saves.like("50%"), "50\\%")


class Tools(unittest.TestCase):
    def test_a_missing_program_says_how_to_build_it(self):
        with self.assertRaisesRegex(native.ToolMissing, "cargo build --release --locked"):
            native.require_tool("xml-index", explicit=Path(tempfile.gettempdir()) / "no-such-xml-index.exe")

    def test_environment_variable_names_the_program(self):
        self.assertEqual(native.tool_path("xml-index", environ={"PHOBOS_XML_INDEX": "elsewhere"}), Path("elsewhere"))

    def test_a_failed_build_is_reported(self):
        calls = []

        def run(command, cwd):
            calls.append(command)
            return SimpleNamespace(returncode=101)

        with self.assertRaisesRegex(native.ToolMissing, "exit code 101"):
            native.build_tools(environ={"PHOBOS_MODKIT_BUILD": "build-here"}, run=run)
        self.assertEqual(calls[0][:4], ["cargo", "build", "--release", "--locked"])
        self.assertEqual(calls[0][-2:], ["--target-dir", "build-here"])

    def test_builds_go_outside_the_repository(self):
        self.assertEqual(native.build_dir({"LOCALAPPDATA": "L"}, "win32"), Path("L") / "phobos-modkit" / "target")
        self.assertEqual(native.build_dir({}, "linux", home="h"), Path("h") / ".cache" / "phobos-modkit" / "target")
        self.assertEqual(native.build_dir({"PHOBOS_MODKIT_BUILD": "b", "LOCALAPPDATA": "L"}, "win32"), Path("b"))
        with tempfile.TemporaryDirectory() as tmp:
            built = Path(tmp) / "release" / native.program_name("xml-index")
            built.parent.mkdir(parents=True)
            built.write_bytes(b"")
            self.assertEqual(native.tool_path("xml-index", environ={"PHOBOS_MODKIT_BUILD": tmp}), built)


class FailedBuilds(Folders):
    def test_a_failing_indexer_leaves_no_frozen_copy(self):
        fake = Path(self.tmp.name) / "xml-index-fake"
        fake.write_text("")

        def run(command, capture_output, text):
            self.assertTrue(Path(command[-1]).is_file(), "the frozen copy exists while indexing")
            return SimpleNamespace(returncode=1, stdout="", stderr="xml-index: broken on purpose")

        with self.assertRaisesRegex(saves.SaveError, "broken on purpose"):
            saves.build(self.save, self.cache, indexer=fake, run=run)
        self.assertEqual(list(self.cache.glob("*.frozen.rws")), [])


@needs_indexer
class Indexing(Folders):
    def test_built_once_then_reused_until_the_save_changes(self):
        index, built = saves.ensure(self.save, self.cache)
        self.assertEqual(built.rows["thing"], 10)
        self.assertEqual(list(self.cache.glob("*.frozen.rws")), [])
        self.assertIsNone(saves.ensure(self.save, self.cache)[1])
        later = time.time() + 5
        os.utime(self.save, (later, later))
        self.assertIsNotNone(saves.ensure(self.save, self.cache)[1])

    def test_a_changed_schema_rebuilds(self):
        saves.ensure(self.save, self.cache)
        changed = Path(self.tmp.name) / "schema.toml"
        changed.write_text(saves.SCHEMA.read_text(encoding="utf-8") + "\n# changed\n", encoding="utf-8")
        self.assertIsNotNone(saves.ensure(self.save, self.cache, schema=changed)[1])

    def test_a_read_only_save_still_indexes(self):
        os.chmod(self.save, stat.S_IREAD)
        index, built = saves.ensure(self.save, self.cache)
        self.assertTrue(index.is_file())
        self.assertEqual(list(self.cache.glob("*.frozen.rws")), [])

    def test_the_index_records_where_it_came_from(self):
        index, _ = saves.ensure(self.save, self.cache)
        meta = saves.read_meta(index)
        self.assertEqual(meta["source"], "Example.rws")
        self.assertEqual(meta["schema_sha"], saves.schema_digest())
        self.assertEqual(meta["indexer"], "xml-index")


@needs_indexer
class Reports(Folders):
    def setUp(self):
        super().setUp()
        index, _ = saves.ensure(self.save, self.cache)
        self.conn = saves.open_read_only(index)

    def tearDown(self):
        self.conn.close()
        super().tearDown()

    def rows(self, report, section=0):
        return report.sections[section].table.rows

    def test_summary(self):
        report = reports.summary(self.conn)
        text = render_markdown(report)
        self.assertIn('scenario "Example Landing". 62 in-game days (1.0 years)', text)
        self.assertIn("2 hours of play", text)
        self.assertEqual(self.rows(report, 0), [(0, "Base_Player", "8 x 8", 5, 1)])
        self.assertEqual(self.rows(report, 2), [("Human", 1)])

    def test_things_by_def_and_listed(self):
        by_def = {r[0]: r for r in self.rows(reports.things(self.conn))}
        self.assertEqual(by_def["Steel"][2], 75)
        held = self.rows(reports.things(self.conn, held=True, listing=True))
        self.assertEqual(sorted((r[0], r[7]) for r in held),
                         [("Apparel_Parka103", "Human200"), ("Human302", "Corpse_Human104"),
                          ("MealSimple102", "Human200")])
        self.assertEqual(len(self.rows(reports.things(self.conn, place="world pawn", listing=True))), 1)
        self.assertEqual(self.rows(reports.things(self.conn, def_="Filth_*"))[0][0], "Filth_Dirt")

    def test_pawns_by_faction(self):
        self.assertEqual([r[0] for r in self.rows(reports.pawns(self.conn, faction="player"))], ["Annie"])
        raiders = reports.pawns(self.conn, faction="Example Raiders")
        self.assertEqual([r[0] for r in self.rows(raiders)], ["Cora Example", "Dov", "Eli Example"])

    def test_hediffs_of_one_pawn_and_by_def(self):
        annie = self.rows(reports.hediffs(self.conn, pawn="Annie"))
        self.assertEqual([(r[2], r[5]) for r in annie], [("Gunshot", 12), ("Example_Addiction", None)])
        grouped = {r[0]: r for r in self.rows(reports.hediffs(self.conn, def_="*Addiction"))}
        self.assertEqual(grouped["Example_Addiction"][1:3], (1, 1))

    def test_find_walks_the_holders(self):
        (section,) = reports.find(self.conn, "Apparel_Parka103").sections
        self.assertEqual([r[0] for r in section.table.rows], ["Apparel_Parka103", "Human200"])
        self.assertIn("No thing has that ID", render_markdown(reports.find(self.conn, "Nothing1")))

    def test_world_objects_counted_and_listed(self):
        counted = self.rows(reports.world(self.conn))
        self.assertIn(("Settlement", "Example Raiders", 1), counted)
        listed = self.rows(reports.world(self.conn, faction="Example Raiders"))
        self.assertEqual([(r[0], r[2]) for r in listed], [(3, None), (2, "Raider Camp")])
        self.assertEqual(self.rows(reports.world(self.conn, def_="Example.*"))[0][1], "Example_Site")

    def test_components_and_their_values(self):
        listed = {r[0]: r for r in self.rows(reports.components(self.conn))}
        self.assertEqual(listed["Example.WorldComponent_Wars"][1:], ("world", None, 5))
        self.assertEqual(listed["Example.MapComponent_Alarm"][1:], ("map", 0, 1))
        values = self.rows(reports.components(self.conn, cls="*Wars"))
        self.assertEqual([(r[2], r[3]) for r in values], [("warActive", "True"), ("battle/attacker", "Faction_2"),
                                                           ("battle/stage", "3"), ("history/li/tick", "100"),
                                                           ("history/li/tick", "200")])
        self.assertEqual(self.rows(reports.components(self.conn, value="Faction_2"))[0][2], "battle/attacker")
        self.assertEqual(self.rows(reports.components(self.conn, path="armed", map_=0))[0][0],
                         "Example.MapComponent_Alarm")

    def test_schema_paths_with_counts(self):
        rows = self.rows(reports.schema(self.conn, under="savegame/meta", depth=1))
        self.assertIn((1, "savegame/meta/modIds"), rows)
        self.assertNotIn("savegame/meta/modIds/li", [r[1] for r in rows])

    def test_queries_cannot_change_the_index(self):
        self.assertEqual(self.rows(reports.sql(self.conn, "SELECT COUNT(*) FROM skill")), [(1,)])
        with self.assertRaises(sqlite3.OperationalError):
            reports.sql(self.conn, "DELETE FROM thing")

    def test_tables_say_when_rows_were_cut(self):
        text = render_markdown(reports.things(self.conn, top=2))
        self.assertIn("Showing 2 of", text)


@needs_indexer
class Command(Folders):
    def run_main(self, *args):
        out = io.StringIO()
        code = main([*args, "--saves", str(self.saves), "--cache", str(self.cache)], environ=ONLY_INDEXER, out=out)
        return code, out.getvalue()

    def test_first_run_builds_and_the_next_reuses(self):
        code, text = self.run_main()
        self.assertEqual(code, EXIT_OK)
        self.assertIn("Index of Example.rws, built now from a frozen copy", text)
        self.assertIn("# Save summary", text)
        self.assertIn("reused", self.run_main("pawns")[1])

    def test_each_report_runs(self):
        for args in (["schema"], ["things", "--list", "--held"], ["pawns", "--faction", "player"], ["world"],
                     ["world", "--name", "Raider*"], ["components"], ["components", "--class", "*Alarm"],
                     ["hediffs", "--pawn", "Annie"], ["find", "ChunkA*"], ["sql", "SELECT 1"], ["index"]):
            code, text = self.run_main(*args)
            self.assertEqual(code, EXIT_OK, args)
            self.assertIn("Index of Example.rws", text)

    def test_json_and_reading_an_index_directly(self):
        code, text = self.run_main("pawns", "--json")
        data = json.loads(text)
        self.assertEqual(data["report"]["sections"][0]["blocks"][0]["headers"][0], "Name")
        out = io.StringIO()
        index = self.cache / saves.CACHE_FOLDER / "Example.sqlite"
        self.assertEqual(main(["things", "--index", str(index)], environ={}, out=out), EXIT_OK)
        self.assertIn("Index of Example.rws, reused", out.getvalue())

    def test_options_before_the_report_name_mean_summary(self):
        code, text = self.run_main("--top", "3")
        self.assertIn("# Save summary", text)

    def test_unknown_saves_and_indexes_are_usage_errors(self):
        self.assertEqual(self.run_main("--save", "Nope")[0], EXIT_USAGE)
        self.assertEqual(main(["things", "--index", str(Path(self.tmp.name) / "none.sqlite")], environ={},
                              out=io.StringIO()), EXIT_USAGE)

    def test_the_cache_is_closed_after_each_command(self):
        self.run_main()
        index = self.cache / saves.CACHE_FOLDER / "Example.sqlite"
        with closing(sqlite3.connect(index)) as conn:  # would fail to write on Windows if a handle stayed open
            conn.execute("PRAGMA user_version = 1")
        self.assertEqual(self.run_main("index")[0], EXIT_OK)


if __name__ == "__main__":
    unittest.main()
