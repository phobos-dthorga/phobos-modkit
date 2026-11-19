"""decisions: the owner's open questions from config/decisions.json, and their answers (1.45.0)."""
import io
import json
from pathlib import Path
import tempfile
import unittest

import support  # noqa: F401  (puts the package on the path)
from phobos_modkit import decisions

SAMPLE = {"schemaVersion": 1, "decisions": [
    {"id": "page-keys", "question": "Renumber the page keys?", "context": "The bar is grouped now.",
     "options": [{"id": "renumber", "label": "Renumber them"}, {"id": "keep", "label": "Keep them"}],
     "lean": "renumber", "why": "They would match the bar", "from": "docs/design-record.md", "asked": "2026-11-19"},
    {"id": "stale-days", "question": "How old before Home speaks up?",
     "options": [{"id": "seven", "label": "Seven days"}, {"id": "three", "label": "Three days"}]}]}


class DecisionsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "sample-repo"
        (self.root / "config").mkdir(parents=True)
        self.write(SAMPLE)
        self.environ = {"PHOBOS_DECISIONS": str(Path(self.temp.name) / "answers")}

    def tearDown(self):
        self.temp.cleanup()

    def write(self, data):
        (self.root / "config" / "decisions.json").write_text(json.dumps(data), encoding="utf-8")

    def test_answers_go_to_one_file_per_repository(self):
        self.assertEqual(decisions.answers_file(self.root, self.environ).name, "sample-repo.jsonl")

    def test_open_first_and_the_last_answer_decides(self):
        self.assertEqual([d["answer"] for d in decisions.listed(self.root, self.environ)], [None, None])
        decisions.answer(self.root, "page-keys", "keep", environ=self.environ)
        decisions.answer(self.root, "page-keys", "renumber", "but keep G for Logs", environ=self.environ)
        found = decisions.listed(self.root, self.environ)
        self.assertEqual(found[0]["id"], "stale-days")
        self.assertEqual(found[1]["answer"]["option"], "renumber")
        self.assertEqual(found[1]["answer"]["words"], "but keep G for Logs")

    def test_other_needs_words_and_unknowns_are_refused(self):
        with self.assertRaises(decisions.DecisionError):
            decisions.answer(self.root, "page-keys", "other", environ=self.environ)
        decisions.answer(self.root, "page-keys", "other", "letters only", environ=self.environ)
        with self.assertRaises(decisions.DecisionError):
            decisions.answer(self.root, "page-keys", "maybe", environ=self.environ)
        with self.assertRaises(decisions.DecisionError):
            decisions.answer(self.root, "no-such", "keep", environ=self.environ)

    def test_a_malformed_config_is_refused_with_its_reason(self):
        for broken in ({"decisions": [{"id": "Bad Id", "question": "q", "options": [{"id": "a"}, {"id": "b"}]}]},
                       {"decisions": [{"id": "one", "question": "q", "options": [{"id": "a"}]}]},
                       {"decisions": [{"id": "one", "question": "q", "options": [{"id": "a"}, {"id": "b"}], "lean": "c"}]},
                       {"decisions": [{"id": "one", "question": "", "options": [{"id": "a"}, {"id": "b"}]}]}):
            self.write(broken)
            with self.assertRaises(decisions.DecisionError):
                decisions.read_config(self.root)

    def test_no_config_is_no_decisions(self):
        (self.root / "config" / "decisions.json").unlink()
        self.assertEqual(decisions.listed(self.root, self.environ), [])

    def test_command_line(self):
        out = io.StringIO()
        self.assertEqual(decisions.main(["list", "--root", str(self.root), "--json"], out, self.environ), 0)
        data = json.loads(out.getvalue())["data"]
        self.assertEqual(data["waiting"], 2)
        out = io.StringIO()
        code = decisions.main(["answer", "--root", str(self.root), "--id", "page-keys", "--option", "nope", "--json"],
                              out, self.environ)
        self.assertEqual(code, decisions.EXIT_REFUSED)
        self.assertFalse(json.loads(out.getvalue())["data"]["ok"])
        out = io.StringIO()
        decisions.main(["answer", "--root", str(self.root), "--id", "page-keys", "--option", "keep"], out, self.environ)
        out = io.StringIO()
        decisions.main(["list", "--root", str(self.root)], out, self.environ)
        self.assertIn("ANSWERED Keep them", out.getvalue())


if __name__ == "__main__":
    unittest.main()
