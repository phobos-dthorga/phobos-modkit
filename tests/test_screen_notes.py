"""screen-notes: what the owner flagged in D'thorga Companion, listed, resolved and reopened (1.41.0)."""
from datetime import datetime, timezone
import io
import json
from pathlib import Path
import tempfile
import unittest

import support  # noqa: F401  (puts the package on the path)
from phobos_modkit import screen_notes


def write_note(folder, note_id, time, words, page="Mods", picture=True):
    where = Path(folder) / note_id
    where.mkdir(parents=True)
    (where / "note.json").write_text(json.dumps({
        "format": 1, "time": time, "game": "Sample Game", "page": page, "address": f"dthorga://{page.lower()}/sample",
        "words": words, "version": "0.22.0", "window": {"width": 1600, "height": 900}}), encoding="utf-8")
    if picture:
        (where / "picture.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    return where


class ScreenNotesTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.folder = Path(self.temp.name) / "screen-notes"
        self.environ = {screen_notes.VARIABLE: str(self.folder)}

    def tearDown(self):
        self.temp.cleanup()

    def run_cli(self, *argv):
        out = io.StringIO()
        code = screen_notes.main(list(argv), out, self.environ)
        return code, out.getvalue()

    def test_the_folder_is_the_companions_unless_named(self):
        self.assertEqual(screen_notes.folder(self.environ), self.folder)
        found = screen_notes.folder({"LOCALAPPDATA": self.temp.name})
        self.assertEqual(found.name, "screen-notes")

    def test_open_notes_newest_first_with_their_picture(self):
        write_note(self.folder, "20261119-090000", "2026-11-18T22:00:00+00:00", "The chart overlaps")
        write_note(self.folder, "20261119-100000", "2026-11-18T23:00:00+00:00", "", page="Timeline", picture=False)
        (self.folder / "not-a-note").mkdir()
        found = screen_notes.notes(self.folder)
        self.assertEqual([n["id"] for n in found], ["20261119-100000", "20261119-090000"])
        self.assertIsNone(found[0]["picture"])
        self.assertTrue(found[1]["picture"].endswith("picture.png"))
        self.assertEqual(found[1]["window"], {"width": 1600, "height": 900})

    def test_resolve_hides_a_note_until_all_is_asked_and_reopen_brings_it_back(self):
        write_note(self.folder, "20261119-090000", "2026-11-18T22:00:00+00:00", "Too small")
        note = screen_notes.resolve(self.folder, "20261119-090000", "Made the text larger",
                                    now=datetime(2026, 11, 19, tzinfo=timezone.utc))
        self.assertEqual(note["resolved"], {"time": "2026-11-19T00:00:00+00:00", "how": "Made the text larger"})
        self.assertEqual(screen_notes.notes(self.folder), [])
        self.assertEqual(len(screen_notes.notes(self.folder, include_resolved=True)), 1)
        screen_notes.reopen(self.folder, "20261119-090000")
        self.assertEqual(len(screen_notes.notes(self.folder)), 1)
        self.assertTrue((self.folder / "20261119-090000" / "note.json").is_file())

    def test_refusals(self):
        write_note(self.folder, "20261119-090000", "2026-11-18T22:00:00+00:00", "x")
        with self.assertRaises(screen_notes.NoteError):
            screen_notes.resolve(self.folder, "../elsewhere", "done")
        with self.assertRaises(screen_notes.NoteError):
            screen_notes.resolve(self.folder, "20261119-090001", "done")
        with self.assertRaises(screen_notes.NoteError):
            screen_notes.resolve(self.folder, "20261119-090000", "   ")
        with self.assertRaises(screen_notes.NoteError):
            screen_notes.reopen(self.folder, "20261119-090000")

    def test_command_line(self):
        code, text = self.run_cli("list")
        self.assertEqual(code, 0)
        self.assertIn("never saved a note", text)
        write_note(self.folder, "20261119-090000", "2026-11-18T22:00:00+00:00", "The chart overlaps")
        code, text = self.run_cli("list", "--json")
        data = json.loads(text)["data"]
        self.assertEqual(data["open"], 1)
        code, text = self.run_cli("resolve", "20261119-090000", "--how", "Moved the legend")
        self.assertEqual(code, 0)
        self.assertIn("dealt with", text)
        code, text = self.run_cli("resolve", "nonsense", "--how", "x")
        self.assertEqual(code, screen_notes.EXIT_REFUSED)
        code, text = self.run_cli("list", "--all")
        self.assertIn("Moved the legend", text)


if __name__ == "__main__":
    unittest.main()
