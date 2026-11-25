"""What a repository is made of: every committed file by product, kind, lines and size; how that grew; where the work goes; and
what each product holds for players (1.39.0).

A file's **product** is the one whose changelog sits in its nearest folder above it (as `changes` names products), or, for a C#
project, the product its `.csproj` ships into (`<ModFolder>`, a folder holding a product's changelog); a file under neither is
outside any product and is grouped by its top folder. A file's **kind** comes from its extension and a few folder names: code,
tests, data, words, pictures, sounds, build, other. Lines are counted in text files only; a picture or a sound has none.

Only committed files count (git's own list), so nothing ignored, private or half-written is measured. Everything here reads; git is
asked, never told. The day-by-day history keeps each file version's line count in the kit's cache, so only new versions are read.
"""
from __future__ import annotations

from collections import defaultdict
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path, PurePosixPath
import re
import sqlite3
import subprocess

from . import cache as derived
from .changes import changelogs, product_name
from .installs import parse_changelog

CACHE_NAMESPACE = "makeup"
SCHEMA = "1"

KINDS = ("code", "tests", "data", "words", "pictures", "sounds", "build", "other")
CODE = {".cs": "C#", ".lua": "Lua", ".py": "Python", ".ts": "TypeScript", ".js": "JavaScript", ".svelte": "Svelte",
        ".rs": "Rust", ".java": "Java", ".cpp": "C++", ".c": "C", ".h": "C/C++ header", ".ps1": "PowerShell", ".sh": "Shell",
        ".mjs": "JavaScript", ".css": "CSS", ".html": "HTML", ".fx": "Shader", ".shader": "Shader", ".hlsl": "Shader"}
DATA = {".xml": "XML", ".json": "JSON", ".toml": "TOML", ".yml": "YAML", ".yaml": "YAML", ".ini": "INI", ".csv": "CSV",
        ".jsonl": "JSON lines", ".tsv": "TSV"}
WORDS = {".md": "Markdown", ".txt": "Text", ".rst": "reStructuredText"}
PICTURES = {".png", ".jpg", ".jpeg", ".dds", ".psd", ".svg", ".gif", ".webp", ".tga", ".kra", ".ico", ".bmp", ".xcf"}
SOUNDS = {".ogg", ".wav", ".mp3", ".flac", ".opus"}
BUILD = {".csproj", ".props", ".targets", ".sln", ".lock", ".gitattributes", ".gitignore", ".gitmodules", ".editorconfig"}
BUILD_NAMES = {"package.json", "package-lock.json", "cargo.toml", "cargo.lock", "pyproject.toml", "tsconfig.json", "makefile"}
TEST_FOLDERS = {"tests", "test", "__tests__", "spec"}
WORD_FOLDERS = {"languages", "translate", "localization", "locales"}
TEXT_LIMIT = 8 * 1024 * 1024
MOD_FOLDER = re.compile(r"<ModFolder>\s*([^<\s]+)\s*</ModFolder>")
KEYED_ENTRY = re.compile(r"^\s*<([A-Za-z_][\w.]*)>", re.M)


def classify(path):
    """(kind, language) of a repository path, by its extension and folders."""
    pure = PurePosixPath(path)
    folders = {part.lower() for part in pure.parts[:-1]}
    suffix = pure.suffix.lower()
    name = pure.name.lower()
    if suffix in PICTURES:
        return "pictures", suffix[1:].upper()
    if suffix in SOUNDS:
        return "sounds", suffix[1:].upper()
    if suffix in BUILD or name in BUILD_NAMES:
        return "build", suffix[1:] or name
    if suffix in CODE:
        return ("tests" if folders & TEST_FOLDERS else "code"), CODE[suffix]
    if suffix in DATA:
        if folders & TEST_FOLDERS:
            return "tests", DATA[suffix]
        return ("words" if folders & WORD_FOLDERS else "data"), DATA[suffix]
    if suffix in WORDS:
        return "words", WORDS[suffix]
    return "other", suffix[1:] or name


def is_text(kind):
    return kind not in ("pictures", "sounds")


def count_lines(data):
    if b"\0" in data[:8192]:
        return 0
    return data.count(b"\n") + (1 if data and not data.endswith(b"\n") else 0)


