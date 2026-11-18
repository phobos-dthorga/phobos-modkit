"""A store that keeps every version of the assemblies a project depends on, so two builds can still be compared after
the game's launcher has replaced the older one.

Game-free: a game adapter decides which files to keep and what to call their versions, and hands them in as Sources.
A file is stored once per distinct content (by SHA-256), compressed with gzip, under objects/; an SQLite index records
each version the archive has seen: who it belongs to, its file name, its version text and when it was first seen.

The archive is not derived data: it holds what can no longer be fetched once a launcher replaces the file. So it does
not live in the kit's cache (a temp folder by default, which the system may clear) but in its own folder, by default in
the user's local application data, which cloud-sync tools usually leave alone.
"""
from __future__ import annotations

from contextlib import closing
from dataclasses import dataclass
import gzip
import hashlib
import os
from pathlib import Path
import shutil
import sqlite3
import sys

from . import __version__
from .cache import CacheError, file_stamp, remove, write_meta
from .paths import resolve

ARCHIVE = ("assemblyArchivePath", "PHOBOS_ASSEMBLY_ARCHIVE")
INDEX_NAME = "archive.sqlite"
OBJECTS = "objects"
EXTRACTED = "extracted"
FORMAT = "1"
CHUNK = 1 << 20

SCHEMA = """
CREATE TABLE IF NOT EXISTS versions (
    id INTEGER PRIMARY KEY,
    owner TEXT NOT NULL,          -- who the file belongs to: the game, or a mod's package ID
    owner_name TEXT NOT NULL,     -- a name for people
    file TEXT NOT NULL,           -- the file's name, as the owner ships it
    sha256 TEXT NOT NULL,
    size INTEGER NOT NULL,
    version TEXT NOT NULL,        -- the owner's own version text, when it has one
    source_mtime_ns INTEGER NOT NULL,
    seen_at TEXT NOT NULL         -- when the archive first saw this content for this owner and file
);
CREATE INDEX IF NOT EXISTS versions_by_file ON versions (owner, file, id);
"""


class ArchiveError(RuntimeError):
    pass


@dataclass(frozen=True)
class Source:
    """One file to keep: whose it is, a name for people, the owner's version text and where it is now."""
    owner: str
    owner_name: str
    version: str
    path: Path


@dataclass(frozen=True)
class Version:
    id: int
    owner: str
    owner_name: str
    file: str
    sha256: str
    size: int
    version: str
    seen_at: str


def default_archive(platform=None, environ=None, home=None):
    """%LOCALAPPDATA%\\phobos-modkit\\assembly-archive on Windows; the XDG data folder elsewhere."""
    platform = platform or sys.platform
    environ = os.environ if environ is None else environ
    home = Path.home() if home is None else Path(home)
    if platform == "win32":
        base = Path(environ.get("LOCALAPPDATA") or home / "AppData" / "Local")
    elif platform == "darwin":
        base = home / "Library" / "Application Support"
    else:
        base = Path(environ.get("XDG_DATA_HOME") or home / ".local" / "share")
    return base / "phobos-modkit" / "assembly-archive"


def archive_root(explicit=None, environ=None, settings_file=None, platform=None):
    """Argument, then PHOBOS_ASSEMBLY_ARCHIVE, then assemblyArchivePath in the settings file, then the default."""
    return resolve(*ARCHIVE, default_archive(platform, environ), explicit, environ, settings_file)


def _sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(CHUNK), b""):
            digest.update(block)
    return digest.hexdigest()


