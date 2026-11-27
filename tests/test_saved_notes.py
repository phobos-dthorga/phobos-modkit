"""Saved histories as seen-in-play notes (1.121.0): RimWorld's reader on copies of the hand-written fixture save, and test-pass
reading them beside the game's notes. The fixture's pawn keeps a history list (ExampleSystems_History: burning at tick 100, boiling at
tick 200); the tests plant a version ledger in the game's components.

Tests that index a save need the compiled xml-index program and skip when it is not built, as test_rimworld_save's do.
"""
import io
import json
import os
from pathlib import Path
import stat
import tempfile
import time
import unittest

from support import FIXTURES
from phobos_modkit import native, testpass, testpass_cli
from phobos_modkit.games.rimworld import saved_notes

FIXTURE = FIXTURES / "rimworld" / "Example.rws"
INDEXER = native.tool_path("xml-index")
needs_indexer = unittest.skipUnless(INDEXER.is_file(), "xml-index is not built (cargo build --release)")
LEDGER = """    <components>
      <li Class="Example.VersionLedger">
        <Example_VersionLedger>
          <li>50|Example Widgets|1.0.0</li>
          <li>150|Example Widgets|1.1.0</li>
        </Example_VersionLedger>
      </li>
    </components>
"""
SOURCE = {"name": "history", "mod": "Example Widgets", "select": {"def": "Human"}, "list": "ExampleSystems_History", "tick": "tick",
          "key": "saved.example.{stage}", "detail": "{stage} at {tick}"}
SAVED = {"saves": 2, "ledger": "Example_VersionLedger", "sources": [SOURCE]}


class Pieces(unittest.TestCase):
    def test_a_lists_items_by_field_in_save_order(self):
        rows = [("H/li[1]/tick", "200"), ("H/li[0]/tick", "100"), ("H/li[0]/stage", "burning"), ("Other/li[0]/tick", "5")]
        self.assertEqual(saved_notes.items_of(rows, "H"), [{"tick": "100", "stage": "burning"}, {"tick": "200"}])

    def test_the_version_that_ran_at_a_tick(self):
        ledger = {"Example Widgets": [(50, "1.0.0"), (150, "1.1.0")]}
        self.assertEqual([saved_notes.version_at(ledger, "Example Widgets", t) for t in (10, 50, 149, 150, 900)],
                         ["0", "1.0.0", "1.0.0", "1.1.0", "1.1.0"])
        self.assertEqual(saved_notes.version_at(ledger, "Other", 900), "0")

    def test_the_saved_section_is_checked(self):
        for broken, words in (({"sources": []}, "sources"), ({"sources": [dict(SOURCE, select={})]}, "select"),
                              ({"sources": [{k: v for k, v in SOURCE.items() if k != "key"}]}, "key"),
                              ({"sources": [dict(SOURCE, keys={"a": "b"})]}, "keyBy"),
                              ({"sources": [SOURCE], "saves": 0}, "saves")):
            with self.assertRaises(saved_notes.SavedError, msg=broken) as raised:
                saved_notes.check_config(broken)
            self.assertIn(words, str(raised.exception))


