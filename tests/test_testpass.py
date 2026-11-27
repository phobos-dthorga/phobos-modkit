"""test-pass: the test list, the game's seen-in-play notes and the owner's verdicts. Every file here is written by hand."""
import io
import json
from pathlib import Path
import tempfile
import unittest

import support  # noqa: F401  (puts the package on the path)
from phobos_modkit import testpass, testpass_cli

DOC = """# In-game test pass

## The ones that matter

| # | What it proves | What to do | What passes |
| --- | --- | --- | --- |
| 1 | **A thrown track** (Framework 0.115.0) | Destroy a track | The tank stops |
| 2 | **Turret power** | Flatten the battery | It turns by hand. **Passed: the owner, 10 Nov 2026** |
| 3 | **Headlights** | Night | Lit. **Headlights light the ground: passed, the owner, 13 Nov 2026** |
| 4 | **A pipe with a \\| in it** | Look | Fine |

## If play brings them up

| # | What | When it comes up | What passes |
| --- | --- | --- | --- |
| P1 | **The Harrier** | A battle | It flies |

Some text after.
"""

CONFIG = {"doc": "docs/test-pass.md", "rows": {"1": ["vehicles.track-thrown"], "2": ["vehicles.turret-hand-cranked"],
                                              "P1": ["harrier.sortie"]}, "prefixes": {}}


def note(key, time, version="0.118.0", detail="M1A2"):
    return json.dumps({"format": 1, "time": time, "key": key, "mod": "D'thorga Framework", "version": version, "detail": detail})


def verdict(row, word, time, note=""):
    return json.dumps({"format": 1, "time": time, "row": row, "verdict": word, "note": note})


class Repo:
    def __init__(self, seen=(), verdicts=(), config=CONFIG):
        self.folder = tempfile.TemporaryDirectory()
        self.root = Path(self.folder.name)
        (self.root / "config").mkdir()
        (self.root / "docs").mkdir()
        (self.root / "config" / "test-evidence.json").write_text(json.dumps(config), encoding="utf-8")
        (self.root / "docs" / "test-pass.md").write_text(DOC, encoding="utf-8")
        self.seen = self.root / "seen.jsonl"
        self.seen.write_text("\n".join(seen) + "\n", encoding="utf-8")
        self.verdicts = self.root / "verdicts.jsonl"
        self.verdicts.write_text("\n".join(verdicts) + "\n", encoding="utf-8")

    def evidence(self):
        return testpass.gather(self.root, [self.seen], [self.verdicts])

    def run(self, *argv):
        out = io.StringIO()
        code = testpass_cli.main([argv[0], "--root", str(self.root), "--seen", str(self.seen),
                                  "--verdicts", str(self.verdicts), *argv[1:]], environ={}, out=out)
        return code, out.getvalue()

    def doc(self):
        return (self.root / "docs" / "test-pass.md").read_text(encoding="utf-8")

    def close(self):
        self.folder.cleanup()


class Parsing(unittest.TestCase):
    def test_rows_come_from_every_table_with_a_hash_column(self):
        rows = testpass.parse_rows(DOC)
        self.assertEqual([r.id for r in rows], ["1", "2", "3", "4", "P1"])
        self.assertEqual(rows[4].section, "If play brings them up")

    def test_the_title_is_the_first_bold_text(self):
        self.assertEqual(testpass.parse_rows(DOC)[0].title, "A thrown track")

    def test_an_escaped_bar_stays_in_its_cell(self):
        row = testpass.parse_rows(DOC)[3]
        self.assertEqual(len(row.cells), 4)
        self.assertIn("\\|", row.cells[1])

    def test_status_reads_the_last_cell(self):
        self.assertEqual([r.status for r in testpass.parse_rows(DOC)], ["open", "passed", "partial", "open", "open"])

    def test_the_last_marker_wins(self):
        row = testpass.Row("9", "", [], ["9", "x", "y", "**Passed: the owner, 1 Nov** then **Failed: the owner, 2 Nov**"], 0)
        self.assertEqual(row.status, "failed")