def git(root, *args, stdin=None):
    result = subprocess.run(["git", "-C", str(root), "-c", "core.fsmonitor=false", "-c", "core.quotepath=off", *args],
                            input=stdin, capture_output=True, check=False)
    if result.returncode != 0:
        raise MakeupError(f"git {args[0]} failed: {result.stderr.decode('utf-8', 'replace').strip()[:300]}")
    return result.stdout


class MakeupError(RuntimeError):
    """Something the tool cannot read; said in words."""


# ---------------------------------------------------------------- products

class Products:
    """Which product each path belongs to, from changelog folders and C# projects' <ModFolder>."""

    def __init__(self, folders, projects):
        self.folders = folders              # {folder ("" for the root): product name}
        self.projects = projects            # {project folder: product name}

    def of(self, path):
        parts = PurePosixPath(path).parts[:-1]
        for depth in range(len(parts), -1, -1):
            folder = "/".join(parts[:depth])
            if folder in self.projects:
                return self.projects[folder]
            if folder in self.folders and folder:
                return self.folders[folder]
        return self.folders.get("")

    @staticmethod
    def group_of(path):
        """Where a file outside any product is grouped: its top folder, or the repository's own files."""
        parts = PurePosixPath(path).parts
        return parts[0] if len(parts) > 1 else ""


def products_from(root, paths, read):
    """Products for a set of paths, reading changelog titles and .csproj files with `read(path) -> bytes`."""
    folders = {}
    for path in paths:
        if PurePosixPath(path).name == "CHANGELOG.md":
            folder = str(PurePosixPath(path).parent) if "/" in path else ""
            folder = "" if folder == "." else folder
            title = parse_changelog(read(path).decode("utf-8", "replace")).title
            folders[folder] = product_name(title, path, root)
    by_folder_name = {PurePosixPath(f).name.lower(): name for f, name in folders.items() if f}
    projects = {}
    for path in paths:
        if path.lower().endswith(".csproj"):
            found = MOD_FOLDER.search(read(path).decode("utf-8", "replace"))
            if found and found.group(1).lower() in by_folder_name:
                folder = str(PurePosixPath(path).parent)
                projects["" if folder == "." else folder] = by_folder_name[found.group(1).lower()]
    return Products(folders, projects)


def read_blobs(root, blobs, kept=None):
    """{blob: bytes} for these blobs, in one git cat-file --batch; `kept` (a dict) holds what earlier calls read."""
    kept = {} if kept is None else kept
    missing = [b for b in dict.fromkeys(blobs) if b not in kept]
    if missing:
        output = git(root, "cat-file", "--batch", stdin=("\n".join(missing) + "\n").encode())
        position = 0
        for blob in missing:
            end = output.index(b"\n", position)
            header = output[position:end].split()
            position = end + 1
            if len(header) < 3 or header[1] == b"missing":
                kept[blob] = b""
                continue
            size = int(header[2])
            kept[blob] = output[position:position + size]
            position += size + 1
    return kept


def _wanted_for_products(paths):
    return [p for p in paths if PurePosixPath(p).name == "CHANGELOG.md" or p.lower().endswith(".csproj")]


# ---------------------------------------------------------------- now

def tracked(root):
    """[(path, blob, size)] of every file HEAD holds."""
    listing = git(root, "ls-tree", "-r", "-l", "-z", "HEAD")
    found = []
    for record in listing.split(b"\0"):
        if not record:
            continue
        meta, _, path = record.partition(b"\t")
        mode, kind, blob, size = meta.split()
        if kind != b"blob":
            continue
        found.append((path.decode("utf-8", "replace"), blob.decode(), int(size) if size != b"-" else 0))
    return found


