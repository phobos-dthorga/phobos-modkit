"""RimWorld saves: picking one, indexing a frozen copy with xml-index, and opening the index read-only.

An index is derived data under the kit's cache convention (phobos_modkit.cache): a SQLite file whose `meta` table
records the save's name, size and modification time and a hash of the schema, so it is rebuilt whenever either
changes. The save itself is only ever read: it is copied first, because the game may write it while it is being
read, and the copy is deleted as soon as the index is built.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import subprocess

from ... import __version__
from ... import cache as derived
from ...cache import open_read_only, read_meta  # noqa: F401  (part of this module's interface)
from ...native import require_tool
from ...query import like  # noqa: F401  (part of this module's interface)

SCHEMA = Path(__file__).with_name("save-schema.toml")
SAVE_SUFFIX = ".rws"
INDEX_SUFFIX = ".sqlite"
FROZEN_SUFFIX = ".frozen.rws"
CACHE_FOLDER = "rimworld-saves"  # this tool's folder in the kit's cache


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
    return derived.digest(schema)


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


def index_for(cache, save):
    return Path(cache) / f"{Path(save).stem}{INDEX_SUFFIX}"


def provenance(save, schema=SCHEMA):
    """The meta keys an index of this save, as it is now, must carry to be current."""
    return {**derived.file_stamp(save), "schema_sha": schema_digest(schema)}


def is_current(index, save, schema=SCHEMA):
    """True when the index was built from this save as it is now, with this schema."""
    return derived.is_current(index, provenance(save, schema))


def build(save, cache, indexer=None, environ=None, run=subprocess.run, schema=SCHEMA):
    """Index a frozen copy of save into the cache folder. Returns Built; raises SaveError."""
    program = require_tool("xml-index", indexer, environ)
    save = Path(save)
    index = index_for(cache, save)
    try:
        with derived.frozen_copy(save, cache, f"{save.stem}{FROZEN_SUFFIX}") as (frozen, stamp):
            meta = {**stamp, "source": save.name, "schema_sha": schema_digest(schema), "kit_version": __version__}
            command = [str(program), "build", "--schema", str(schema), "--out", str(index), "--force"]
            for key, value in meta.items():
                command += ["--meta", f"{key}={value}"]
            command.append(str(frozen))
            result = run(command, capture_output=True, text=True)
    except derived.CacheError:
        raise SaveError(f"{save.name} changed while it was being copied. Wait until the game has finished saving, "
                        f"then run this again.") from None
    if result.returncode != 0:
        raise SaveError(f"Indexing {save.name} failed: {result.stderr.strip() or 'no message'}")
    summary = json.loads(result.stdout.strip().splitlines()[-1])
    return Built(index, summary["elements"], summary["rows"], summary["seconds"])


def stale_index(index, environ=None, settings_file=None):
    """Why an index in the cache is no longer any use, or None: its save has gone from the Saves folder, or has been
    saved over since (the next question about it builds a new index anyway). For the cleanup command."""
    from . import paths
    name = read_meta(index).get("source")
    if not name:
        return None
    save = paths.saves_path(None, environ, settings_file) / name
    if not save.is_file():
        return f"its save, {name}, is no longer in the Saves folder"
    if not is_current(index, save):
        return f"{name} has been saved again since, so the next question about it builds a new index"
    return None


# What the cleanup command may clear from this tool's cache folder.
CACHE_POLICY = {"folder": CACHE_FOLDER, "stale": stale_index}


def ensure(save, cache, indexer=None, environ=None, rebuild=False, run=subprocess.run, schema=SCHEMA):
    """(index path, Built or None): the current index of save, built only when missing or stale."""
    index = index_for(cache, save)
    if not rebuild and is_current(index, save, schema):
        return index, None
    built = build(save, cache, indexer, environ, run, schema)
    return built.index, built
