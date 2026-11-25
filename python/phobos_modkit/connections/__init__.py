"""Connections: how a repository's code fits together, for every language a game's mods are written in.

One shape for every language (owner, 19 Nov 2026: "flow-charts and the such which show relationships between functions, classes,
etc."): things (a type, a method, a field, a function, a module, a Def) and the connections between them (calls, holds, builds on,
overrides, patches, uses, imports), each marked exact or by name. Four readers fill it:

- C#, exact, from the built assemblies (calls, fields, inheritance, overrides, Harmony patches), placed in the source by the code
  scanner; by name from the source where nothing is built (`csharp.py`).
- XML Defs, from the files: a Def's parent, the Defs it names and the C# classes it uses (`defs.py`).
- Lua, by name: Lua cannot be read exactly without running it (`lua.py`).
- Python, read by Python's own parser; calls by name (`pycode.py`).
- TypeScript and Svelte (`webcode.py`) and Rust (`rustcode.py`), by name, since 1.128.0; and the window's asks joined to the host's
  Tauri commands that answer them (`join_window_to_host`).

When the game is named and has a table of them (`data_names`, 1.117.0), a fifth adds the names that cross between its data
files and its code: the things its data files declare (a translation key, a data object) and what names each (`datanames.py`).

The graph is kept per repository in the kit's cache, rebuilt when any file it was read from changes.
"""
from __future__ import annotations

from contextlib import closing
from dataclasses import dataclass, field
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import time

from .. import cache as derived

CACHE_NAMESPACE = "connections"
SCHEMA = "2"   # 2 (1.128.0): TypeScript, Svelte and Rust
SKIP = {".git", "obj", "node_modules", "external", ".local", "target", "dist", "__pycache__", ".venv", "venv", "artifacts",
        ".claude", ".vs", ".idea"}
GROUP_LIMIT = 80

# Each connection kind, read both ways: what the thing in the middle does to others, and what others do to it.
RELATIONS = {
    "calls": ("calls", "called-by"),
    "holds": ("holds", "belongs-to"),
    "builds-on": ("builds-on", "built-on-by"),
    "overrides": ("overrides", "overridden-by"),
    "patches": ("patches", "patched-by"),
    "uses": ("uses", "used-by"),
    "imports": ("imports", "imported-by"),
}


class ConnectionsError(ValueError):
    """A request this tool refuses, with the reason in words."""


@dataclass
class Node:
    id: str                       # language-prefixed and unique: cs:Ns.Type.Method, def:ThingDef/Name, lua:Name, py:module.name
    name: str                     # what a person reads
    kind: str                     # type, class, interface, struct, enum, method, property, field, function, module, def
    language: str                 # csharp, xml, lua, python
    file: str = None              # in the repository, forward slashes
    line: int = None
    end: int = None
    owner: str = None             # the id of what holds it
    external: bool = False        # not this repository's: the game's, another mod's, a library's
    assembly: str = None


@dataclass
class Edge:
    source: str
    target: str
    kind: str                     # one of RELATIONS
    exact: bool = True


@dataclass
class Graph:
    nodes: dict = field(default_factory=dict)
    edges: list = field(default_factory=list)
    readers: list = field(default_factory=list)   # what each reader found, for the summary: {language, how, nodes, edges}

    def add(self, node):
        known = self.nodes.get(node.id)
        if known is None or (known.external and not node.external) or (known.file is None and node.file):
            self.nodes[node.id] = node
        return self.nodes[node.id]

    def ensure(self, node_id, name, kind, language, **fields):
        """A node, made as an outside one when no reader has placed it."""
        if node_id not in self.nodes:
            self.nodes[node_id] = Node(node_id, name, kind, language, external=True, **fields)
        return self.nodes[node_id]

    def link(self, source, target, kind, exact=True):
        if source != target:
            self.edges.append(Edge(source, target, kind, exact))


