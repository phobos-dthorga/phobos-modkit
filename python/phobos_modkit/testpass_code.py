"""Where the code notes each test row's evidence: the code side of a test list (1.36.0).

A test list's evidence map names, for each row, the keys of the seen-in-play notes that stand for it; the game writes a note with
that key, as a string in the call, where the feature happens. This finds every such string in the repository's code, places it in
the method, function or type whose lines hold it (phobos-modkit's connections), and says which rows it stands for. A key the code
builds at run time is found by its prefix, as the map's `prefixes` name it.

Only C#, Lua and Python are read, and never a folder named `tests` or `test`: a test that names a key is not where the game notes
it. It reads the code as text, so a key written in a comment counts too; the map's own checks keep comments rare.
"""
from __future__ import annotations

import re
from pathlib import Path

from . import connections
from . import testpass

SUFFIXES = (".cs", ".lua", ".py")
TEST_FOLDERS = frozenset({"tests", "test"})
STRING = re.compile(r'"([^"\\\r\n]{1,200})"')


def rows_by_key(config):
    """Every key the map names, with the rows it stands for, in row order."""
    found = {}
    for row, parts in testpass.parse_mapping(config).items():
        for part in parts:
            for item in part.items:
                rows = found.setdefault(item.key, [])
                if row not in rows:
                    rows.append(row)
    for rule in testpass.parse_order(config):
        for item in (rule.first, rule.then):
            rows = found.setdefault(item.key, [])
            if rule.row and rule.row not in rows:
                rows.append(rule.row)
    return found


def _files(root):
    return [(relative, path) for relative, path in connections.source_files(root, SUFFIXES)
            if not TEST_FOLDERS & set(Path(relative).parts[:-1])]


def _matches(text, keys, prefixes):
    """(line, key or prefix) for every string in the text that is a mapped key or starts with a mapped prefix."""
    found = []
    starts = [0]
    for match in re.finditer("\n", text):
        starts.append(match.end())
    line = 0
    for match in STRING.finditer(text):
        while line + 1 < len(starts) and starts[line + 1] <= match.start():
            line += 1
        value = match.group(1)
        if value in keys:
            found.append((line + 1, value))
        else:
            prefix = next((p for p in prefixes if value.startswith(p)), None)
            if prefix:
                found.append((line + 1, prefix))
    return found


def places(root, config, conn):
    """Every place the code notes a mapped key: {key, prefix, file, line, thing, rows}, by file and line."""
    by_key = rows_by_key(config)
    prefixes = sorted(config.get("prefixes") or {}, key=len, reverse=True)
    found = []
    for relative, path in _files(root):
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if '"' not in text:
            continue
        for line, key in dict.fromkeys(_matches(text, by_key, prefixes)):
            is_prefix = key not in by_key
            rows = sorted({r for k, rs in by_key.items() if k.startswith(key) for r in rs}, key=_row_order) if is_prefix \
                else by_key[key]
            holding = connections.in_lines(conn, relative, [line])
            thing = {k: holding[0][k] for k in ("id", "name", "kind")} if holding else None
            found.append({"key": key, "prefix": is_prefix, "file": relative, "line": line, "thing": thing, "rows": rows})
    return found


def _row_order(row):
    return (0, int(row), "") if row.isdigit() else (1, 0, row)


def unplaced(config, found):
    """Keys the map names that no string in the code matches, by key: rows whose notes the code never writes as written."""
    seen = {p["key"] for p in found}
    prefixes = tuple(config.get("prefixes") or {})
    return sorted(k for k in rows_by_key(config) if k not in seen and not any(k.startswith(p) for p in prefixes if p in seen))