class Evidence(unittest.TestCase):
    def test_a_row_seen_working_waits_for_the_owner(self):
        repo = Repo(seen=[note("vehicles.track-thrown", "2026-11-17T10:00:00Z")])
        try:
            evidence = repo.evidence()
            row = evidence.rows[0]
            self.assertEqual(evidence.pending(row),
                             "**Seen working by the game, 17 Nov 2026 (D'thorga Framework 0.118.0); awaiting the owner's word.**")
        finally:
            repo.close()

    def test_a_passed_row_is_not_marked_seen(self):
        repo = Repo(seen=[note("vehicles.turret-hand-cranked", "2026-11-17T10:00:00Z")])
        try:
            self.assertIsNone(repo.evidence().pending(repo.evidence().rows[1]))
        finally:
            repo.close()

    def test_the_latest_verdict_wins_and_cleared_removes_it(self):
        repo = Repo(verdicts=[verdict("1", "passed", "2026-11-17T10:00:00Z"), verdict("1", "failed", "2026-11-17T11:00:00Z", "stuck"),
                              verdict("P1", "passed", "2026-11-17T10:00:00Z"), verdict("P1", "cleared", "2026-11-17T12:00:00Z")])
        try:
            verdicts = repo.evidence().verdicts
            self.assertEqual(verdicts["1"].verdict, "failed")
            self.assertNotIn("P1", verdicts)
        finally:
            repo.close()

    def test_unreadable_lines_are_counted_and_skipped(self):
        repo = Repo(seen=["not json", note("vehicles.track-thrown", "2026-11-17T10:00:00Z"), json.dumps({"key": "x"})],
                    verdicts=[verdict("1", "maybe", "2026-11-17T10:00:00Z")])
        try:
            evidence = repo.evidence()
            self.assertEqual(evidence.unreadable, 3)
            self.assertIn("vehicles.track-thrown", evidence.seen)
        finally:
            repo.close()

    def test_keys_no_row_names_are_listed(self):
        repo = Repo(seen=[note("medical.something", "2026-11-17T10:00:00Z")])
        try:
            self.assertEqual(repo.evidence().unmapped, ["medical.something"])
        finally:
            repo.close()

    def test_missing_files_hold_nothing(self):
        repo = Repo()
        try:
            evidence = testpass.gather(repo.root, [repo.root / "none.jsonl"], [repo.root / "none.jsonl"])
            self.assertEqual((evidence.seen, evidence.verdicts), ({}, {}))
        finally:
            repo.close()

    def test_a_part_looks_only_at_its_keys_notes_and_judges_the_same(self):
        """1.147.1: the index by key narrows the notes a part looks at; the answer, and its notes' order, are the same."""
        notes = [testpass.Note("a.x", "2026-11-01T00:00:00Z", "M", "1.0.0", "one"),
                 testpass.Note("b.y", "2026-11-02T00:00:00Z", "M", "1.0.0", "two"),
                 testpass.Note("a.x", "2026-11-03T00:00:00Z", "M", "0.9.0", "three"),
                 testpass.Note("c.z", "2026-11-04T00:00:00Z", "M", "1.0.0", "four", variant="hot"),
                 testpass.Note("b.y", "2026-11-05T00:00:00Z", "M", "1.0.0", "five")]
        by_key = testpass.index_by_key(notes)
        self.assertEqual(by_key, {"a.x": [0, 2], "b.y": [1, 4], "c.z": [3]})
        versions = {"M": (1, 0, 0)}
        for items in ((testpass.Item("a.x"),), (testpass.Item("b.y"), testpass.Item("a.x")), (testpass.Item("c.z", "cold"),),
                      (testpass.Item("c.z", "hot"),), (testpass.Item("none"),)):
            part = testpass.Part("p", items)
            self.assertEqual(testpass.check_part(part, notes, versions, by_key), testpass.check_part(part, notes, versions))
        both = testpass.check_part(testpass.Part("p", (testpass.Item("b.y"), testpass.Item("a.x"))), notes, versions, by_key)
        self.assertEqual([n.detail for n in both.good], ["one", "two", "five"])


