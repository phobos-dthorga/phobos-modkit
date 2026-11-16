"""test-pass: what a repository's in-game test list is waiting for, from the game's seen-in-play notes and the owner's verdicts.

    test-pass report --root REPO              rows waiting for the owner, rows the game has seen working, verdicts not yet written
    test-pass apply --root REPO               what apply would write into the test list (a preview)
    test-pass apply --root REPO --apply       write it

The repository's config/test-evidence.json names the test list and maps rows to evidence. The notes file comes from --seen, or
from the game the config names (its adapter knows where the mod writes it). Verdicts come from --verdicts, the environment
variable PHOBOS_TEST_VERDICTS, a settings file's companionTestVerdictsPath, or D'thorga Companion's own folder. A note never
passes a row; only a verdict does. apply writes only inside the test list.
"""
from __future__ import annotations

import argparse
from importlib import import_module
import os
from pathlib import Path
import sys

from . import testpass
from .manifest import READS, WRITES
from .paths import resolve
from .report import Bullets, Report, Table, envelope_text, home_redactor, keep, render_markdown

EXIT_OK, EXIT_FAILED, EXIT_USAGE = 0, 1, 2
VERDICTS = ("companionTestVerdictsPath", "PHOBOS_TEST_VERDICTS")
COMPANION_ID = "org.phobosdthorga.companion"


