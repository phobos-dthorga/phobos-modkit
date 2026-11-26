"""test-pass: what a repository's in-game test list is waiting for, from the game's seen-in-play notes and the owner's verdicts.

    test-pass report --root REPO              rows waiting for the owner, rows the game has seen working, verdicts not yet written
    test-pass apply --root REPO               what apply would write into the test list (a preview)
    test-pass apply --root REPO --apply       write it
    test-pass apply --verdict "55:partial:the landing only" --apply
                                              write a verdict the owner gave in conversation
    test-pass code --root REPO                where the code notes each row's keys, and in which method (1.36.0)

The repository's config/test-evidence.json names the test list and maps rows to evidence: keys, narrowed by a case or the detail,
with the figures they should show, in parts, with rules on the order of notes. The notes file comes from --seen, or from the game the
config names (its adapter knows where the mod writes it). Verdicts come from --verdicts, the environment variable
PHOBOS_TEST_VERDICTS, a settings file's companionTestVerdictsPath, or D'thorga Companion's own folder; the owner's decisions on notes
no row names from --decisions, PHOBOS_TEST_KEY_DECISIONS, companionTestKeyDecisionsPath or the same folder. A note never passes a
row; only a verdict does. apply writes only inside the test list.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from importlib import import_module
import os
from pathlib import Path
import sys

from . import checks as check_engine, connections, testpass, testpass_code
from .progress import Progress
from .manifest import READS, WRITES
from .paths import COMPANION_ID, companion_data, resolve  # noqa: F401  (COMPANION_ID: read by callers)
from .report import Bullets, Report, Table, envelope_text, home_redactor, keep, render_markdown

EXIT_OK, EXIT_FAILED, EXIT_USAGE = 0, 1, 2
VERDICTS = ("companionTestVerdictsPath", "PHOBOS_TEST_VERDICTS")
DECISIONS = ("companionTestKeyDecisionsPath", "PHOBOS_TEST_KEY_DECISIONS")
_DECIDED = {"make-row": "make a row", "no-row": "no row needed"}




def verdicts_path(root, explicit=None, environ=None, settings=None):
    """The owner's verdicts for this repository: one JSON-lines file per repository, named after its folder."""
    default = companion_data(environ) / "test-verdicts" / f"{Path(root).resolve().name}.jsonl"
    return resolve(*VERDICTS, default, explicit, environ, settings)


def decisions_path(root, explicit=None, environ=None, settings=None):
    """The owner's decisions on notes no row names, beside the verdicts: one JSON-lines file per repository."""
    default = companion_data(environ) / "test-key-decisions" / f"{Path(root).resolve().name}.jsonl"
    return resolve(*DECISIONS, default, explicit, environ, settings)


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
        s.add_argument("--decisions", help="the owner's decisions on notes no row names (default: D'thorga Companion's)")
        s.add_argument("--settings", help="a JSON settings file naming paths")
        s.add_argument("--verdict", action="append", default=[], metavar="ROW:WORD[:NOTE]",
                       help="a verdict the owner gave in conversation (WORD passed, partial or failed; repeatable)")
        s.add_argument("--no-saves", action="store_true",
                       help="leave out the saves' histories, when the evidence map names them (1.121.0); faster")
        s.add_argument("--all", action="store_true", help="list every row, not only those waiting")
        s.add_argument("--top", type=int, default=40, help="rows per table (default 40)")
        s.add_argument("--json", action="store_true", help="print JSON instead of Markdown")
        s.add_argument("--no-redact", action="store_true", help="show the home folder instead of ~")
        if name == "apply":
            s.add_argument("--apply", action="store_true", help="write the test list; without it, only show what would change")
    s = sub.add_parser("code", help="where the code notes each row's keys, and in which method, function or type")
    s.add_argument("--root", help="the repository (default: the current folder)")
    s.add_argument("--top", type=int, default=40, help="places to list (default 40)")
    s.add_argument("--json", action="store_true", help="print JSON instead of Markdown")
    s.add_argument("--no-redact", action="store_true", help="show the home folder instead of ~")
    return p


