"""One SQLite index per C# source tree (a "corpus"), kept in the kit's cache and rebuilt when its files change.

A corpus is a folder (every .cs file under it) or a single .cs file. Its index holds the files and every declaration
scan.declarations finds, with provenance in the meta table: the root, a digest of every file's path, size and time,
the index format and the kit's version. Queries read the indexes; finding uses reads the source files themselves.
"""
from __future__ import annotations

from contextlib import closing
from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import re
import sqlite3
import threading
import time

from .. import __version__
from .. import cache as derived
from .. import file_lock
from ..query import like
from .scan import declarations

INDEX_FORMAT = "1"
CACHE_FOLDER = "code-index"
SKIPPED_PARTS = {"obj", "bin", ".git", ".vs"}
TYPE_KINDS = ("class", "struct", "interface", "enum", "record", "delegate")
# Two runs building one index at once (1.141.1): each writes its own half-built file, named with its process and thread, so
# neither deletes the other's; the build lock only saves the second run the work. One corpus builds in seconds, so a lock
# older than BUILD_STALE_S was left by a run that stopped, and a run waits a little longer than that before giving up.
BUILD_STALE_S = 5 * 60
BUILD_WAIT_S = BUILD_STALE_S + 60


class CodeError(ValueError):
    pass


@dataclass(frozen=True)
class Corpus:
    name: str
    root: Path

    def files(self):
        """Every .cs file of the corpus, as (relative POSIX path, absolute path), sorted."""
        root = Path(self.root)
        if root.is_file():
            return [(root.name, root)]
        if not root.is_dir():
            raise CodeError(f"{self.name}: no folder or file at {root}")
        found = []
        for path in root.rglob("*.cs"):
            if SKIPPED_PARTS.isdisjoint(path.relative_to(root).parts[:-1]):
                found.append((path.relative_to(root).as_posix(), path))
        return sorted(found)


def fingerprint(files):
    digest = hashlib.sha256()
    for relative, path in files:
        info = path.stat()
        digest.update(f"{relative}|{info.st_size}|{info.st_mtime_ns}\n".encode())
    return digest.hexdigest()[:derived.DIGEST_LENGTH]


def index_path(cache, corpus):
    key = hashlib.sha256(str(Path(corpus.root).resolve()).lower().encode()).hexdigest()[:10]
    safe = re.sub(r"[^A-Za-z0-9._-]+", "-", corpus.name)[:60]
    return Path(cache) / f"{safe}-{key}.sqlite"


def provenance(corpus, files):
    return {"index_format": INDEX_FORMAT, "kit_version": __version__, "root": str(Path(corpus.root).resolve()),
            "source_digest": fingerprint(files)}


SCHEMA = """
CREATE TABLE files (id INTEGER PRIMARY KEY, path TEXT NOT NULL, lines INTEGER NOT NULL);
CREATE TABLE decls (id INTEGER PRIMARY KEY, file INTEGER NOT NULL, kind TEXT NOT NULL, name TEXT NOT NULL,
                    owner TEXT NOT NULL, full TEXT NOT NULL, signature TEXT NOT NULL, start INTEGER NOT NULL,
                    "end" INTEGER NOT NULL);
CREATE INDEX decls_name ON decls (name COLLATE NOCASE);
CREATE INDEX decls_full ON decls (full COLLATE NOCASE);
CREATE INDEX decls_owner ON decls (owner COLLATE NOCASE);
CREATE INDEX decls_file ON decls (file, start);
"""


def _building_name(target):
    return target.with_name(f"{target.stem}.{os.getpid()}-{threading.get_ident()}.building")


def _discard(path):
    """Delete a half-built file; False when another run still holds it, which is never an error."""
    try:
        derived.remove(path)
        return True
    except OSError:
        return False


def leftovers(target, older_than_s=BUILD_STALE_S, now=time.time):
    """Half-built files of this index (and their journals) not touched for older_than_s: what a run that stopped left behind."""
    target = Path(target)
    found = []
    for pattern in (f"{target.stem}.building*", f"{target.stem}.*.building*"):
        for path in target.parent.glob(pattern):
            try:
                if now() - path.stat().st_mtime > older_than_s:
                    found.append(path)
            except OSError:
                continue
    return sorted(set(found))


def _put_in_place(temporary, target):
    try:
        temporary.replace(target)
    except PermissionError:
        derived.remove(target)      # an index marked read-only can be deleted, not replaced
        temporary.replace(target)


