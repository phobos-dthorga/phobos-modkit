"""rimworld-startup and rimworld-readiness on made-up sessions and a made-up install."""
import io
import json
from pathlib import Path
import tempfile
import unittest

import support  # noqa: F401  (the package on the import path)
from phobos_modkit.games.rimworld import loading, readiness, startup
from phobos_modkit.games.rimworld.mods import ModIndex
from phobos_modkit.games.rimworld.readiness_cli import main as readiness_main
from phobos_modkit.games.rimworld.startup_cli import EXIT_FAILED, EXIT_OK, main as startup_main


def session_xml(loading_ms, to_menu, list_hash, mods, stages=(("Loading Defs", 40000.0),)):
    mod_items = "".join(
        f"<li><modName>{name}</modName><modPackageId>{package}</modPackageId><metrics><keys><li>LoadingProgress.StartupImpact.ParseXml</li></keys>"
        f"<values><li>{cost}</li></values></metrics><totalImpact>{cost}</totalImpact><offThreadTotalImpact>{extra}</offThreadTotalImpact></li>"
        for name, package, cost, extra in mods)
    stage_items = "".join(f"<li><stage>{s}</stage><wallMs>{w}</wallMs><attributedMs>{w}</attributedMs></li>" for s, w in stages)
    return (f"<StartupImpactSession><sessionData><loadingTime>{loading_ms}</loadingTime><mods>{mod_items}</mods><modsLoaded>{len(mods)}</modsLoaded>"
            f"<defsParsed>100</defsParsed><patchOperationsApplied>10</patchOperationsApplied><modListHash>{list_hash}</modListHash>"
            f"<stageTimings>{stage_items}</stageTimings><timeToMenu>{to_menu}</timeToMenu></sessionData></StartupImpactSession>")


CE = ("Combat Stuff", "Some.Combat", 4000.0, 500.0)
ART = ("Art Pack", "some.art", 1000.0, 0.0)
NEW = ("New Mod", "some.new", 300.0, 0.0)


def sessions_folder(tmp):
    folder = Path(tmp) / "StartupImpactSessions"
    folder.mkdir()
    (folder / "20261101-100000.xml").write_text(session_xml(90000, 100000, "1", [CE, ART]), encoding="utf-8")
    (folder / "20261102-100000.xml").write_text(session_xml(70000, 80000, "1", [CE, ART]), encoding="utf-8")
    (folder / "20261103-100000.xml").write_text(session_xml(95000, 110000, "2", [CE, ART, NEW]), encoding="utf-8")
    (folder / "index.xml").write_text("<sessionIndex />", encoding="utf-8")
    (folder / "20261104-100000.xml").write_text("not xml", encoding="utf-8")
    return folder


def run_startup(argv):
    out = io.StringIO()
    code = startup_main(argv, out=out)
    return code, out.getvalue()