def code_report(root, config, environ, top):
    """Where the code notes each row's keys: the places, and the keys the code never writes as the map names them."""
    conn = connections.open_graph(root, environ, None, Progress(environ))
    try:
        found = testpass_code.places(root, config, conn)
    finally:
        conn.close()
    missing = testpass_code.unplaced(config, found)
    rows = sorted({r for p in found for r in p["rows"]}, key=testpass_code._row_order)
    report = Report(f"Test list code: {len(found):,} places note keys for {len(rows):,} rows")
    report.section("Places", Table(["Key", "Where", "In", "Rows"],
                                   [[p["key"] + ("*" if p["prefix"] else ""), f"{p['file']}:{p['line']}",
                                     p["thing"]["name"] if p["thing"] else "-", ", ".join(p["rows"])] for p in found[:top]],
                                   total=len(found)))
    if missing:
        report.section("Keys no code writes as named", Bullets(missing[:top]))
    return report, {"doc": config["doc"], "places": found, "unplaced": missing}


def _version(version):
    return ".".join(str(n) for n in version)


def _figures(values):
    return ", ".join(f"{k} {v:g}" for k, v in sorted(values.items())) or "no figures"


def _note_data(note):
    return {"key": note.key, "time": note.time, "mod": note.mod, "version": note.version, "detail": note.detail, "on": note.on,
            "kind": note.kind, "variant": note.variant, "values": note.values, "tick": note.tick, "source": note.source or "game"}


def _kinds_words(kinds):
    """"1 kind: L-ATV", "2 kinds: L-ATV, M1075 HEMTT"."""
    return f"{len(kinds)} kind{'' if len(kinds) == 1 else 's'}: " + ", ".join(kinds)[:70]


def _parts_words(check):
    """"2 of 3: wet brakes, air filter" for a row in parts; empty for a row of one."""
    if check is None or len(check.parts) < 2:
        return ""
    return f"{len(check.seen_parts)} of {len(check.parts)}: " + ", ".join(p.name for p in check.seen_parts)


def _row_data(row, evidence):
    verdict = evidence.verdicts.get(row.id)
    check = evidence.checks.get(row.id)
    return {"id": row.id, "section": row.section, "title": row.title, "status": row.status,
            "cells": dict(zip(row.columns, row.cells)),
            "seen": [{"key": s.key, "first": s.first, "last": s.last, "count": s.count, "mod": s.mod, "version": s.version,
                      "detail": s.detail} for s in evidence.sightings(row.id)],
            "evidence_keys": evidence.keys(row.id),
            "parts": [] if check is None else [
                {"name": p.name, "state": p.state, "seen": len(p.good), "expected": p.expected,
                 "off": [_note_data(n) for n in p.off[-3:]], "stale": len(p.stale),
                 "stale_version": max((n.version for n in p.stale), key=lambda v: testpass.version_tuple(v) or (), default="")}
                for p in check.parts],
            "kinds": [] if check is None else check.kinds,
            "versions": {} if check is None else {m: _version(v) for m, v in sorted(check.versions.items())},
            "order_problems": [_order_data(o) for o in evidence.order if o.row == row.id],
            "verdict": None if verdict is None else {"verdict": verdict.verdict, "time": verdict.time, "note": verdict.note,
                                                     "via": verdict.via},
            "pending": evidence.pending(row)}


def _order_data(problem):
    return {"rule": problem.rule, "row": problem.row, "on": problem.on, "kind": problem.kind, "time": problem.time,
            "detail": problem.detail}


def _unrowed_data(evidence):
    rows = []
    for key in evidence.unmapped + sorted(k for k, d in evidence.decisions.items() if d.decision == "no-row" and k in evidence.seen):
        sighting, decision = evidence.seen[key], evidence.decisions.get(key)
        rows.append({"key": key, "count": sighting.count, "last": sighting.last, "detail": sighting.detail,
                     "decision": decision.decision if decision else None, "note": decision.note if decision else ""})
    return rows


