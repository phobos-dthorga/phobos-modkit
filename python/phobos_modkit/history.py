"""History: what happened to a repository's products over time, as facts, and each changelog as it stood at any moment.

Two kinds of fact (owner, 19 Nov 2026: "a timeline ... that records/shows how updates were applied, changed, removed, etc. over
time ... I like coming back and reading the CHANGELOGs from a particular update-in-moment"):

- **What the repository did**, recovered from git back to each repository's first commit: a product's changelog started, a
  version written, entries added, reworded or removed, a version removed or released, a product renamed, a product ended (merged
  into another). Every commit that touched a changelog is read once, its file parsed and compared with the one before; the
  facts are kept in the kit's cache and only new commits are read after that.
- **What happened on this PC**, which git cannot know: installed, went back, backed up, built, textures encoded. These are kept
  as they happen, one JSON line each, in the history log (`historyPath`, by default D'thorga Companion's folder; owner's choice,
  19 Nov 2026), one file per game. Recorded from 19 Nov 2026 on; earlier installs were not recovered (owner's choice).

The core names no game: a game reaches the log only as the name a caller passes.
"""
from __future__ import annotations

from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import subprocess

from . import cache as derived
from . import changes
from .installs import UNRELEASED, compare, parse_changelog
from .paths import companion_data, resolve

LOG = ("historyPath", "PHOBOS_HISTORY")
LOG_FORMAT = 1
CACHE_NAMESPACE = "history"
SCHEMA = "3"                  # raise when the facts worked out from git change, so every cache is rebuilt
MAX_LISTED = 8                # entries named in one fact
SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")
_DRAFT, _RELEASED = "draft", "released"


# ---------------------------------------------------------------- the history log (what happened on this PC)

def log_folder(environ=None, settings=None):
    """Where the history log is kept: historyPath, else the history folder in D'thorga Companion's own folder."""
    return resolve(*LOG, companion_data(environ) / "history", None, environ, settings)


def log_file(game, environ=None, settings=None):
    return log_folder(environ, settings) / f"{SAFE_NAME.sub('-', str(game)) or 'game'}.jsonl"


def now_iso(now=None):
    return (now or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat(timespec="seconds")


def record(game, kind, environ=None, settings=None, now=None, **fields):
    """Appends one fact to the game's history log. Never raises: the work it records has already happened, and a log that cannot
    be written must not undo it. Returns whether the line was written."""
    try:
        path = log_file(game, environ, settings)
        path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps({"format": LOG_FORMAT, "time": now_iso(now), "kind": kind, "game": game,
                           **{k: v for k, v in fields.items() if v is not None}}, ensure_ascii=False)
        with open(path, "a", encoding="utf-8", newline="\n") as handle:
            handle.write(line + "\n")
        return True
    except (OSError, TypeError, ValueError):
        return False


def read_log(game, environ=None, settings=None):
    """Every fact in the game's history log, oldest first; a line that cannot be read is skipped."""
    found = []
    try:
        lines = log_file(game, environ, settings).read_text(encoding="utf-8").splitlines()
    except OSError:
        return found
    for line in lines:
        try:
            fact = json.loads(line)
        except ValueError:
            continue
        if isinstance(fact, dict) and fact.get("format") == LOG_FORMAT and fact.get("kind") and fact.get("time"):
            fact["source"] = "log"
            found.append(fact)
    return found


# ---------------------------------------------------------------- reading old versions out of git

def git_lines(root, *arguments):
    return changes.git(root, *arguments, check=False).splitlines()


class Blobs:
    """Files as they stood at commits, read through one `git cat-file --batch` process."""

    def __init__(self, root):
        command = ["git", "--no-optional-locks", "-c", "core.fsmonitor=false", "-C", str(root), "cat-file", "--batch"]
        self.process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)

    def read(self, commit, path):
        """The file's text at that commit; None when it was not there."""
        self.process.stdin.write(f"{commit}:{path}\n".encode("utf-8"))
        self.process.stdin.flush()
        header = self.process.stdout.readline().decode("utf-8", "replace").split()
        if len(header) < 3 or header[-1] == "missing":
            return None
        size = int(header[2])
        data = self.process.stdout.read(size)
        self.process.stdout.read(1)
        return data.decode("utf-8", "replace")

    def close(self):
        try:
            self.process.stdin.close()
            self.process.wait(timeout=30)
        except (OSError, subprocess.SubprocessError):
            self.process.kill()
        finally:
            if self.process.stdout:
                self.process.stdout.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


def commits_of(root, path):
    """[(hash, unix time, subject)] of every commit that touched a path, oldest first; deleted files included."""
    found = []
    for line in git_lines(root, "log", "--reverse", "--format=%H%x1f%at%x1f%s", "--", path):
        parts = line.split("\x1f")
        if len(parts) == 3:
            found.append((parts[0], int(parts[1] or 0), parts[2]))
    return found


