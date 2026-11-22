"""The mod-list sorter (1.74.0), on made-up mods and a synthetic RimWorld install. Nothing reads a real one."""
import io
import json
from pathlib import Path
import tempfile
import unittest

from phobos_modkit import mod_list as core
from phobos_modkit import mod_list_cli as cli
from phobos_modkit import mod_sort
from phobos_modkit.games.rimworld.mod_list import RimWorld, read_rimsort_rules, read_workshop_rules
from phobos_modkit.mod_list import Mod, ModList, Need

from test_mod_list import FakeRimWorld, about


class Plain:
    """The least an adapter does for the sorter: ids compared without case."""
    game = "plain"

    def key(self, mod_id):
        return mod_id.lower()

    def pick(self, candidates, listed):
        return candidates[0] if candidates else None

    def listed_id(self, mod):
        return mod.id


def mod(mod_id, after=(), before=(), needs=(), source="workshop", name=None):
    return Mod(mod_id, name or mod_id.title(), source, load_after=list(after), load_before=list(before),
               needs=[Need((n,)) for n in needs])


def sort(ids, mods, sets=(), how=mod_sort.FEWEST):
    adapter = Plain()
    installed = core.Installed(adapter, mods)
    return mod_sort.arrange(adapter, ModList("active", "Active", Path("nowhere"), list(ids)), installed, list(sets), how)


def rule_set(source, rules):
    return mod_sort.RuleSet(source, "Your rules" if source == mod_sort.YOURS else "Community", "here", rules)


class Fewest(unittest.TestCase):
    def test_a_list_that_keeps_every_rule_is_left_alone(self):
        found = sort(["a", "b", "c"], [mod("a"), mod("b", after=["a"]), mod("c")])
        self.assertEqual(found["ids"], ["a", "b", "c"])
        self.assertEqual(found["moves"], [])

    def test_one_mod_out_of_place_is_the_only_one_moved_and_why_is_said(self):
        found = sort(["b", "c", "d", "a"], [mod("a", before=["b"]), mod("b"), mod("c"), mod("d")])
        self.assertEqual(len(found["moves"]), 1)
        self.assertLess(found["ids"].index("a"), found["ids"].index("b"))
        self.assertIn("its own files", found["moves"][0]["why"][0])
        self.assertEqual(found["moves"][0]["sources"], ["own"])

    def test_the_backward_pass_moves_one_mod_where_the_forward_would_move_two(self):
        # x must be before a, and a before b: moving x up is one move; holding a and b back would be two.
        found = sort(["a", "b", "c", "x"], [mod("a", before=["b"]), mod("b"), mod("c"), mod("x", before=["a"])])
        self.assertEqual(found["ids"], ["x", "a", "b", "c"])
        self.assertEqual([m["key"] for m in found["moves"]], ["x"])

    def test_a_needed_mod_loads_first(self):
        found = sort(["a", "lib"], [mod("a", needs=["lib"]), mod("lib")])
        self.assertEqual(found["ids"], ["lib", "a"])
        self.assertEqual(found["rules"]["needs"], 1)

    def test_community_and_owner_rules_count_and_bottom_goes_last(self):
        community = rule_set(mod_sort.COMMUNITY, {"a": {"after": [("b", "a note")], "before": [], "top": None, "bottom": None},
                                                  "perf": {"after": [], "before": [], "top": None, "bottom": "last"}})
        found = sort(["perf", "a", "b", "c"], [mod("perf"), mod("a"), mod("b"), mod("c")], [community])
        self.assertEqual(found["ids"][-1], "perf")
        self.assertLess(found["ids"].index("b"), found["ids"].index("a"))
        self.assertTrue(any("a note" in w for m in found["moves"] for w in m["why"]))

    def test_top_never_goes_above_the_games_own(self):
        top = rule_set(mod_sort.YOURS, {"fast": {"after": [], "before": [], "top": "", "bottom": None}})
        mods = [mod("core", source="game"), mod("dlc", after=["core"], source="game"), mod("x"), mod("fast")]
        found = sort(["core", "dlc", "x", "fast"], mods, [top])
        self.assertEqual(found["ids"], ["core", "dlc", "fast", "x"])

    def test_a_mod_that_must_load_before_the_game_still_may(self):
        mods = [mod("harmony", before=["core"]), mod("core", source="game"), mod("x", after=["harmony"])]
        found = sort(["harmony", "core", "x"], mods, how=mod_sort.FULL)
        self.assertEqual(found["ids"], ["harmony", "core", "x"])

    def test_a_loop_sets_aside_its_weakest_rule_and_says_which(self):
        community = rule_set(mod_sort.COMMUNITY, {"a": {"after": [("b", "")], "before": [], "top": None, "bottom": None}})
        found = sort(["a", "b"], [mod("a"), mod("b", after=["a"])], [community])
        self.assertEqual(found["ids"], ["a", "b"])
        self.assertEqual(len(found["set_aside"]), 1)
        self.assertEqual(found["set_aside"][0]["source"], "community")
        self.assertIn("→", found["set_aside"][0]["loop"])

    def test_your_rule_beats_a_mods_own_in_a_loop(self):
        yours = rule_set(mod_sort.YOURS, {"a": {"after": [("b", "")], "before": [], "top": None, "bottom": None}})
        found = sort(["a", "b"], [mod("a"), mod("b", after=["a"])], [yours])
        self.assertEqual(found["ids"], ["b", "a"])
        self.assertEqual(found["set_aside"][0]["source"], "own")

    def test_a_workshop_requirement_orders_mods_and_yields_to_a_mods_own_rule(self):
        workshop = rule_set(mod_sort.WORKSHOP, {"a": {"after": [("lib", "listed")], "before": [], "top": None, "bottom": None}})
        found = sort(["a", "lib"], [mod("a"), mod("lib")], [workshop])
        self.assertEqual(found["ids"], ["lib", "a"])
        self.assertEqual(found["rules"]["workshop"], 1)
        self.assertEqual(found["moves"][0]["sources"], ["workshop"])
        looped = sort(["a", "lib"], [mod("a"), mod("lib", after=["a"])], [workshop])
        self.assertEqual(looped["ids"], ["a", "lib"])
        self.assertEqual(looped["set_aside"][0]["source"], "workshop")

    def test_a_mod_listed_twice_is_refused(self):
        with self.assertRaises(core.FixError):
            sort(["a", "b", "a"], [mod("a"), mod("b")])

    def test_a_mod_not_on_this_pc_stays_with_its_neighbours(self):
        found = sort(["a", "gone", "b"], [mod("a"), mod("b")])
        self.assertEqual(found["ids"], ["a", "gone", "b"])


