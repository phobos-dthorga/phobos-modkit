"""claims: who is working on what, taken and released by agent sessions (1.44.0); refusals as JSON in records and screen-notes."""
from datetime import datetime, timedelta, timezone
import io
import json
from pathlib import Path
import tempfile
import threading
import unittest

import support  # noqa: F401  (puts the package on the path)
from phobos_modkit import claims, records, screen_notes

NOW = datetime(2026, 11, 19, 10, 0, tzinfo=timezone.utc)


class ClaimsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.board = Path(self.temp.name) / "claims.json"
        self.environ = {"PHOBOS_CLAIMS": str(self.board)}

    def tearDown(self):
        self.temp.cleanup()

    def run_cli(self, *argv):
        out = io.StringIO()
        return claims.main(list(argv), out, self.environ), out.getvalue()

    def test_the_board_is_named_by_its_setting(self):
        self.assertEqual(claims.board_file(self.environ), self.board)

    def test_a_thing_is_held_by_one_session_whatever_its_spelling(self):
        claims.take(self.board, "phobos-modkit 1.44.0", "session-a", "claims board")
        with self.assertRaises(claims.ClaimError) as refused:
            claims.take(self.board, "  Phobos-ModKit   1.44.0 ", "session-b")
        self.assertIn("session-a", str(refused.exception))
        claims.take(self.board, "phobos-modkit 1.44.0", "session-a")
        self.assertEqual(len(claims.read_board(self.board)), 1)

    def test_release_by_its_holder_by_force_or_everything(self):
        claims.take(self.board, "row 237", "session-a")
        claims.take(self.board, "row 238", "session-a")
        claims.take(self.board, "0.174.0", "session-b")
        with self.assertRaises(claims.ClaimError):
            claims.release(self.board, "0.174.0", "session-a")
        self.assertEqual(len(claims.release(self.board, "0.174.0", "session-a", force=True)), 1)
        self.assertEqual(len(claims.release(self.board, None, "session-a", everything=True)), 2)
        self.assertEqual(claims.read_board(self.board), [])
        with self.assertRaises(claims.ClaimError):
            claims.release(self.board, "row 237", "session-a")

    def test_a_claim_older_than_a_day_is_shown_as_old(self):
        claims.take(self.board, "row 1", "session-a", now=NOW - timedelta(hours=30))
        claims.take(self.board, "row 2", "session-b", now=NOW - timedelta(minutes=20))
        found = claims.listed(self.board, NOW)
        self.assertEqual([c["what"] for c in found], ["row 1", "row 2"])
        self.assertTrue(found[0]["old"])
        self.assertFalse(found[1]["old"])

    def test_sessions_taking_at_once_never_lose_a_claim(self):
        errors = []

        def take(n):
            try:
                claims.take(self.board, f"row {n}", f"session-{n}")
            except Exception as error:  # noqa: BLE001  (a lost claim must say why)
                errors.append(repr(error))

        threads = [threading.Thread(target=take, args=(n,)) for n in range(24)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(errors, [])
        self.assertEqual(len(claims.read_board(self.board)), 24)
        self.assertFalse(Path(str(self.board) + ".lock").exists())

    def test_a_lock_left_by_a_crashed_run_is_broken(self):
        lock = Path(str(self.board) + ".lock")
        lock.write_text("", encoding="utf-8")
        old = datetime.now().timestamp() - claims.LOCK_STALE_S - 5
        import os
        os.utime(lock, (old, old))
        claims.take(self.board, "row 1", "session-a")
        self.assertEqual(len(claims.read_board(self.board)), 1)

    def test_command_line_refusals_are_json(self):
        self.assertEqual(self.run_cli("take", "row 9", "--by", "a")[0], 0)
        code, text = self.run_cli("take", "row 9", "--by", "b", "--json")
        self.assertEqual(code, claims.EXIT_REFUSED)
        self.assertEqual(json.loads(text)["data"]["ok"], False)
        code, text = self.run_cli("list", "--json")
        self.assertEqual(json.loads(text)["data"]["claims"][0]["by"], "a")
        code, text = self.run_cli("release", "--by", "a")
        self.assertEqual(code, claims.EXIT_REFUSED)

    def test_records_and_screen_notes_refuse_in_json_too(self):
        out = io.StringIO()
        code = records.main(["backup", "--json"], out, {"LOCALAPPDATA": self.temp.name, "XDG_DATA_HOME": self.temp.name,
                                                        "PHOBOS_SETTINGS": str(self.board) + ".none"})
        self.assertEqual(code, records.EXIT_REFUSED)
        self.assertEqual(json.loads(out.getvalue())["data"]["ok"], False)
        out = io.StringIO()
        code = screen_notes.main(["resolve", "nonsense", "--how", "x", "--json"], out,
                                 {screen_notes.VARIABLE: self.temp.name})
        self.assertEqual(json.loads(out.getvalue())["data"]["refusal"].startswith("'nonsense'"), True)


if __name__ == "__main__":
    unittest.main()
