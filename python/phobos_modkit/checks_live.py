"""Live checks: the check engine over one snapshot of a running .NET program (1.120.0). Game-free.

Every live check in a file is answered from the same snapshot: each becomes one `values` request to the heap reader (the named
paths read from every object of its kind), the reader answers them all, then lets the snapshot go. A game's adapter names the
process, the install it trusts and how its objects are described; RimWorld's is `rimworld-perf look-check`. How checks are written:
`docs/checks.md`; the request: `docs/heap-reader.md`.
"""
from __future__ import annotations

import json
from pathlib import Path

from . import heap_reader as hr
from .checks import Result, Row, data, judge, notes_of, report
from .paths import cache_root
from .report import Fact, render_json

# Figures a live check notes (1.134.0): a snapshot is not kept, so its notes are kept here, one file a game, in the kit's cache,
# and test-pass reads them beside the game's own seen-in-play notes.
LIVE_NOTES_FOLDER = "live-notes"

SELECT_KEYS = ("type", "subclasses", "take", "items")
CAVEAT = ("Read from one snapshot of the running game: it paused for the moment the snapshot took, then ran on, and nothing was "
          "written to it. A snapshot holds what was in memory at that instant, garbage not yet collected included. A finding is a "
          "state the rules say should not happen; it is not an in-game test, and a check can be wrong.")
FROZEN_CAVEAT = ("Read from the running game frozen (1.132.0): it stood still while it was read, then ran on, and nothing was "
                 "written to it. What was in memory then is what was read, garbage not yet collected included. A finding is a "
                 "state the rules say should not happen; it is not an in-game test, and a check can be wrong.")


def request_for(check):
    """The heap reader's values request for one live check; ValueError says what its select lacks."""
    select = check.select or {}
    unknown = sorted(set(select) - set(SELECT_KEYS))
    if unknown:
        raise ValueError("select takes " + ", ".join(SELECT_KEYS) + ", not " + ", ".join(unknown))
    if not isinstance(select.get("type"), str) or not select["type"]:
        raise ValueError("select needs \"type\", the full name of the kind of object to read (as look lists it)")
    if not check.read:
        raise ValueError("it reads nothing: \"read\" names each value's field path")
    request = {"op": "values", "type": select["type"], "paths": list(dict.fromkeys(check.read.values())),
               "subclasses": bool(select.get("subclasses"))}
    for key in ("take", "items"):
        if isinstance(select.get(key), int) and select[key] > 0:
            request[key] = select[key]
    return request


def rows_of(check, data):
    """(rows, limits) from a values answer: one Row per object, and sentences on anything the reader left out."""
    rows, cut = [], 0
    for item in data.get("items", []):
        values = item.get("values") or {}
        label = item.get("summary") or f"{item.get('type') or data.get('type')} at {item.get('address')}"
        rows.append(Row(item.get("address", ""), label, {name: values.get(path) for name, path in check.read.items()}))
        cut += bool(item.get("cut"))
    limits = []
    if data.get("more"):
        limits.append(f"Read the first {data.get('take', 0):,} of {data.get('count', 0):,} objects of {data.get('type')}; "
                      "raise select's take to read more.")
    if cut:
        limits.append(f"On {cut:,} objects a list was cut at {data.get('itemLimit', 0):,} items; raise select's items to read more.")
    return rows, limits


def _asked(checks):
    """([(check, its request)], [a Result for each check that cannot ask])."""
    results, asked = [], []
    for check in checks:
        try:
            asked.append((check, request_for(check)))
        except ValueError as problem:
            results.append(Result(check, problem=str(problem)))
    return asked, results


def run(pid, runtime_folder, checks, describe=(), environ=None, run_requests=hr.run_requests, freeze=False):
    """(the reader's first line, a Result for each live check). One snapshot answers them all, or (freeze, 1.132.0) one read of
    the game frozen. Raises heap_reader.LookError when no snapshot could be taken."""
    asked, results = _asked(checks)
    if not asked:
        return {}, results
    requests = [request for _, request in asked]
    ready, answers = (run_requests(pid, runtime_folder, requests, describe, environ, freeze=True) if freeze
                      else run_requests(pid, runtime_folder, requests, describe, environ))
    return ready, _judged(checks, asked, answers, results)


def live_notes_path(game, environ=None, settings_file=None):
    """Where a game's live figure notes are kept (1.134.0): one JSON line a note, in the kit's cache."""
    return Path(cache_root(None, environ, settings_file)) / LIVE_NOTES_FOLDER / f"{game}.jsonl"


def keep_notes(results, path, version_of, time):
    """Adds every figure the live checks noted to the game's live notes (1.134.0), each as a seen-in-play note at <time> (when
    the game was read) with its mod's version from version_of(mod name), "0" when unknown. How many were kept."""
    notes = []
    for result in results:
        if result.check.note and not result.problem:
            notes.extend(notes_of(result, time, version_of(result.check.note["mod"]) or "0", "check", {"live": True}))
    if notes:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8", newline="\n") as fh:
            for note in notes:
                fh.write(json.dumps(note, ensure_ascii=False) + "\n")
    return len(notes)


def run_held(checks, ask):
    """A Result for each live check, asked of a snapshot already held (1.123.0, look-serve's checks request): ask(request) gives the
    reader's answer. Raises heap_reader.LookError when the snapshot is let go meanwhile."""
    asked, results = _asked(checks)
    return _judged(checks, asked, [ask(request) for _, request in asked], results)


def held_answer(checks, files, ask, redact=None, keep=None):
    """look-serve's checks answer (1.123.0): every live check asked of the snapshot held, as data for a program's page: the check
    data, and the report under "report" as a program reads any report. keep(results) (1.134.0) keeps the figures noted, and may
    give a line for the report."""
    results = run_held(checks, ask)
    report = checks_report(results, files)
    said = keep(results) if keep else None
    if said:
        report.lines.insert(1, said)
    return dict(data(results), report=render_json(report, redact))


def checks_report(results, files, frozen=False):
    """The live checks' report, naming the check files it ran."""
    return report("Live checks", results, facts=[Fact("Checks", ", ".join(files))], caveat=FROZEN_CAVEAT if frozen else CAVEAT)


def _judged(checks, asked, answers, results):
    for (check, _), answer in zip(asked, answers):
        if not answer.get("ok"):
            results.append(Result(check, problem=answer.get("error") or "The heap reader could not answer."))
            continue
        rows, limits = rows_of(check, answer.get("data") or {})
        results.append(judge(check, rows, limits))
    order = {c.id: n for n, c in enumerate(checks)}
    results.sort(key=lambda r: order[r.check.id])
    return results
