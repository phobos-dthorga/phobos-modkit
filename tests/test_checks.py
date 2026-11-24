"""Checks (1.119.0): the game-free engine, RimWorld's save checks on the hand-written fixture save, and live checks over a
stand-in heap reader (1.120.0; test_heap_reader runs them on a real snapshot).

Save tests need the compiled xml-index program and skip when it is not built, as test_rimworld_save's do.
"""
import io
import json
import os
from pathlib import Path
import shutil
import stat
import tempfile
import unittest

from support import FIXTURES
from phobos_modkit import checks
from phobos_modkit import checks_live
from phobos_modkit import native
from phobos_modkit.games.rimworld import save as saves
from phobos_modkit.games.rimworld import save_checks
from phobos_modkit.games.rimworld.save_cli import EXIT_OK, EXIT_USAGE, main
from phobos_modkit.report import render_markdown

FIXTURE = FIXTURES / "rimworld" / "Example.rws"
HAVE_INDEXER = native.tool_path("xml-index").is_file()
needs_indexer = unittest.skipUnless(HAVE_INDEXER, "xml-index is not built (cargo build --release)")
ONLY_INDEXER = {"PHOBOS_XML_INDEX": str(native.tool_path("xml-index"))}


def rule(**fields):
    entry = {"id": "a", "title": "A rule", "source": "save", "select": {"def": "Human"}, "read": {"x": "x"}, "fault": "x > 1"}
    entry.update(fields)
    return checks.parse_check(entry, "test")


class Values(unittest.TestCase):
    def test_numbers_flags_and_text(self):
        self.assertEqual(checks.value_of("75"), 75)
        self.assertEqual(checks.value_of("0.993"), 0.993)
        self.assertEqual(checks.value_of("-2"), -2)
        self.assertEqual(checks.value_of("True"), True)
        self.assertEqual(checks.value_of("Steel"), "Steel")
        self.assertEqual(checks.value_of(["1", "x", None]), [1, "x", None])
        self.assertTrue(checks.FUNCTIONS["isnan"](checks.value_of("NaN")))
        self.assertTrue(checks.FUNCTIONS["isnan"](checks.value_of(["1", "-Infinity"])))
        self.assertFalse(checks.FUNCTIONS["isnan"](checks.value_of(["1", "2"])))


class Expressions(unittest.TestCase):
    def test_what_the_language_does(self):
        e = checks.Expression("sum(stacks) > 300 and count(orders) < 6")
        self.assertTrue(e({"stacks": [75] * 13, "orders": ["a"] * 5}))
        self.assertFalse(e({"stacks": [75, 2], "orders": []}))
        self.assertEqual(checks.Expression("max(a) - min(a)")({"a": [3, 9, 4]}), 6)
        self.assertEqual(checks.Expression("unique(a)")({"a": ["Steel", "Steel", "Cloth"]}), ["Steel", "Cloth"])
        self.assertEqual(checks.Expression("x / y")({"x": 1, "y": 0}), None)
        self.assertTrue(checks.Expression("contains(k, 'Steel')")({"k": ["Cloth", "Steel"]}))
        self.assertEqual(checks.Expression("'big' if x > 2 else 'small'")({"x": 3}), "big")

    def test_a_missing_value_never_makes_a_fault_by_comparing(self):
        self.assertFalse(checks.Expression("x > 1")({"x": None}))
        self.assertFalse(checks.Expression("x < 1")({}))
        self.assertTrue(checks.Expression("x == None")({}))
        self.assertFalse(checks.Expression("x > 1")({"x": "text"}))

    def test_anything_that_could_run_code_is_refused(self):
        for text in ("__import__('os')", "x.real", "open('f')", "[a for a in b]", "lambda: 1", "x[0]", "f(**k)", "sum(x, start=1)"):
            with self.assertRaises(checks.CheckError, msg=text):
                checks.Expression(text, "test")

    def test_a_bad_expression_says_where(self):
        with self.assertRaises(checks.CheckError) as raised:
            checks.Expression("x >", "checks.json, check 3")
        self.assertIn("checks.json, check 3", str(raised.exception))


