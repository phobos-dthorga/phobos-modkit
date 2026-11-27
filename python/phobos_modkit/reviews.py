"""reviews: what the owner has marked as read, so a check stops asking about it (1.137.0).

    reviews list --root REPO [--kind KIND]                                  every mark kept for a repository
    reviews mark --root REPO --kind KIND --id ID --build BUILD [--note N]    marks one thing as read, for one build
    reviews mark --root REPO --kind KIND --id ID --clear                    takes a mark back

A check that asks the owner to read something (an update that touched a temporary patch's fault, today) offers **I've read it**
in D'thorga Companion. The mark names the build that was read: a newer build asks again. Marks are appended, one JSON line each,
to a file per repository in the Companion's folder (companionReviewsPath, PHOBOS_REVIEWS), as picks and decisions are; the last
line for a thing decides, so a mark can be taken back. Nothing in the repository changes: a repository may also keep its own
notes (rimworld-update-check's "reviewed"), which the check reads first. No game in it: `kind` is the check's own word for what
it asks about, and the check reads only its own kind.
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
from .paths import companion_data, resolve
from .report import Bullets, Report, envelope_text, home_redactor, keep, render_markdown

EXIT_OK, EXIT_USAGE, EXIT_REFUSED = 0, 2, 3
MARKS = ("companionReviewsPath", "PHOBOS_REVIEWS")
MARK_FORMAT = 1
KIND = re.compile(r"^[a-z][a-z0-9-]{0,39}$")
BUILD = re.compile(r"^[0-9a-f]{6,64}$")
MAX_ID = 120
MAX_NOTE = 2000
# The kinds the tools ask about, each with the check that reads it.
TEMPORARY_PATCH = "temporary-patch"


class ReviewError(ValueError):
    """A request this command refuses, with the reason in words."""


def marks_file(root, environ=None):
    """The owner's marks for a repository: companionReviewsPath (a folder), else reviews/<repository>.jsonl in the Companion's
    folder."""
    folder = resolve(*MARKS, companion_data(environ) / "reviews", None, environ)
    return Path(folder) / f"{Path(root).resolve().name}.jsonl"


def _one_line(value, limit):
    return " ".join(value.split())[:limit] if isinstance(value, str) else ""


def check_mark(kind, thing, build=None, note=None, clear=False):
    """The mark's fields, cleaned; refuses a kind, id or build of the wrong shape."""
    if not isinstance(kind, str) or not KIND.match(kind):
        raise ReviewError(f"{kind!r} is not a kind: lower-case letters, digits and hyphens")
    thing = _one_line(thing, MAX_ID + 1)
    if not thing or len(thing) > MAX_ID:
        raise ReviewError(f"the id must be one line of 1 to {MAX_ID} characters")
    if clear:
        return {"kind": kind, "id": thing, "clear": True}
    build = (build or "").strip().lower()
    if not BUILD.match(build):
        raise ReviewError(f"{build!r} is not a build: 6 to 64 hexadecimal digits, the start of its SHA-256")
    return {"kind": kind, "id": thing, "build": build, "note": _one_line(note, MAX_NOTE)}


def read_marks(path):
    """{(kind, id): the last line for it} from a marks file; a line that is not a mark is passed over; a cleared mark is gone."""
    found = {}
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except OSError:
        return found
    for text in lines:
        try:
            line = json.loads(text)
        except ValueError:
            continue
        if not isinstance(line, dict) or not isinstance(line.get("kind"), str) or not isinstance(line.get("id"), str):
            continue
        key = (line["kind"], line["id"])
        if line.get("clear"):
            found.pop(key, None)
        elif isinstance(line.get("build"), str) and BUILD.match(line["build"]):
            found[key] = line
    return found


def marks(root, kind, environ=None):
    """{id: {"build", "on", "note"}} for one kind: what a check reads, in the shape of a repository's own "reviewed" note."""
    return {thing: {"build": line["build"], "on": str(line.get("time", ""))[:10], "note": line.get("note", "")}
            for (k, thing), line in read_marks(marks_file(root, environ)).items() if k == kind}


def mark(root, kind, thing, build=None, note=None, clear=False, environ=None, now=None):
    """Appends one mark, or its taking back. Returns the line written."""
    line = check_mark(kind, thing, build, note, clear)
    line = {"format": MARK_FORMAT, **line,
            "time": (now or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat(timespec="seconds")}
    path = marks_file(root, environ)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(line, ensure_ascii=False) + "\n")
    return line


def _parser():
    p = argparse.ArgumentParser(prog="reviews", description=__doc__.split("\n\n")[0],
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="report", required=True)
    s = sub.add_parser("list", help="every mark kept for a repository")
    s.add_argument("--root", required=True, help="the repository")
    s.add_argument("--kind", help="only this kind of mark")
    m = sub.add_parser("mark", help="marks one thing as read for one build, or takes a mark back")
    m.add_argument("--root", required=True, help="the repository the thing belongs to")
    m.add_argument("--kind", required=True, help=f"what kind of thing, as the check names it (today: {TEMPORARY_PATCH})")
    m.add_argument("--id", required=True, help="the thing, as the check names it")
    m.add_argument("--build", help="the start of the SHA-256 of the build that was read, as the check shows it")
    m.add_argument("--note", help="what was found, in a line")
    m.add_argument("--clear", action="store_true", help="take the mark back instead")
    for parser in (s, m):
        parser.add_argument("--json", action="store_true", help="print JSON instead of Markdown")
        parser.add_argument("--no-redact", action="store_true", help="show the home folder instead of ~")
    return p


def main(argv=None, out=None, environ=None):
    out = out or sys.stdout
    environ = os.environ if environ is None else environ
    try:
        args = _parser().parse_args(list(sys.argv[1:] if argv is None else argv))
    except SystemExit as stop:
        return EXIT_USAGE if stop.code else EXIT_OK
    redact = keep if args.no_redact else home_redactor()

    def write(report, data):
        out.write((envelope_text("reviews", report, redact, data) if args.json else render_markdown(report, redact)) + "\n")

    if args.report == "mark":
        try:
            line = mark(args.root, args.kind, args.id, args.build, args.note, args.clear, environ)
        except ReviewError as refused:
            write(Report(f"Refused: {refused}"), {"ok": False, "refusal": str(refused)})
            return EXIT_REFUSED
        title = (f"Taken back: {line['id']} is no longer marked as read" if line.get("clear")
                 else f"Marked as read: {line['id']}, build {line['build']}")
        write(Report(title), {"ok": True, "mark": line})
        return EXIT_OK
    kept = [{"kind": kind, "id": thing, **line} for (kind, thing), line in read_marks(marks_file(args.root, environ)).items()
            if not args.kind or kind == args.kind]
    kept.sort(key=lambda line: (line["kind"], line["id"]))
    report = Report(f"Marked as read: {len(kept)}")
    report.lines.append(f"Kept in {marks_file(args.root, environ)}.")
    if kept:
        report.section("Marks", Bullets([f"{line['kind']} {line['id']}: build {line['build']}, {str(line.get('time', ''))[:10]}"
                                         + (f": {line['note']}" if line.get("note") else "") for line in kept]))
    write(report, {"marks": kept, "file": str(marks_file(args.root, environ))})
    return EXIT_OK


MANIFEST = {"game": None, "parser": _parser, "effect": READS,
            "reports": {"list": {"question": "What have I marked as read?"},
                        "mark": {"effect": WRITES, "surface": "reviews",
                                 "note": "appends the owner's mark to the Companion's reviews file; nothing in the repository changes"}}}