def now(root, environ=None, progress=None):
    """Every committed file: {path, product, group, kind, language, bytes, lines}, and the products' names."""
    root = Path(root).resolve()
    files = tracked(root)
    with closing(_line_cache(root, environ)) as lines_of:
        counts = _lines(root, [(blob, size) for path, blob, size in files if is_text(classify(path)[0])], lines_of, progress)
    blob_of = {path: blob for path, blob, _ in files}
    contents = read_blobs(root, [blob_of[p] for p in _wanted_for_products(blob_of)])
    products = products_from(root, list(blob_of), lambda p: contents[blob_of[p]])
    found = []
    for path, blob, size in files:
        kind, language = classify(path)
        product = products.of(path)
        found.append({"path": path, "product": product, "group": None if product else Products.group_of(path), "kind": kind,
                      "language": language, "bytes": size, "lines": counts.get(blob, 0) if is_text(kind) else 0})
    return {"repository": root.name, "commit": git(root, "rev-parse", "--short=12", "HEAD").decode().strip(),
            "kinds": list(KINDS), "products": sorted(set(products.folders.values()) | set(products.projects.values())),
            "files": found}


def _line_cache(root, environ):
    folder = derived.folder(CACHE_NAMESPACE, None, environ)
    folder.mkdir(parents=True, exist_ok=True)
    tag = re.sub(r"[^A-Za-z0-9._-]+", "-", Path(root).name)
    conn = sqlite3.connect(folder / f"{tag}-lines.sqlite")
    conn.execute("CREATE TABLE IF NOT EXISTS lines (blob TEXT PRIMARY KEY, lines INTEGER)")
    return conn


def _lines(root, blobs, conn, progress=None):
    """{blob: lines} for text blobs, reading only those the cache has not seen (git cat-file --batch)."""
    wanted = {blob for blob, size in blobs if size <= TEXT_LIMIT}
    known = {}
    listed = list(wanted)
    for start in range(0, len(listed), 500):
        chunk = listed[start:start + 500]
        known.update(conn.execute(f"SELECT blob, lines FROM lines WHERE blob IN ({','.join('?' * len(chunk))})", chunk))
    missing = [b for b in listed if b not in known]
    if missing:
        if progress:
            progress(f"Counting lines in {len(missing):,} file versions", 1, 2)
        contents = read_blobs(root, missing)
        for blob in missing:
            known[blob] = count_lines(contents[blob])
        conn.executemany("INSERT OR REPLACE INTO lines VALUES (?, ?)", [(b, known[b]) for b in missing])
        conn.commit()
    return known


# ---------------------------------------------------------------- growth

def folder_size(folder):
    """(bytes, files) of everything under a folder; (0, 0) when it is not there."""
    total, count = 0, 0
    for path in Path(folder).rglob("*"):
        try:
            if path.is_file():
                total += path.stat().st_size
                count += 1
        except OSError:
            continue
    return total, count


def installed_sizes(root, environ=None):
    """Each mod's size as installed (1.127.0; the owner's answer on D'thorga Companion's Decisions page, "Add it"): the folder the
    repository's installs.json and its game's adapter name for it, encoded textures and all, beside its folder in the repository.
    None for a repository with no installs.json; a problem, in words, when the installed mods can't be found."""
    from . import installs
    if not (Path(root) / "config" / "installs.json").is_file():
        return None
    try:
        place = installs.place(root, environ=environ)
    except Exception as problem:  # noqa: BLE001 - an adapter's or a settings file's failure is said, never a crash of the report
        return {"problem": str(problem) or type(problem).__name__, "folder": None, "mods": []}
    source = Path(root) / place.config["mods"]
    mods = []
    for folder in sorted((p for p in source.iterdir() if p.is_dir()), key=lambda p: p.name.lower()) if source.is_dir() else []:
        installed = place.installed(folder.name)
        size, files = folder_size(installed)
        repository_size, _ = folder_size(folder)
        mods.append({"mod": folder.name, "found": installed.is_dir(), "bytes": size, "files": files,
                     "repositoryBytes": repository_size})
    return {"problem": None, "folder": str(place.target), "mods": sorted(mods, key=lambda m: -m["bytes"])}


def daily_commits(root):
    """[(day, commit)] the last commit of each day on the first-parent line, oldest first."""
    log = git(root, "log", "--first-parent", "--format=%H %cs", "HEAD").decode().split("\n")
    last = {}
    for line in reversed([l for l in log if l.strip()]):
        commit, day = line.split()
        last[day] = commit
    return sorted(last.items())


