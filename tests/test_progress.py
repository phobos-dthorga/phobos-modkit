"""Progress lines: written only when asked for, passed on from a child command, and never on standard output."""
import io
import json
import sys
import unittest

import support  # noqa: F401  (puts the package on the path)
from phobos_modkit import progress

CHILD = ("import sys\n"
         "print('copied 4 files', flush=True)\n"
         "print('{\"progress\": 1, \"label\": \"Building Thing\", \"step\": 1, \"of\": 2}', file=sys.stderr, flush=True)\n"
         "print('a warning', file=sys.stderr, flush=True)\n"
         "sys.exit(3)\n")


class ProgressTests(unittest.TestCase):
    def test_nothing_is_written_unless_asked(self):
        stream = io.StringIO()
        progress.Progress({}, stream)("Working", 1, 2)
        self.assertEqual(stream.getvalue(), "")

    def test_a_line_carries_what_it_was_given(self):
        stream = io.StringIO()
        say = progress.Progress({progress.ENV: "1"}, stream)
        say("Building Thing", 3, 23)
        say("Reading the save")
        say(detail="copied 4 files")
        lines = [json.loads(line) for line in stream.getvalue().splitlines()]
        self.assertEqual(lines, [{"progress": 1, "label": "Building Thing", "step": 3, "of": 23},
                                 {"progress": 1, "label": "Reading the save"}, {"progress": 1, "detail": "copied 4 files"}])
        self.assertTrue(all(progress.is_line(line) for line in stream.getvalue().splitlines()))
        self.assertFalse(progress.is_line("error: something failed"))

    def test_a_child_command_is_read_as_it_runs(self):
        stream = io.StringIO()
        say = progress.Progress({progress.ENV: "1"}, stream)
        code, lines = progress.run_streaming([sys.executable, "-c", CHILD], progress=say, timeout=60)
        self.assertEqual((code, lines), (3, ["copied 4 files", "a warning"]))
        heard = [json.loads(line) for line in stream.getvalue().splitlines()]
        self.assertIn({"progress": 1, "detail": "copied 4 files"}, heard)
        self.assertIn({"progress": 1, "label": "Building Thing", "step": 1, "of": 2}, heard)

    def test_a_silent_run_still_returns_the_output(self):
        code, lines = progress.run_streaming([sys.executable, "-c", CHILD], timeout=60)
        self.assertEqual((code, lines), (3, ["copied 4 files", "a warning"]))


if __name__ == "__main__":
    unittest.main()
