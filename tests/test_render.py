"""Reports: the Markdown summary, one signature in full, and JSON."""
import json
import unittest

from support import fixture_text
from phobos_modkit.games.rimworld import log as rimworld_log
from phobos_modkit.logs import render
from phobos_modkit.logs.triage import build_report

HOME = r"C:\Users\tester"


def report():
    current = rimworld_log.parse(fixture_text("rimworld/player-1.7.log"), "Player.log")
    previous = rimworld_log.parse(fixture_text("rimworld/player-prev-1.7.log"), "Player-prev.log")
    return build_report(current, previous)


class Markdown(unittest.TestCase):
    def setUp(self):
        self.report = report()
        self.text = render.to_markdown(self.report, redact=render.home_redactor(HOME))

    def test_sections_in_order(self):
        positions = [self.text.index(h) for h in ("## Notices", "## Counts", "## Signatures",
                                                  "## One exception, several messages",
                                                  "## Compared with Player-prev.log", "## Reading this")]
        self.assertEqual(positions, sorted(positions))

    def test_header_line_names_the_game_version_and_start(self):
        self.assertIn("RimWorld 1.7.9999.1, started 2026-01-02 10:00:00.000 +00:00.", self.text)

    def test_every_listed_signature_has_its_id(self):
        for g in self.report.groups:
            if g.level in render.DEFAULT_LEVELS:
                self.assertIn(f"| {g.id} |", self.text)

    def test_info_is_counted_but_not_listed(self):
        self.assertIn("| INFO |", self.text)
        self.assertNotIn("Engine starting.", self.text)

    def test_home_folder_is_redacted_and_pipes_escaped(self):
        self.assertNotIn(HOME, self.text)
        self.assertIn(r"~\AppData\LocalLow\Example\settings.xml \| using defaults", self.text)

    def test_one_mod_is_named_once_by_its_strongest_clue(self):
        row = next(line for line in self.text.splitlines() if "Example_First" in line and line.startswith("|"))
        self.assertIn("Example Patches (source); workshop:1111111111 (file); XmlExtensions (caller)", row)

    def test_comparison_lists_new_and_gone(self):
        self.assertIn("Example error that the next run no longer has.", self.text)
        self.assertIn("### New", self.text)

    def test_rendering_is_repeatable(self):
        self.assertEqual(self.text, render.to_markdown(report(), redact=render.home_redactor(HOME)))


class Detail(unittest.TestCase):
    def test_one_signature_in_full_with_its_siblings(self):
        r = report()
        alice = next(g for g in r.groups if "for Alice" in g.example.headline)
        bob = next(g for g in r.groups if "for Bob" in g.example.headline)
        text = render.group_detail(r, alice)
        self.assertIn(f"# Signature {alice.id}", text)
        self.assertIn("ERROR [Verse], 2 times", text)
        self.assertIn(f"The same exception also starts: {bob.id}.", text)
        self.assertIn("in ExampleWidgets.dll:token", text)
        self.assertIn("| finalizer | example.rescue |", text)

    def test_long_bodies_are_cut(self):
        r = report()
        g = r.groups[0]
        text = render.group_detail(r, g, max_lines=1)
        if len(g.example.body) > 1:
            self.assertIn("more lines", text)


class Json(unittest.TestCase):
    def test_complete_and_serialisable(self):
        data = json.loads(json.dumps(render.to_json(report(), redact=render.home_redactor(HOME))))
        self.assertEqual(data["format"], render.JSON_FORMAT)
        self.assertEqual(data["log"]["messages"], 18)
        self.assertEqual(len(data["clusters"]), 1)
        self.assertEqual(data["comparison"]["previous"], "Player-prev.log")
        self.assertNotIn(HOME, json.dumps(data))
        kinds = {n["kind"] for n in data["notices"]}
        self.assertIn("save-loaded", kinds)


class Redaction(unittest.TestCase):
    def test_either_slash_and_any_case(self):
        redact = render.home_redactor(HOME)
        self.assertEqual(redact(r"c:\users\TESTER\x and C:/Users/tester/y"), r"~\x and ~/y")

    def test_a_root_home_redacts_nothing(self):
        self.assertEqual(render.home_redactor("/")("/etc/x"), "/etc/x")


if __name__ == "__main__":
    unittest.main()
