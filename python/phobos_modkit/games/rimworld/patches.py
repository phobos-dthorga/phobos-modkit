"""Which active mods patch which methods with Harmony: read from their assemblies' metadata, never by running them.

The reader is the kit's C# tool (dotnet/PhobosModKit.Assemblies, System.Reflection.Metadata): it opens each DLL as a file
and finds [HarmonyPatch] classes and harmony.Patch(...) calls. This module chooses the DLLs the game loads (each active
mod's load folders for the game's version, then their Assemblies folders; the shared Harmony copies are skipped), runs the
reader on the ones that changed since last time, and keeps the results in SQLite in the kit's cache.

What the metadata can and cannot say is in the reader's notes: a target a TargetMethod works out at run time is read from
that method's code when it names it plainly; an original passed in a variable is "worked out at run time".
"""
from __future__ import annotations

from contextlib import closing
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import tempfile

from ... import __version__
from ... import cache as derived
from ... import native
from . import loading
from .mods import SHARED_ASSEMBLIES

CACHE_FOLDER = "rimworld-patches"
INDEX_NAME = "patches.sqlite"
READER_PROJECT = native.KIT_ROOT / "dotnet" / "PhobosModKit.Assemblies" / "PhobosModKit.Assemblies.csproj"
READER_NAME = "PhobosModKit.Assemblies"
INDEX_FORMAT = "1"


class PatchesError(RuntimeError):
    pass


def reader_folder(environ=None):
    return native.build_dir(environ) / "dotnet" / "tool" / "assemblies"


def reader_path(environ=None):
    return reader_folder(environ) / native.program_name(READER_NAME)


def build_reader(environ=None, run=subprocess.run):
    """Build the C# reader into the kit's build folder. Raises PatchesError without the .NET SDK or on failure."""
    if run is subprocess.run and shutil.which("dotnet") is None:
        raise PatchesError("The .NET SDK is not installed; install .NET 10 from https://dotnet.microsoft.com to read assemblies.")
    command = ["dotnet", "build", str(READER_PROJECT), "-c", "Release", "-o", str(reader_folder(environ)), "--nologo",
               "-v", "q"]
    result = run(command, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise PatchesError(f"Building the assembly reader failed:\n{(result.stdout or '')[-2000:]}")


def ensure_reader(environ=None, run=subprocess.run):
    """The reader's path, built first when it is missing or was built by another version of the kit."""
    tool = reader_path(environ)
    stamp = reader_folder(environ) / "kit-version.txt"
    current = stamp.read_text(encoding="utf-8").strip() if stamp.is_file() else ""
    if not tool.is_file() or current != __version__:
        build_reader(environ, run)
        stamp.parent.mkdir(parents=True, exist_ok=True)
        stamp.write_text(__version__, encoding="utf-8")
    return tool


def mod_assemblies(active, version):
    """(ActiveMod, DLL path) for every assembly the game loads from each active mod, in load order."""
    active_ids = {loading.bare_id(a.listed_id) for a in active}
    found = []
    for entry in active:
        if entry.mod is None or entry.mod.source == "Ludeon":
            continue
        seen = set()
        for folder in loading.load_folders(entry.mod.folder, version, active_ids):
            assemblies = folder / "Assemblies"
            if not assemblies.is_dir():
                continue
            for dll in sorted(assemblies.glob("*.dll"), key=lambda p: p.name.lower()):
                if dll.stem.lower() in SHARED_ASSEMBLIES or dll.name.lower() in seen:
                    continue
                seen.add(dll.name.lower())
                found.append((entry, dll))
    return found


SCHEMA = """
CREATE TABLE IF NOT EXISTS assemblies (path TEXT PRIMARY KEY, size INTEGER, mtime_ns INTEGER, assembly TEXT,
                                       version TEXT, error TEXT);
CREATE TABLE IF NOT EXISTS patches (path TEXT, source TEXT, kind TEXT, target_type TEXT, target_member TEXT,
                                    method_type TEXT, argument_types TEXT, patch_class TEXT, patch_method TEXT,
                                    can_skip INTEGER, priority INTEGER, note TEXT);
CREATE INDEX IF NOT EXISTS patches_target ON patches (target_member, target_type);
CREATE INDEX IF NOT EXISTS patches_path ON patches (path);
CREATE TABLE IF NOT EXISTS owners (path TEXT, position INTEGER, package_id TEXT, mod TEXT);
"""


def refresh(index, found, environ=None, run=subprocess.run, rebuild=False):
    """Bring the index up to date with found (ActiveMod, DLL) pairs: read only DLLs new or changed since last time.
    Returns (read, kept, built_reader)."""
    index = Path(index)
    index.parent.mkdir(parents=True, exist_ok=True)
    meta = derived.read_meta(index)
    if rebuild or meta.get("index_format") != INDEX_FORMAT or meta.get("kit_version") != __version__:
        derived.remove(index)
    built = False
    with closing(sqlite3.connect(index)) as conn:
        conn.executescript(SCHEMA)
        known = {row[0]: (row[1], row[2]) for row in conn.execute("SELECT path, size, mtime_ns FROM assemblies")}
        current = {}
        for _, dll in found:
            info = dll.stat()
            current[str(dll)] = (info.st_size, info.st_mtime_ns)
        stale = [p for p in known if p not in current or known[p] != current[p]]
        for path in stale:
            conn.execute("DELETE FROM assemblies WHERE path = ?", (path,))
            conn.execute("DELETE FROM patches WHERE path = ?", (path,))
        wanted = [p for p in current if p not in known or known[p] != current[p]]
        if wanted:
            tool = reader_path(environ)
            if not tool.is_file():
                build_reader(environ, run)
                built = True
            for record in read_assemblies(tool, wanted, run):
                path = record["path"]
                size, mtime = current[path]
                conn.execute("INSERT OR REPLACE INTO assemblies VALUES (?, ?, ?, ?, ?, ?)",
                             (path, size, mtime, record.get("assembly", ""), record.get("version", ""), record.get("error", "")))
                conn.executemany("INSERT INTO patches VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", [
                    (path, p["source"], p["kind"], p["targetType"], p["targetMember"], p["methodType"],
                     json.dumps(p["argumentTypes"]), p["patchClass"], p["patchMethod"], int(p["canSkip"]), p["priority"],
                     p["note"]) for p in record.get("patches", [])])
        conn.execute("DELETE FROM owners")
        conn.executemany("INSERT INTO owners VALUES (?, ?, ?, ?)",
                         [(str(dll), entry.position, entry.mod.package_id, entry.mod.name) for entry, dll in found])
        derived.write_meta(conn, {"index_format": INDEX_FORMAT, "kit_version": __version__, "assemblies": len(current)})
        conn.commit()
    return len(wanted), len(current) - len(wanted), built


def read_assemblies(tool, paths, run=subprocess.run):
    """The reader's records for paths, one dict per DLL (its patches, or an error)."""
    handle, listing = tempfile.mkstemp(prefix="phobos-assemblies-", suffix=".txt")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as file:
            file.write("\n".join(paths))
        result = run([str(tool), "patches", "@" + listing], capture_output=True, check=False)
    finally:
        os.remove(listing)
    if result.returncode != 0:
        raise PatchesError(f"The assembly reader failed: {(result.stderr or b'').decode('utf-8', 'replace')[-1000:]}")
    return [json.loads(line) for line in result.stdout.decode("utf-8").splitlines() if line.strip()]