def deleted_changelogs(root):
    """Changelogs a commit removed and none put back, as paths in the repository."""
    current, gone = set(changes.changelogs(root)), set()
    for line in git_lines(root, "log", "--diff-filter=D", "--format=", "--name-only", "--", "*CHANGELOG.md", "CHANGELOG.md"):
        if line.strip() and line.strip() not in current:
            gone.add(line.strip())
    return sorted(gone)


def history_headings(root, commit):
    """{name: changelog path} for every "## <name> history" heading a commit added: where a removed changelog's history went."""
    found, path = {}, None
    for line in git_lines(root, "show", "--format=", "--unified=0", "--no-color", commit, "--", "*CHANGELOG.md", "CHANGELOG.md"):
        if line.startswith("+++ "):
            path = line[6:].strip() if line.startswith("+++ b/") else None
            continue
        heading = re.match(r"^\+## (.+) history\s*$", line)
        if heading and path:
            found[heading.group(1).strip()] = path
    return found


def merged_into(root, commit, product, blobs):
    """The product whose changelog took in this one's history at the commit that removed it; None when none did."""
    target = history_headings(root, commit).get(product)
    if not target:
        return None
    text = blobs.read(commit, target)
    return changes.product_name(parse_changelog(text).title, target, root) if text is not None else None


# ---------------------------------------------------------------- facts from two states of a changelog

def _status(rest):
    lower = (rest or "").lower()
    return _RELEASED if _RELEASED in lower else _DRAFT if _DRAFT in lower else ""


def _listed(entries):
    return [{"lead": e.lead, "section": e.section} for e in entries[:MAX_LISTED]]


def _by_version(entries):
    grouped = {}
    for entry in entries:
        grouped.setdefault(entry.version, []).append(entry)
    return grouped


def facts_between(before, after, base):
    """The facts one commit made, from the changelog before it (None at its first commit) and after it (None when removed).
    base holds the fields every fact shares: time, commit, subject, changelog, product."""
    found = []

    def fact(kind, **fields):
        found.append({**base, "kind": kind, **fields})

    if before is None and after is not None:
        versions = [v for v in after.headings if v != UNRELEASED]
        fact("product-started", count=len(after.entries), versions=len(versions), newest=versions[0] if versions else None)
        return found
    if after is None:
        return found
    if before.title and after.title and before.title != after.title:
        fact("product-renamed", was=changes.product_name(before.title, base["changelog"], ""),
             now=changes.product_name(after.title, base["changelog"], ""))
    old_versions, new_versions = set(before.headings), set(after.headings)
    written = [v for v in after.headings if v not in old_versions and v != UNRELEASED]
    removed = [v for v in before.headings if v not in new_versions and v != UNRELEASED]
    delta = compare(before, after)
    now_by_version = _by_version(after.entries)
    then_by_version = _by_version(before.entries)
    for version in written:
        entries = now_by_version.get(version, [])
        fact("version-written", version=version, count=len(entries), entries=_listed(entries),
             summary=after.summaries.get(version, ""), heading=after.headings.get(version, ""))
    for version in removed:
        entries = then_by_version.get(version, [])
        fact("version-removed", version=version, count=len(entries), entries=_listed(entries))
    for version in [v for v in after.headings if v in old_versions]:
        if _status(before.headings.get(version)) == _DRAFT and _status(after.headings.get(version)) == _RELEASED:
            fact("version-released", version=version, heading=after.headings.get(version, ""))
    for version, entries in _by_version([e for e in delta.gain if e.version not in written]).items():
        fact("entries-added", version=version, count=len(entries), entries=_listed(entries))
    for version, entries in _by_version([e for e in delta.lose if e.version not in removed]).items():
        fact("entries-removed", version=version, count=len(entries), entries=_listed(entries))
    reworded = {}
    for was, now in delta.reworded:
        reworded.setdefault(now.version, []).append({"lead": now.lead, "section": now.section, "was": was.text, "now": now.text})
    for version, pairs in reworded.items():
        fact("entries-reworded", version=version, count=len(pairs), entries=pairs[:MAX_LISTED])
    return found


# ---------------------------------------------------------------- the cache of facts from git

def _cache_file(root, environ=None, settings=None):
    root = Path(root).resolve()
    tag = hashlib.sha1(str(root).lower().encode("utf-8")).hexdigest()[:10]
    return derived.folder(CACHE_NAMESPACE, None, environ, settings) / f"{SAFE_NAME.sub('-', root.name)}-{tag}.sqlite"


def _open(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT)")
    if dict(conn.execute("SELECT key, value FROM meta").fetchall()).get("schema") != SCHEMA:
        conn.execute("DROP TABLE IF EXISTS state")
        conn.execute("DROP TABLE IF EXISTS facts")
        derived.write_meta(conn, {"schema": SCHEMA})
    conn.execute("CREATE TABLE IF NOT EXISTS state (changelog TEXT PRIMARY KEY, last_commit TEXT)")
    conn.execute("CREATE TABLE IF NOT EXISTS facts (changelog TEXT, seq INTEGER, body TEXT)")
    return conn


