"""The mod-list check (1.72.0), on synthetic RimWorld and Project Zomboid installs in a temporary folder. Nothing reads a real one."""
import io
import json
from pathlib import Path
import tempfile
import unittest

import support
from phobos_modkit import mod_list as core
from phobos_modkit import mod_list_cli as cli
from phobos_modkit.games import mod_list_game
from phobos_modkit.games.rimworld.mod_list import RimWorld, _preview, read_about
from phobos_modkit.games.zomboid.mod_list import Zomboid as ZomboidAdapter, _poster, info_file, read_list
from phobos_modkit.manifest import describe


def about(folder, package_id, name, extra="", versions=("1.7",)):
    target = Path(folder) / "About"
    target.mkdir(parents=True, exist_ok=True)
    supported = "".join(f"<li>{v}</li>" for v in versions)
    (target / "About.xml").write_text(f"<ModMetaData><name>{name}</name><packageId>{package_id}</packageId>"
                                      f"<supportedVersions>{supported}</supportedVersions>{extra}</ModMetaData>", encoding="utf-8")


def need(package_id, name="", workshop=""):
    url = f"<steamWorkshopUrl>steam://url/CommunityFilePage/{workshop}</steamWorkshopUrl>" if workshop else ""
    return f"<li><packageId>{package_id}</packageId><displayName>{name}</displayName>{url}</li>"


MODS_CONFIG = """<?xml version="1.0" ?>\r
<ModsConfigData>\r
  <version>1.7.5014 rev1195</version>\r
  <activeMods>\r
{items}  </activeMods>\r
  <knownExpansions>\r
    <li>ludeon.rimworld.royalty</li>\r
  </knownExpansions>\r
</ModsConfigData>\r
"""


def mods_config(path, ids):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(MODS_CONFIG.format(items="".join(f"    <li>{i}</li>\r\n" for i in ids)).encode("utf-8"))


class FakeRimWorld:
    """A RimWorld install with a Core, local and Workshop mods, a ModsConfig.xml and Steam's Workshop record."""

    def __init__(self, root, active, subscribed=("1000000001", "1000000002", "1000000003", "1000000004", "1000000005")):
        root = Path(root)
        self.game = root / "steamapps" / "common" / "RimWorld"
        self.workshop = root / "steamapps" / "workshop" / "content" / "294100"
        self.config = root / "Config"
        about(self.game / "Data" / "Core", "Ludeon.RimWorld", "Core")
        about(self.game / "Mods" / "LocalThing", "example.local", "Local Thing")
        about(self.workshop / "1000000001", "example.market", "Market",
              "<loadAfter><li>example.hostel</li></loadAfter><incompatibleWith><li>example.rival</li></incompatibleWith>")
        (self.workshop / "1000000001" / "Languages").mkdir(parents=True)
        (self.workshop / "1000000001" / "Languages" / "Keyed.xml").write_text("<Hint>Guests of the Hostel buy here.</Hint>",
                                                                              encoding="utf-8")
        about(self.workshop / "1000000002", "example.hostel", "Hostel")
        about(self.workshop / "1000000003", "example.needy", "Needy",
              "<modDependencies>" + need("example.library", "Library") + "</modDependencies>"
              "<modDependenciesByVersion><v1.7>" + need("example.library", "Library")
              + need("example.absent", "Absent Thing", "1000000099") + "</v1.7></modDependenciesByVersion>",
              versions=("1.6",))
        about(self.workshop / "1000000004", "example.library", "Library")
        about(self.workshop / "1000000005", "example.rival", "Rival")
        record = root / "steamapps" / "workshop" / "appworkshop_294100.acf"
        items = "".join(f'"{i}" {{ "size" "1" }}' for i in subscribed)
        record.write_text(f'"AppWorkshop" {{ "appid" "294100" "WorkshopItemsInstalled" {{ {items} }} }}', encoding="utf-8")
        mods_config(self.config / "ModsConfig.xml", active)
        self.root = root

    def environ(self, tmp):
        return support.isolated_environ(tmp, RIMWORLD_PATH=str(self.game), RIMWORLD_WORKSHOP_PATH=str(self.workshop),
                                        RIMWORLD_CONFIG_PATH=str(self.config), PHOBOS_STEAM=str(self.root),
                                        PHOBOS_MOD_LIST=str(Path(tmp) / "mod-list"), PHOBOS_RIMSORT=str(Path(tmp) / "RimSort"),
                                        RIMWORLD_SAVES_PATH=str(Path(tmp) / "Saves"), RIMWORLD_LOGS_PATH=str(Path(tmp) / "Logs"))


