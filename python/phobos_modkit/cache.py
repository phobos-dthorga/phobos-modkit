"""Derived data: files a tool builds from a source (a save, a mod list, a fetched page) and rebuilds when it changes.

The kit's convention: derived data is a SQLite file in the kit's cache folder (phobos_modkit.paths.cache_root), with
a `meta` table of provenance keys saying what it was built from. Common keys:

    source, source_size, source_mtime_ns   the file it was built from, and that file's size and time
    schema_sha                              a hash of the schema or rules that shaped it
    kit_version                             the kit that built it

A file is current when every expected key matches; otherwise the tool rebuilds it. Because every derived file is
SQLite, one tool can read another's with ATTACH, and a question that crosses tools is one query.
"""
from __future__ import annotations

from contextlib import closing, contextmanager
import hashlib
import os
from pathlib import Path
import shutil
import sqlite3
import stat

from . import file_lock
from .paths import cache_root

DIGEST_LENGTH = 16
# One run builds a derived file at a time (1.128.1). The Defs index takes minutes to build, and a second build of it started
# meanwhile deleted the first one's half-written file under it ("being used by another process"; the owner's screen note of
# 26 Nov 2026). The second waits up to BUILD_WAIT_S; a lock older than BUILD_STALE_S was left by a run that stopped.
BUILD_WAIT_S = 20 * 60
BUILD_STALE_S = 60 * 60


class CacheError(RuntimeError):
    pass


@contextmanager
def one_builder(target, error=CacheError, wait_s=BUILD_WAIT_S, stale_s=BUILD_STALE_S):
    """Holds the build lock of the derived file `target` (a `.lock` file beside it) while the block builds it.

    Inside the block, a caller checks again whether the file is current: the run it waited for may have just built it. Raises
    `error` when another run held the lock for longer than `wait_s`.
    """
    target = Path(target)
    lock = target.with_name(target.name + ".lock")
    try:
        with file_lock.held(lock, wait_s, stale_s):
            yield
    except file_lock.LockBusy:
        raise error(f"Another run has been building {target.name} for over {wait_s / 60:.0f} minutes. Try again once it has "
                    f"finished, or delete {lock} if nothing is building it.") from None


def folder(namespace, explicit=None, environ=None, settings_file=None):
    """One tool's folder in the kit's cache, e.g. cache_root/rimworld-saves. Created when something is written."""
    return cache_root(explicit, environ, settings_file) / namespace


def file_stamp(path, prefix="source"):
    """A file's size and modification time as provenance keys: {prefix}_size and {prefix}_mtime_ns."""
    info = Path(path).stat()
    return {f"{prefix}_size": str(info.st_size), f"{prefix}_mtime_ns": str(info.st_mtime_ns)}


def digest(path):
    """A short hash of a file's bytes, for schema_sha and similar keys."""
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()[:DIGEST_LENGTH]


def open_read_only(path):
    """A connection that cannot change the file."""
    return sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True)


def read_meta(path):
    """The meta table as a dict; {} when the file is missing or unreadable. The connection closes at once: on
    Windows an open handle would stop the file from being replaced."""
    if not Path(path).is_file():
        return {}
    try:
        with closing(open_read_only(path)) as conn:
            return dict(conn.execute("SELECT key, value FROM meta").fetchall())
    except sqlite3.Error:
        return {}


def write_meta(conn, values):
    """Record provenance in an open, writable connection (for derived files a Python tool builds itself)."""
    conn.execute("CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT)")
    conn.executemany("INSERT OR REPLACE INTO meta VALUES (?, ?)", [(k, str(v)) for k, v in values.items()])


def is_current(path, expected):
    """True when the derived file exists and its provenance matches every expected key."""
    meta = read_meta(path)
    return bool(meta) and all(meta.get(k) == str(v) for k, v in expected.items())


def remove(path):
    """Delete a file even if something marked it read-only; nothing happens when it is missing."""
    path = Path(path)
    try:
        path.unlink(missing_ok=True)
    except PermissionError:
        os.chmod(path, stat.S_IREAD | stat.S_IWRITE)
        path.unlink(missing_ok=True)


@contextmanager
def frozen_copy(source, into, name=None, copy=shutil.copyfile):
    """A private copy of a file another program may write while it is read; deleted when the block ends.

    Yields (copy's path, the source's stamp before copying). Only the contents are copied, so a read-only source
    cannot make the copy undeletable. Raises CacheError when the source changed while it was being copied.
    """
    source, into = Path(source), Path(into)
    into.mkdir(parents=True, exist_ok=True)
    target = into / (name or f"{source.stem}.frozen{source.suffix}")
    before = file_stamp(source)
    try:
        copy(source, target)
        if file_stamp(source) != before:
            raise CacheError(f"{source.name} changed while it was being copied. Wait until the program writing it "
                             f"has finished, then run this again.")
        yield target, before
    finally:
        remove(target)