def _changelog_facts(conn, root, path, blobs, progress=None):
    """Brings one changelog's facts up to date in the cache and returns them, oldest first."""
    commits = commits_of(root, path)
    last = (conn.execute("SELECT last_commit FROM state WHERE changelog = ?", (path,)).fetchone() or [None])[0]
    hashes = [c[0] for c in commits]
    if last in hashes:
        start = hashes.index(last) + 1
        text = blobs.read(last, path)
        before = parse_changelog(text) if text is not None else None
        seq = (conn.execute("SELECT COALESCE(MAX(seq), -1) FROM facts WHERE changelog = ?", (path,)).fetchone()[0]) + 1
    else:
        conn.execute("DELETE FROM facts WHERE changelog = ?", (path,))
        start, before, seq = 0, None, 0
    product = changes.product_name(before.title, path, root) if before is not None else None
    for position, (commit, when, subject) in enumerate(commits[start:], start + 1):
        if progress and (position % 25 == 0 or position == len(commits)):
            progress(f"Reading the history of {path}", position, len(commits))
        text = blobs.read(commit, path)
        after = parse_changelog(text) if text is not None else None
        if after is not None:
            product = changes.product_name(after.title, path, root)
        base = {"time": datetime.fromtimestamp(when, timezone.utc).isoformat(timespec="seconds"), "commit": commit,
                "subject": subject, "changelog": path, "product": product or Path(path).parent.name or Path(root).name,
                "source": "git"}
        facts = facts_between(before, after, base)
        if before is not None and after is None:
            facts.append({**base, "kind": "product-ended", "mergedInto": merged_into(root, commit, base["product"], blobs)})
        for fact in facts:
            conn.execute("INSERT INTO facts VALUES (?, ?, ?)", (path, seq, json.dumps(fact, ensure_ascii=False)))
            seq += 1
        before = after
    if hashes:
        conn.execute("INSERT OR REPLACE INTO state VALUES (?, ?)", (path, hashes[-1]))
    conn.commit()
    return [json.loads(row[0]) for row in conn.execute("SELECT body FROM facts WHERE changelog = ? ORDER BY seq", (path,))]


def repository_facts(root, environ=None, settings=None, progress=None):
    """Every fact git holds about a repository's changelogs, current and removed, oldest first."""
    root = Path(root).resolve()
    paths = changes.changelogs(root) + deleted_changelogs(root)
    found = []
    with closing(_open(_cache_file(root, environ, settings))) as conn, Blobs(root) as blobs:
        for position, path in enumerate(paths, 1):
            if progress:
                progress(f"Reading the history of {path}", position, len(paths))
            found += _changelog_facts(conn, root, path, blobs)
    for fact in found:
        fact["repository"] = root.name
    return sorted(found, key=lambda f: f["time"])


# ---------------------------------------------------------------- a changelog as it stood

def commit_at(root, path, when):
    """The last commit at or before a moment that touched the changelog; None when it did not exist yet."""
    lines = git_lines(root, "log", "-1", f"--before={when}", "--format=%H", "--", path)
    return lines[0].strip() if lines else None


def describe(root, commit):
    found = changes.describe(root, commit)
    if found is None:
        return None
    return {"hash": found.hash, "time": datetime.fromtimestamp(found.time, timezone.utc).isoformat(timespec="seconds"),
            "author": found.author, "subject": found.subject}


def as_it_stood(root, path, commit):
    """The changelog at a commit, each entry marked by what happened to it since: kept, reworded (with its words now) or removed;
    and how many entries were added since. None when the file was not there at that commit."""
    root = Path(root).resolve()
    with Blobs(root) as blobs:
        text = blobs.read(commit, path)
    if text is None:
        return None
    then = parse_changelog(text)
    current = root / path
    now = parse_changelog(current.read_text(encoding="utf-8", errors="replace")) if current.is_file() else None
    delta = compare(then, now) if now is not None else None
    # compare keeps reworded entries out of its lost list, so the two never overlap
    removed = {e.key for e in (delta.lose if delta else then.entries)}
    reworded = {a.key: b.text for a, b in (delta.reworded if delta else [])}
    versions = []
    for version, rest in then.headings.items():
        entries = []
        for entry in [e for e in then.entries if e.version == version]:
            fate = "reworded" if entry.key in reworded else "removed" if entry.key in removed else "kept"
            entries.append({"section": entry.section, "text": entry.text, "lead": entry.lead, "since": fate,
                            "now": reworded.get(entry.key)})
        versions.append({"version": version, "heading": rest, "summary": then.summaries.get(version, ""), "entries": entries})
    return {"product": changes.product_name(then.title, path, root), "commit": describe(root, commit), "changelog": path,
            "stillThere": now is not None, "versions": versions,
            "since": {"added": len(delta.gain) if delta else 0, "reworded": len(reworded), "removed": len(removed)}}