ACTIVE = ["ludeon.rimworld", "example.market", "example.hostel", "example.needy", "example.rival", "example.market",
          "example.gone", "someone.market.hostel.compatibility"]


class RimWorldChecks(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.fake = FakeRimWorld(self.tmp.name, ACTIVE)
        self.environ = self.fake.environ(self.tmp.name)
        self.adapter = RimWorld(self.environ)
        self.installed = core.Installed(self.adapter, self.adapter.installed())
        self.memory_file = core.remembered_file("rimworld", self.environ)
        self.memory_file.parent.mkdir(parents=True, exist_ok=True)
        self.memory_file.write_text(json.dumps({"format": 1, "mods": {"example.gone": {
            "id": "example.gone", "name": "Gone Mod", "source": "workshop", "workshop_id": "1000000077"}}}), encoding="utf-8")
        memory = core.remember(self.memory_file, self.adapter, self.installed.mods)
        steam = {"1000000077": 9, "1000000001": 1, "1000000002": 1, "1000000003": 1, "1000000004": 1, "1000000005": 9}
        self.problems = core.check(self.adapter, self.adapter.lists()[0], self.installed, memory, steam,
                                   self.adapter.subscribed())

    def tearDown(self):
        self.tmp.cleanup()

    def of(self, kind):
        return [p for p in self.problems if p.kind == kind]

    def test_a_mod_taken_off_the_workshop_is_named_and_explained(self):
        gone = next(p for p in self.of("missing") if p.id == "example.gone")
        self.assertEqual(gone.name, "Gone Mod")
        self.assertIn("took it off the Workshop", gone.why)
        self.assertEqual([f.action for f in gone.fixes], ["remove"])

    def test_a_patch_never_seen_gets_a_clue_from_the_mods_its_id_names(self):
        patch = next(p for p in self.of("missing") if p.id == "someone.market.hostel.compatibility")
        self.assertIn("No check has seen it", patch.why)
        self.assertIn("Market's own files mention Hostel", patch.clue)

    def test_a_mod_listed_twice_offers_to_keep_the_first(self):
        twice = self.of("twice")
        self.assertEqual(len(twice), 1)
        self.assertEqual(twice[0].fixes[0].action, "remove-extra")

    def test_the_version_list_replaces_the_plain_one(self):
        needs = {p.name: p for p in self.of("needs")}
        self.assertEqual(set(needs), {"Library", "Absent Thing"})
        self.assertEqual(needs["Library"].fixes[0].action, "enable")
        self.assertEqual(needs["Absent Thing"].fixes, [])
        self.assertEqual(needs["Absent Thing"].workshop_id, "1000000099")

    def test_order_and_clashes_follow_the_mods_own_files(self):
        self.assertIn("must load after Hostel", self.of("order")[0].title)
        clash = self.of("clash")
        self.assertEqual(len(clash), 1)
        self.assertEqual(len(clash[0].fixes), 2)

    def test_early_warnings_and_versions(self):
        self.assertIn("Rival", self.of("removed")[0].title)
        self.assertEqual([p.name for p in self.of("version")], ["Needy"])

    def test_a_mod_steam_no_longer_keeps_is_a_warning(self):
        fake = FakeRimWorld(Path(self.tmp.name) / "other", ["example.hostel"], subscribed=("1000000001",))
        adapter = RimWorld(fake.environ(self.tmp.name))
        installed = core.Installed(adapter, adapter.installed())
        found = core.check(adapter, adapter.lists()[0], installed, {}, None, adapter.subscribed())
        self.assertEqual([p.kind for p in found], ["unsubscribed"])

    def test_a_known_problem_is_warned_of_only_when_every_mod_it_names_is_active(self):
        problem = {"id": "market-hostel", "game": "rimworld", "checked": "2026-11-23", "what": "Market and Hostel clash.",
                   "do": "Switch one off.", "mods": [{"id": "Example.Market", "name": "Market"},
                                                     {"id": "example.hostel", "name": "Hostel"}]}
        absent = dict(problem, id="market-library", mods=[{"id": "example.market", "name": "Market"},
                                                          {"id": "example.library", "name": "Library"}])
        fixed = dict(problem, id="fixed-one", fixed="2026-11-20")
        other_game = dict(problem, id="other-game", game="project-zomboid")
        old_version = dict(problem, id="old-version", gameVersions=["1.5"])
        known = [("me/game:feeds", {"problems": [problem, absent, fixed, other_game, old_version]})]
        found = core.check(self.adapter, self.adapter.lists()[0], self.installed, {}, None, None, known=known)
        warned = [p for p in found if p.kind == "known"]
        self.assertEqual(["Market and Hostel"], [p.name for p in warned])
        self.assertEqual("warning", warned[0].severity)
        self.assertIn("Switch one off. (Checked 2026-11-23, from me/game:feeds.)", warned[0].why)

    def test_problems_come_before_warnings_and_notes(self):
        order = [p.severity for p in self.problems]
        self.assertEqual(order, sorted(order, key=core.SEVERITIES.index))


class RimWorldChanges(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.fake = FakeRimWorld(self.tmp.name, ["ludeon.rimworld", "example.hostel", "example.needy", "example.gone",
                                                 "example.hostel"])
        self.environ = self.fake.environ(self.tmp.name)
        self.adapter = RimWorld(self.environ)
        self.installed = core.Installed(self.adapter, self.adapter.installed())
        self.path = self.fake.config / "ModsConfig.xml"

    def tearDown(self):
        self.tmp.cleanup()

    def fresh(self):
        return RimWorld(self.environ).lists()[0]

    def test_rendering_the_same_ids_gives_the_same_file(self):
        text = self.path.read_bytes().decode("utf-8")
        self.assertEqual(self.adapter.render(text, self.fresh().ids), text)

    def test_switching_on_goes_just_before_the_first_mod_that_needs_it(self):
        ids, _ = core.plan(self.adapter, self.fresh(), self.installed, core.ENABLE, "example.library")
        self.assertEqual(ids.index("example.library"), ids.index("example.needy") - 1)

    def test_a_change_keeps_a_backup_and_undo_puts_it_back(self):
        before = self.path.read_bytes()
        words, backup, ids = core.apply_fix(self.adapter, self.fresh(), self.installed, core.REMOVE, "example.gone",
                                            lambda names: [], self.environ)
        self.assertNotIn("example.gone", ids)
        self.assertEqual(backup.read_bytes(), before)
        self.assertNotIn(b"example.gone", self.path.read_bytes())
        self.assertIn(b"\r\n    <li>example.hostel</li>", self.path.read_bytes())
        core.undo(self.adapter, self.fresh(), lambda names: [], self.environ)
        self.assertEqual(self.path.read_bytes(), before)

    def test_moving_and_switching_on_at_a_place(self):
        ids, words = core.plan(self.adapter, self.fresh(), None, core.MOVE, "example.gone", 1)
        self.assertEqual((ids[0], words), ("example.gone", "move example.gone to place 1"))
        ids, _ = core.plan(self.adapter, self.fresh(), None, core.MOVE, "example.gone", 999)
        self.assertEqual(ids[-1], "example.gone")
        ids, _ = core.plan(self.adapter, self.fresh(), self.installed, core.ENABLE, "example.library", 2)
        self.assertEqual(ids[1], "example.library")
        for place in (None, 0, 4):
            with self.assertRaises(core.FixError):
                core.plan(self.adapter, self.fresh(), None, core.MOVE, "example.gone", place)

    def test_undo_walks_back_one_change_at_a_time(self):
        first = self.path.read_bytes()
        nobody = lambda names: []
        core.apply_fix(self.adapter, self.fresh(), None, core.MOVE, "example.gone", nobody, self.environ, place=1)
        second = self.path.read_bytes()
        core.apply_fix(self.adapter, self.fresh(), None, core.REMOVE, "example.needy", nobody, self.environ)
        self.assertEqual(core.undo(self.adapter, self.fresh(), nobody, self.environ)["why"], "take example.needy off the list")
        self.assertEqual(self.path.read_bytes(), second)
        self.assertEqual(core.undo(self.adapter, self.fresh(), nobody, self.environ)["why"], "move example.gone to place 1")
        self.assertEqual(self.path.read_bytes(), first)
        with self.assertRaises(core.FixError):
            core.undo(self.adapter, self.fresh(), nobody, self.environ)

    def test_keeping_the_first_of_two(self):
        core.apply_fix(self.adapter, self.fresh(), self.installed, core.REMOVE_EXTRA, "example.hostel", lambda names: [],
                       self.environ)
        self.assertEqual(self.fresh().ids.count("example.hostel"), 1)

    def test_changes_wait_while_the_game_or_rimsort_runs(self):
        before = self.path.read_bytes()
        with self.assertRaises(core.FixError) as refused:
            core.apply_fix(self.adapter, self.fresh(), self.installed, core.REMOVE, "example.gone",
                           lambda names: ["RimSort.exe"], self.environ)
        self.assertIn("RimSort.exe is running", str(refused.exception))
        self.assertEqual(self.path.read_bytes(), before)

    def test_undo_refuses_when_the_list_changed_since(self):
        core.apply_fix(self.adapter, self.fresh(), self.installed, core.REMOVE, "example.gone", lambda names: [], self.environ)
        mods_config(self.path, ["ludeon.rimworld", "example.hostel"])
        with self.assertRaises(core.FixError) as refused:
            core.undo(self.adapter, self.fresh(), lambda names: [], self.environ)
        self.assertIn("has changed since", str(refused.exception))

    def test_nonsense_changes_are_refused(self):
        for action, mod_id in ((core.REMOVE, "example.never"), (core.ENABLE, "example.hostel"), (core.ENABLE, "x.not.here"),
                               ("delete", "example.hostel")):
            with self.assertRaises(core.FixError):
                core.plan(self.adapter, self.fresh(), self.installed, action, mod_id)


class RimWorldAbout(unittest.TestCase):
    def test_force_rules_count_and_local_mods_carry_their_workshop_number(self):
        with tempfile.TemporaryDirectory() as tmp:
            about(tmp, "Example.Forced", "Forced", "<forceLoadAfter><li>a.b</li></forceLoadAfter>")
            (Path(tmp) / "About" / "PublishedFileId.txt").write_text("3000000001", encoding="utf-8")
            mod = read_about(tmp, "local", "", "1.7")
            self.assertEqual((mod.id, mod.load_after, mod.workshop_id), ("example.forced", ["a.b"], "3000000001"))


ZOMBOID_LIST = "VERSION = 1,\r\n\r\nmods\r\n{{\r\n{items}}}\r\n\r\nmaps\r\n{{\r\n}}\r\n"


def zomboid_list(path, ids):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(ZOMBOID_LIST.format(items="".join(f"    mod = {i},\r\n" for i in ids)).encode("utf-8"))


def mod_info(folder, lines):
    Path(folder).mkdir(parents=True, exist_ok=True)
    (Path(folder) / "mod.info").write_text("\n".join(lines) + "\n", encoding="utf-8")


class ZomboidLists(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.data = root / "Zomboid"
        (self.data / "version.txt").parent.mkdir(parents=True)
        (self.data / "version.txt").write_text("42.16.0 abc", encoding="utf-8")
        mod_info(self.data / "mods" / "Lib", ["id=Lib", "name=Library", "versionMin=42.0.0"])
        mod_info(self.data / "mods" / "Chem", ["id=Chem", "name=Chem Old"])
        mod_info(self.data / "mods" / "Chem" / "42.15", ["id=Chem", "name=Chemistry", r"require=\Lib,\Vaccine",
                                                          r"loadModAfter=\Lib", "versionMin=42.15.0"])
        mod_info(self.data / "mods" / "Chem" / "42.99", ["id=Chem", "name=Chemistry Future", "versionMin=42.99.0"])
        zomboid_list(self.data / "mods" / "default.txt", ["Chem", "Lib", "Some Workshop Mod's Name"])
        zomboid_list(self.data / "Saves" / "Sandbox" / "Run 1" / "mods.txt", ["Lib"])
        self.adapter = ZomboidAdapter(support.isolated_environ(self.tmp.name), data=self.data, steam=root / "Steam")

    def tearDown(self):
        self.tmp.cleanup()

    def test_a_mod_names_the_poster_its_mod_info_names(self):
        # 1.82.0: the Mod list shows each mod's own picture.
        mod_info(self.data / "mods" / "Lib", ["id=Lib", "name=Library", "versionMin=42.0.0", "poster=poster.png"])
        (self.data / "mods" / "Lib" / "poster.png").write_bytes(b"png")
        mods = {m.id: m for m in self.adapter.installed()}
        self.assertEqual(Path(mods["Lib"].preview).name, "poster.png")
        self.assertEqual(mods["Chem"].preview, "")
        self.assertEqual(_poster(self.data, "../outside.png"), "")

    def test_lists_ids_with_spaces_and_apostrophes(self):
        self.assertEqual(read_list(self.data / "mods" / "default.txt"), ["Chem", "Lib", "Some Workshop Mod's Name"])
        self.assertEqual([m.key for m in self.adapter.lists()], ["default", "save:Sandbox/Run 1"])

    def test_the_version_folder_not_above_the_game_is_read(self):
        self.assertEqual(info_file(self.data / "mods" / "Chem", "42.16.0").parent.name, "42.15")
        chem = next(m for m in self.adapter.installed() if m.id == "Chem")
        self.assertEqual((chem.name, [n.ids for n in chem.needs], chem.load_after),
                         ("Chemistry", [("Lib",), ("Vaccine",)], ["Lib"]))

    def test_without_the_game_installed_workshop_mods_are_not_called_missing(self):
        installed = core.Installed(self.adapter, self.adapter.installed())
        found = core.check(self.adapter, self.adapter.lists()[0], installed, {}, None, None)
        kinds = sorted(p.kind for p in found)
        self.assertEqual(kinds, ["needs", "order", "unchecked"])
        self.assertTrue(any("not installed" in n for n in self.adapter.notes()))

    def test_rendering_keeps_the_file_and_a_change_writes_the_mods_block_only(self):
        mod_list = self.adapter.lists()[0]
        text = mod_list.path.read_bytes().decode("utf-8")
        self.assertEqual(self.adapter.render(text, mod_list.ids), text)
        changed = self.adapter.render(text, ["Lib"])
        self.assertEqual(changed, ZOMBOID_LIST.format(items="    mod = Lib,\r\n"))


class Command(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.fake = FakeRimWorld(self.tmp.name, ["ludeon.rimworld", "example.hostel", "example.gone"])
        self.environ = self.fake.environ(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def run_cli(self, *argv, running=None):
        out = io.StringIO()
        code = cli.main(list(argv) + ["--json"], self.environ, out, post=lambda url, data: (200, b'{"response": {}}'),
                        running=running or (lambda names: []))
        return code, json.loads(out.getvalue()) if out.getvalue() else None

    def test_check_names_the_lists_and_problems(self):
        code, answer = self.run_cli("check", "--name", "RimWorld", "--online")
        self.assertEqual(code, 0)
        data = answer["data"]
        self.assertTrue(data["supported"] and data["online"])
        self.assertEqual([p["id"] for p in data["problems"] if p["kind"] == "missing"], ["example.gone"])
        self.assertEqual(data["lists"][0]["key"], "active")

    def test_fix_previews_then_applies_and_undo_goes_back(self):
        path = self.fake.config / "ModsConfig.xml"
        before = path.read_bytes()
        code, answer = self.run_cli("fix", "--name", "rimworld", "--list", "active", "--remove", "example.gone")
        self.assertEqual((code, answer["data"]["applied"], path.read_bytes()), (0, False, before))
        code, answer = self.run_cli("fix", "--name", "rimworld", "--list", "active", "--remove", "example.gone", "--apply")
        self.assertEqual((code, answer["data"]["removed"]), (0, ["example.gone"]))
        code, answer = self.run_cli("backups", "--name", "rimworld")
        self.assertEqual(len(answer["data"]["backups"]), 1)
        code, answer = self.run_cli("undo", "--name", "rimworld", "--list", "active", "--apply")
        self.assertEqual((code, path.read_bytes()), (0, before))

    def write(self, ids, was, *more, running=None):
        out = io.StringIO()
        code = cli.main(["write", "--name", "rimworld", "--list", "active", *more, "--json"], self.environ, out,
                        running=running or (lambda names: []), stdin=io.StringIO(json.dumps({"ids": ids, "was": was})))
        return code, json.loads(out.getvalue())

    def test_save_writes_a_whole_new_list_at_once_after_a_backup(self):
        # 1.142.0, the owner's choice "Hold until Save": moves and switches made freely, written as one change.
        path = self.fake.config / "ModsConfig.xml"
        before = path.read_bytes()
        was = ["ludeon.rimworld", "example.hostel", "example.gone"]
        new = ["ludeon.rimworld", "example.library", "example.gone", "example.hostel"]
        code, answer = self.write(new, was)
        self.assertEqual((code, answer["data"]["applied"], path.read_bytes()), (0, False, before))
        self.assertEqual((answer["data"]["on"], answer["data"]["off"]), (["example.library"], []))
        code, answer = self.write(new, was, "--apply")
        self.assertEqual((code, answer["data"]["applied"]), (0, True))
        code, answer = self.run_cli("mods", "--name", "rimworld")
        self.assertEqual([e["key"] for e in answer["data"]["lists"][0]["entries"]], new)
        code, answer = self.run_cli("undo", "--name", "rimworld", "--list", "active", "--apply")
        self.assertEqual((code, path.read_bytes()), (0, before))

    def test_save_refuses_a_list_changed_since_the_editing_began_and_what_cannot_be(self):
        path = self.fake.config / "ModsConfig.xml"
        before = path.read_bytes()
        stale = ["ludeon.rimworld", "example.gone"]
        cases = [(["ludeon.rimworld", "example.hostel"], stale, "changed since you began"),
                 (["ludeon.rimworld", "example.hostel", "example.hostel"], ["ludeon.rimworld", "example.hostel", "example.gone"],
                  "twice"),
                 (["ludeon.rimworld", "example.nowhere"], ["ludeon.rimworld", "example.hostel", "example.gone"], "not on this PC"),
                 (["ludeon.rimworld", "example.hostel", "example.gone"], ["ludeon.rimworld", "example.hostel", "example.gone"],
                  "nothing to save")]
        for ids, was, said in cases:
            code, answer = self.write(ids, was, "--apply")
            self.assertEqual((code, answer["data"]["ok"]), (cli.EXIT_REFUSED, False), said)
            self.assertIn(said, answer["data"]["refusal"])
        code, answer = self.write(["ludeon.rimworld"], ["ludeon.rimworld", "example.hostel", "example.gone"], "--apply",
                                  running=lambda names: ["RimWorld.exe"])
        self.assertIn("RimWorld.exe is running", answer["data"]["refusal"])
        self.assertEqual(path.read_bytes(), before)

    def test_a_refused_change_says_why_and_changes_nothing(self):
        code, answer = self.run_cli("fix", "--name", "rimworld", "--list", "active", "--remove", "example.gone", "--apply",
                                    running=lambda names: ["RimWorld.exe"])
        self.assertEqual((code, answer["data"]["ok"]), (1, False))
        self.assertIn("RimWorld.exe is running", answer["data"]["refusal"])

    def test_mods_names_every_mod_and_each_list_in_order(self):
        code, answer = self.run_cli("mods", "--name", "RimWorld")
        data = answer["data"]
        self.assertEqual(code, 0)
        self.assertIn("example.library", [m["key"] for m in data["mods"]])
        market = next(m for m in data["mods"] if m["key"] == "example.market")
        self.assertEqual((market["load_after"], market["incompatible"]), (["example.hostel"], ["example.rival"]))
        self.assertTrue(market["folder"].endswith("1000000001"))
        needy = next(m for m in data["mods"] if m["key"] == "example.needy")
        self.assertIn(["example.library"], needy["need_ids"])
        self.assertEqual([e["key"] for e in data["lists"][0]["entries"]], ["ludeon.rimworld", "example.hostel", "example.gone"])
        self.assertEqual(data["changes"], {"active": 0})

    def test_a_move_answers_with_the_list_as_it_now_stands(self):
        code, answer = self.run_cli("fix", "--name", "rimworld", "--list", "active", "--move", "example.gone", "--to", "1",
                                    "--apply")
        self.assertEqual((code, answer["data"]["ids"][0]), (0, "example.gone"))
        code, answer = self.run_cli("undo", "--name", "rimworld", "--list", "active", "--apply")
        self.assertEqual(answer["data"]["ids"][-1], "example.gone")

    def test_a_game_without_an_adapter_is_told_in_words(self):
        for report in ("check", "mods"):
            code, answer = self.run_cli(report, "--name", "Kenshi")
            self.assertEqual((code, answer["data"]["supported"]), (0, False))
            self.assertIn("cannot read Kenshi", answer["data"]["notes"][0])

    def test_games_by_name_or_steam_number(self):
        self.assertEqual(mod_list_game("Project Zomboid")[0], "project-zomboid")
        self.assertEqual(mod_list_game(app_id=294100)[0], "rimworld")
        self.assertIsNone(mod_list_game("Kenshi"))

    def test_the_manifest_says_what_each_report_does(self):
        reports = {r["name"]: r for r in describe("mod-list", ".mod_list_cli", "")["reports"]}
        self.assertEqual({k: (v["effect"], v["when"]) for k, v in reports.items()},
                         {"check": ("reads-online", "--online"), "fix": ("writes", "--apply"), "undo": ("writes", "--apply"),
                      "sort": ("writes", "--apply"), "rules": ("writes", "--apply"),
                      "lists": ("reads", None), "compare": ("reads", None), "load": ("writes", "--apply"),
                      "since": ("reads", None),
                      "save": ("writes", "--apply"), "forget": ("writes", "--apply"), "export": ("writes", "--apply"),
                      "subscribe": ("writes", "--apply"), "unsubscribe": ("writes", "--apply"), "write": ("writes", "--apply"),
                          "mods": ("reads", None), "databases": ("reads-online", "--fetch"), "backups": ("reads", None), "games": ("reads", None)})
        self.assertEqual(reports["check"]["surface"], "mod-list")


if __name__ == "__main__":
    unittest.main()


class Previews(unittest.TestCase):
    def test_a_rimworld_mod_names_its_about_preview_when_it_has_one(self):
        with tempfile.TemporaryDirectory() as tmp:
            about(Path(tmp) / "Boats", "a.boats", "Boats")
            about(Path(tmp) / "Oars", "a.oars", "Oars")
            (Path(tmp) / "Boats" / "About" / "Preview.png").write_bytes(b"png")
            self.assertEqual(Path(_preview(Path(tmp) / "Boats")).name, "Preview.png")
            self.assertEqual(_preview(Path(tmp) / "Oars"), "")