class Applying(unittest.TestCase):
    def test_a_verdict_replaces_the_awaiting_note_and_keeps_the_note(self):
        repo = Repo(seen=[note("vehicles.track-thrown", "2026-11-17T10:00:00Z")])
        try:
            text, _ = testpass.apply_to_text(repo.doc(), repo.evidence())
            (repo.root / "docs" / "test-pass.md").write_text(text, encoding="utf-8")
            repo.verdicts.write_text(verdict("1", "passed", "2026-11-18T09:00:00Z", "the tank | stopped\nat once") + "\n", encoding="utf-8")
            text, changed = testpass.apply_to_text(repo.doc(), repo.evidence())
            line = next(l for l in text.splitlines() if l.startswith("| 1 |"))
            self.assertNotIn("awaiting", line)
            self.assertTrue(line.endswith("**Passed: the owner, 18 Nov 2026, through D'thorga Companion: the tank \\| stopped at once.** |"))
            self.assertEqual(len(changed), 1)
        finally:
            repo.close()

    def test_applying_twice_changes_nothing_the_second_time(self):
        repo = Repo(seen=[note("vehicles.track-thrown", "2026-11-17T10:00:00Z")], verdicts=[verdict("P1", "failed", "2026-11-17T10:00:00Z")])
        try:
            text, changed = testpass.apply_to_text(repo.doc(), repo.evidence())
            self.assertEqual(len(changed), 2)
            (repo.root / "docs" / "test-pass.md").write_text(text, encoding="utf-8")
            again, changed = testpass.apply_to_text(repo.doc(), repo.evidence())
            self.assertEqual((again, changed), (text, []))
        finally:
            repo.close()

    def test_line_endings_are_kept(self):
        repo = Repo(seen=[note("vehicles.track-thrown", "2026-11-17T10:00:00Z")])
        try:
            text, _ = testpass.apply_to_text(repo.doc().replace("\n", "\r\n"), repo.evidence())
            self.assertNotIn("\n", text.replace("\r\n", ""))
        finally:
            repo.close()


class PartsAndConversation(unittest.TestCase):
    def test_a_part_pass_is_written_as_one_and_read_back_as_one(self):
        repo = Repo(verdicts=[verdict("1", "partial", "2026-11-18T09:00:00Z", "the take-off only")])
        try:
            text, _ = testpass.apply_to_text(repo.doc(), repo.evidence())
            line = next(l for l in text.splitlines() if l.startswith("| 1 |"))
            self.assertTrue(line.endswith("**Passed in part: the owner, 18 Nov 2026, through D'thorga Companion: the take-off only.** |"))
            self.assertEqual(testpass.parse_rows(text)[0].status, "partial")
        finally:
            repo.close()

    def test_a_verdict_given_in_conversation_says_so(self):
        given = testpass.parse_verdict("2:passed:the turret turned by hand", "2026-11-18T10:00:00+00:00")
        self.assertEqual((given.row, given.verdict, given.via), ("2", "passed", "conversation"))
        self.assertEqual(testpass.verdict_text(given),
                         "**Passed: the owner, 18 Nov 2026, in conversation: the turret turned by hand.**")
        # A note may hold colons of its own.
        self.assertEqual(testpass.parse_verdict("P1:failed:at 10:30 it fell", "t").note, "at 10:30 it fell")

    def test_a_badly_written_verdict_says_what_to_give(self):
        for text in ("2", "2:maybe", ":passed"):
            with self.assertRaises(testpass.TestPassError):
                testpass.parse_verdict(text, "t")

    def test_the_command_line_writes_a_conversation_verdict(self):
        from datetime import datetime, timezone
        repo = Repo(verdicts=[verdict("1", "failed", "2026-11-17T10:00:00Z")])
        try:
            out = io.StringIO()
            code = testpass_cli.main(["apply", "--root", str(repo.root), "--seen", str(repo.seen), "--verdicts", str(repo.verdicts),
                                      "--verdict", "1:partial:it stops, but slowly", "--apply"], environ={}, out=out,
                                     now=datetime(2026, 11, 18, 12, 0, tzinfo=timezone.utc))
            self.assertEqual(code, 0)
            line = next(l for l in repo.doc().splitlines() if l.startswith("| 1 |"))
            # The one given on the command line replaces the file's for its row.
            self.assertNotIn("Failed", line)
            self.assertTrue(line.endswith("**Passed in part: the owner, 18 Nov 2026, in conversation: it stops, but slowly.** |"))
        finally:
            repo.close()

    def test_a_bad_verdict_on_the_command_line_is_a_usage_error(self):
        import contextlib
        repo = Repo()
        try:
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                code, _ = repo.run("apply", "--verdict", "1:maybe")
            self.assertEqual(code, testpass_cli.EXIT_USAGE)
            self.assertIn("ROW:WORD", err.getvalue())
        finally:
            repo.close()


