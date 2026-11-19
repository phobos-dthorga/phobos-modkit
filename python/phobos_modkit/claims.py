"""claims: who is working on what, so agent sessions sharing a machine never take the same version number or test row (1.44.0).

    claims list                                         every claim, oldest first, with its age
    claims take WHAT --by SESSION [--note TEXT]         holds WHAT for a session; refused while another session holds it
    claims release WHAT --by SESSION [--force]          lets it go (--force: one another session left behind)
    claims release --all --by SESSION                   lets go of everything a session holds

WHAT is a few plain words naming the thing: "phobos-modkit 1.44.0", "phobos-rimworld row 237", "D'thorga Framework 0.174.0".
Two claims are the same thing when their words match, ignoring case and spacing. A session names itself as other sessions
address it (phobos-rimworld-11). A claim never expires by itself: one older than a day is shown as old, so a session that ended
without letting go is easy to see, and --force lets another session take it over.

The board is one file, claims.json in D'thorga Companion's folder (claimsPath, PHOBOS_CLAIMS), changed under a lock file and
written whole; the Companion's Home shows it (owner's go-ahead, 19 Nov 2026, the Companion's docs/later.md item 3).
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
import time

from .manifest import READS, WRITES
from .paths import companion_data, resolve
from .report import Bullets, Report, Table, envelope_text, home_redactor, keep, render_markdown

EXIT_OK, EXIT_USAGE, EXIT_REFUSED = 0, 2, 3
BOARD = ("claimsPath", "PHOBOS_CLAIMS")
BOARD_FORMAT = 1
OLD_HOURS = 24
LOCK_WAIT_S = 10.0
LOCK_STALE_S = 60.0
LOCK_POLL_S = 0.05
# Windows can refuse a rename or a delete for a moment while a virus scanner or the indexer holds a file just written.
HELD_TRIES = 50
HELD_WAIT_S = 0.02
MAX_WORDS = 200
MAX_NOTE = 500


class ClaimError(ValueError):
    """A request this command refuses, with the reason in words."""


def board_file(environ=None):
    """The claims board: claimsPath, else claims.json in D'thorga Companion's folder."""
    return resolve(*BOARD, companion_data(environ) / "claims.json", None, environ)


def same_thing(words):
    """What makes two claims the same: their words, ignoring case and spacing."""
    return " ".join(str(words).split()).casefold()


def _now(now=None):
    return (now or datetime.now(timezone.utc)).astimezone(timezone.utc)


def _patiently(step):
    """Runs a file step, trying again for up to a second while Windows says another program holds the file."""
    for attempt in range(HELD_TRIES):
        try:
            return step()
        except PermissionError:
            if attempt == HELD_TRIES - 1:
                raise
            time.sleep(HELD_WAIT_S)
    return None


@contextmanager
def _locked(path):
    """Holds the board's lock file while the board is read and rewritten; a lock left by a crashed run is broken after a minute."""
    lock = Path(str(path) + ".lock")
    lock.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + LOCK_WAIT_S
    while True:
        try:
            handle = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.close(handle)
            break
        except (FileExistsError, PermissionError):
            # Windows answers PermissionError, not FileExistsError, while a lock just let go is still being deleted: busy either way.
            try:
                if time.time() - lock.stat().st_mtime > LOCK_STALE_S:
                    lock.unlink(missing_ok=True)
                    continue
            except OSError:
                continue
            if time.monotonic() > deadline:
                raise ClaimError("the claims board is busy; try again in a moment") from None
            time.sleep(LOCK_POLL_S)
    try:
        yield
    finally:
        _patiently(lambda: lock.unlink(missing_ok=True))


