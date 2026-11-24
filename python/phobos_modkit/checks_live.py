"""Live checks: the check engine over one snapshot of a running .NET program (1.120.0). Game-free.

Every live check in a file is answered from the same snapshot: each becomes one `values` request to the heap reader (the named
paths read from every object of its kind), the reader answers them all, then lets the snapshot go. A game's adapter names the
process, the install it trusts and how its objects are described; RimWorld's is `rimworld-perf look-check`. How checks are written:
`docs/checks.md`; the request: `docs/heap-reader.md`.
"""
from __future__ import annotations

from . import heap_reader as hr
from .checks import Result, Row, judge

SELECT_KEYS = ("type", "subclasses", "take", "items")
CAVEAT = ("Read from one snapshot of the running game: it paused for the moment the snapshot took, then ran on, and nothing was "
          "written to it. A snapshot holds what was in memory at that instant, garbage not yet collected included. A finding is a "
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


def run(pid, runtime_folder, checks, describe=(), environ=None, run_requests=hr.run_requests):
    """(the reader's first line, a Result for each live check). One snapshot answers them all. Raises heap_reader.LookError when
    no snapshot could be taken."""
    results, asked = [], []
    for check in checks:
        try:
            asked.append((check, request_for(check)))
        except ValueError as problem:
            results.append(Result(check, problem=str(problem)))
    if not asked:
        return {}, results
    ready, answers = run_requests(pid, runtime_folder, [request for _, request in asked], describe, environ)
    for (check, _), answer in zip(asked, answers):
        if not answer.get("ok"):
            results.append(Result(check, problem=answer.get("error") or "The heap reader could not answer."))
            continue
        rows, limits = rows_of(check, answer.get("data") or {})
        results.append(judge(check, rows, limits))
    order = {c.id: n for n, c in enumerate(checks)}
    results.sort(key=lambda r: order[r.check.id])
    return ready, results