def build(corpus, target, files=None):
    """Index the corpus into target (replacing it). Returns (files, declarations, seconds)."""
    started = time.monotonic()
    files = corpus.files() if files is None else files
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = _building_name(target)
    _discard(temporary)
    count = 0
    try:
        with closing(sqlite3.connect(temporary)) as conn:
            conn.executescript(SCHEMA)
            for file_id, (relative, path) in enumerate(files, 1):
                text = path.read_text(encoding="utf-8", errors="replace")
                found = declarations(text)
                conn.execute("INSERT INTO files VALUES (?, ?, ?)", (file_id, relative, text.count("\n") + 1))
                conn.executemany("INSERT INTO decls (file, kind, name, owner, full, signature, start, \"end\") "
                                 "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                                 [(file_id, d.kind, d.name, d.owner, d.full, d.signature, d.start, d.end) for d in found])
                count += len(found)
            derived.write_meta(conn, {**provenance(corpus, files), "files": len(files), "declarations": count})
            conn.commit()
        try:
            file_lock.patiently(lambda: _put_in_place(temporary, target))
        except PermissionError:
            raise CodeError(f"{corpus.name}: another program held {target.name} for over a second, so its new index could "
                            f"not replace it. Run this again.") from None
    finally:
        _discard(temporary)
    return len(files), count, time.monotonic() - started


def _stamp(path):
    try:
        info = Path(path).stat()
        return info.st_size, info.st_mtime_ns
    except OSError:
        return None


def ensure(corpus, cache, rebuild=False, waiting=None):
    """The corpus's current index, building it when missing, stale or asked for. Returns (path, built: bool).

    One run builds an index at a time; another run wanting it waits, then uses what the first built. `waiting(corpus)` is
    called when this run has to wait.
    """
    target = index_path(cache, corpus)
    files = corpus.files()
    expected = provenance(corpus, files)
    if not rebuild and derived.is_current(target, expected):
        return target, False
    before = _stamp(target)
    if waiting and target.with_name(target.name + ".lock").exists():
        waiting(corpus)
    with derived.one_builder(target, CodeError, BUILD_WAIT_S, BUILD_STALE_S):
        # The run this one waited for may have just built it, a rebuild included.
        if derived.is_current(target, expected) and (not rebuild or _stamp(target) != before):
            return target, False
        for leftover in leftovers(target):
            _discard(leftover)
        build(corpus, target, files)
    return target, True


# ---- Queries ----

@dataclass
class Hit:
    corpus: str
    path: str               # relative to the corpus root
    kind: str
    full: str
    signature: str
    start: int
    end: int


def _rows(conn, corpus, sql, params):
    return [Hit(corpus, *row) for row in conn.execute(sql, params).fetchall()]


SELECT = ('SELECT f.path, d.kind, d.full, d.signature, d.start, d."end" FROM decls d JOIN files f ON f.id = d.file ')


def find(path, corpus, pattern, kinds=(), top=None):
    """Declarations whose name or full name matches the wildcard pattern."""
    clauses, params = ["(d.name LIKE ? ESCAPE '\\' OR d.full LIKE ? ESCAPE '\\')"], [like(pattern)] * 2
    if kinds:
        clauses.append(f"d.kind IN ({', '.join('?' * len(kinds))})")
        params += list(kinds)
    sql = SELECT + "WHERE " + " AND ".join(clauses) + " ORDER BY d.full COLLATE NOCASE, f.path, d.start"
    if top:
        sql += f" LIMIT {int(top) + 1}"
    with closing(derived.open_read_only(path)) as conn:
        return _rows(conn, corpus, sql, params)


def resolve(path, corpus, name, kinds=()):
    """Declarations a dotted name points at: an exact full name, else one whose full name ends with it at a dot."""
    kind_sql, kind_params = "", []
    if kinds:
        kind_sql = f" AND d.kind IN ({', '.join('?' * len(kinds))})"
        kind_params = list(kinds)
    with closing(derived.open_read_only(path)) as conn:
        exact = _rows(conn, corpus, SELECT + "WHERE d.full = ? COLLATE NOCASE" + kind_sql + " ORDER BY f.path, d.start",
                      [name] + kind_params)
        if exact:
            return exact
        last = name.rsplit(".", 1)[-1]
        candidates = _rows(conn, corpus, SELECT + "WHERE d.name = ? COLLATE NOCASE" + kind_sql + " ORDER BY d.full, f.path, d.start",
                           [last] + kind_params)
    suffix = "." + name.lower()
    return [h for h in candidates if h.full.lower().endswith(suffix) or h.full.lower() == name.lower()]


def members(path, corpus, type_full):
    """The declarations directly inside a type, in source order."""
    with closing(derived.open_read_only(path)) as conn:
        return _rows(conn, corpus, SELECT + "WHERE d.owner = ? COLLATE NOCASE ORDER BY f.path, d.start", [type_full])


def enclosing(path, file_path):
    """Every declaration in one file as (start, end, kind, full), for finding what holds a line."""
    with closing(derived.open_read_only(path)) as conn:
        return conn.execute('SELECT d.start, d."end", d.kind, d.full FROM decls d JOIN files f ON f.id = d.file '
                            "WHERE f.path = ? ORDER BY d.start", [file_path]).fetchall()


def counts(path):
    meta = derived.read_meta(path)
    return int(meta.get("files", 0)), int(meta.get("declarations", 0))
