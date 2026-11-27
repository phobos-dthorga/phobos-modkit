"""The community's lists a mod manager downloads for sorting and checking, fetched by the kit itself (1.144.0).

Game-free. A game's mod-list adapter names its lists as data (`databases`): each a public GitHub repository and the files read from
it, as its mod manager clones them (RimWorld's are RimSort's: the community's load-order rules, the Steam Workshop database, and
Mlie's No Version Warning and Use This Instead). So the manager can retire (the owner's choice of 28 Nov 2026, "Own data + your
rules"), the kit fetches the same files from raw.githubusercontent.com into its own cache, keyless, outside GitHub's hourly API
count; each file is asked for with the ETag of the copy kept, so an unchanged file is not downloaded again.

Readers take **the newer of the kit's copy and the manager's**, so nothing changes while the manager still refreshes its own, and
nothing goes stale once it is gone. Files are read only, never copied into a repository.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import gzip
import json
import os
from pathlib import Path
import time

from . import cache as derived
from .github import GitHubError, http_get

RAW = "https://raw.githubusercontent.com"
FRESH_DAYS = 7                      # older than this, a list is called stale and the Companion fetches it again (agent default)
MOST_BYTES = 200 * 1024 * 1024      # a file larger than this, unpacked, is refused (agent default; the Workshop database is ~50 MB)
RECORD = "fetched.json"


class DatabaseError(RuntimeError):
    pass


@dataclass(frozen=True)
class Database:
    """One list: where it is published, which of its files are read, and where the game's mod manager keeps its own copy."""
    name: str               # a plain id, e.g. "community-rules"
    label: str              # in words, e.g. "The community's load-order rules"
    repo: str               # "owner/repository" on GitHub
    files: tuple            # paths in the repository; "{version}" stands for the game's version
    licence: str
    manager: str = ""       # its folder inside the mod manager's data folder, "" when the manager keeps none
    ref: str = "main"
    packed: tuple = ()      # files published also gzipped, fetched as their .gz and unpacked (smaller downloads)

    def paths(self, version):
        """The repository paths read for this game version (a "{version}" path is left out when the version is unknown)."""
        return [f.replace("{version}", version) for f in self.files if version or "{version}" not in f]


def folder(game, environ=None, settings=None):
    return derived.folder("mod-databases", None, environ, settings) / game


def our_copy(game, database, relative, environ=None, settings=None):
    return folder(game, environ, settings) / database.name / relative


def _record_path(game, environ, settings):
    return folder(game, environ, settings) / RECORD


def _read_record(path):
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _iso(seconds):
    return datetime.fromtimestamp(seconds, timezone.utc).isoformat(timespec="seconds")


def _mtime(path):
    try:
        return Path(path).stat().st_mtime
    except OSError:
        return None


def newest(*paths):
    """The newest of these files that is there, or None."""
    found = [(m, str(p)) for p in paths if p is not None and (m := _mtime(p)) is not None]
    return Path(max(found)[1]) if found else None


def _header(headers, name):
    for key, value in (headers or {}).items():
        if key.lower() == name.lower():
            return value
    return ""


def _write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".part")
    temporary.write_bytes(data)
    os.replace(temporary, path)


def fetch(game, databases, version, environ=None, settings=None, get=http_get, now=None, only=None, progress=None):
    """Fetches each list's files into the kit's cache; [{name, label, fetched, unchanged, missing, error}] in the lists' order.

    A file GitHub says is unchanged (304) is kept and its time renewed, so it counts as fresh. One list failing leaves the others
    fetched and its own last copy in place."""
    now = now or time.time()
    record_path = _record_path(game, environ, settings)
    record = _read_record(record_path)
    results = []
    chosen = [d for d in databases if not only or d.name in only]
    for step, database in enumerate(chosen, 1):
        if progress:
            progress(step, len(chosen), database.label)
        entry = record.setdefault(database.name, {})
        tags = entry.setdefault("files", {})
        outcome = {"name": database.name, "label": database.label, "fetched": 0, "unchanged": 0, "missing": [], "error": ""}
        for relative in database.paths(version):
            remote = relative + (".gz" if relative in database.packed else "")
            target = our_copy(game, database, relative, environ, settings)
            headers = {"If-None-Match": tags[relative]} if tags.get(relative) and target.is_file() else {}
            try:
                status, body, answer = get(f"{RAW}/{database.repo}/{database.ref}/{remote}", headers=headers)
            except GitHubError as error:
                outcome["error"] = str(error)
                break
            if status == 304:
                os.utime(target, (now, now))
                outcome["unchanged"] += 1
                continue
            if status == 404:
                outcome["missing"].append(relative)
                continue
            if status != 200:
                outcome["error"] = f"GitHub answered {status} for {database.repo}/{remote}"
                break
            try:
                data = gzip.decompress(body) if relative in database.packed else body
            except (OSError, EOFError):
                outcome["error"] = f"{database.repo}/{remote} was not a whole gzip file"
                break
            if len(data) > MOST_BYTES:
                outcome["error"] = f"{database.repo}/{relative} is larger than {MOST_BYTES // (1024 * 1024)} MB; not kept"
                break
            _write(target, data)
            os.utime(target, (now, now))
            tags[relative] = _header(answer, "ETag")
            outcome["fetched"] += 1
        if not outcome["error"]:
            entry["at"] = _iso(now)
        results.append(outcome)
    record_path.parent.mkdir(parents=True, exist_ok=True)
    _write(record_path, json.dumps(record, indent=1).encode("utf-8"))
    return results


def status(game, databases, version, manager_root=None, environ=None, settings=None, now=None):
    """Each list as it stands: the kit's copy and the manager's, each with its age, which one is read, and whether it is stale."""
    now = now or time.time()
    record = _read_record(_record_path(game, environ, settings))
    rows = []
    for database in databases:
        ours, theirs = [], []
        for relative in database.paths(version):
            ours.append(_mtime(our_copy(game, database, relative, environ, settings)))
            if manager_root is not None and database.manager:
                theirs.append(_mtime(Path(manager_root) / database.manager / relative))
        our_time = min(ours) if ours and all(m is not None for m in ours) else None
        their_time = min(theirs) if theirs and all(m is not None for m in theirs) else None
        read_time = max((t for t in (our_time, their_time) if t is not None), default=None)
        rows.append({"name": database.name, "label": database.label, "repo": database.repo, "licence": database.licence,
                     "ours": _iso(our_time) if our_time else "", "theirs": _iso(their_time) if their_time else "",
                     "read": ("" if read_time is None else "ours" if read_time == our_time else "theirs"),
                     "age_days": None if read_time is None else round((now - read_time) / 86400, 1),
                     "stale": read_time is None or now - read_time > FRESH_DAYS * 86400,
                     "fetched": (record.get(database.name) or {}).get("at", "")})
    return rows