class Archive:
    """The store at root. Nothing is created until something is added."""

    def __init__(self, root):
        self.root = Path(root)
        self.index = self.root / INDEX_NAME

    def _object(self, sha):
        return self.root / OBJECTS / sha[:2] / f"{sha}.gz"

    def _connect(self):
        self.root.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.index)
        conn.executescript(SCHEMA)
        write_meta(conn, {"format": FORMAT, "kit_version": __version__})
        return conn

    def _store(self, path, sha):
        """Compress path into the object store unless that content is there already."""
        target = self._object(sha)
        if target.is_file():
            return
        target.parent.mkdir(parents=True, exist_ok=True)
        partial = target.with_suffix(".partial")
        with open(path, "rb") as src, gzip.open(partial, "wb", compresslevel=6) as out:
            shutil.copyfileobj(src, out, CHUNK)
        os.replace(partial, target)

    def add(self, sources, now):
        """Keep each source whose content differs from the last version kept for its owner and file.

        Returns [(Source, "new" | "first" | "same")]. now is the time text to record (passed in, for tests).
        """
        results = []
        with closing(self._connect()) as conn:
            for source in sources:
                path = Path(source.path)
                before = file_stamp(path)
                sha = _sha256(path)
                last = conn.execute("SELECT sha256 FROM versions WHERE owner = ? AND file = ? ORDER BY id DESC LIMIT 1",
                                    (source.owner, path.name)).fetchone()
                if last and last[0] == sha:
                    results.append((source, "same"))
                    continue
                self._store(path, sha)
                if file_stamp(path) != before:
                    raise CacheError(f"{path.name} changed while it was being kept. Wait until the program updating it "
                                     f"has finished, then run this again.")
                conn.execute("INSERT INTO versions (owner, owner_name, file, sha256, size, version, source_mtime_ns, seen_at) "
                             "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                             (source.owner, source.owner_name, path.name, sha, int(before["source_size"]),
                              source.version, int(before["source_mtime_ns"]), now))
                results.append((source, "new" if last else "first"))
            conn.commit()
        return results

    def versions(self):
        """Every version kept, oldest first within each owner and file."""
        if not self.index.is_file():
            return []
        with closing(sqlite3.connect(self.index)) as conn:
            rows = conn.execute("SELECT id, owner, owner_name, file, sha256, size, version, seen_at FROM versions "
                                "ORDER BY owner, file COLLATE NOCASE, id").fetchall()
        return [Version(*row) for row in rows]

    def stored_bytes(self):
        """The object store's size on disk."""
        folder = self.root / OBJECTS
        return sum(p.stat().st_size for p in folder.rglob("*.gz")) if folder.is_dir() else 0

    def extract(self, version):
        """The version's file, unpacked under extracted/<first 16 of its hash>/<its file name>; reused when present."""
        source = self._object(version.sha256)
        if not source.is_file():
            raise ArchiveError(f"The archive lists {version.file} ({version.sha256[:12]}) but its stored copy is missing.")
        target = self.root / EXTRACTED / version.sha256[:16] / version.file
        if target.is_file() and target.stat().st_size == version.size:
            return target
        target.parent.mkdir(parents=True, exist_ok=True)
        partial = target.with_name(target.name + ".partial")
        with gzip.open(source, "rb") as src, open(partial, "wb") as out:
            shutil.copyfileobj(src, out, CHUNK)
        if _sha256(partial) != version.sha256:
            remove(partial)
            raise ArchiveError(f"The stored copy of {version.file} ({version.sha256[:12]}) does not unpack to what was kept.")
        os.replace(partial, target)
        return target


def history(versions, file, owner=None):
    """The versions of one file, oldest first: matched by file name (any case) and, when given, owner.

    Raises ArchiveError when nothing matches or when several owners ship a file of that name and none was named.
    """
    wanted = [v for v in versions if v.file.lower() == file.lower() and (owner is None or v.owner.lower() == owner.lower())]
    if not wanted:
        raise ArchiveError(f"The archive holds no {file}" + (f" from {owner}" if owner else "") + ". The list report shows what it holds.")
    owners = sorted({v.owner for v in wanted})
    if len(owners) > 1:
        raise ArchiveError(f"Several owners ship {file}: {', '.join(owners)}. Name one with --owner.")
    return wanted


def pick(chain, back):
    """The version `back` steps before the newest (0 is the newest)."""
    if back < 0 or back >= len(chain):
        raise ArchiveError(f"Only {len(chain)} version(s) of {chain[-1].file} are kept, so there is none {back} back from the newest.")
    return chain[-1 - back]
