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


if __name__ == "__main__":
    unittest.main()