def companion_data(environ=None):
    """D'thorga Companion's own data folder, where Tauri keeps an app's local data."""
    environ = os.environ if environ is None else environ
    if sys.platform == "win32" and environ.get("LOCALAPPDATA"):
        return Path(environ["LOCALAPPDATA"]) / COMPANION_ID
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / COMPANION_ID
    return Path(environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share") / COMPANION_ID


def verdicts_path(root, explicit=None, environ=None, settings=None):
    """The owner's verdicts for this repository: one JSON-lines file per repository, named after its folder."""
    default = companion_data(environ) / "test-verdicts" / f"{Path(root).resolve().name}.jsonl"
    return resolve(*VERDICTS, default, explicit, environ, settings)


def seen_paths(config, explicit, environ=None, settings=None):
    if explicit:
        return [Path(p) for p in explicit]
    game = config.get("game")
    if not game:
        return []
    try:
        paths = import_module(f".games.{game}.paths", __package__)
    except ImportError:
        return []
    finder = getattr(paths, "seen_in_play_path", None)
    return [Path(finder(None, environ, settings))] if finder else []


def _parser():
    p = argparse.ArgumentParser(prog="test-pass", description=__doc__.split("\n\n")[0],
                                formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__.split("\n\n", 1)[1])
    sub = p.add_subparsers(dest="report", required=True)
    for name, helptext in (("report", "rows waiting for the owner, rows seen working, verdicts not yet written"),
                           ("apply", "write verdicts and seen-working notes into the test list; a preview without --apply")):
        s = sub.add_parser(name, help=helptext)
        s.add_argument("--root", help="the repository (default: the current folder)")
        s.add_argument("--seen", action="append", help="a seen-in-play notes file (repeatable; default: from the config's game)")
        s.add_argument("--verdicts", help="the owner's verdicts file (default: D'thorga Companion's, for this repository)")
        s.add_argument("--settings", help="a JSON settings file naming paths")
        s.add_argument("--all", action="store_true", help="list every row, not only those waiting")
        s.add_argument("--top", type=int, default=40, help="rows per table (default 40)")
        s.add_argument("--json", action="store_true", help="print JSON instead of Markdown")
        s.add_argument("--no-redact", action="store_true", help="show the home folder instead of ~")
        if name == "apply":
            s.add_argument("--apply", action="store_true", help="write the test list; without it, only show what would change")
    return p


def _row_data(row, evidence):
    verdict = evidence.verdicts.get(row.id)
    return {"id": row.id, "section": row.section, "title": row.title, "status": row.status,
            "cells": dict(zip(row.columns, row.cells)),
            "seen": [{"key": s.key, "first": s.first, "last": s.last, "count": s.count, "mod": s.mod, "version": s.version,
                      "detail": s.detail} for s in evidence.sightings(row.id)],
            "evidence_keys": evidence.mapping.get(row.id, []),
            "verdict": None if verdict is None else {"verdict": verdict.verdict, "time": verdict.time, "note": verdict.note},
            "pending": evidence.pending(row)}


def build_report(evidence, changed=None, applied=False, everything=False, top=40):
    rows = evidence.rows
    waiting = [r for r in rows if r.status in ("open", "partial", "seen") and r.id not in evidence.verdicts]
    seen = [r for r in waiting if evidence.sightings(r.id)]
    unwritten = [r for r in rows if r.id in evidence.verdicts and evidence.pending(r)]
    if changed is None:
        title = (f"Test pass: {len(waiting):,} rows waiting for the owner, {len(seen):,} seen working, "
                 f"{len(unwritten):,} verdicts not yet written")
    else:
        title = f"Test pass: {len(changed):,} rows {'written' if applied else 'to write (preview)'}"
    report = Report(title)
    report.lines.append(f"{len(rows):,} rows in the test list; {sum(r.status == 'passed' for r in rows):,} passed, "
                        f"{sum(r.status == 'partial' for r in rows):,} passed in part, {sum(r.status == 'failed' for r in rows):,} failed.")
    report.lines.append("A seen-working note says a feature ran without an error, never that it looked right; only the owner's "
                        "verdict passes a row.")
    if changed is not None:
        if changed:
            report.section("Written" if applied else "Would write", Table(
                ["#", "Row", "Adds"], [[r.id, r.title, sentence] for r, sentence in changed[:top]], total=len(changed)))
        else:
            report.lines.append("Nothing to write: every verdict and sighting is already in the test list.")
        if not applied and changed:
            report.lines.append("**Preview only. Add --apply to write the test list.**")
        return report
    if seen:
        report.section("Seen working, awaiting your word", Table(
            ["#", "Row", "Last seen", "On", "Notes"],
            [[r.id, r.title, testpass.day(max(s.last for s in evidence.sightings(r.id))),
              "; ".join(sorted({s.detail for s in evidence.sightings(r.id) if s.detail}))[:80],
              ", ".join(s.key for s in evidence.sightings(r.id))] for r in seen[:top]], total=len(seen)))
    if unwritten:
        report.section("Verdicts not yet in the test list", Table(
            ["#", "Row", "Verdict", "When", "Note"],
            [[r.id, r.title, evidence.verdicts[r.id].verdict, testpass.day(evidence.verdicts[r.id].time), evidence.verdicts[r.id].note]
             for r in unwritten[:top]], total=len(unwritten)))
    listed = rows if everything else [r for r in waiting if r not in seen]
    if listed:
        report.section("Every row" if everything else "Still waiting, nothing seen yet", Table(
            ["#", "Row", "Status", "Section"], [[r.id, r.title, r.status, r.section] for r in listed[:top]], total=len(listed)))
    notes = []
    if evidence.unmapped:
        notes.append("Seen keys no row names: " + ", ".join(evidence.unmapped[:10]) + ".")
    if evidence.unreadable:
        notes.append(f"{evidence.unreadable:,} note or verdict lines could not be read and were skipped.")
    if notes:
        report.section("Left out", Bullets(notes))
    return report


def main(argv=None, environ=None, out=None):
    out = out or sys.stdout
    environ = os.environ if environ is None else environ
    try:
        args = _parser().parse_args(list(sys.argv[1:] if argv is None else argv))
    except SystemExit as stop:
        return EXIT_USAGE if stop.code else EXIT_OK
    redact = keep if args.no_redact else home_redactor()
    root = Path(args.root or ".").resolve()
    try:
        config = testpass.load_config(root)
        seen = seen_paths(config, args.seen, environ, args.settings)
        verdicts = verdicts_path(root, args.verdicts, environ, args.settings)
        evidence = testpass.gather(root, seen, [verdicts], config)
    except testpass.TestPassError as error:
        print(redact(str(error)), file=sys.stderr)
        return EXIT_USAGE
    changed = None
    if args.report == "apply":
        doc = root / config["doc"]
        text = doc.read_text(encoding="utf-8")
        written, changed = testpass.apply_to_text(text, evidence)
        if args.apply and changed:
            with open(doc, "w", encoding="utf-8", newline="") as fh:
                fh.write(written)
    report = build_report(evidence, changed, bool(getattr(args, "apply", False)), args.all, args.top)
    data = {"doc": config["doc"], "seen_files": [str(p) for p in seen], "verdicts_file": str(verdicts),
            "rows": [_row_data(r, evidence) for r in evidence.rows]}
    out.write((envelope_text("test-pass", report, redact, data) if args.json else render_markdown(report, redact)) + "\n")
    return EXIT_OK


MANIFEST = {"game": None, "parser": _parser, "effect": READS,
            "reports": {"report": {"question": "Which in-game tests are waiting for me, and which has the game seen working?"},
                        "apply": {"effect": WRITES, "when": "--apply"}}}
