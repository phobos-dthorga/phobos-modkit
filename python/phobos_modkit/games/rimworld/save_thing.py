"""One thing's saved data in full: every value its comps and mods wrote, read from the save itself.

The index keeps a few columns per thing (def, place, health) and, since 1.52.0, where the thing starts and ends in the
save file. This report reads only those bytes, so it answers in a moment even for a 300 MB save, and it reads the save
only while it is still the one the index was built from (its size and modification time unchanged).

What it shows, in our own words of how RimWorld writes a thing (read from 1.7 saves):

- a thing's comps write straight into its element, so their values sit beside <def>, each under the comp's own tags;
- a dictionary is written as <keys> and <values>, two lists in step: shown here as name[key], value;
- a list's items are each <li>: numbered here from 0, as li[0], li[1];
- things it holds (a vehicle's crew, a pawn's inventory and apparel) are things of their own, left out unless asked for.
"""
from __future__ import annotations

import re
import sqlite3
import xml.etree.ElementTree as ET

from ... import cache as derived
from ...report import Report, Section, Table

HELD = "phobos-held"  # an attribute no save writes: marks the stand-in for a held thing cut out before parsing


class ThingError(RuntimeError):
    pass


def _wildcard(pattern):
    """A case-blind whole match where * is any run and ? any one character; everything else, [ and ] included, is literal."""
    if not pattern:
        return None
    text = "".join(".*" if c == "*" else "." if c == "?" else re.escape(c) for c in pattern)
    return re.compile(text, re.IGNORECASE | re.DOTALL)


def _text(element):
    return (element.text or "").strip()


def _simple(element):
    return len(element) == 0


def _dictionary(element):
    """(keys, values) when the element is a saved dictionary: only <keys> and <values>, lists of equal length, simple keys."""
    if len(element) != 2 or [c.tag for c in element] != ["keys", "values"]:
        return None
    keys, values = list(element[0]), list(element[1])
    if len(keys) != len(values) or not all(k.tag == "li" and _simple(k) for k in keys):
        return None
    return [_text(k) for k in keys], values


def _children(node, path):
    """(child, its path) for each child: tags by name, list items numbered li[0], li[1]."""
    items = 0
    for child in node:
        if child.tag == "li":
            name, items = f"li[{items}]", items + 1
        else:
            name = child.tag
        yield child, f"{path}/{name}" if path else name


def flatten(element):
    """(path, value) for every value under element, in save order. Containers with nothing in them are left out."""
    rows = []

    def walk(node, path):
        if HELD in node.attrib:
            rows.append((path, f"held thing {node.get(HELD)} ({node.get('def')}), left out"))
            return
        for name, value in node.attrib.items():
            rows.append((f"{path}@{name}", value))
        found = _dictionary(node)
        if found is not None:
            for key, value in zip(*found):
                walk(value, f"{path}[{key}]")
        elif _simple(node):
            if _text(node):
                rows.append((path, _text(node)))
        else:
            for child, child_path in _children(node, path):
                walk(child, child_path)

    for child, path in _children(element, ""):
        walk(child, path)
    return rows


def _part(path):
    """The top-level tag a path starts with."""
    return re.split(r"[/\[@]", path, maxsplit=1)[0]


def _read_slice(save, meta, start, end):
    """The bytes from start to end of the save, refused unless it is still the file the index was built from."""
    def unchanged():
        stamp = derived.file_stamp(save)
        return all(meta.get(k) == v for k, v in stamp.items())

    if not unchanged():
        raise ThingError(f"{save.name} has been saved again since it was indexed. Run this again: the index is rebuilt "
                         f"first.")
    with open(save, "rb") as handle:
        handle.seek(start)
        data = handle.read(end - start)
    if not unchanged() or len(data) != end - start:
        raise ThingError(f"{save.name} changed while it was being read. Wait until the game has finished saving, then "
                         f"run this again.")
    return data


