"""Save checks for RimWorld: the rows the kit's check engine judges, read from a save (1.119.0).

A check's `select` chooses things from the save's index (by def, class, place or map, with * and ? as wildcards); its `read` names
values in each thing's own saved data by their path, as `rimworld-save thing` shows them. In a path `*` stands for any run of
characters within one step and `**` for any run across steps, so `PhobosWorkStore_Held/innerList/li[*]/stackCount` reads every
item's stack. A path with a wildcard reads a list, in save order; one without reads a single value, or None when it is not saved.

Two kinds of check need no rule of their own, because the adapter knows what to look for:

- `numbers`: any value saved as NaN or infinity under the paths named (default: every path naming Phobos), the mark of a division by
  nothing. RimWorld writes a float's NaN as "NaN" and its infinities as "Infinity" and "-Infinity".
- `references`: any value under the paths named that refers to a thing (RimWorld writes "Thing_" and the thing's ID) that is not in
  the save. The game drops such a reference when it loads, with an error in its log.
"""
from __future__ import annotations

import re

from ...checks import Expression, Row, judge, Result
from ...query import Filters
from . import save_thing

KINDS = ("numbers", "references")
DEFAULT_PATHS = "**Phobos**"
_REFERENCE = re.compile(r"Thing_(.+)")


def path_pattern(pattern):
    """A case-blind whole match: ** is any run, * any run within one step (no /), ? one character; the rest is literal."""
    out, i = [], 0
    while i < len(pattern):
        if pattern.startswith("**", i):
            out.append(".*")
            i += 2
        elif pattern[i] == "*":
            out.append("[^/]*")
            i += 1
        elif pattern[i] == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(pattern[i]))
            i += 1
    return re.compile("".join(out), re.IGNORECASE | re.DOTALL)


def has_wildcard(pattern):
    return "*" in pattern or "?" in pattern


def read_values(rows, read):
    """{name: value or list} from one thing's (path, value) rows: a path with a wildcard gives every match in save order."""
    found = {}
    for name, pattern in read.items():
        compiled = path_pattern(pattern)
        if has_wildcard(pattern):
            found[name] = [v for p, v in rows if compiled.fullmatch(p)]
        else:
            found[name] = next((v for p, v in rows if compiled.fullmatch(p)), None)
    return found


def select_things(conn, select):
    """The things a check's `select` names: (row id, thing ID, def, class, start, end, place, map, x, z), in index order."""
    unknown = sorted(set(select) - {"def", "class", "place", "map"})
    if unknown:
        raise ValueError("select takes def, class, place and map, not " + ", ".join(unknown))
    filters = Filters()
    filters.text("t.def", select.get("def"))
    filters.text("t.class", select.get("class"))
    filters.equal("pl.place", select.get("place"))
    filters.equal("t.map", select.get("map"))
    sql = ("SELECT t.id, t.thing_id, t.def, t.class, t.start, t.\"end\", pl.place, t.map, t.pos_x, t.pos_z "
           "FROM thing t LEFT JOIN thing_place pl ON pl.id = t.id" + filters.where + " ORDER BY t.id")
    return conn.execute(sql, filters.params).fetchall()


def where_text(place, map_, x, z):
    if place == "map" and x is not None:
        return f"map {map_} at {x}, {z}"
    return f"a {place}" if place else "elsewhere in the save"


class SaveReader:
    """One save's things, each read once however many checks ask for it."""

    def __init__(self, conn, save, meta):
        self.conn, self.save, self.meta = conn, save, meta
        self._values, self._ids = {}, None

    def values(self, thing):
        row_id, _, _, _, start, end = thing[:6]
        if row_id not in self._values:
            self._values[row_id] = save_thing.values_of(self.conn, self.save, self.meta, row_id, start, end)
        return self._values[row_id]

    def thing_ids(self):
        if self._ids is None:
            self._ids = {r[0].lower() for r in self.conn.execute("SELECT thing_id FROM thing WHERE thing_id IS NOT NULL")}
        return self._ids


def _rows_for(check, reader, things):
    rows = []
    paths = path_pattern(check.options.get("paths", DEFAULT_PATHS)) if check.kind in KINDS else None
    for thing in things:
        saved = reader.values(thing)
        label = f"{thing[1]}, {where_text(*thing[6:10])}"
        if check.kind == "numbers":
            values = {"bad": [p for p, v in saved if paths.fullmatch(p) and v.strip().lower() in
                              ("nan", "infinity", "-infinity", "∞", "-∞")]}
        elif check.kind == "references":
            known = reader.thing_ids()
            values = {"bad": [f"{p} = {v}" for p, v in saved if paths.fullmatch(p)
                              and (m := _REFERENCE.fullmatch(v.strip())) and m.group(1).lower() not in known]}
        else:
            values = read_values(saved, check.read)
        rows.append(Row(thing[1], label, values))
    return rows


_KIND_RULES = {
    "numbers": ("count(bad) > 0", "{count(bad)} values saved as NaN or infinity: {bad}"),
    "references": ("count(bad) > 0", "{count(bad)} references to things the save does not hold: {bad}"),
}


def run(conn, save, meta, checks):
    """A Result for each save check, in the file's order."""
    reader = SaveReader(conn, save, meta)
    results = []
    for check in checks:
        if check.kind in _KIND_RULES:
            fault, says = _KIND_RULES[check.kind]
            check.fault = check.fault or Expression(fault, check.id)
            check.says = check.says or says
        try:
            if not check.select:
                raise ValueError("it needs \"select\", saying which things to read (reading every thing would take minutes)")
            things = select_things(conn, check.select)
            results.append(judge(check, _rows_for(check, reader, things)))
        except (ValueError, save_thing.ThingError) as problem:
            results.append(Result(check, problem=str(problem)))
    return results
