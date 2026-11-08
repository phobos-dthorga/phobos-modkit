"""The RimWorld Def index, its load rules and reports, on a synthetic install built in a temporary folder.

Nothing here reads a real game. The fake install has the game's own Core, a Workshop mod and a local mod, with
LoadFolders conditions, version folders, a shadowed file, MayRequire, duplicates and patches.
"""
import io
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import time
import unittest
from contextlib import closing

import support  # noqa: F401
from phobos_modkit import cache as derived
from phobos_modkit.games.rimworld import defs, loading
from phobos_modkit.games.rimworld import defs_reports as reports
from phobos_modkit.games.rimworld.defs_cli import EXIT_OK, EXIT_USAGE, main
from phobos_modkit.games.rimworld.mods import InstalledMod
from phobos_modkit.report import render_markdown


def write(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def about(folder, package_id, name):
    write(Path(folder) / "About" / "About.xml",
          f"<ModMetaData><name>{name}</name><packageId>{package_id}</packageId></ModMetaData>")


def defs_file(path, *elements):
    write(path, "<Defs>" + "".join(elements) + "</Defs>")


def fake_install(root):
    root = Path(root)
    game = root / "steamapps" / "common" / "RimWorld"
    workshop = root / "steamapps" / "workshop" / "content" / "294100"
    config = root / "Config"
    write(game / "Version.txt", "1.7.9999 rev1")
    write(root / "steamapps" / "workshop" / "appworkshop_294100.acf", '"AppWorkshop" {}')

    core = game / "Data" / "Core"
    about(core, "Ludeon.RimWorld", "Core")
    defs_file(core / "Defs" / "Things.xml",
              '<ThingDef Name="BaseGun" Abstract="True"><thingClass>ThingWithComps</thingClass></ThingDef>',
              '<ThingDef ParentName="BaseGun"><defName>Gun_A</defName><label>gun a</label></ThingDef>',
              "<ThingDef><defName>Steel</defName><label>steel</label></ThingDef>",
              '<ThingDef Name="SharedBase" Abstract="True"><label>core base</label></ThingDef>')
    defs_file(core / "Defs" / "Rocks.xml",
              '<ThingDef Name="RockBase" Abstract="True"><building><isNaturalRock>true</isNaturalRock></building>'
              '</ThingDef>',
              '<ThingDef ParentName="RockBase"><defName>Granite</defName></ThingDef>',
              '<ThingDef ParentName="RockBase"><defName>MineableSteel</defName>'
              '<building><isResourceRock>true</isResourceRock></building></ThingDef>',
              '<ThingDef ParentName="RockBase"><defName>Marble</defName>'
              '<building><naturalTerrain>Soil</naturalTerrain></building></ThingDef>',
              "<TerrainTemplateDef><defName>Carpet</defName></TerrainTemplateDef>",
              "<ColorDef><defName>Structure_Red</defName><colorType>Structure</colorType></ColorDef>",
              "<ColorDef><defName>Ideo_Blue</defName><colorType>Ideo</colorType></ColorDef>")

    widgets = workshop / "2222222222"
    about(widgets, "example.widgets", "Example Widgets")
    defs_file(widgets / "Defs" / "Root.xml", "<ThingDef><defName>RootThing</defName></ThingDef>")
    defs_file(widgets / "1.7" / "Defs" / "W.xml",
              '<ThingDef MayRequire="not.active"><defName>NeedsAbsent</defName></ThingDef>',
              '<ThingDef MayRequireAnyOf="Ludeon.RimWorld,not.active"><defName>NeedsCore</defName></ThingDef>',
              "<ThingDef><defName>Dup</defName><label>first</label></ThingDef>",
              "<ThingDef><defName>Dup</defName><label>second</label></ThingDef>",
              '<ThingDef ParentName="SharedBase"><defName>WidgetGun</defName></ThingDef>',
              '<ThingDef Name="GatedBase" Abstract="True" MayRequire="not.active"><label>gated</label></ThingDef>',
              '<ThingDef ParentName="GatedBase"><defName>GatedChild</defName></ThingDef>')
    defs_file(widgets / "1.8" / "Defs" / "Future.xml", "<ThingDef><defName>FromTheFuture</defName></ThingDef>")

    workshop_copy = workshop / "3333333333"
    about(workshop_copy, "example.local", "Example Local (Workshop copy)")

    local = game / "Mods" / "Example Local"
    about(local, "example.local", "Example Local")
    write(local / "LoadFolders.xml", """<loadFolders><v1.6><li>Old</li></v1.6><v1.7>
        <li>/</li><li>1.7</li>
        <li IfModActive="Example.Widgets_steam">Mods/Widgets</li>
        <li IfModNotActive="example.widgets">Mods/NoWidgets</li>
        <li IfModActiveAll="example.widgets,not.active">Mods/Never</li>
    </v1.7></loadFolders>""")
    defs_file(local / "Defs" / "Shadow.xml", "<ThingDef><defName>ShadowedRoot</defName></ThingDef>")
    defs_file(local / "1.7" / "Defs" / "Shadow.xml", "<ThingDef><defName>ShadowWinner</defName></ThingDef>")
    defs_file(local / "1.7" / "Defs" / "Guns.xml",
              '<ThingDef ParentName="BaseGun"><defName>Gun_A</defName><label>better gun a</label></ThingDef>',
              '<ThingDef Name="SharedBase" Abstract="True"><label>local base</label></ThingDef>',
              '<ThingDef ParentName="SharedBase"><defName>LocalGun</defName></ThingDef>')
    defs_file(local / "Mods" / "Widgets" / "Defs" / "Tie.xml", "<ThingDef><defName>TieIn</defName></ThingDef>")
    defs_file(local / "Mods" / "NoWidgets" / "Defs" / "Alone.xml", "<ThingDef><defName>Alone</defName></ThingDef>")
    defs_file(local / "Mods" / "Never" / "Defs" / "N.xml", "<ThingDef><defName>Never</defName></ThingDef>")
    write(local / "Defs" / "Broken.xml", "<Defs><ThingDef>")
    write(local / "Patches" / "P.xml", """<Patch>
        <Operation Class="PatchOperationReplace"><xpath>Defs/ThingDef[defName="Steel"]/label</xpath>
            <value><label>shiny steel</label></value></Operation>
        <Operation Class="PatchOperationFindMod"><mods><li>Example Widgets</li></mods>
            <match Class="PatchOperationAdd">
                <xpath>Defs/ThingDef[defName="Gun_A" or defName="Steel"]/comps</xpath><value><li/></value>
            </match></Operation>
    </Patch>""")

    write(config / "ModsConfig.xml", """<ModsConfigData><version>1.7.9999 rev1</version><activeMods>
        <li>ludeon.rimworld</li><li>example.widgets</li><li>example.local</li><li>example.missing</li>
    </activeMods></ModsConfigData>""")
    return defs.Install(game, workshop, config)


class Install(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.install = fake_install(self.root)
        self.cache = self.root / "cache"

    def tearDown(self):
        self.tmp.cleanup()

    def built(self):
        index, built = defs.ensure(self.install, self.cache)
        return index, built

    def query(self, sql, params=()):
        index, _ = self.built()
        with closing(derived.open_read_only(index)) as conn:
            return conn.execute(sql, params).fetchall()


class LoadRules(unittest.TestCase):
    def test_bare_ids_ignore_case_and_the_workshop_suffix(self):
        self.assertEqual(loading.bare_id(" Example.Mod_steam "), "example.mod")

    def test_active_mods_prefer_local_copies_and_steam_suffix_means_workshop(self):
        local = InstalledMod("x.mod", "Local", "Local", Path("l"))
        steam = InstalledMod("x.mod", "Workshop", "Workshop", Path("w"), "1")
        found = loading.resolve_active([steam, local], ["x.mod", "x.mod_steam", "y.mod"])
        self.assertEqual([a.mod for a in found], [local, steam, None])

    def test_may_require_needs_every_mod_and_any_of_needs_one(self):
        element = lambda **attrs: type("E", (), {"get": lambda self, k: attrs.get(k)})()
        active = {"a", "b"}
        self.assertTrue(loading.may_load(element(MayRequire="A,b_steam"), active))
        self.assertFalse(loading.may_load(element(MayRequire="a,c"), active))
        self.assertTrue(loading.may_load(element(MayRequireAnyOf="c,B"), active))
        self.assertFalse(loading.may_load(element(MayRequireAnyOf="c,d"), active))

    def test_later_load_folders_win_the_same_path(self):
        loaded, skipped = loading.files_the_game_loads([("root", ["Defs/a.xml", "Defs/b.xml"]), ("1.7", ["Defs/a.xml"])])
        self.assertEqual(loaded, {"Defs/a.xml": "1.7", "Defs/b.xml": "root"})
        self.assertEqual(skipped, [("root", "Defs/a.xml", "1.7")])


class Folders(Install):
    def test_load_folders_with_every_condition(self):
        local = self.install.game / "Mods" / "Example Local"
        folders = loading.load_folders(local, "1.7", {"ludeon.rimworld", "example.widgets", "example.local"})
        self.assertEqual([f.relative_to(local).as_posix() if f != local else "" for f in folders],
                         ["", "1.7", "Mods/Widgets"])

    def test_without_load_folders_the_newest_version_not_above_the_games(self):
        widgets = self.install.workshop / "2222222222"
        self.assertEqual([f.name for f in loading.load_folders(widgets, "1.7", set())], ["2222222222", "1.7"])


class Building(Install):
    def test_counts_and_mods(self):
        _, built = self.built()
        self.assertEqual((built.mods, built.patches), (4, 2))
        mods = self.query("SELECT position, name, source, installed FROM mod ORDER BY position")
        self.assertEqual(mods, [(0, "Core", "Ludeon", 1), (1, "Example Widgets", "Workshop", 1),
                                (2, "Example Local", "Local", 1), (3, None, None, 0)])

    def test_the_later_mod_keeps_a_shared_name_and_the_first_copy_wins_inside_one_mod(self):
        guns = self.query("SELECT m.name, d.label, d.wins FROM def d JOIN mod m ON m.position = d.mod_position "
                          "WHERE d.def_name = 'Gun_A' ORDER BY d.mod_position")
        self.assertEqual(guns, [("Core", "gun a", 0), ("Example Local", "better gun a", 1)])
        self.assertEqual(self.query("SELECT label, wins FROM def WHERE def_name = 'Dup' ORDER BY id"),
                         [("first", 1), ("second", 0)])

    def test_what_loads(self):
        names = {n for (n,) in self.query("SELECT def_name FROM def WHERE wins")}
        self.assertTrue({"RootThing", "NeedsCore", "TieIn", "ShadowWinner", "Steel"} <= names)
        self.assertFalse(names & {"NeedsAbsent", "FromTheFuture", "Alone", "Never", "ShadowedRoot"})
        self.assertEqual(self.query("SELECT abstract, loads FROM def WHERE name = 'BaseGun'"), [(1, 0)])

    def test_problems_name_missing_mods_shadowed_and_unreadable_files(self):
        problems = {(k, f) for k, f in self.query("SELECT kind, file FROM problem")}
        self.assertIn(("missing", None), problems)
        self.assertIn(("shadowed", "Defs/Shadow.xml"), problems)
        self.assertIn(("unreadable", "Defs/Broken.xml"), problems)

    def test_patches_with_their_targets_and_find_mod_conditions(self):
        rows = self.query("SELECT operation, def_type, find_mods FROM patch ORDER BY id")
        self.assertEqual(rows, [("PatchOperationReplace", "ThingDef", None),
                                ("PatchOperationAdd", "ThingDef", "Example Widgets")])
        targets = self.query("SELECT def_name FROM patch_target ORDER BY patch_id, def_name")
        self.assertEqual(targets, [("Steel",), ("Gun_A",), ("Steel",)])


class GameMadeDefs(Install):
    def test_stone_floors_and_carpets_the_game_makes(self):
        made = self.query("SELECT def_type, def_name, made_from FROM def WHERE implied ORDER BY def_name")
        self.assertEqual([n for _, n, _ in made], ["CarpetRed", "Granite_Rough", "Granite_RoughHewn",
                                                   "Granite_Smooth", "Marble_RoughHewn", "Marble_Smooth"])
        self.assertEqual({t for t, _, _ in made}, {"TerrainDef"})
        self.assertEqual(made[0][2], "TerrainTemplateDef Carpet and ColorDef Structure_Red")

    def test_game_made_defs_load_and_have_no_xml(self):
        index, _ = self.built()
        with closing(derived.open_read_only(index)) as conn:
            self.assertEqual(conn.execute("SELECT wins FROM def WHERE def_name = 'Granite_Smooth'").fetchone(), (1,))
            text = render_markdown(reports.show(conn, "Granite_Smooth"))
        self.assertIn("made by the game from ThingDef Granite; it has no XML of its own", text)


class Staleness(Install):
    def test_reused_until_the_mod_list_a_local_mod_or_the_workshop_changes(self):
        self.assertIsNotNone(self.built()[1])
        self.assertIsNone(self.built()[1])
        for path in (self.install.mods_config, self.install.game / "Mods" / "Example Local" / "1.7" / "Defs" /
                     "Guns.xml", self.install.manifest):
            later = time.time() + 10
            os.utime(path, (later, later))
            self.assertIsNotNone(self.built()[1], path.name)
            self.assertIsNone(self.built()[1])

    def test_no_mods_config_is_a_clear_error(self):
        os.remove(self.install.mods_config)
        with self.assertRaisesRegex(defs.DefsError, "No ModsConfig.xml"):
            self.built()


class Reports(Install):
    def setUp(self):
        super().setUp()
        index, _ = self.built()
        self.conn = derived.open_read_only(index)

    def tearDown(self):
        self.conn.close()
        super().tearDown()

    def test_summary(self):
        text = render_markdown(reports.summary(self.conn))
        self.assertIn("4 active mods, 1 of them not installed.", text)
        self.assertIn("| ThingDef | Gun_A | Core > Example Local | Example Local |", text)

    def test_who_lists_fates_and_patches(self):
        report = reports.who(self.conn, "Gun_A")
        fates = [(r[2], r[4]) for r in report.sections[0].table.rows]
        self.assertEqual(fates, [("Core", "replaced by a later mod"), ("Example Local", "kept")])
        self.assertEqual(report.sections[1].table.rows[0][1], "PatchOperationAdd")

    def test_show_gives_the_xml_and_the_parent_chain(self):
        text = render_markdown(reports.show(self.conn, "Gun_A"))
        self.assertIn("<label>better gun a</label>", text)
        self.assertIn("## Parent BaseGun", text)
        self.assertIn("<thingClass>ThingWithComps</thingClass>", text)
        self.assertIn("No Def or abstract parent has that name", render_markdown(reports.show(self.conn, "Nope")))

    def test_show_cuts_long_xml_at_the_line_limit_unless_it_is_zero(self):
        cut = render_markdown(reports.show(self.conn, "Gun_A", max_lines=1))
        self.assertIn("more lines (raise --lines, or 0 for all)", cut)
        self.assertNotIn("<label>better gun a</label>", cut)
        whole = render_markdown(reports.show(self.conn, "Gun_A", max_lines=0))
        self.assertIn("<label>better gun a</label>", whole)
        self.assertNotIn("more lines", whole)

    def test_parents_come_from_the_latest_mod_at_or_before_the_child(self):
        widget = render_markdown(reports.show(self.conn, "WidgetGun"))
        self.assertIn("<label>core base</label>", widget)
        self.assertNotIn("local base", widget)
        self.assertIn("<label>local base</label>", render_markdown(reports.show(self.conn, "LocalGun")))

    def test_a_parent_whose_may_require_is_unmet_is_missing(self):
        text = render_markdown(reports.show(self.conn, "GatedChild"))
        self.assertIn("the game reports the parent as missing", text)
        self.assertNotIn("<label>gated</label>", text)

    def test_list_patches_mods_and_sql(self):
        kept = reports.list_defs(self.conn, def_type="ThingDef", name="Gun_*").sections[0].table.rows
        self.assertEqual(len(kept), 1)
        everything = reports.list_defs(self.conn, name="Gun_A", include_all=True).sections[0].table.rows
        self.assertEqual(len(everything), 2)
        self.assertEqual(len(reports.patches(self.conn, target="Steel").sections[0].table.rows), 2)
        self.assertEqual(len(reports.patches(self.conn, mod="Example Local", operation="*Replace").sections[0]
                             .table.rows), 1)
        self.assertEqual(reports.mods(self.conn).sections[0].table.rows[3][1], "(not installed)")
        self.assertEqual(reports.sql(self.conn, "SELECT COUNT(*) FROM def WHERE wins").sections[0].table.rows,
                         [(22,)])
        # Core: Steel, Granite, MineableSteel, Marble, Carpet, Structure_Red, Ideo_Blue; Widgets: RootThing, NeedsCore,
        # Dup, WidgetGun, GatedChild; Local: ShadowWinner, Gun_A, LocalGun, TieIn; made by the game: CarpetRed and
        # Granite's three stone floors and Marble's two.
        with self.assertRaises(sqlite3.OperationalError):
            reports.sql(self.conn, "DELETE FROM def")


class Command(Install):
    def run_main(self, *args):
        out = io.StringIO()
        code = main([*args, "--game", str(self.install.game), "--workshop", str(self.install.workshop),
                     "--config", str(self.install.config), "--cache", str(self.root / "kitcache")], environ={}, out=out)
        return code, out.getvalue()

    def test_builds_then_reuses(self):
        code, text = self.run_main()
        self.assertEqual(code, EXIT_OK)
        self.assertIn("built now", text)
        self.assertIn("reused", self.run_main("who", "Steel")[1])

    def test_each_report_runs(self):
        for args in (["mods"], ["who", "Gun_*"], ["show", "Gun_A", "--type", "ThingDef"], ["list", "--all"],
                     ["patches", "--target", "Steel"], ["sql", "SELECT 1"], ["index"]):
            code, text = self.run_main(*args)
            self.assertEqual(code, EXIT_OK, args)

    def test_json(self):
        data = json.loads(self.run_main("who", "Gun_A", "--json")[1])
        self.assertEqual(data["report"]["sections"][0]["blocks"][0]["rows"][1][2], "Example Local")

    def test_a_missing_config_is_a_usage_error(self):
        out = io.StringIO()
        code = main(["--config", str(self.root / "nowhere"), "--cache", str(self.root / "c")], environ={}, out=out)
        self.assertEqual(code, EXIT_USAGE)


if __name__ == "__main__":
    unittest.main()


PATCHED_DUMP = """<?xml version="1.0" encoding="utf-8"?>
<!-- Written for these tests in the shape D'thorga Framework writes: every Def after patches, before inheritance. -->
<Defs gameVersion="1.7.9999 rev1" written="2026-11-09T10:00:00Z" activeMods="3">
  <ThingDef Name="BaseGun" Abstract="True"><thingClass>ThingWithComps</thingClass></ThingDef>
  <ThingDef><defName>Steel</defName><label>shiny steel</label><comps><li /></comps></ThingDef>
  <ThingDef ParentName="BaseGun"><defName>Gun_A</defName><label>better gun a</label></ThingDef>
  <ThingDef><defName>AddedByPatch</defName></ThingDef>
</Defs>
"""


class PatchedDefs(Install):
    run_main = Command.run_main

    def test_a_def_as_patched_and_what_changed(self):
        dump = self.root / "PatchedDefs.xml"
        write(dump, PATCHED_DUMP)
        code, text = self.run_main("patched", "Steel", "--dump", str(dump))
        self.assertEqual(code, EXIT_OK)
        self.assertIn("written 2026-11-09T10:00:00Z by game 1.7.9999 rev1 with 3 active mods", text)
        self.assertIn("<label>shiny steel</label>", text)
        self.assertIn("-  <label>steel</label>", text)
        self.assertIn("+  <label>shiny steel</label>", text)
        self.assertIn("--- as written (Core)", text)
        code, text = self.run_main("patched", "Gun_A", "--dump", str(dump))
        self.assertIn("Nothing: the Def is as its mod wrote it.", text)
        code, text = self.run_main("patched", "AddedByPatch", "--dump", str(dump))
        self.assertIn("a patch may have added this Def", text)
        code, text = self.run_main("patched", "BaseGun", "--dump", str(dump))
        self.assertIn("Nothing: the Def is as its mod wrote it.", text)

    def _dump_now(self, text=PATCHED_DUMP):
        dump = self.root / "PatchedDefs.xml"
        write(dump, text)
        os.utime(dump, (time.time() + 60, time.time() + 60))
        return dump

    def test_a_file_newer_than_the_install_is_not_called_out_of_date(self):
        code, text = self.run_main("patched", "Steel", "--dump", str(self._dump_now()))
        self.assertEqual(code, EXIT_OK)
        self.assertNotIn("may be out of date", text)

    def test_changes_after_the_file_are_named(self):
        dump = self.root / "PatchedDefs.xml"
        write(dump, PATCHED_DUMP)
        os.utime(dump, (1, 1))
        code, text = self.run_main("patched", "Steel", "--dump", str(dump))
        self.assertEqual(code, EXIT_OK)
        self.assertIn("may be out of date", text)
        self.assertIn("the mod list has been saved since", text)
        self.assertIn("XML changed since in the game's Mods folder", text)

    def test_a_different_mod_count_or_game_version_is_reported(self):
        changed = PATCHED_DUMP.replace('activeMods="3"', 'activeMods="9"').replace('gameVersion="1.7.9999 rev1"',
                                                                                   'gameVersion="1.7.1 rev1"')
        code, text = self.run_main("patched", "Steel", "--dump", str(self._dump_now(changed)))
        self.assertIn("written with 9 active mods and", text)
        self.assertIn("the game is now 1.7.9999 rev1", text)

    def test_who_and_show_point_at_the_patched_view_only_when_the_file_exists(self):
        dump = self._dump_now()
        for report in ("who", "show"):
            code, text = self.run_main(report, "Steel", "--dump", str(dump))
            self.assertEqual(code, EXIT_OK)
            self.assertIn("the patched report shows Steel as the game reads it", text)
            code, text = self.run_main(report, "Steel", "--dump", str(self.root / "none.xml"))
            self.assertNotIn("the patched report shows", text)

    def test_without_a_dump_the_command_says_how_to_get_one(self):
        out = io.StringIO()
        code = main(["patched", "Steel", "--game", str(self.install.game), "--workshop", str(self.install.workshop),
                     "--config", str(self.install.config), "--cache", str(self.root / "kitcache")], environ={}, out=out)
        self.assertNotEqual(code, EXIT_OK)