def _cut_held(data, start, held):
    """data with each held thing's bytes replaced by an empty element of the same tag naming it, so paths stay as saved."""
    for thing_id, def_, h_start, h_end in sorted(held, key=lambda h: h[2], reverse=True):
        a, b = h_start - start, h_end - start
        tag = re.match(rb"<([^\s/>]+)", data[a:b]) if 0 <= a < b <= len(data) else None
        if tag:
            stand_in = f'<{tag.group(1).decode("utf-8")} {HELD}="{thing_id}" def="{def_}" />'
            data = data[:a] + stand_in.encode("utf-8") + data[b:]
    return data


def thing(conn, save, meta, thing_id, path=None, value=None, include_held=False, top=50):
    """The Report for one thing's saved data. save is the .rws file the index was built from; meta is the index's meta."""
    try:
        row = conn.execute("""SELECT t.id, t.thing_id, t.def, t.class, t.start, t."end", pl.place, t.map, t.pos_x,
                                     t.pos_z, h.thing_id
                              FROM thing t LEFT JOIN thing_place pl ON pl.id = t.id LEFT JOIN thing h ON h.id = t.holder
                              WHERE t.thing_id = ? COLLATE NOCASE ORDER BY t.id LIMIT 1""", (thing_id,)).fetchone()
    except sqlite3.OperationalError as problem:  # an index built before 1.52.0 has no start or end
        if "no such column" in str(problem):
            raise ThingError("This index was built before things' places in the save were recorded. Run this again "
                             "with --rebuild.") from None
        raise
    report = Report(f"{thing_id}: what the save holds for it")
    if row is None:
        report.lines.append("No thing has that ID. IDs join the def and a number, as in Steel12345; find takes wildcards.")
        return report
    row_id, found_id, def_, cls, start, end, place, map_, x, z, holder = row
    if save is None:
        raise ThingError("This report reads the save itself, which an index read with --index alone does not give. "
                         "Name the save with --save.")
    if start is None or end is None:
        raise ThingError("The index does not say where this thing sits in the save. Run this again with --rebuild.")
    held = conn.execute("SELECT thing_id, def, start, \"end\" FROM thing WHERE holder = ? ORDER BY id",
                        (row_id,)).fetchall()
    data = _read_slice(save, meta, start, end)
    if not include_held:
        data = _cut_held(data, start, held)
    try:
        element = ET.fromstring(data)
    except ET.ParseError as problem:
        raise ThingError(f"Its part of the save could not be read as XML ({problem}).") from None
    rows = flatten(element)
    match_path, match_value = _wildcard(path), _wildcard(value)
    chosen = [r for r in rows if (match_path is None or match_path.fullmatch(r[0]))
              and (match_value is None or match_value.fullmatch(r[1]))]

    if holder:
        where = f"held by {holder}"
    elif place == "map" and x is not None:
        where = f"on map {map_} at {x}, {z}"
    else:
        where = f"a {place}" if place else "somewhere in the save"
    report.lines.append(f"{found_id}: {def_} ({cls or 'no class'}), {where}. Its part of the save is "
                        f"{(end - start) / 1024:,.1f} KB, holding {len(rows):,} values.")
    report.lines.append("Dictionaries show as name[key]; list items as li[0], li[1]; @Class is the type a value was "
                        "saved as. Narrow it with --path or --value (* and ? are wildcards; the whole path must match, "
                        "so write *charge*).")
    parts = {}
    for row_path, _ in rows:
        parts[_part(row_path)] = parts.get(_part(row_path), 0) + 1
    by_size = sorted(parts.items(), key=lambda p: (-p[1], p[0]))
    report.sections.append(Section("Its parts, by tag", [Table(["Tag", "Values"], by_size[:top], len(by_size))]))
    if held:
        report.sections.append(Section(
            "Things it holds" + (", included below" if include_held else ", left out (--held includes them)"),
            [Table(["ID", "Def"], [(h[0], h[1]) for h in held[:top]], len(held))]))
    report.sections.append(Section("Values" if not (path or value) else "Values that match",
                                   [Table(["Path", "Value"], chosen[:top], len(chosen))]))
    return report