class CommandLine(unittest.TestCase):
    def test_report_names_what_waits(self):
        repo = Repo(seen=[note("vehicles.track-thrown", "2026-11-17T10:00:00Z")])
        try:
            code, out = repo.run("report")
            self.assertEqual(code, 0)
            self.assertIn("1 seen working", out)
            self.assertIn("Seen working, awaiting your word", out)
        finally:
            repo.close()

    def test_apply_previews_unless_asked(self):
        repo = Repo(verdicts=[verdict("1", "passed", "2026-11-17T10:00:00Z")])
        try:
            before = repo.doc()
            code, out = repo.run("apply")
            self.assertEqual((code, repo.doc()), (0, before))
            self.assertIn("Preview only", out)
            code, out = repo.run("apply", "--apply")
            self.assertIn("**Passed: the owner, 17 Nov 2026, through D'thorga Companion.**", repo.doc())
        finally:
            repo.close()

    def test_json_gives_every_row(self):
        repo = Repo(verdicts=[verdict("2", "failed", "2026-11-17T10:00:00Z")])
        try:
            code, out = repo.run("report", "--json")
            rows = json.loads(out)["data"]["rows"]
            self.assertEqual([r["id"] for r in rows], ["1", "2", "3", "4", "P1"])
            self.assertEqual(rows[1]["verdict"]["verdict"], "failed")
            self.assertEqual(rows[0]["cells"]["What to do"], "Destroy a track")
        finally:
            repo.close()

    def test_a_missing_config_says_what_to_add(self):
        with tempfile.TemporaryDirectory() as folder:
            out, err = io.StringIO(), io.StringIO()
            import contextlib
            with contextlib.redirect_stderr(err):
                code = testpass_cli.main(["report", "--root", folder], environ={}, out=out)
            self.assertEqual(code, testpass_cli.EXIT_USAGE)
            self.assertIn("test-evidence.json is missing", err.getvalue())

    def test_verdicts_default_to_the_companions_folder_per_repository(self):
        path = testpass_cli.verdicts_path(Path("/work/phobos-rimworld"), environ={"LOCALAPPDATA": "/appdata", "XDG_DATA_HOME": "/data"})
        self.assertEqual(path.name, "phobos-rimworld.jsonl")
        self.assertEqual(path.parent.name, "test-verdicts")
        self.assertEqual(path.parent.parent.name, testpass_cli.COMPANION_ID)

    def test_an_environment_variable_names_another_verdicts_file(self):
        path = testpass_cli.verdicts_path(Path("/work/x"), environ={"PHOBOS_TEST_VERDICTS": "/elsewhere/v.jsonl"})
        self.assertEqual(path, Path("/elsewhere/v.jsonl"))


# ---- 1.19.0: notes that say what they were seen on, and evidence that judges them ----