class Full(unittest.TestCase):
    def test_a_full_resort_puts_the_game_first_then_names_in_order(self):
        mods = [mod("zed", name="Zed"), mod("core", source="game", name="Core"), mod("apple", name="Apple")]
        found = sort(["zed", "core", "apple"], mods, how=mod_sort.FULL)
        self.assertEqual(found["ids"], ["core", "apple", "zed"])
        self.assertTrue(any("game's own first" in w for m in found["moves"] for w in m["why"]))

    def test_mods_no_rule_places_go_in_order_of_their_names_and_say_so(self):
        found = sort(["zed", "apple"], [mod("zed", name="Zed"), mod("apple", name="Apple")], how=mod_sort.FULL)
        self.assertEqual(found["ids"], ["apple", "zed"])
        self.assertIn("order of their names", found["moves"][0]["why"][0])


class OwnRules(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "rules.json"

    def tearDown(self):
        self.tmp.cleanup()

    def test_rules_are_kept_refused_twice_and_dropped(self):
        mod_sort.add_rule(Plain(), self.path, "A", "after", "B")
        with self.assertRaises(core.FixError):
            mod_sort.add_rule(Plain(), self.path, "a", "after", "b")
        with self.assertRaises(core.FixError):
            mod_sort.add_rule(Plain(), self.path, "a", "after", "A")
        mod_sort.add_rule(Plain(), self.path, "C", "bottom")
        self.assertEqual([r["kind"] for r in mod_sort.load_own_rules(self.path)], ["after", "bottom"])
        rule_set = mod_sort.own_rule_set(Plain(), self.path)
        self.assertEqual(rule_set.rules["a"]["after"], [("B", "")])
        self.assertEqual(rule_set.rules["c"]["bottom"], "")
        mod_sort.drop_rule(self.path, 1)
        self.assertEqual(len(mod_sort.load_own_rules(self.path)), 1)
        with self.assertRaises(core.FixError):
            mod_sort.drop_rule(self.path, 5)

    def test_rimsorts_workshop_database_gives_each_mod_its_required_items_by_package_id(self):
        self.path.write_text(json.dumps({"version": 1, "database": {
            "1000": {"packageId": "X.One", "name": "One", "dependencies": {
                "2000": ["Two", "url"], "1826140": ["Biotech", "url"], "9999": ["Unknown", "url"], "1000": ["Itself", "url"]}},
            "2000": {"packageId": "x.two", "name": "Two"},
            "1826140": {"appid": True, "packageid": "ludeon.rimworld.biotech", "name": "RimWorld - Biotech"}}}),
            encoding="utf-8")
        rules = read_workshop_rules(self.path)
        self.assertEqual([other for other, _ in rules["x.one"]["after"]], ["x.two", "ludeon.rimworld.biotech"])
        self.assertIn("lists Two as required", rules["x.one"]["after"][0][1])
        self.assertNotIn("x.two", rules)
        self.assertIs(read_workshop_rules(self.path), rules)
        self.assertIsNone(read_workshop_rules(Path(self.tmp.name) / "none.json"))

    def test_rimsorts_files_are_read_with_their_notes_and_only_true_placings(self):
        self.path.write_text(json.dumps({"rules": {"x.one": {
            "loadAfter": {"x.two": {"name": ["Two"], "comment": ["why", "not"]}},
            "loadTop": {"value": True, "comment": "early"}, "loadBottom": {"comment": ""}}}}), encoding="utf-8")
        rules = read_rimsort_rules(self.path)
        self.assertEqual(rules["x.one"]["after"], [("x.two", "why; not")])
        self.assertEqual(rules["x.one"]["top"], "early")
        self.assertIsNone(rules["x.one"]["bottom"])


class SeveralAtOnce(unittest.TestCase):
    def setUp(self):
        self.list = ModList("active", "Active", Path("nowhere"), ["a", "b", "c", "d", "e"])

    def test_several_move_as_one_block_in_their_order(self):
        ids, words = core.plan(Plain(), self.list, None, core.MOVE, ["d", "b"], 1)
        self.assertEqual(ids, ["b", "d", "a", "c", "e"])
        self.assertIn("2 mods", words)

    def test_several_switch_off_together(self):
        ids, _ = core.plan(Plain(), self.list, None, core.REMOVE, ["a", "e"])
        self.assertEqual(ids, ["b", "c", "d"])

    def test_several_switch_on_at_a_place(self):
        installed = core.Installed(Plain(), [mod("f"), mod("g")])
        ids, _ = core.plan(Plain(), self.list, installed, core.ENABLE, ["f", "g"], 2)
        self.assertEqual(ids, ["a", "f", "g", "b", "c", "d", "e"])

    def test_a_block_already_there_is_refused(self):
        with self.assertRaises(core.FixError):
            core.plan(Plain(), self.list, None, core.MOVE, ["a", "b"], 1)


class Command(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.fake = FakeRimWorld(self.tmp.name, ["example.market", "ludeon.rimworld", "example.hostel"])
        self.environ = self.fake.environ(self.tmp.name)
        rimsort = Path(self.environ["PHOBOS_RIMSORT"]) / "dbs"
        rimsort.mkdir(parents=True)
        (rimsort / "userRules.json").write_text(json.dumps({"rules": {"example.hostel": {"loadTop": {"value": True}}}}),
                                                encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def run_cli(self, *argv):
        out = io.StringIO()
        code = cli.main(list(argv) + ["--json"], self.environ, out, running=lambda names: [])
        return code, json.loads(out.getvalue())["data"]

    def test_sort_previews_then_writes_with_a_backup_that_undo_takes_back(self):
        code, data = self.run_cli("sort", "--name", "RimWorld", "--list", "active")
        self.assertEqual(code, 0)
        self.assertEqual(data["ids"], ["ludeon.rimworld", "example.hostel", "example.market"])
        self.assertFalse(data["applied"])
        self.assertEqual(RimWorld(self.environ).lists()[0].ids, ["example.market", "ludeon.rimworld", "example.hostel"])
        code, data = self.run_cli("sort", "--name", "RimWorld", "--list", "active", "--apply")
        self.assertTrue(data["applied"])
        self.assertEqual(RimWorld(self.environ).lists()[0].ids, ["ludeon.rimworld", "example.hostel", "example.market"])
        code, _ = self.run_cli("undo", "--name", "RimWorld", "--list", "active", "--apply")
        self.assertEqual(code, 0)
        self.assertEqual(RimWorld(self.environ).lists()[0].ids, ["example.market", "ludeon.rimworld", "example.hostel"])

    def test_rules_are_listed_kept_and_dropped(self):
        code, data = self.run_cli("rules", "--name", "RimWorld")
        self.assertEqual(code, 0)
        self.assertEqual([r["words"] for r in data["theirs"]], ["example.hostel loads at the top"])
        code, data = self.run_cli("rules", "--name", "RimWorld", "--mod", "example.market", "--before", "example.hostel",
                                  "--apply")
        self.assertTrue(data["applied"])
        self.assertEqual(data["rules"][0]["words"], "example.market loads before example.hostel")
        code, data = self.run_cli("rules", "--name", "RimWorld", "--drop", "1", "--apply")
        self.assertEqual(data["rules"], [])

    def test_several_moves_from_the_command(self):
        about(self.fake.workshop / "1000000004", "example.library", "Library")
        code, data = self.run_cli("fix", "--name", "RimWorld", "--list", "active", "--move", "example.hostel", "--move",
                                  "example.market", "--to", "1", "--apply")
        self.assertEqual(code, 0)
        self.assertEqual(data["ids"], ["example.market", "example.hostel", "ludeon.rimworld"])


if __name__ == "__main__":
    unittest.main()