@needs_indexer
class FromSaves(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.saves, self.cache = base / "Saves", base / "cache"
        self.saves.mkdir()
        text = FIXTURE.read_text(encoding="utf-8").replace("    </scenario>\n", "    </scenario>\n" + LEDGER, 1)
        # The older save holds the first event only; the newer both, so the first is counted once, from the older save.
        older = text.replace("""              <li Class="Example.FaultEvent">
                <tick>200</tick>
                <stage>boiling</stage>
              </li>
""", "")
        self.older, self.newer = self.saves / "Older.rws", self.saves / "Newer.rws"
        self.older.write_text(older, encoding="utf-8")
        os.utime(self.older, (time.time() - 3600, time.time() - 3600))
        self.newer.write_text(text, encoding="utf-8")
        self.environ = {"PHOBOS_XML_INDEX": str(INDEXER), "RIMWORLD_SAVES_PATH": str(self.saves),
                        "PHOBOS_MODKIT_CACHE": str(self.cache)}

    def tearDown(self):
        for path in Path(self.tmp.name).rglob("*"):
            if path.is_file():
                os.chmod(path, stat.S_IREAD | stat.S_IWRITE)
        self.tmp.cleanup()

    def test_each_item_once_with_its_version_tick_and_save(self):
        notes, read = saved_notes.for_test_pass(SAVED, self.environ)
        self.assertEqual([(n["key"], n["tick"], n["version"], n["save"]) for n in notes],
                         [("saved.example.burning", 100, "1.0.0", "Older.rws"), ("saved.example.boiling", 200, "1.1.0", "Newer.rws")])
        self.assertEqual(notes[0]["on"], "Human200")
        self.assertEqual(notes[0]["detail"], "Human: burning at 100")
        self.assertEqual(read, [("Older.rws", 1, True), ("Newer.rws", 1, True)])

    def test_without_a_ledger_every_note_is_version_nought(self):
        notes, read = saved_notes.for_test_pass(dict(SAVED, ledger="Nothing_Saved"), self.environ)
        self.assertEqual({n["version"] for n in notes}, {"0"})
        self.assertFalse(any(ledger for _, _, ledger in read))

    def test_each_saves_answer_is_kept_and_used_again_until_something_changes(self):
        """1.147.1: a save's answer is kept beside its index; the same save and rules give it back without reading the save."""
        first = saved_notes.for_test_pass(SAVED, self.environ, checks_sha="")
        cache = self.cache / "rimworld-saves"
        kept = sorted(p.name for p in cache.glob(f"*{saved_notes.ANSWER_SUFFIX}"))
        self.assertEqual(kept, ["Newer.notes.sqlite", "Older.notes.sqlite"])
        original = saved_notes._read_save
        try:
            saved_notes._read_save = lambda *a, **k: self.fail("a kept answer was not used")
            self.assertEqual(saved_notes.for_test_pass(SAVED, self.environ, checks_sha=""), first)
        finally:
            saved_notes._read_save = original
        # Other rules, or a save saved again, read the save afresh.
        read = []
        saved_notes._read_save = lambda *a, **k: read.append(a[0].name) or original(*a, **k)
        try:
            saved_notes.for_test_pass(SAVED, self.environ, checks_sha="another check file")
            self.assertEqual(read, ["Older.rws", "Newer.rws"])
            read.clear()
            os.utime(self.newer, (time.time() + 5, time.time() + 5))
            saved_notes.for_test_pass(SAVED, self.environ, checks_sha="another check file")
            self.assertEqual(read, ["Newer.rws"])
        finally:
            saved_notes._read_save = original

    def test_figure_checks_with_no_digest_of_their_file_are_never_kept(self):
        """Without the check file's digest a changed check could not be told from the kept answer, so nothing is kept."""
        cache = self.cache / "rimworld-saves"
        original = saved_notes._read_save
        saved_notes._read_save = lambda *a, **k: ([], [], False)
        try:
            saved_notes.gather(SAVED, self.saves, cache, None, self.environ, None, figure_checks=["a stand-in check"],
                               checks_sha=None)
        finally:
            saved_notes._read_save = original
        self.assertEqual(list(cache.glob(f"*{saved_notes.ANSWER_SUFFIX}")), [])

    def test_test_pass_reads_them_judges_their_age_and_orders_them_by_tick(self):
        repo = Path(self.tmp.name) / "repo"
        (repo / "config").mkdir(parents=True)
        (repo / "docs").mkdir()
        (repo / "docs" / "tests.md").write_text(
            "| # | What | What passes |\n| --- | --- | --- |\n"
            "| 1 | **Boils** (Widgets 1.1.0) | It boils |\n| 2 | **Burns** (Widgets 1.1.0) | It burns |\n", encoding="utf-8")
        config = {"doc": "docs/tests.md", "game": "rimworld", "versionNames": {"Example Widgets": "Widgets"},
                  "rows": {"1": ["saved.example.boiling"], "2": ["saved.example.burning"]},
                  "order": [{"name": "boiling before burning", "row": "2", "first": "saved.example.boiling",
                             "then": "saved.example.burning"}],
                  "saved": SAVED}
        (repo / "config" / "test-evidence.json").write_text(json.dumps(config), encoding="utf-8")
        out = io.StringIO()
        code = testpass_cli.main(["report", "--root", str(repo), "--seen", str(repo / "none.jsonl"), "--verdicts",
                                  str(repo / "v.jsonl"), "--decisions", str(repo / "d.jsonl"), "--json"],
                                 environ=self.environ, out=out)
        self.assertEqual(code, 0)
        data = json.loads(out.getvalue())["data"]
        rows = {r["id"]: r for r in data["rows"]}
        self.assertEqual(rows["1"]["parts"][0]["state"], "seen")     # boiling ran on 1.1.0, the version the row names
        self.assertEqual(rows["2"]["parts"][0]["state"], "stale")    # burning ran on 1.0.0, older than the row's 1.1.0
        self.assertEqual(rows["2"]["parts"][0]["stale_version"], "1.0.0")
        self.assertEqual([o["rule"] for o in data["order_problems"]], ["boiling before burning"])
        self.assertEqual([s["save"] for s in data["saves_read"]], ["Older.rws", "Newer.rws"])
        out = io.StringIO()
        testpass_cli.main(["report", "--root", str(repo), "--seen", str(repo / "none.jsonl"), "--verdicts", str(repo / "v.jsonl"),
                           "--decisions", str(repo / "d.jsonl"), "--no-saves"], environ=self.environ, out=out)
        self.assertIn("left out (--no-saves)", out.getvalue())

    def test_figure_checks_note_each_saves_figures_for_test_pass(self):
        """1.129.0: a save check with a note gives one note per thing in each save, judged by the row's expect."""
        repo = Path(self.tmp.name) / "repo"
        (repo / "config").mkdir(parents=True)
        (repo / "docs").mkdir()
        (repo / "docs" / "tests.md").write_text(
            "| # | What | What passes |\n| --- | --- | --- |\n"
            "| 1 | **Ann shoots** (Widgets 1.1.0) | Level 8 |\n| 2 | **Ann shoots well** (Widgets 1.1.0) | Level 12 |\n",
            encoding="utf-8")
        figure = {"id": "shooting", "title": "Ann's shooting", "source": "save", "select": {"def": "Human", "class": "Pawn"},
                  "read": {"skills": "skills/skills/li[*]/def", "levels": "skills/skills/li[*]/level"},
                  "when": "contains(skills, 'Shooting')",
                  "note": {"key": "check.example.shooting", "mod": "Example Widgets", "figures": {"level": "max(levels)"}}}
        (repo / "config" / "checks.json").write_text(json.dumps({"checks": [figure]}), encoding="utf-8")
        config = {"doc": "docs/tests.md", "game": "rimworld", "versionNames": {"Example Widgets": "Widgets"},
                  "rows": {"1": [{"key": "check.example.shooting", "expect": {"level": "8..10"}}],
                           "2": [{"key": "check.example.shooting", "expect": {"level": ">= 12"}}]},
                  "saved": SAVED}
        (repo / "config" / "test-evidence.json").write_text(json.dumps(config), encoding="utf-8")
        out = io.StringIO()
        code = testpass_cli.main(["report", "--root", str(repo), "--seen", str(repo / "none.jsonl"), "--verdicts",
                                  str(repo / "v.jsonl"), "--decisions", str(repo / "d.jsonl"), "--json"],
                                 environ=self.environ, out=out)
        self.assertEqual(code, 0)
        envelope = json.loads(out.getvalue())
        rows = {r["id"]: r for r in envelope["data"]["rows"]}
        self.assertEqual(rows["1"]["parts"][0]["state"], "expected")    # level 8 in both saves, on 1.1.0
        self.assertEqual(rows["2"]["parts"][0]["state"], "off")         # never 12
        self.assertEqual([s["notes"] for s in envelope["data"]["saves_read"]], [2, 2])    # each save: its new history item and its own figure
        self.assertTrue(any("figures noted by 1 save checks" in line for line in envelope["report"]["lines"]))

    def test_a_broken_check_file_leaves_the_figures_out_and_says_why(self):
        repo = Path(self.tmp.name) / "repo"
        (repo / "config").mkdir(parents=True)
        (repo / "config" / "checks.json").write_text('{"checks": [{"id": "x"}]}', encoding="utf-8")
        figures, problem = testpass_cli.figure_checks(repo, "rimworld")
        self.assertEqual(figures, [])
        self.assertIn("left out", problem)


class NotesFromObjects(unittest.TestCase):
    def test_a_note_object_keeps_its_tick_and_source(self):
        found = testpass.note_from({"key": "k", "time": "2026-11-25T00:00:00Z", "tick": 5, "source": "save"})
        self.assertEqual((found.tick, found.source), (5, "save"))
        self.assertIsNone(testpass.note_from({"key": "k"}))
        self.assertIsNone(testpass.note_from({"key": "k", "time": "t", "tick": True}).tick)


if __name__ == "__main__":
    unittest.main()
