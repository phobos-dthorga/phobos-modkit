"""Which assemblies each .NET assembly is built on (its AssemblyRef table), read by the kit's assembly reader (`refs`, 1.84.0) and
kept per file version in the kit's cache, so a second read of hundreds of assemblies costs only their dates. Game-free.

Used by the mod-list sorter (the owner's choice, 23 Nov 2026: "read assemblies"): a mod whose code is built on another mod's
assembly loads after that mod, which catches a dependency neither mod declared (seen 23 Nov 2026: I Am Mother's Vanilla Nutrient
Paste compat assembly is built on Vanilla Expanded Framework's PipeSystem, and failed to load once a re-sort put it first).
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import tempfile

from . import assemblies
from .paths import cache_root

CACHE_FORMAT = 2              # 2 (1.84.0): each entry also says which assemblies its types inherit from
CACHE_NAME = "assembly-refs.json"


def _stamp(path):
    try:
        stat = os.stat(path)
    except OSError:
        return None
    return f"{stat.st_size}:{stat.st_mtime_ns}"


def _cache_file(environ):
    return Path(cache_root(None, environ)) / CACHE_NAME


def _load(path):
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data.get("files", {}) if isinstance(data, dict) and data.get("format") == CACHE_FORMAT else {}


def _save(path, files):
    try:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        partial = Path(path).with_name(Path(path).name + ".partial")
        partial.write_text(json.dumps({"format": CACHE_FORMAT, "files": files}), encoding="utf-8")
        os.replace(partial, path)
    except OSError:
        pass


def read_references(paths, environ=None, run=subprocess.run, reader=None):
    """{path: {"assembly": name, "references": [names], "inherits": [names its types' parents come from]}} for each readable .NET assembly among the paths (native DLLs and unreadable
    files are left out). Builds the reader first when it is missing; raises assemblies.ReaderError when it cannot be built."""
    cache_file = _cache_file(environ)
    cached = _load(cache_file)
    found, wanted = {}, []
    for path in map(str, paths):
        stamp = _stamp(path)
        if stamp is None:
            continue
        entry = cached.get(path)
        if entry and entry.get("stamp") == stamp:
            if entry.get("assembly"):
                found[path] = entry
        else:
            wanted.append((path, stamp))
    if wanted:
        tool = reader or assemblies.ensure_reader(environ, run)
        with tempfile.TemporaryDirectory(prefix="phobos-refs-") as folder:
            listing = Path(folder) / "files.txt"
            listing.write_text("\n".join(p for p, _ in wanted), encoding="utf-8")
            result = run([str(tool), "refs", "@" + str(listing)], capture_output=True, check=False)
        answers = {}
        for line in (result.stdout or b"").decode("utf-8", errors="replace").splitlines():
            try:
                record = json.loads(line)
            except ValueError:
                continue
            answers[os.path.normcase(record.get("path", ""))] = record
        for path, stamp in wanted:
            record = answers.get(os.path.normcase(path), {})
            entry = {"stamp": stamp, "assembly": record.get("assembly", "") if "error" not in record else "",
                     "references": list(record.get("references") or []), "inherits": list(record.get("inherits") or [])}
            cached[path] = entry
            if entry["assembly"]:
                found[path] = entry
        _save(cache_file, cached)
    return found