def growth(root, environ=None, progress=None):
    """[{day, commit, kinds: {kind: [lines, bytes]}, products: {product: [lines, bytes]}}], one point a day, oldest first."""
    root = Path(root).resolve()
    days = daily_commits(root)
    points = []
    kept = {}
    with closing(_line_cache(root, environ)) as conn:
        for index, (day, commit) in enumerate(days, 1):
            if progress:
                progress(f"Reading {day}", index, len(days))
            listing = git(root, "ls-tree", "-r", "-l", "-z", commit)
            files = []
            for record in listing.split(b"\0"):
                if not record:
                    continue
                meta, _, path = record.partition(b"\t")
                mode, kind, blob, size = meta.split()
                if kind == b"blob":
                    files.append((path.decode("utf-8", "replace"), blob.decode(), int(size) if size != b"-" else 0))
            counts = _lines(root, [(b, s) for p, b, s in files if is_text(classify(p)[0])], conn)
            blob_of = {p: b for p, b, _ in files}
            read_blobs(root, [blob_of[p] for p in _wanted_for_products(blob_of)], kept)
            products = products_from(root, list(blob_of), lambda p: kept[blob_of[p]])
            kinds, owned = defaultdict(lambda: [0, 0]), defaultdict(lambda: [0, 0])
            for path, blob, size in files:
                kind, _ = classify(path)
                lines = counts.get(blob, 0) if is_text(kind) else 0
                kinds[kind][0] += lines
                kinds[kind][1] += size
                name = products.of(path) or f"({Products.group_of(path)})"
                owned[name][0] += lines
                owned[name][1] += size
            points.append({"day": day, "commit": commit[:12], "kinds": dict(kinds), "products": dict(owned)})
    return {"repository": root.name, "kinds": list(KINDS), "points": points}


# ---------------------------------------------------------------- churn

def churn(root, days=30, now_time=None):
    """{path: {commits, added, removed, last}} for every file a commit changed in the last `days` (0: every commit)."""
    root = Path(root).resolve()
    args = ["log", "--no-merges", "--numstat", "--format=%x00%cs", "--no-renames", "HEAD"]
    if days:
        since = (now_time or datetime.now(timezone.utc)) - timedelta(days=days)
        args.insert(1, f"--since={since.strftime('%Y-%m-%d')}")
    text = git(root, *args).decode("utf-8", "replace")
    found = {}
    day = ""
    for line in text.splitlines():
        if line.startswith("\0"):
            day = line[1:].strip()
            continue
        parts = line.split("\t")
        if len(parts) != 3:
            continue
        added, removed, path = parts
        entry = found.setdefault(path, {"commits": 0, "added": 0, "removed": 0, "last": day})
        entry["commits"] += 1
        entry["added"] += int(added) if added.isdigit() else 0
        entry["removed"] += int(removed) if removed.isdigit() else 0
        entry["last"] = max(entry["last"], day)
    return found


# ---------------------------------------------------------------- census

def census(root, graph, files):
    """{product: {defs: {type: count}, pictures, sounds, keys}}: what each product holds for players.

    Defs come from the repository's connections graph (XML Defs, abstract ones left out); text keys are the entries of the
    language files under a Keyed folder.
    """
    root = Path(root).resolve()
    product_of = {f["path"]: f["product"] or f"({f['group']})" for f in files}
    found = defaultdict(lambda: {"defs": defaultdict(int), "pictures": 0, "sounds": 0, "keys": 0})
    for node_id, path in graph.execute("SELECT id, file FROM nodes WHERE kind = 'def' AND external = 0 AND file IS NOT NULL"):
        def_type = node_id[len("def:"):].split("/", 1)[0]
        found[product_of.get(path, "(unknown)")]["defs"][def_type] += 1
    for f in files:
        name = product_of[f["path"]]
        if f["kind"] in ("pictures", "sounds"):
            found[name][f["kind"]] += 1
        elif "/keyed/" in f"/{f['path'].lower()}" and f["path"].lower().endswith(".xml"):
            try:
                text = (root / f["path"]).read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            found[name]["keys"] += max(0, len(KEYED_ENTRY.findall(text)) - 1)
    return {name: {**value, "defs": dict(sorted(value["defs"].items(), key=lambda kv: -kv[1]))} for name, value in found.items()}