def rich(key, time, on="", kind="", variant="", values=None, detail="", version="0.138.0"):
    line = {"format": 1, "time": time, "key": key, "mod": "D'thorga Framework", "version": version, "detail": detail}
    line.update({k: v for k, v in (("on", on), ("kind", kind), ("variant", variant)) if v})
    if values is not None:
        line["values"] = values
    return json.dumps(line)


def config(rows, **more):
    return {"doc": "docs/test-pass.md", "rows": rows, "prefixes": {}, **more}


class Judging(unittest.TestCase):
    def evidence(self, rows, seen, **more):
        repo = Repo(seen=seen, config=config(rows, **more))
        self.addCleanup(repo.close)
        return repo, repo.evidence()

    def test_a_figure_off_from_what_the_row_expects_does_not_count_as_seen(self):
        rows = {"1": [{"key": "grid", "expect": {"W": ">= 300"}}]}
        _, evidence = self.evidence(rows, [rich("grid", "2026-11-19T10:00:00Z", values={"W": 0.09})])
        part = evidence.checks["1"].parts[0]
        self.assertEqual(part.state, "off")
        self.assertEqual(evidence.sightings("1"), [])
        self.assertIsNone(evidence.pending(evidence.rows[0]))

    def test_a_figure_as_expected_counts_and_says_so(self):
        rows = {"1": [{"key": "grid", "expect": {"W": ">= 300", "loadsA": "> 0"}}]}
        _, evidence = self.evidence(rows, [rich("grid", "2026-11-19T10:00:00Z", values={"W": 0.09}),
                                           rich("grid", "2026-11-19T11:00:00Z", values={"W": 960, "loadsA": 30})])
        self.assertEqual(evidence.checks["1"].parts[0].state, "expected")
        self.assertEqual(len(evidence.sightings("1")), 1)

    def test_a_note_with_no_figures_cannot_meet_an_expectation(self):
        _, evidence = self.evidence({"1": [{"key": "grid", "expect": {"W": "1..2000"}}]}, [note("grid", "2026-11-19T10:00:00Z")])
        self.assertEqual(evidence.checks["1"].parts[0].state, "off")

    def test_every_form_of_expectation(self):
        values = {"x": 5}
        for text, holds in ((">= 5", True), ("> 5", False), ("<= 5", True), ("< 5", False), ("= 5", True), ("4..6", True),
                            ("6..9", False), ("-1 .. 5", True)):
            self.assertEqual(testpass.parse_check("x", text).holds(values), holds, text)
        with self.assertRaises(testpass.TestPassError):
            testpass.parse_check("x", "about 5")

    def test_a_case_and_a_wildcard_narrow_the_evidence(self):
        rows = {"1": [{"key": "stopped", "detail": "*track*"}], "2": [{"key": "stage", "variant": "too weak"}]}
        _, evidence = self.evidence(rows, [rich("stopped", "2026-11-19T10:00:00Z", detail="L-ATV: Engine too badly damaged."),
                                           rich("stage", "2026-11-19T10:00:00Z", variant="barely enough")])
        self.assertEqual(evidence.checks["1"].parts[0].state, "none")
        self.assertEqual(evidence.checks["2"].parts[0].state, "none")
        _, evidence = self.evidence(rows, [rich("stopped", "2026-11-19T10:00:00Z", detail="M1A2: Left TRACK thrown"),
                                           rich("stage", "2026-11-19T10:00:00Z", variant="too weak")])
        self.assertEqual([evidence.checks[r].parts[0].state for r in ("1", "2")], ["seen", "seen"])

    def test_a_row_in_parts_says_how_many_were_seen_and_grows(self):
        rows = {"1": {"parts": {"wet brakes": ["wet"], "air filter": ["filter"], "a service": ["service"]}}}
        repo, evidence = self.evidence(rows, [rich("wet", "2026-11-19T10:00:00Z")])
        text, changed = testpass.apply_to_text(repo.doc(), evidence)
        self.assertIn("1 of 3 parts (wet brakes)", changed[0][1])
        (repo.root / "docs" / "test-pass.md").write_text(text, encoding="utf-8")
        repo.seen.write_text("\n".join([rich("wet", "2026-11-19T10:00:00Z"), rich("filter", "2026-11-19T12:00:00Z")]) + "\n",
                             encoding="utf-8")
        text, changed = testpass.apply_to_text(repo.doc(), repo.evidence())
        line = next(l for l in text.splitlines() if l.startswith("| 1 |"))
        self.assertIn("2 of 3 parts (wet brakes, air filter)", line)
        self.assertEqual(line.count("Seen working by the game"), 1)
        (repo.root / "docs" / "test-pass.md").write_text(text, encoding="utf-8")
        self.assertEqual(testpass.apply_to_text(repo.doc(), repo.evidence())[1], [])

    def test_a_sighting_older_than_its_row_is_stale(self):
        # Row 1 is written for Framework 0.115.0; a note from 0.114.0 is older, one from 0.115.0 is not.
        rows = {"1": ["vehicles.track-thrown"]}
        names = {"versionNames": {"D'thorga Framework": "Framework"}}
        _, evidence = self.evidence(rows, [note("vehicles.track-thrown", "2026-11-17T10:00:00Z", version="0.114.0")], **names)
        self.assertEqual(evidence.checks["1"].parts[0].state, "stale")
        self.assertIsNone(evidence.pending(evidence.rows[0]))
        _, evidence = self.evidence(rows, [note("vehicles.track-thrown", "2026-11-17T10:00:00Z", version="0.115.0")], **names)
        self.assertEqual(evidence.checks["1"].parts[0].state, "seen")

    def test_row_versions_skip_other_mods_and_written_sentences(self):
        row = testpass.Row("9", "", [], ["9", "**X** (Patches 0.21.0, Framework 0.119.0)",
                                         "Needs Vehicle Framework 1.7.2537. Framework 0.137.3: a turbine warns",
                                         "Lit. **Seen working by the game, 18 Nov 2026 (D'thorga Framework 0.140.0); awaiting the owner's word.**"], 0)
        found = testpass.row_versions(row, {"D'thorga Framework": "Framework", "D'thorga Patches": ["Patches"]})
        self.assertEqual(found, {"D'thorga Framework": (0, 137, 3), "D'thorga Patches": (0, 21, 0)})

    def test_order_rules_find_a_refusal_with_no_warning_before_it(self):
        rule = {"name": "warn first", "row": "1", "first": {"key": "stage", "variant": "barely"},
                "then": {"key": "stage", "variant": "too weak"}}
        seen = [rich("stage", "2026-11-19T10:00:00Z", on="Abrams1", variant="barely"),
                rich("stage", "2026-11-19T10:05:00Z", on="Abrams1", variant="too weak"),
                # A second refusal on the same tank needs a warning of its own.
                rich("stage", "2026-11-19T12:00:00Z", on="Abrams1", variant="too weak"),
                # Another tank's warning does not count for this one.
                rich("stage", "2026-11-19T09:00:00Z", on="Abrams2", variant="barely"),
                rich("stage", "2026-11-19T09:30:00Z", on="Hind1", kind="Hind", variant="too weak", detail="Hind: too weak"),
                # A note from before notes said what they were on cannot be checked.
                rich("stage", "2026-11-19T08:00:00Z", variant="too weak")]
        _, evidence = self.evidence({"1": ["stage"]}, seen, order=[rule])
        self.assertEqual([(p.on, p.time) for p in evidence.order],
                         [("Abrams1", "2026-11-19T12:00:00Z"), ("Hind1", "2026-11-19T09:30:00Z")])
        self.assertEqual(evidence.unchecked_order, 1)

    def test_breadth_counts_kinds_or_the_detail_before_its_colon(self):
        _, evidence = self.evidence({"1": ["k"]}, [rich("k", "2026-11-19T10:00:00Z", kind="M1A2Abrams"),
                                                   rich("k", "2026-11-19T11:00:00Z", detail="L-ATV: wet"),
                                                   rich("k", "2026-11-19T12:00:00Z", kind="M1A2Abrams")])
        self.assertEqual(evidence.checks["1"].kinds, ["L-ATV", "M1A2Abrams"])

    def test_a_generic_key_on_two_rows_must_be_shared_on_purpose(self):
        rows = {"1": ["cranked", {"key": "stopped", "detail": "*track*"}], "2": ["cranked", "stopped"]}
        self.assertEqual(len(testpass.map_problems(config(rows))), 1)
        self.assertEqual(testpass.map_problems(config(rows, shared={"cranked": "both test a gun cranked by hand"})), [])

    def test_a_badly_written_map_says_what_to_give(self):
        for rows in ({"1": [{"variant": "x"}]}, {"1": [{"key": "k", "colour": "red"}]}, {"1": {"parts": {"a": []}}},
                     {"1": "k"}, {"1": [{"key": "k", "expect": {"W": "lots"}}]}):
            with self.assertRaises(testpass.TestPassError, msg=str(rows)):
                testpass.parse_mapping(config(rows))

    def test_mapped_keys_reads_every_form(self):
        rows = {"1": ["a", {"key": "b"}], "2": {"parts": {"x": [{"key": "c", "variant": "v"}]}}}
        rule = {"first": "d", "then": {"key": "e"}}
        self.assertEqual(testpass.mapped_keys(config(rows, order=[rule])), {"a", "b", "c", "d", "e"})