def source_files(root, suffixes):
    """Every file under root with one of these suffixes, skipping build, dependency and private folders, as (relative, path)."""
    root = Path(root)
    found = []
    for folder, folders, files in os.walk(root):
        folders[:] = sorted(f for f in folders if f not in SKIP and not f.startswith("."))
        for name in sorted(files):
            if name.lower().endswith(suffixes):
                path = Path(folder) / name
                found.append((path.relative_to(root).as_posix(), path))
    return found


def fingerprint(paths):
    digest = hashlib.sha256()
    for path in sorted({str(p) for p in paths}):
        try:
            stat = os.stat(path)
        except OSError:
            continue
        digest.update(f"{path}|{stat.st_size}|{stat.st_mtime_ns}\n".encode("utf-8"))
    return digest.hexdigest()


# ---------------------------------------------------------------- the store

def _cache_file(root, environ=None, settings=None, table=None):
    """One store a repository, and one more for each game whose table of data names it is read with."""
    root = Path(root).resolve()
    tag = hashlib.sha1(str(root).lower().encode("utf-8")).hexdigest()[:10]
    safe = re.sub(r"[^A-Za-z0-9._-]+", "-", root.name)
    game = f"-{re.sub(r'[^A-Za-z0-9]+', '', table.source)}" if table else ""
    return derived.folder(CACHE_NAMESPACE, None, environ, settings) / f"{safe}-{tag}{game}.sqlite"


def join_window_to_host(root, graph, environ=None):
    """Each window function that asks the host for a command, joined to the `#[tauri::command]` function that answers it, exactly:
    a command's name is one function's (1.128.0)."""
    from . import rustcode, webcode
    commands = rustcode.commands(root)
    if not commands:
        return None
    joined = 0
    for asker, command in webcode.asked(root):
        target = commands.get(command)
        if target and asker in graph.nodes and target in graph.nodes:
            graph.link(asker, target, "calls")
            joined += 1
    return f"exactly, by the command's name ({joined} asks joined)"


def _inputs(root, table=None):
    from . import csharp, datanames, defs, lua, pycode, rustcode, webcode
    found = (csharp.inputs(root) + defs.inputs(root) + lua.inputs(root) + pycode.inputs(root) + webcode.inputs(root)
             + rustcode.inputs(root))
    return found + (datanames.inputs(root, table) if table else [])


def read_graph(root, environ=None, progress=None, table=None):
    """Every reader's part of the graph, freshly read. `table` is a game's table of the names that cross between its data files
    and its code (`data_names.table_for`), read last, over what the others found."""
    from . import csharp, datanames, defs, lua, pycode, rustcode, webcode
    graph = Graph()
    steps = [("C#", csharp.read), ("XML Defs", defs.read), ("Lua", lua.read), ("Python", pycode.read),
             ("TypeScript and Svelte", webcode.read), ("Rust", rustcode.read), ("window to host", join_window_to_host)]
    if table:
        steps.append(("data names", lambda root, graph, environ: datanames.read(root, graph, environ, table)))
    for position, (label, reader) in enumerate(steps, 1):
        if progress:
            progress(f"Reading the {label} code", position, len(steps))
        before_nodes, before_edges = len(graph.nodes), len(graph.edges)
        how = reader(root, graph, environ)
        if how:
            graph.readers.append({"language": label, "how": how, "nodes": len(graph.nodes) - before_nodes,
                                  "edges": len(graph.edges) - before_edges})
    return graph