def figure_checks(root, game):
    """(the repository's save checks that note figures, a sentence when its check file could not be read) (1.129.0). A broken
    check file never stops the report: its figures are left out, and the report says why."""
    path = Path(root) / check_engine.CHECK_FILE
    if not path.is_file():
        return [], None
    try:
        kinds = import_module(f".games.{game}.save_checks", __package__).KINDS
    except ImportError:
        return [], None
    try:
        return [c for c in check_engine.load_checks(path, "save", kinds) if c.note], None
    except check_engine.CheckError as error:
        return [], f"The figure checks were left out: {error}"


def saved_notes(config, environ, settings, skip=False, root=None):
    """(notes, saves read, sentences for the report): the saves' histories when the evidence map names them and the game's
    adapter reads them (1.121.0), with the figures the repository's save checks note in the same saves (1.129.0). A missing Saves
    folder or unreadable save is a sentence, not a failure: the game's own notes still count."""
    saved, game = config.get("saved"), config.get("game")
    if not saved or not game:
        return [], [], []
    if skip:
        return [], [], ["The saves' histories and figures were left out (--no-saves)."]
    try:
        adapter = import_module(f".games.{game}.saved_notes", __package__)
    except ImportError:
        return [], [], [f"The game {game} has no reader for saved histories, so its saves were not read."]
    figures, problem = figure_checks(root, game) if root else ([], None)
    sentences = [problem] if problem else []
    try:
        notes, read = adapter.for_test_pass(saved, environ, settings, Progress(environ), figures)
    except adapter.SavedError as error:
        raise testpass.TestPassError(f"{testpass.CONFIG}: {error}") from None
    except Exception as error:  # noqa: BLE001 - a save that cannot be read must not stop the report
        return [], [], sentences + [f"The saves' histories could not be read ({error})."]
    with_ledger = sum(1 for _, _, ledger in read if ledger)
    from_checks = sum(1 for note in notes if note.get("source") == "check")
    sentences.insert(0, f"{len(notes) - from_checks:,} notes read from the histories in the newest {len(read):,} saves"
                     + (f", and {from_checks:,} figures noted by {len(figures):,} save checks" if figures else "")
                     + (f"; {len(read) - with_ledger:,} of them hold no version ledger, so their notes count as stale for any row "
                        "naming a version" if with_ledger < len(read) else "") + ".")
    return notes, read, sentences


def build_report(evidence, changed=None, applied=False, everything=False, top=40, map_problems=()):
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
    if evidence.order:
        report.section("Out of order: a note came without the one that should come before it", Table(
            ["Rule", "Row", "On", "When", "Detail"],
            [[o.rule, o.row, o.kind or o.on, testpass.day(o.time), o.detail] for o in evidence.order[:top]], total=len(evidence.order)))
    if seen:
        report.section("Seen working, awaiting your word", Table(
            ["#", "Row", "Parts", "Last seen", "On", "Notes"],
            [[r.id, r.title, _parts_words(evidence.checks.get(r.id)),
              testpass.day(max(s.last for s in evidence.sightings(r.id))),
              _kinds_words(evidence.checks[r.id].kinds),
              ", ".join(s.key for s in evidence.sightings(r.id))] for r in seen[:top]], total=len(seen)))
    off = [(r, p) for r in waiting if r.id in evidence.checks for p in evidence.checks[r.id].parts if p.state == "off"]
    if off:
        report.section("Seen, but not with the figures the row expects", Table(
            ["#", "Row", "Part", "Last seen with", "Expects"],
            [[r.id, r.title, p.name or "the row", _figures(p.off[-1].values), "; ".join(p.expected)] for r, p in off[:top]],
            total=len(off)))
    stale = [(r, p) for r in waiting if r.id in evidence.checks for p in evidence.checks[r.id].parts if p.state == "stale"]
    if stale:
        report.section("Seen only before the row last changed", Table(
            ["#", "Row", "Part", "Last seen on", "The row names"],
            [[r.id, r.title, p.name or "the row", f"{p.stale[-1].mod} {p.stale[-1].version}",
              ", ".join(f"{m} {_version(v)}" for m, v in sorted(evidence.checks[r.id].versions.items()))]
             for r, p in stale[:top]], total=len(stale)))
    if unwritten:
        report.section("Verdicts not yet in the test list", Table(
            ["#", "Row", "Verdict", "When", "Note"],
            [[r.id, r.title, evidence.verdicts[r.id].verdict, testpass.day(evidence.verdicts[r.id].time), evidence.verdicts[r.id].note]
             for r in unwritten[:top]], total=len(unwritten)))
    listed = rows if everything else [r for r in waiting if r not in seen]
    if listed:
        report.section("Every row" if everything else "Still waiting, nothing seen yet", Table(
            ["#", "Row", "Status", "Section"], [[r.id, r.title, r.status, r.section] for r in listed[:top]], total=len(listed)))
    if evidence.unmapped:
        report.section("Notes no row names", Table(
            ["Key", "Notes", "Last seen", "Last detail", "Your word"],
            [[k, f"{evidence.seen[k].count:,}", testpass.day(evidence.seen[k].last), evidence.seen[k].detail,
              _DECIDED.get(evidence.decisions[k].decision, "") if k in evidence.decisions else ""] for k in evidence.unmapped[:top]],
            total=len(evidence.unmapped)))
    notes = []
    if map_problems:
        notes.extend(f"Evidence map: {problem}." for problem in map_problems)
    if evidence.unchecked_order:
        notes.append(f"{evidence.unchecked_order:,} notes an order rule names say nothing of what they were seen on (written before "
                     "notes did) and could not be checked.")
    if evidence.unreadable:
        notes.append(f"{evidence.unreadable:,} note, verdict or decision lines could not be read and were skipped.")
    if notes:
        report.section("Left out", Bullets(notes))
    return report