class Withdrawing(unittest.TestCase):
    def test_a_seen_sentence_no_note_stands_for_is_taken_back(self):
        # Written from a generic note; the map now narrows the evidence and that note no longer fits.
        repo = Repo(seen=[rich("stopped", "2026-11-19T10:00:00Z", detail="L-ATV: Engine too badly damaged.")],
                    config=config({"1": ["stopped"]}))
        try:
            text, _ = testpass.apply_to_text(repo.doc(), repo.evidence())
            self.assertIn("Seen working by the game", text)
            (repo.root / "docs" / "test-pass.md").write_text(text, encoding="utf-8")
            (repo.root / "config" / "test-evidence.json").write_text(
                json.dumps(config({"1": [{"key": "stopped", "detail": "*track*"}]})), encoding="utf-8")
            text, changed = testpass.apply_to_text(repo.doc(), repo.evidence())
            line = next(l for l in text.splitlines() if l.startswith("| 1 |"))
            self.assertNotIn("Seen working", line)
            self.assertTrue(line.endswith("| The tank stops |"), line)
            self.assertEqual(changed[0][1], testpass.WITHDRAWN)
        finally:
            repo.close()

    def test_nothing_is_taken_back_when_no_notes_were_read(self):
        repo = Repo(seen=[rich("stopped", "2026-11-19T10:00:00Z")], config=config({"1": ["stopped"]}))
        try:
            text, _ = testpass.apply_to_text(repo.doc(), repo.evidence())
            (repo.root / "docs" / "test-pass.md").write_text(text, encoding="utf-8")
            repo.seen.write_text("", encoding="utf-8")
            self.assertEqual(testpass.apply_to_text(repo.doc(), repo.evidence())[1], [])
        finally:
            repo.close()

    def test_a_verdict_is_never_taken_back(self):
        repo = Repo(seen=[rich("other", "2026-11-19T10:00:00Z")], verdicts=[verdict("1", "passed", "2026-11-18T10:00:00Z")],
                    config=config({"1": ["stopped"]}))
        try:
            text, _ = testpass.apply_to_text(repo.doc(), repo.evidence())
            (repo.root / "docs" / "test-pass.md").write_text(text, encoding="utf-8")
            self.assertEqual(testpass.apply_to_text(repo.doc(), repo.evidence())[1], [])
        finally:
            repo.close()