def open_graph(root, environ=None, settings=None, progress=None, rebuild=False, game=None):
    """The repository's graph in the cache, read again when any file it came from changed. Returns an open connection. With a
    `game` that has a table of data names, the graph holds those too, in a store of its own."""
    from .. import data_names
    root = Path(root).resolve()
    table = data_names.table_for(game)
    path = _cache_file(root, environ, settings, table)
    wanted = {"schema": SCHEMA, "inputs": fingerprint(_inputs(root, table))}
    if table:
        wanted["data_names"] = hashlib.sha1(table.sha.encode("utf-8")).hexdigest()
    if not rebuild and path.is_file():
        conn = sqlite3.connect(path)
        meta = dict(conn.execute("SELECT key, value FROM meta").fetchall()) if _has_meta(conn) else {}
        if all(meta.get(k) == v for k, v in wanted.items()):
            return conn
        conn.close()
    started = time.monotonic()
    graph = read_graph(root, environ, progress, table)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".building")
    derived.remove(temporary)
    with closing(sqlite3.connect(temporary)) as conn:
        conn.executescript("""
            CREATE TABLE nodes (id TEXT PRIMARY KEY, name TEXT, kind TEXT, language TEXT, file TEXT, line INTEGER, "end" INTEGER,
                                owner TEXT, external INTEGER, assembly TEXT);
            CREATE TABLE edges (source TEXT, target TEXT, kind TEXT, exact INTEGER);
            CREATE INDEX edges_source ON edges (source);
            CREATE INDEX edges_target ON edges (target);
            CREATE INDEX nodes_name ON nodes (name COLLATE NOCASE);
            CREATE INDEX nodes_file ON nodes (file);
        """)
        conn.executemany("INSERT INTO nodes VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                         [(n.id, n.name, n.kind, n.language, n.file, n.line, n.end, n.owner, int(n.external), n.assembly)
                          for n in graph.nodes.values()])
        unique = {(e.source, e.target, e.kind): e for e in graph.edges if e.source in graph.nodes and e.target in graph.nodes}
        conn.executemany("INSERT INTO edges VALUES (?, ?, ?, ?)",
                         [(e.source, e.target, e.kind, int(e.exact)) for e in unique.values()])
        derived.write_meta(conn, {**wanted, "readers": json.dumps(graph.readers), "seconds": f"{time.monotonic() - started:.2f}"})
        conn.commit()
    derived.remove(path)
    temporary.replace(path)
    return sqlite3.connect(path)


def _has_meta(conn):
    return conn.execute("SELECT 1 FROM sqlite_master WHERE name = 'meta'").fetchone() is not None


# ---------------------------------------------------------------- questions

NODE_COLUMNS = 'id, name, kind, language, file, line, "end", owner, external, assembly'


def _node(row):
    return {"id": row[0], "name": row[1], "kind": row[2], "language": row[3], "file": row[4], "line": row[5], "end": row[6],
            "owner": row[7], "external": bool(row[8]), "assembly": row[9]}


def node(conn, node_id):
    row = conn.execute(f"SELECT {NODE_COLUMNS} FROM nodes WHERE id = ?", (node_id,)).fetchone()
    return _node(row) if row else None


def degrees(conn, ids):
    """How many connections each of these things has, both ways."""
    found = {}
    for node_id in ids:
        found[node_id] = conn.execute("SELECT (SELECT COUNT(*) FROM edges WHERE source = ?) + (SELECT COUNT(*) FROM edges "
                                      "WHERE target = ?)", (node_id, node_id)).fetchone()[0]
    return found


def around(conn, node_id, limit=GROUP_LIMIT):
    """The thing and everything one connection away, grouped by relation: what it calls and what calls it, what holds it and what it
    holds, and so on. Each group lists up to `limit` things, with how many there are in all and whether every one is exact."""
    centre = node(conn, node_id)
    if centre is None:
        raise ConnectionsError(f"{node_id!r} is not in this repository's connections.")
    groups = []
    for kind, (outward, inward) in RELATIONS.items():
        for relation, sql in ((outward, "SELECT target, exact FROM edges WHERE source = ? AND kind = ?"),
                              (inward, "SELECT source, exact FROM edges WHERE target = ? AND kind = ?")):
            rows = conn.execute(sql, (node_id, kind)).fetchall()
            if not rows:
                continue
            others = [node(conn, other) for other, _ in rows]
            exact = {other: bool(flag) for other, flag in rows}
            others.sort(key=lambda n: (n["external"], n["name"].lower()))
            shown = others[:limit]
            counted = degrees(conn, [n["id"] for n in shown])
            groups.append({"relation": relation, "kind": kind, "outward": relation == outward, "count": len(others),
                           "exact": all(exact.values()),
                           "nodes": [{**n, "exact": exact[n["id"]], "connections": counted[n["id"]]} for n in shown]})
    return {"centre": {**centre, "connections": degrees(conn, [node_id])[node_id]}, "groups": groups}


