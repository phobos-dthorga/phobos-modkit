"""The shared report model: every block renders to Markdown and JSON, and redaction reaches every piece of text."""
import json
import unittest

import support  # noqa: F401
from phobos_modkit.report import (Bullets, Code, Report, Table, home_redactor, render_json, render_markdown)

HOME = r"C:\Users\tester"


def sample():
    report = Report(r"Report for C:\Users\tester")
    report.lines += ["First line.", r"Read from C:\Users\tester\file."]
    report.blocks.append("An opening paragraph.")
    report.section("Table", Table(["Name", "Count", "Note"],
                                  [("a|b", 12345, r"C:\Users\tester\x"), ("c", 7, None)], total=40,
                                  widths={2: 6}))
    report.section("List", Bullets(["one", r"two in C:\Users\tester"]))
    report.section("Sub", Code([r"at C:\Users\tester\Mod.dll", "line two"]), level=3)
    report.section("Empty", Table(["A"], []))
    report.section("Nothing at all")
    return report


class Markdown(unittest.TestCase):
    def setUp(self):
        self.text = render_markdown(sample(), home_redactor(HOME))

    def test_layout(self):
        lines = self.text.splitlines()
        self.assertEqual(lines[:5], ["# Report for ~", "", "First line.", r"Read from ~\file.", ""])
        self.assertIn("### Sub", lines)
        self.assertEqual(self.text.count("```"), 2)

    def test_tables_escape_pipes_format_numbers_cut_cells_and_say_when_rows_were_cut(self):
        self.assertIn(r"| a\|b | 12,345 | ~\x |", self.text)
        self.assertIn("| c | 7 |  |", self.text)
        self.assertIn("Showing 2 of 40; raise --top to see more.", self.text)

    def test_empty_tables_and_sections_say_none(self):
        self.assertEqual(self.text.count("None."), 2)

    def test_redaction_reaches_every_block(self):
        self.assertNotIn("tester", self.text)

    def test_widths_cut_long_cells(self):
        report = Report("t")
        report.section("s", Table(["x"], [("abcdefghij",)], widths={0: 4}))
        self.assertIn("| abcd... |", render_markdown(report))


class Json(unittest.TestCase):
    def test_every_block_has_a_type_and_redaction_applies(self):
        data = json.loads(json.dumps(render_json(sample(), home_redactor(HOME))))
        self.assertEqual(data["format"], 1)
        self.assertEqual([b["type"] for s in data["sections"] for b in s["blocks"]],
                         ["table", "bullets", "code", "table"])
        table = data["sections"][0]["blocks"][0]
        self.assertEqual((table["total"], table["rows"][0][1]), (40, 12345))
        self.assertNotIn("tester", json.dumps(data))

    def table_values(self, rows):
        report = Report("t")
        report.section("s", Table(["a"], rows))
        return render_json(report)["sections"][0]["blocks"][0]["values"]

    def test_numbers_are_given_for_sorting(self):
        self.assertEqual(self.table_values([("1,234",), ("5",), (7,), (2.5,)]), [[1234.0], [5.0], [7], [2.5]])

    def test_percentages_and_signs_are_numbers(self):
        self.assertEqual(self.table_values([("12.5%",), ("+0.6%",), ("-3%",)]), [[12.5], [0.6], [-3.0]])

    def test_empty_cells_do_not_spoil_a_column(self):
        self.assertEqual(self.table_values([("5",), ("",), (None,)]), [[5.0], [None], [None]])

    def test_one_word_makes_a_column_text(self):
        self.assertEqual(self.table_values([("5",), ("some",)]), [[None], [None]])

    def test_mixed_units_cannot_be_compared(self):
        self.assertEqual(self.table_values([("5 MB",), ("900 KB",)]), [[None], [None]])

    def test_things_that_only_look_numeric_stay_text(self):
        self.assertEqual(self.table_values([("1.2.0",), ("9 Nov 2026",)]), [[None], [None]])

    def test_true_and_false_are_not_numbers(self):
        self.assertEqual(self.table_values([(True,), (False,)]), [[None], [None]])

    def test_a_table_with_no_rows_has_no_values(self):
        self.assertEqual(self.table_values([]), [])

    def test_unknown_blocks_are_refused(self):
        report = Report("t")
        report.section("s", 42)
        with self.assertRaises(TypeError):
            render_markdown(report)


class Sections(unittest.TestCase):
    def test_a_section_finds_its_first_table(self):
        report = Report("t")
        table = Table(["x"], [(1,)])
        section = report.section("s", "words", table)
        self.assertIs(section.table, table)
        self.assertIsNone(report.section("none", "words").table)


if __name__ == "__main__":
    unittest.main()