class Sessions(unittest.TestCase):
    def test_sessions_are_read_in_order_without_the_index(self):
        with tempfile.TemporaryDirectory() as tmp:
            sessions, unreadable = startup.read_sessions(sessions_folder(tmp))
        self.assertEqual([s.id for s in sessions], ["20261101-100000", "20261102-100000", "20261103-100000"])
        self.assertEqual(unreadable, ["20261104-100000.xml"])
        self.assertEqual(sessions[0].mods["some.combat"].milliseconds, 4500.0)
        self.assertEqual(sessions[0].mods["some.combat"].metrics, (("ParseXml", 4000.0),))

    def test_only_the_newest_list_is_compared_fairly(self):
        with tempfile.TemporaryDirectory() as tmp:
            sessions, _ = startup.read_sessions(sessions_folder(tmp))
        self.assertEqual([s.id for s in startup.same_list(sessions)], ["20261103-100000"])
        self.assertEqual(startup.list_change(sessions[1], sessions[2]), (["New Mod"], []))

    def test_the_summary_names_the_dearest_mod_and_the_list_change(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, text = run_startup(["--sessions", str(sessions_folder(tmp))])
        self.assertEqual(code, EXIT_OK)
        self.assertIn("3 launches recorded", text)
        self.assertIn("+1, -0", text)
        self.assertLess(text.index("Combat Stuff"), text.index("Art Pack"))
        self.assertIn("20261104-100000.xml", text)

    def test_compare_defaults_to_the_last_two_and_names_what_was_added(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, text = run_startup(["compare", "--sessions", str(sessions_folder(tmp))])
        self.assertEqual(code, EXIT_OK)
        self.assertIn("20261102-100000 against 20261103-100000", text)
        self.assertIn("New Mod", text)
        self.assertIn("+30.0 s", text)

    def test_compare_by_the_start_of_an_id_and_refuses_an_unclear_one(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = str(sessions_folder(tmp))
            code, text = run_startup(["compare", "20261101", "20261102", "--sessions", folder])
            self.assertEqual(code, EXIT_OK)
            self.assertIn("The mod list did not change", text)
            code, text = run_startup(["compare", "2026", "20261102", "--sessions", folder])
        self.assertEqual(code, EXIT_FAILED)
        self.assertIn("matches 3 launches", text)

    def test_one_mod_across_the_launches(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, text = run_startup(["mod", "combat*", "--sessions", str(sessions_folder(tmp))])
        self.assertEqual(code, EXIT_OK)
        self.assertIn("ParseXml", text)

    def test_a_missing_folder_says_which_mod_writes_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, text = run_startup(["--sessions", str(Path(tmp) / "none")])
        self.assertEqual(code, EXIT_FAILED)
        self.assertIn("Loading Progress", text)


ABOUT = "<ModMetaData><name>{name}</name><packageId>{pid}</packageId><supportedVersions>{versions}</supportedVersions></ModMetaData>"


def make_mod(root, folder, name, pid, versions=("1.6",)):
    mod = root / folder
    (mod / "About").mkdir(parents=True)
    items = "".join(f"<li>{v}</li>" for v in versions)
    (mod / "About" / "About.xml").write_text(ABOUT.format(name=name, pid=pid, versions=items), encoding="utf-8")
    return mod


def install(tmp):
    root = Path(tmp)
    game = root / "RimWorld"
    (game / "Data").mkdir(parents=True)
    (game / "Version.txt").write_text("1.7.5000 rev1", encoding="utf-8")
    mods = game / "Mods"
    ready = make_mod(mods, "Ready", "Ready Mod", "some.ready", ("1.6", "1.7"))
    old = make_mod(mods, "Old", "Old Mod", "some.old")
    (old / "Assemblies").mkdir()
    (old / "Assemblies" / "Old.dll").write_bytes(b"MZ junk Prepatcher more junk")
    (old / "AssetBundles").mkdir()
    (old / "AssetBundles" / "pack").write_bytes(b"x")
    plain = make_mod(mods, "Plain", "Plain Mod", "some.plain")
    (ready / "Assemblies").mkdir()
    (ready / "Assemblies" / "Ready.dll").write_bytes(b"MZ nothing")
    config = root / "Config"
    config.mkdir()
    (config / "ModsConfig.xml").write_text(
        "<ModsConfigData><version>1.7.5000 rev1</version><activeMods><li>some.ready</li><li>some.old</li><li>some.plain</li></activeMods></ModsConfigData>",
        encoding="utf-8")
    return game, config, root / "cache", root / "empty-workshop", plain


class Readiness(unittest.TestCase):
    def run_tool(self, tmp, *extra, transpilers=None):
        game, config, cache, workshop, _ = install(tmp) if not (Path(tmp) / "RimWorld").exists() else (
            Path(tmp) / "RimWorld", Path(tmp) / "Config", Path(tmp) / "cache", Path(tmp) / "empty-workshop", None)
        out = io.StringIO()
        code = readiness_main(["--game", str(game), "--config", str(config), "--cache", str(cache), "--workshop", str(workshop), *extra],
                              out=out, read_transpilers=lambda found: dict(transpilers or {"some.old": 2}))
        return code, out.getvalue()

    def test_the_mods_are_sorted_by_how_closely_they_depend_on_the_game(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, text = self.run_tool(tmp)
        self.assertEqual(code, EXIT_OK)
        self.assertIn("1 of 3 active mods declare 1.7", text)
        self.assertLess(text.index("Old Mod"), text.index("Plain Mod"))
        self.assertIn("first run", text)

    def test_another_version_can_be_asked_about(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, text = self.run_tool(tmp, "--game-version", "1.8")
        self.assertIn("0 of 3 active mods declare 1.8", text)

    def test_the_next_run_says_what_changed(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.run_tool(tmp)
            _, same = self.run_tool(tmp)
            self.assertIn("Nothing changed", same)
            _, text = self.run_tool(tmp, transpilers={"some.old": 5})
        self.assertIn("transpilers 2 to 5", text)

    def test_no_save_leaves_nothing_to_compare(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.run_tool(tmp, "--no-save")
            _, text = self.run_tool(tmp)
        self.assertIn("first run", text)

    def test_the_byte_scans_and_the_row(self):
        with tempfile.TemporaryDirectory() as tmp:
            game, *_ = install(tmp)
            index = ModIndex.scan([("Local", game / "Mods")])
            active = loading.resolve_active(index.mods, ["some.old", "some.plain"])
            dlls = {"some.old": [game / "Mods" / "Old" / "Assemblies" / "Old.dll"]}
            rows = readiness.assess(active, dlls, {"some.old": 1}, {}, "1.7")
        self.assertEqual([(r["prepatcher"], r["bundles"]) for r in rows], [(True, True), (False, False)])
        self.assertEqual(rows[0]["about"], ["1.6"])
        self.assertGreater(readiness.risk(rows[0]), readiness.risk(rows[1]))

    def test_json_output_is_valid(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, text = self.run_tool(tmp, "--json")
        self.assertIn("title", json.loads(text))


if __name__ == "__main__":
    unittest.main()