def flow(conn, node_id, depth=2, limit=24):
    """Who calls the thing and what it calls, up to `depth` steps each way, as columns from the furthest caller to the furthest
    callee, with the calls between neighbouring columns: a flow chart's worth."""
    if node(conn, node_id) is None:
        raise ConnectionsError(f"{node_id!r} is not in this repository's connections.")
    columns = {0: [node_id]}
    seen = {node_id}
    edges = []
    for direction, sql, step in ((-1, "SELECT source, exact FROM edges WHERE target = ? AND kind = 'calls'", -1),
                                 (1, "SELECT target, exact FROM edges WHERE source = ? AND kind = 'calls'", 1)):
        frontier = [node_id]
        for level in range(1, depth + 1):
            found = []
            for current in frontier:
                for other, exact in conn.execute(sql, (current,)).fetchall()[:limit]:
                    source, target = (other, current) if direction < 0 else (current, other)
                    edges.append({"source": source, "target": target, "exact": bool(exact)})
                    if other not in seen and len(found) < limit:
                        seen.add(other)
                        found.append(other)
            if not found:
                break
            columns[level * step] = found
            frontier = found
    ordered = sorted(columns)
    nodes = {n: node(conn, n) for n in seen}
    return {"centre": node_id, "columns": [{"step": c, "nodes": [nodes[n] for n in columns[c]]} for c in ordered],
            "edges": [e for e in edges if e["source"] in nodes and e["target"] in nodes]}


def find(conn, pattern, kinds=(), top=60, ours_only=True):
    """Things whose name matches a pattern (* and ? as wildcards; plain text matches anywhere in the name)."""
    like = pattern.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_").replace("*", "%").replace("?", "_")
    if "%" not in like and "_" not in pattern.replace("\\_", ""):
        like = f"%{like}%"
    clauses, params = ["(name LIKE ? ESCAPE '\\' OR id LIKE ? ESCAPE '\\')"], [like, like]
    if kinds:
        clauses.append(f"kind IN ({', '.join('?' for _ in kinds)})")
        params += list(kinds)
    if ours_only:
        clauses.append("external = 0")
    rows = conn.execute(f"SELECT {NODE_COLUMNS} FROM nodes WHERE {' AND '.join(clauses)} ORDER BY length(name), name LIMIT ?",
                        (*params, top)).fetchall()
    return [_node(r) for r in rows]


def in_lines(conn, file, lines):
    """The innermost things declared over any of these lines of a file: what a change to those lines changed."""
    rows = conn.execute(f'SELECT {NODE_COLUMNS} FROM nodes WHERE file = ? AND line IS NOT NULL AND external = 0', (file,)).fetchall()
    found = {}
    for line in lines:
        holding = [r for r in rows if r[5] <= line <= (r[6] or r[5])]
        if holding:
            inner = min(holding, key=lambda r: (r[6] or r[5]) - r[5])
            found.setdefault(inner[0], [_node(inner), 0])[1] += 1
    return [{**n, "linesChanged": count} for n, count in found.values()]


def summary(conn):
    meta = dict(conn.execute("SELECT key, value FROM meta").fetchall())
    kinds = conn.execute("SELECT language, kind, COUNT(*) FROM nodes WHERE external = 0 GROUP BY language, kind "
                         "ORDER BY language, COUNT(*) DESC").fetchall()
    edges = conn.execute("SELECT kind, exact, COUNT(*) FROM edges GROUP BY kind, exact ORDER BY kind").fetchall()
    return {"readers": json.loads(meta.get("readers", "[]")), "seconds": float(meta.get("seconds", 0)),
            "things": [{"language": l, "kind": k, "count": c} for l, k, c in kinds],
            "connections": [{"kind": k, "exact": bool(e), "count": c} for k, e, c in edges]}