def main(argv=None, environ=None, out=None, now=None):
    out = out or sys.stdout
    environ = os.environ if environ is None else environ
    try:
        args = _parser().parse_args(list(sys.argv[1:] if argv is None else argv))
    except SystemExit as stop:
        return EXIT_USAGE if stop.code else EXIT_OK
    redact = keep if args.no_redact else home_redactor()
    root = Path(args.root or ".").resolve()
    if args.report == "code":
        try:
            report, data = code_report(root, testpass.load_config(root), environ, args.top)
        except (testpass.TestPassError, connections.ConnectionsError) as error:
            print(redact(str(error)), file=sys.stderr)
            return EXIT_USAGE
        out.write((envelope_text("test-pass", report, redact, data) if args.json else render_markdown(report, redact)) + "\n")
        return EXIT_OK
    try:
        config = testpass.load_config(root)
        seen = seen_paths(config, args.seen, environ, args.settings)
        verdicts = verdicts_path(root, args.verdicts, environ, args.settings)
        decisions = decisions_path(root, args.decisions, environ, args.settings)
        stamp = (now or datetime.now(timezone.utc)).isoformat()
        given = [testpass.parse_verdict(text, stamp) for text in args.verdict]
        from_saves, saves_read, saves_sentences = saved_notes(config, environ, args.settings, args.no_saves, root)
        evidence = testpass.gather(root, seen, [verdicts], config, given, [decisions], from_saves)
        problems = testpass.map_problems(config)
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
    report = build_report(evidence, changed, bool(getattr(args, "apply", False)), args.all, args.top, problems)
    for n, sentence in enumerate(saves_sentences):
        report.lines.insert(2 + n, sentence)
    data = {"doc": config["doc"], "seen_files": [str(p) for p in seen], "verdicts_file": str(verdicts),
            "decisions_file": str(decisions), "rows": [_row_data(r, evidence) for r in evidence.rows],
            "order_problems": [_order_data(o) for o in evidence.order], "unchecked_order": evidence.unchecked_order,
            "unrowed": _unrowed_data(evidence), "map_problems": problems,
            "saves_read": [{"save": name, "notes": count, "ledger": ledger} for name, count, ledger in saves_read]}
    out.write((envelope_text("test-pass", report, redact, data) if args.json else render_markdown(report, redact)) + "\n")
    return EXIT_OK


MANIFEST = {"game": None, "parser": _parser, "effect": READS,
            "reports": {"report": {"question": "Which in-game tests are waiting for me, and which has the game seen working?"},
                        "apply": {"effect": WRITES, "when": "--apply"},
                        "code": {"note": "where the code notes each row's keys; for a program joining rows to code"}}}
