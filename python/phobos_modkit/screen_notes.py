"""screen-notes: what the owner flagged as looking wrong in D'thorga Companion, for agent sessions to read at the start (1.41.0).

    screen-notes list [--all]              the open notes (--all: the dealt-with ones too), newest first
    screen-notes resolve ID --how WORDS    marks a note dealt with, saying how
    screen-notes reopen ID                 marks a dealt-with note open again

The owner presses one key on any page of the Companion ("something's off"), adds a few words or none, and the Companion writes a
folder for the note: `picture.png`, the page as it was, and `note.json` (when, the game, the page, its address, the words, the
Companion's version, the window's size). A session reads the picture with its own file reader. Resolving writes `resolved.json`
beside them; nothing is ever deleted, so the owner can look back at what was flagged and what was done.

The notes live in the Companion's own folder (`screen-notes`), where it writes them; PHOBOS_SCREEN_NOTES names another folder, for
tests. It is not a setting: the Companion and this command must agree on the folder, and only the folder the Companion writes holds
notes.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import sys

from .manifest import READS, WRITES
from .paths import companion_data
from .report import Bullets, Report, Table, envelope_text, home_redactor, keep, render_markdown

EXIT_OK, EXIT_USAGE, EXIT_REFUSED = 0, 2, 3
FOLDER_NAME = "screen-notes"
VARIABLE = "PHOBOS_SCREEN_NOTES"
NOTE_FILE = "note.json"
RESOLVED_FILE = "resolved.json"
PICTURE_FILE = "picture.png"
RESOLVED_FORMAT = 1
NOTE_ID = re.compile(r"^[0-9]{8}-[0-9]{6}(-[0-9]{1,3})?$")
MAX_HOW = 2000
WORDS_SHOWN = 160


class NoteError(ValueError):
    """A request this command refuses, with the reason in words."""


def folder(environ=None):
    """Where the notes are: PHOBOS_SCREEN_NOTES, else `screen-notes` in D'thorga Companion's own folder."""
    environ = os.environ if environ is None else environ
    named = environ.get(VARIABLE)
    return Path(named) if named else companion_data(environ) / FOLDER_NAME


def _read_json(path):
    try:
        with open(path, encoding="utf-8") as handle:
            found = json.load(handle)
    except (OSError, ValueError):
        return None
    return found if isinstance(found, dict) else None


def _text(value, limit=4000):
    return value[:limit] if isinstance(value, str) else ""


def read_note(where):
    """One note as a dict, or None when its folder holds no readable note."""
    note = _read_json(where / NOTE_FILE)
    if note is None:
        return None
    resolved = _read_json(where / RESOLVED_FILE)
    picture = where / PICTURE_FILE
    window = note.get("window") if isinstance(note.get("window"), dict) else {}
    return {
        "id": where.name,
        "time": _text(note.get("time"), 40),
        "game": _text(note.get("game"), 200),
        "page": _text(note.get("page"), 200),
        "address": _text(note.get("address")),
        "words": _text(note.get("words")),
        "version": _text(note.get("version"), 40),
        "window": {k: window.get(k) for k in ("width", "height") if isinstance(window.get(k), int)},
        "picture": str(picture) if picture.is_file() else None,
        "folder": str(where),
        "resolved": ({"time": _text(resolved.get("time"), 40), "how": _text(resolved.get("how"))}
                     if resolved is not None else None),
    }


def notes(where, include_resolved=False):
    """Every note in the folder, newest first; the dealt-with ones only when asked for."""
    if not where.is_dir():
        return []
    found = []
    for child in where.iterdir():
        if child.is_dir() and NOTE_ID.match(child.name):
            note = read_note(child)
            if note is not None and (include_resolved or note["resolved"] is None):
                found.append(note)
    return sorted(found, key=lambda n: (n["time"], n["id"]), reverse=True)


def _note_folder(where, note_id):
    if not isinstance(note_id, str) or not NOTE_ID.match(note_id):
        raise NoteError(f"{note_id!r} is not a note's name (they look like 20261119-101500)")
    found = where / note_id
    if not (found / NOTE_FILE).is_file():
        raise NoteError(f"there is no note {note_id}")
    return found


def resolve(where, note_id, how, now=None):
    """Marks a note dealt with, saying how. Writes resolved.json beside the note; returns the note as it now reads."""
    how = (how or "").strip()
    if not how:
        raise NoteError("say how the note was dealt with (--how)")
    if len(how) > MAX_HOW:
        raise NoteError(f"keep --how under {MAX_HOW} characters")
    found = _note_folder(where, note_id)
    when = (now or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat(timespec="seconds")
    partial = found / (RESOLVED_FILE + ".partial")
    partial.write_text(json.dumps({"format": RESOLVED_FORMAT, "time": when, "how": how}, ensure_ascii=False, indent=2) + "\n",
                       encoding="utf-8", newline="\n")
    os.replace(partial, found / RESOLVED_FILE)
    return read_note(found)


def reopen(where, note_id):
    """Marks a dealt-with note open again: its resolved.json is removed. The note itself is never touched."""
    found = _note_folder(where, note_id)
    resolved = found / RESOLVED_FILE
    if not resolved.is_file():
        raise NoteError(f"note {note_id} is already open")
    resolved.unlink()
    return read_note(found)


def _parser():
    p = argparse.ArgumentParser(prog="screen-notes", description=__doc__.split("\n\n")[0],
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="report", required=True)
    s = sub.add_parser("list", help="the open notes, newest first")
    s.add_argument("--all", action="store_true", help="the dealt-with notes too")
    for name, helptext in (("resolve", "marks a note dealt with, saying how"), ("reopen", "marks a dealt-with note open again")):
        s2 = sub.add_parser(name, help=helptext)
        s2.add_argument("id", help="the note's name, as list shows it")
        if name == "resolve":
            s2.add_argument("--how", required=True, help="how it was dealt with, in a sentence or two")
        s2.add_argument("--json", action="store_true", help="print JSON instead of Markdown")
        s2.add_argument("--no-redact", action="store_true", help="show the home folder instead of ~")
    s.add_argument("--json", action="store_true", help="print JSON instead of Markdown")
    s.add_argument("--no-redact", action="store_true", help="show the home folder instead of ~")
    return p


def _short(words):
    words = " ".join(words.split())
    return words if len(words) <= WORDS_SHOWN else words[:WORDS_SHOWN - 1] + "…"


def main(argv=None, out=None, environ=None):
    out = out or sys.stdout
    try:
        args = _parser().parse_args(list(sys.argv[1:] if argv is None else argv))
    except SystemExit as stop:
        return EXIT_USAGE if stop.code else EXIT_OK
    redact = keep if args.no_redact else home_redactor()
    where = folder(environ)
    if args.report in ("resolve", "reopen"):
        try:
            note = resolve(where, args.id, args.how) if args.report == "resolve" else reopen(where, args.id)
        except NoteError as refused:
            out.write(f"Refused: {refused}\n")
            return EXIT_REFUSED
        report = Report(f"Screen note {note['id']} " + ("dealt with" if args.report == "resolve" else "open again"))
        report.section("The note", Bullets([f"{note['page']} ({note['game']}), {note['time']}: {_short(note['words']) or '(no words)'}"]))
        out.write((envelope_text("screen-notes", report, redact, {"note": note}) if args.json
                   else render_markdown(report, redact)) + "\n")
        return EXIT_OK
    found = notes(where, include_resolved=args.all)
    open_count = sum(1 for n in found if n["resolved"] is None)
    report = Report(f"Screen notes: {open_count} open" + (f", {len(found) - open_count} dealt with" if args.all else ""))
    if found:
        report.section("Notes", Table(["Note", "When", "Page", "Words", "Dealt with"],
                                      [[n["id"], n["time"], f"{n['page']} ({n['game']})" if n["game"] else n["page"],
                                        _short(n["words"]) or "(no words)",
                                        _short(n["resolved"]["how"]) if n["resolved"] else ""] for n in found]))
        report.section("Reading one", Bullets([
            "Each note's picture is picture.png in its folder; read it to see the page as the owner saw it.",
            "When it is dealt with: screen-notes resolve ID --how \"what was done\"."]))
    else:
        report.section("Notes", Bullets(["Nothing flagged." if where.is_dir() else
                                         "Nothing flagged yet: the Companion has never saved a note here."]))
    out.write((envelope_text("screen-notes", report, redact, {"folder": str(where), "open": open_count, "notes": found})
               if args.json else render_markdown(report, redact)) + "\n")
    return EXIT_OK


MANIFEST = {"game": None, "parser": _parser, "effect": READS,
            "reports": {"list": {"question": "What has the owner flagged as looking wrong in the Companion?"},
                        "resolve": {"effect": WRITES, "note": "writes resolved.json beside one note; nothing is deleted"},
                        "reopen": {"effect": WRITES, "note": "removes one note's resolved.json, so it is open again"}}}