class Decisions(unittest.TestCase):
    def test_no_row_needed_leaves_a_key_out_and_make_a_row_lists_it(self):
        repo = Repo(seen=[note("medical.a", "2026-11-17T10:00:00Z"), note("medical.b", "2026-11-17T10:00:00Z"),
                          note("medical.c", "2026-11-17T10:00:00Z")],
                    config=config({"1": ["vehicles.track-thrown"]}, unrowed={"medical.c": "a dev action's note"}))
        try:
            decisions = repo.root / "decisions.jsonl"
            decisions.write_text("\n".join(json.dumps(d) for d in (
                {"format": 1, "time": "2026-11-18T10:00:00Z", "key": "medical.a", "decision": "no-row"},
                {"format": 1, "time": "2026-11-18T10:00:00Z", "key": "medical.b", "decision": "make-row", "note": "the drip"},
                {"format": 1, "time": "2026-11-18T10:00:00Z", "key": "medical.z", "decision": "maybe"})) + "\n", encoding="utf-8")
            evidence = testpass.gather(repo.root, [repo.seen], [repo.verdicts], decision_paths=[decisions])
            self.assertEqual(evidence.unmapped, ["medical.b"])
            self.assertEqual(evidence.unreadable, 1)
            out = io.StringIO()
            testpass_cli.main(["report", "--root", str(repo.root), "--seen", str(repo.seen), "--verdicts", str(repo.verdicts),
                               "--decisions", str(decisions), "--json"], environ={}, out=out)
            unrowed = json.loads(out.getvalue())["data"]["unrowed"]
            self.assertEqual([(u["key"], u["decision"]) for u in unrowed], [("medical.b", "make-row"), ("medical.a", "no-row")])
        finally:
            repo.close()

    def test_decisions_default_beside_the_verdicts(self):
        path = testpass_cli.decisions_path(Path("/work/phobos-rimworld"), environ={"LOCALAPPDATA": "/appdata", "XDG_DATA_HOME": "/d"})
        self.assertEqual((path.name, path.parent.name), ("phobos-rimworld.jsonl", "test-key-decisions"))