class Parsing(unittest.TestCase):
    def test_a_rule_names_only_what_it_reads(self):
        with self.assertRaises(checks.CheckError) as raised:
            rule(fault="y > 1")
        self.assertIn("names y", str(raised.exception))
        self.assertEqual(rule(fault="id == 'x' or label == 'y'").fault.names, ["id", "label"])

    def test_required_fields_and_choices(self):
        for broken, words in (({"source": "disk"}, "source"), ({"level": "bad"}, "level"), ({"fault": ""}, "fault"),
                              ({"kind": "numbers"}, "kind"), ({"read": {"sum": "x"}}, "cannot name"),
                              ({"read": {"x": 3}}, "read")):
            with self.assertRaises(checks.CheckError, msg=broken) as raised:
                rule(**broken)
            self.assertIn(words, str(raised.exception))
        self.assertEqual(checks.parse_check({"id": "n", "title": "N", "source": "save", "kind": "numbers"}, "t",
                                            ("numbers",)).kind, "numbers")

    def test_a_file_by_source_and_its_faults(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "checks.json"
            path.write_text(json.dumps({"checks": [
                {"id": "a", "title": "A", "source": "save", "read": {"x": "x"}, "fault": "x"},
                {"id": "b", "title": "B", "source": "live", "read": {"x": "x"}, "fault": "x"}]}), encoding="utf-8")
            self.assertEqual([c.id for c in checks.load_checks(path, "live")], ["b"])
            self.assertEqual(len(checks.load_checks(path)), 2)
            path.write_text(json.dumps({"checks": [{"id": "a", "title": "A", "source": "save", "read": {"x": "x"}, "fault": "x"}] * 2}),
                            encoding="utf-8")
            with self.assertRaises(checks.CheckError):
                checks.load_checks(path)
            with self.assertRaises(checks.CheckError):
                checks.load_checks(Path(tmp) / "none.json")


class Judging(unittest.TestCase):
    def test_findings_sentences_and_the_report(self):
        check = rule(read={"stacks": "s", "kinds": "k"}, fault="sum(stacks) > 300", level="look",
                     says="{sum(stacks)} laid out ({unique(kinds)})", row="513", why="The store keeps only what work needs.")
        rows = [checks.Row("HEMTT1", "HEMTT1, map 0", {"stacks": ["75"] * 13, "kinds": ["Steel"] * 13}),
                checks.Row("Truck2", "Truck2, map 0", {"stacks": ["20"], "kinds": ["Steel"]})]
        result = checks.judge(check, rows)
        self.assertEqual(result.read, 2)
        self.assertEqual([f.text for f in result.findings], ["975 laid out (Steel)"])
        text = render_markdown(checks.report("Save checks", [result, checks.Result(rule(id="b"), problem="no select")]))
        self.assertIn("Worth a look: A rule", text)
        self.assertIn("Test row 513.", text)
        self.assertIn("Could not run", text)
        data = checks.data([result])
        self.assertEqual((data["faults"], data["looks"]), (0, 1))

    def test_when_narrows_what_a_rule_applies_to(self):
        check = rule(read={"x": "x", "kind": "k"}, when="kind == 'Truck'", fault="x > 1")
        rows = [checks.Row("a", "a", {"x": "5", "kind": "Car"}), checks.Row("b", "b", {"x": "5", "kind": "Truck"})]
        self.assertEqual([f.row.id for f in checks.judge(check, rows).findings], ["b"])


class Paths(unittest.TestCase):
    def test_wildcards_within_and_across_steps(self):
        rows = [("a/li[0]/stackCount", "75"), ("a/li[1]/stackCount", "2"), ("a/li[1]/x/stackCount", "9"), ("b", "1")]
        found = save_checks.read_values(rows, {"one": "a/li[*]/stackCount", "deep": "a/**/stackCount", "b": "b", "gone": "c"})
        self.assertEqual(found, {"one": ["75", "2"], "deep": ["75", "2", "9"], "b": "1", "gone": None})


@needs_indexer
class SaveChecks(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.saves = Path(self.tmp.name) / "Saves"
        self.cache = Path(self.tmp.name) / "cache"
        self.saves.mkdir()
        self.save = self.saves / "Example.rws"
        self.checks = Path(self.tmp.name) / "checks.json"

    def tearDown(self):
        for path in Path(self.tmp.name).rglob("*"):
            if path.is_file():
                os.chmod(path, stat.S_IREAD | stat.S_IWRITE)
        self.tmp.cleanup()

    def write(self, *entries, change=()):
        text = FIXTURE.read_text(encoding="utf-8")
        for old, new in change:
            self.assertIn(old, text)
            text = text.replace(old, new)
        self.save.write_text(text, encoding="utf-8")
        self.checks.write_text(json.dumps({"checks": list(entries)}), encoding="utf-8")

    def run_main(self, *args):
        out = io.StringIO()
        code = main(["checks", "--saves", str(self.saves), "--cache", str(self.cache), "--checks", str(self.checks), *args],
                    environ=ONLY_INDEXER, out=out)
        return code, out.getvalue()

    def test_a_rule_reads_a_held_things_stack_from_the_index(self):
        self.write({"id": "carry", "title": "Nobody carries meals", "source": "save", "select": {"class": "Pawn", "def": "Human"},
                    "read": {"stacks": "inventory/innerContainer/innerList/li[*]/stackCount",
                             "kinds": "inventory/innerContainer/innerList/li[*]/def"},
                    "fault": "sum(stacks) > 1", "says": "{sum(stacks)} of {unique(kinds)}"})
        code, text = self.run_main()
        self.assertEqual(code, EXIT_OK)
        self.assertIn("Human200, map 0 at 20, 21 | 2 of MealSimple", text)

    def test_nan_and_dangling_references_are_found(self):
        self.write({"id": "numbers", "title": "No NaN", "source": "save", "kind": "numbers", "select": {"def": "Human"},
                    "paths": "Example**"},
                   {"id": "refs", "title": "References hold", "source": "save", "kind": "references", "select": {"def": "Human"},
                    "paths": "jobs/**"},
                   change=(("<li>0.993</li>", "<li>NaN</li>"), ("<thing>Thing_Steel101</thing>", "<thing>Thing_Steel999</thing>")))
        code, text = self.run_main("--json")
        self.assertEqual(code, EXIT_OK)
        found = {c["id"]: c["findings"] for c in json.loads(text)["data"]["checks"]}
        self.assertIn("ExampleSystems_Values[Electrical/charge]", found["numbers"][0]["text"])
        self.assertIn("jobs/curJob/thing = Thing_Steel999", found["refs"][0]["text"])
        self.assertNotIn("targetA", found["refs"][0]["text"])

    def test_the_fixture_as_written_is_clean(self):
        self.write({"id": "numbers", "title": "No NaN", "source": "save", "kind": "numbers", "select": {"def": "Human"},
                    "paths": "**"},
                   {"id": "refs", "title": "References hold", "source": "save", "kind": "references", "select": {"def": "Human"},
                    "paths": "jobs/**"})
        code, text = self.run_main()
        self.assertIn("2 found nothing", text)

    def test_a_check_with_no_select_cannot_run_and_says_why(self):
        self.write({"id": "all", "title": "Everything", "source": "save", "read": {"x": "def"}, "fault": "x == 'Steel'"})
        code, text = self.run_main()
        self.assertEqual(code, EXIT_OK)
        self.assertIn("Could not run", text)
        self.assertIn("reading every thing would take minutes", text)

    def test_a_broken_file_is_a_usage_error(self):
        self.write({"id": "x", "title": "X", "source": "save", "read": {"x": "x"}, "fault": "open('f')"})
        self.assertEqual(self.run_main()[0], EXIT_USAGE)


def live(**fields):
    entry = {"id": "store", "title": "A store holds no more than its work asks", "source": "live",
             "select": {"type": "Phobos.Store"}, "read": {"held": "held.innerList[].stackCount", "orders": "orders#"},
             "fault": "sum(held) > 100 and orders == 0", "says": "{sum(held)} held for no orders"}
    entry.update(fields)
    return checks.parse_check(entry, "test")


class LiveChecks(unittest.TestCase):
    def test_one_snapshot_answers_every_check_in_order(self):
        asked = []

        def reader(pid, folder, requests, describe, environ):
            asked.append(requests)
            first = {"ok": True, "data": {"type": "Phobos.Store", "count": 3, "take": 2, "more": True, "itemLimit": 1000,
                                          "items": [{"address": "0x1", "summary": "HEMTT 1", "values": {
                                              "held.innerList[].stackCount": ["75", "75"], "orders#": 0}},
                                                    {"address": "0x2", "summary": "", "type": "Phobos.Store", "cut": True,
                                                     "values": {"held.innerList[].stackCount": ["5"], "orders#": 0}}]}}
            return {"pid": pid, "snapshotMs": 440}, [first, {"ok": False, "error": "Unknown type"}]

        broken = live(id="broken", select={"name": "x"})
        ready, results = checks_live.run(7, "game", [live(), live(id="second", select={"type": "Other"}), broken], ("Name",),
                                         None, reader)
        self.assertEqual(len(asked), 1)
        self.assertEqual(asked[0][0], {"op": "values", "type": "Phobos.Store", "paths": ["held.innerList[].stackCount", "orders#"],
                                       "subclasses": False})
        self.assertEqual([r.check.id for r in results], ["store", "second", "broken"])
        store, second, broken_result = results
        self.assertEqual([(f.row.label, f.text) for f in store.findings], [("HEMTT 1", "150 held for no orders")])
        self.assertEqual(len(store.limits), 2)
        self.assertIn("first 2 of 3", store.limits[0])
        self.assertEqual(second.problem, "Unknown type")
        self.assertIn("select takes type", broken_result.problem)
        self.assertEqual(ready["snapshotMs"], 440)

    def test_no_snapshot_is_taken_when_no_check_can_ask(self):
        def reader(*args):
            raise AssertionError("no snapshot should be taken")
        _, results = checks_live.run(7, "game", [live(select={})], (), None, reader)
        self.assertIn("needs \"type\"", results[0].problem)


if __name__ == "__main__":
    unittest.main()
