"""RimWorld saves: picking one, indexing a frozen copy with xml-index, and opening the index read-only.

An index is derived data. It lives in a cache folder (by default under the system's temp folder, which cloud-sync
tools usually leave alone) and records the save's size and modification time and a hash of the schema, so it is
rebuilt whenever either changes. The save itself is only ever read: it is copied first, because the game may
write it while it is being read, and the copy is deleted as soon as the index is built.
"""
from __future__ import annotations

from contextlib import closing
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import stat
import subprocess

from ... import __version__
from ...native import require_tool

SCHEMA = Path(__file__).with_name("save-schema.toml")
SAVE_SUFFIX = ".rws"
INDEX_SUFFIX = ".sqlite"
FROZEN_SUFFIX = ".frozen.rws"
CACHE_FOLDER = "rimworld-saves"  # inside the kit's cache root (phobos_modkit.paths.cache_root)


class SaveError(RuntimeError):
    pass


@dataclass
class Built:
    """What one indexing run did."""
    index: Path
    elements: int
    rows: dict
    seconds: float


def schema_digest(schema=SCHEMA):
    return hashlib.sha256(Path(schema).read_bytes()).hexdigest()[:16]


def saves_in(folder):
    folder = Path(folder)
    return sorted((p for p in folder.glob(f"*{SAVE_SUFFIX}") if p.is_file()),
                  key=lambda p: (p.stat().st_mtime_ns, p.name), reverse=True) if folder.is_dir() else []


def find_save(folder, name=None):
    """The save to read: name as a path, or as a save's name with or without .rws, or else the newest save."""
    if name:
        direct = Path(name)
        if direct.is_file():
            return direct
        stem = name[:-len(SAVE_SUFFIX)] if name.lower().endswith(SAVE_SUFFIX) else name
        for save in saves_in(folder):
            if save.stem.lower() == stem.lower():
                return save
        raise SaveError(f"No save named {name} in {folder}.")
    found = saves_in(folder)
    if not found:
        raise SaveError(f"No saves (*{SAVE_SUFFIX}) in {folder}. Name one with --save, or the folder with --saves.")
    return found[0]


def stamp(save):
    info = Path(save).stat()
    return {"source_size": str(info.st_size), "source_mtime_ns": str(info.st_mtime_ns)}


def index_for(cache, save):
    return Path(cache) / f"{Path(save).stem}{INDEX_SUFFIX}"


def open_read_only(index):
    """A connection that cannot change the index."""
    return sqlite3.connect(Path(index).resolve().as_uri() + "?mode=ro", uri=True)


def read_meta(index):
    """The index's meta table; {} when it cannot be read. The connection is closed at once: on Windows an open
    handle would stop the indexer from replacing the file."""
    try:
        with closing(open_read_only(index)) as conn:
            return dict(conn.execute("SELECT key, value FROM meta").fetchall())
    except sqlite3.Error:
        return {}


def is_current(index, save, schema=SCHEMA):
    """True when the index was built from this save as it is now, with this schema."""
    if not Path(index).is_file():
        return False
    meta = read_meta(index)
    expected = {**stamp(save), "schema_sha": schema_digest(schema)}
    return all(meta.get(k) == v for k, v in expected.items())


def _remove(path):
    """Delete a file even if something marked it read-only."""
    try:
        path.unlink(missing_ok=True)
    except PermissionError:
        os.chmod(path, stat.S_IREAD | stat.S_IWRITE)
        path.unlink(missing_ok=True)


def build(save, cache, indexer=None, environ=None, run=subprocess.run, schema=SCHEMA):
    """Index a frozen copy of save into the cache folder. Returns Built; raises SaveError."""
    program = require_tool("xml-index", indexer, environ)
    cache = Path(cache)
    cache.mkdir(parents=True, exist_ok=True)
    save = Path(save)
    before = stamp(save)
    frozen = cache / f"{save.stem}{FROZEN_SUFFIX}"
    index = index_for(cache, save)
    try:
        shutil.copyfile(save, frozen)  # contents only: a read-only save must not make the copy undeletable
        if stamp(save) != before:
            raise SaveError(f"{save.name} changed while it was being copied. Wait until the game has finished "
                            f"saving, then run this again.")
        meta = {**before, "source": save.name, "schema_sha": schema_digest(schema), "kit_version": __version__}
        command = [str(program), "build", "--schema", str(schema), "--out", str(index), "--force"]
        for key, value in meta.items():
            command += ["--meta", f"{key}={value}"]
        command.append(str(frozen))
        result = run(command, capture_output=True, text=True)
        if result.returncode != 0:
            raise SaveError(f"Indexing {save.name} failed: {result.stderr.strip() or 'no message'}")
        summary = json.loads(result.stdout.strip().splitlines()[-1])
    finally:
        _remove(frozen)
    return Built(index, summary["elements"], summary["rows"], summary["seconds"])


def ensure(save, cache, indexer=None, environ=None, rebuild=False, run=subprocess.run, schema=SCHEMA):
    """(index path, Built or None): the current index of save, built only when missing or stale."""
    index = index_for(cache, save)
    if not rebuild and is_current(index, save, schema):
        return index, None
    built = build(save, cache, indexer, environ, run, schema)
    return built.index, built


def like(pattern):
    """A SQL LIKE pattern from a user's text: * and ? are wildcards; % and _ (common in defNames) are literal."""
    escaped = pattern.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return escaped.replace("*", "%").replace("?", "_")
