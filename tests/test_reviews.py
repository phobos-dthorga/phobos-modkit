"""reviews: marks appended to a file per repository, the last line deciding, a mark taken back, and refusals (no Companion)."""
from datetime import datetime, timezone
import io
import json
from pathlib import Path
import tempfile
import unittest

import support  # noqa: F401  (puts the package on the path)
from phobos_modkit import reviews

BUILD = "3d9ff12528d1"
WHEN = datetime(2026, 11, 27, 9, 0, tzinfo=timezone.utc)


class ReviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "some-repository"
        self.root.mkdir()
        self.environ = {"PHOBOS_REVIEWS": str(Path(self.temp.name) / "marks")}

    def run_main(self, *argv):
        out = io.StringIO()
        code = reviews.main([*argv, "--root", str(self.root), "--json"], out=out, environ=self.environ)
        return code, json.loads(out.getvalue())["data"]

    def test_a_mark_is_kept_per_repository_and_read_by_kind(self):
        reviews.mark(self.root, reviews.TEMPORARY_PATCH, "6 (Harrier)", BUILD.upper(), "  the fault\nstands ",
                     environ=self.environ, now=WHEN)
        reviews.mark(self.root, "something-else", "6 (Harrier)", "abcdef", None, environ=self.environ, now=WHEN)
        self.assertEqual(Path(self.temp.name) / "marks" / "some-repository.jsonl", reviews.marks_file(self.root, self.environ))
        self.assertEqual({"6 (Harrier)": {"build": BUILD, "on": "2026-11-27", "note": "the fault stands"}},
                         reviews.marks(self.root, reviews.TEMPORARY_PATCH, self.environ))

    def test_the_last_line_decides_and_a_mark_can_be_taken_back(self):
        reviews.mark(self.root, reviews.TEMPORARY_PATCH, "25", "aaaaaa", environ=self.environ)
        reviews.mark(self.root, reviews.TEMPORARY_PATCH, "25", "bbbbbb", environ=self.environ)
        self.assertEqual("bbbbbb", reviews.marks(self.root, reviews.TEMPORARY_PATCH, self.environ)["25"]["build"])
        reviews.mark(self.root, reviews.TEMPORARY_PATCH, "25", clear=True, environ=self.environ)
        self.assertEqual({}, reviews.marks(self.root, reviews.TEMPORARY_PATCH, self.environ))

    def test_a_line_that_is_not_a_mark_is_passed_over(self):
        path = reviews.marks_file(self.root, self.environ)
        path.parent.mkdir(parents=True)
        path.write_text('not json\n{"kind": "temporary-patch", "id": "7", "build": "nothex"}\n[1]\n', encoding="utf-8")
        self.assertEqual({}, reviews.marks(self.root, reviews.TEMPORARY_PATCH, self.environ))

    def test_shapes_are_refused(self):
        for kind, thing, build in (("Temporary Patch", "6", BUILD), ("temporary-patch", "", BUILD),
                                   ("temporary-patch", "x" * 121, BUILD), ("temporary-patch", "6", "xyz"),
                                   ("temporary-patch", "6", "abc")):
            with self.assertRaises(reviews.ReviewError):
                reviews.mark(self.root, kind, thing, build, environ=self.environ)
        self.assertFalse(reviews.marks_file(self.root, self.environ).exists())

    def test_the_command_marks_lists_and_refuses(self):
        code, data = self.run_main("mark", "--kind", "temporary-patch", "--id", "27 (Prowler)", "--build", BUILD,
                                   "--note", "read for Patches 0.45.2")
        self.assertEqual((0, True), (code, data["ok"]))
        code, data = self.run_main("list")
        self.assertEqual(["27 (Prowler)"], [m["id"] for m in data["marks"]])
        code, data = self.run_main("mark", "--kind", "temporary-patch", "--id", "27 (Prowler)", "--build", "nope")
        self.assertEqual((reviews.EXIT_REFUSED, False), (code, data["ok"]))
        self.assertIn("hexadecimal", data["refusal"])


if __name__ == "__main__":
    unittest.main()