class RichReport(unittest.TestCase):
    def test_the_report_shows_figures_order_and_staleness(self):
        rows = {"1": [{"key": "grid", "expect": {"W": ">= 300"}}], "3": ["lamp"], "4": ["old"]}
        rule = {"name": "warn first", "row": "3", "first": {"key": "lamp", "variant": "warn"},
                "then": {"key": "lamp", "variant": "fail"}}
        doc_rows = {"versionNames": {"D'thorga Framework": "Framework"}, "order": [rule]}
        repo = Repo(seen=[rich("grid", "2026-11-19T10:00:00Z", values={"W": 0.09}),
                          rich("lamp", "2026-11-19T10:00:00Z", on="T1", kind="Truck", variant="fail"),
                          rich("old", "2026-11-19T10:00:00Z", version="0.100.0")], config=config(rows, **doc_rows))
        try:
            (repo.root / "docs" / "test-pass.md").write_text(DOC.replace("| 4 | **A pipe with a \\| in it** |",
                                                                         "| 4 | **A pipe** (Framework 0.120.0) |"), encoding="utf-8")
            code, out = repo.run("report")
            self.assertEqual(code, 0)
            self.assertIn("Seen, but not with the figures the row expects", out)
            self.assertIn("W 0.09", out)
            self.assertIn("Out of order", out)
            self.assertIn("Seen only before the row last changed", out)
            code, out = repo.run("report", "--json")
            data = json.loads(out)["data"]
            row1 = next(r for r in data["rows"] if r["id"] == "1")
            self.assertEqual(row1["parts"][0]["state"], "off")
            self.assertEqual(row1["parts"][0]["off"][0]["values"], {"W": 0.09})
            self.assertEqual(data["order_problems"][0]["on"], "T1")
        finally:
            repo.close()


if __name__ == "__main__":
    unittest.main()