def read_board(path):
    """The claims on the board; [] when it is missing or unreadable."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    found = data.get("claims") if isinstance(data, dict) else None
    return [c for c in found if isinstance(c, dict) and c.get("what") and c.get("by")] if isinstance(found, list) else []


def _write_board(path, claims):
    path = Path(path)
    partial = Path(str(path) + ".partial")
    partial.write_text(json.dumps({"format": BOARD_FORMAT, "claims": claims}, indent=2, ensure_ascii=False) + "\n",
                       encoding="utf-8", newline="\n")
    _patiently(lambda: os.replace(partial, path))


def _hours(taken, now):
    try:
        then = datetime.fromisoformat(taken)
    except (TypeError, ValueError):
        return None
    return round((now - then).total_seconds() / 3600, 1)


def listed(path, now=None):
    """Every claim, oldest first, each with its age in hours and whether it is old."""
    now = _now(now)
    found = []
    for claim in sorted(read_board(path), key=lambda c: c.get("taken", "")):
        hours = _hours(claim.get("taken"), now)
        found.append({**claim, "hours": hours, "old": hours is not None and hours >= OLD_HOURS})
    return found


def _check_words(what, by):
    what, by = " ".join(str(what or "").split()), " ".join(str(by or "").split())
    if not what or len(what) > MAX_WORDS:
        raise ClaimError(f"name the thing in a few words (up to {MAX_WORDS} characters)")
    if not by or len(by) > MAX_WORDS:
        raise ClaimError("name the session with --by, as other sessions address it")
    return what, by


def take(path, what, by, note=None, now=None, force=False):
    """Holds a thing for a session; the same session taking it again refreshes it. Returns the claim."""
    what, by = _check_words(what, by)
    note = " ".join(str(note or "").split())[:MAX_NOTE] or None
    with _locked(path):
        claims = read_board(path)
        key = same_thing(what)
        held = next((c for c in claims if same_thing(c["what"]) == key), None)
        if held and held["by"] != by and not force:
            raise ClaimError(f"{held['what']} is held by {held['by']} since {held.get('taken', '?')}; ask them, or use --force "
                             "if that session has ended")
        claims = [c for c in claims if same_thing(c["what"]) != key]
        claim = {"what": what, "by": by, "taken": _now(now).isoformat(timespec="seconds")}
        if note:
            claim["note"] = note
        claims.append(claim)
        _write_board(path, claims)
    return claim


def release(path, what, by, force=False, everything=False):
    """Lets a thing go, or everything a session holds; returns the claims let go."""
    by = " ".join(str(by or "").split())
    if not by:
        raise ClaimError("name the session with --by")
    with _locked(path):
        claims = read_board(path)
        if everything:
            gone = [c for c in claims if c["by"] == by]
        else:
            what, by = _check_words(what, by)
            gone = [c for c in claims if same_thing(c["what"]) == same_thing(what)]
            if not gone:
                raise ClaimError(f"nobody holds {what}")
            if gone[0]["by"] != by and not force:
                raise ClaimError(f"{gone[0]['what']} is held by {gone[0]['by']}, not {by}; use --force if that session has ended")
        _write_board(path, [c for c in claims if c not in gone])
    return gone


def _parser():
    p = argparse.ArgumentParser(prog="claims", description=__doc__.split("\n\n")[0],
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="report", required=True)
    s = sub.add_parser("list", help="every claim, oldest first, with its age")
    t = sub.add_parser("take", help="holds a thing for a session")
    t.add_argument("what", help='the thing, in a few words ("phobos-modkit 1.44.0")')
    t.add_argument("--by", required=True, help="the session, as other sessions address it")
    t.add_argument("--note", help="what it is for, in a few words")
    t.add_argument("--force", action="store_true", help="take over a claim a session left behind")
    r = sub.add_parser("release", help="lets a thing go")
    r.add_argument("what", nargs="?", help="the thing, as it was taken")
    r.add_argument("--by", required=True, help="the session letting go")
    r.add_argument("--all", action="store_true", help="everything the session holds")
    r.add_argument("--force", action="store_true", help="let go of a claim another session left behind")
    for parser in (s, t, r):
        parser.add_argument("--json", action="store_true", help="print JSON instead of Markdown")
        parser.add_argument("--no-redact", action="store_true", help="show the home folder instead of ~")
    return p


def _age(hours):
    if hours is None:
        return "?"
    return f"{round(hours * 60)} min" if hours < 1 else f"{hours:g} h"


def main(argv=None, out=None, environ=None):
    out = out or sys.stdout
    try:
        args = _parser().parse_args(list(sys.argv[1:] if argv is None else argv))
    except SystemExit as stop:
        return EXIT_USAGE if stop.code else EXIT_OK
    redact = keep if args.no_redact else home_redactor()
    path = board_file(environ)

    def answer(report, data):
        out.write((envelope_text("claims", report, redact, data) if args.json else render_markdown(report, redact)) + "\n")

    try:
        if args.report == "take":
            claim = take(path, args.what, args.by, args.note, force=args.force)
            answer(Report(f"Claimed: {claim['what']}, by {claim['by']}"), {"ok": True, "claim": claim})
            return EXIT_OK
        if args.report == "release":
            if not args.all and not args.what:
                raise ClaimError("name the thing to let go, or --all")
            gone = release(path, args.what, args.by, args.force, args.all)
            report = Report(f"Released: {len(gone)}")
            if gone:
                report.section("Let go", Bullets([c["what"] for c in gone]))
            answer(report, {"ok": True, "released": gone})
            return EXIT_OK
    except ClaimError as refused:
        answer(Report("Refused"), {"ok": False, "refusal": str(refused)})
        return EXIT_REFUSED
    found = listed(path)
    report = Report(f"Claims: {len(found)} held" if found else "Claims: nothing held")
    if found:
        report.section("Held", Table(["What", "By", "For", "Note"],
                                     [[c["what"], c["by"], _age(c["hours"]) + (" (old)" if c["old"] else ""), c.get("note", "")]
                                      for c in found]))
    report.section("How", Bullets(["Before using a shared version number, test row or file: claims take WHAT --by SESSION.",
                                   "When it is committed: claims release WHAT --by SESSION."]))
    answer(report, {"board": str(path), "oldHours": OLD_HOURS, "claims": found})
    return EXIT_OK


MANIFEST = {"game": None, "parser": _parser, "effect": READS,
            "reports": {"list": {"question": "Which agent session is working on what?"},
                        "take": {"effect": WRITES, "note": "adds or refreshes one claim on the board"},
                        "release": {"effect": WRITES, "note": "removes a session's claims from the board"}}}
