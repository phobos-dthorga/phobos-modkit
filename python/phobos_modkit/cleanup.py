"""What the kit's tools, and a repository's builds and tests, leave behind: found, measured and, on request, deleted.

Three sources, each saying why a thing may go:

- **The kit's cache** (phobos_modkit.paths.cache_root): every tool's derived data. A tool may declare a CACHE_POLICY for
  its folder: `stale`, a function naming why one file is no longer any use (its source has gone or changed), and `keep`,
  a reason the folder is never cleared (fetched pages, paced and slow to fetch again). Anything else goes once it has
  not changed for `older_than` days; the tools rebuild it on their next run. Frozen copies a crashed run left behind
  go after an hour.
- **The kit's build folder** (phobos_modkit.native.build_dir): the debug profile, which only the kit's own tests and
  development builds use. The release programs the tools run are never touched.
- **A repository's own rules** (config/cleanup.json): folders and name patterns for what its scripts and tests leave,
  with keep-newest counts and minimum ages. Matches are only ever direct children of the named folder.

Nothing is deleted without apply=True. Git's file-watcher daemons are listed too, and stopped on apply: they are only a
cache, and git starts one again when a repository needs it.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import fnmatch
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time

from . import cache as derived
from .native import build_dir
from .paths import cache_root

CONFIG = Path("config") / "cleanup.json"
SCHEMA_VERSION = 1
DAY = 24 * 60 * 60
FROZEN_MARK = ".frozen"
FROZEN_GRACE_SECONDS = 60 * 60
BUILD_PROFILES = ("debug",)          # cargo profiles only development uses; "release" holds the programs the tools run
BUILDERS = ("cargo", "rustc", "cargo-clippy", "clippy-driver")
_TOKEN = re.compile(r"\{(temp|env:[A-Za-z_][A-Za-z0-9_]*)\}")


class CleanupError(RuntimeError):
    pass


@dataclass
class Item:
    group: str
    path: Path
    size: int
    why: str


@dataclass
class Found:
    items: list = field(default_factory=list)
    notes: list = field(default_factory=list)       # what was skipped, and why
    daemons: list = field(default_factory=list)     # process IDs of git's file-watcher daemons

    @property
    def size(self):
        return sum(i.size for i in self.items)


# ---------------------------------------------------------------- measuring and deleting

def size_of(path):
    """Bytes in a file or a folder, never following links."""
    path = Path(path)
    try:
        if not path.is_dir() or path.is_symlink():
            return path.lstat().st_size
    except OSError:
        return 0
    total, stack = 0, [path]
    while stack:
        try:
            with os.scandir(stack.pop()) as entries:
                for entry in entries:
                    try:
                        if entry.is_dir(follow_symlinks=False):
                            stack.append(entry.path)
                        else:
                            total += entry.stat(follow_symlinks=False).st_size
                    except OSError:
                        pass
        except OSError:
            pass
    return total


def modified(path):
    try:
        return Path(path).lstat().st_mtime
    except OSError:
        return 0.0


def remove(path):
    """Delete a file or a folder, clearing the read-only flag Windows will not delete through (git's object files)."""
    path = Path(path)

    def writable_then_retry(function, failed, *_):
        os.chmod(failed, stat.S_IWRITE)
        function(failed)

    if path.is_dir() and not path.is_symlink():
        if sys.version_info >= (3, 12):
            shutil.rmtree(path, onexc=writable_then_retry)
        else:
            shutil.rmtree(path, onerror=writable_then_retry)
    else:
        derived.remove(path)


# ---------------------------------------------------------------- the kit's cache

def cache_policies():
    """{cache folder name: policy} from every command module that declares CACHE_POLICIES."""
    from importlib import import_module
    from .commands import COMMANDS
    policies = {}
    for module, _ in COMMANDS.values():
        for policy in getattr(import_module(module, __package__), "CACHE_POLICIES", ()):
            policies.setdefault(policy["folder"], policy)
    return policies


def cache_items(root, policies, older_than_days, now, environ=None, settings_file=None):
    """(items, notes) for the kit's cache folder."""
    items, notes = [], []
    root = Path(root)
    if not root.is_dir():
        return items, notes
    cutoff = now - older_than_days * DAY
    for folder in sorted(p for p in root.iterdir() if p.is_dir()):
        policy = policies.get(folder.name, {})
        if policy.get("keep"):
            notes.append(f"Kept the {folder.name} cache: {policy['keep']}.")
            continue
        for entry in sorted(folder.iterdir()):
            why = None
            if FROZEN_MARK in entry.name and modified(entry) < now - FROZEN_GRACE_SECONDS:
                why = "a private copy a run left behind when it stopped early"
            elif policy.get("stale") and entry.is_file():
                try:
                    why = policy["stale"](entry, environ, settings_file)
                except Exception as error:  # noqa: BLE001 - a policy that cannot judge leaves the file to the age rule
                    notes.append(f"Could not judge {entry.name} in {folder.name}: {error}")
            if not why and modified(entry) < cutoff:
                days = int((now - modified(entry)) // DAY)
                why = f"unchanged for {days} days; rebuilt when next needed"
            if why:
                items.append(Item(f"Cache: {folder.name}", entry, size_of(entry), why))
    return items, notes


# ---------------------------------------------------------------- the kit's build folder

def running_builders(listing=None):
    """Names of cargo or rustc processes running now; a build folder is never cleared under one."""
    if listing is None:
        if sys.platform == "win32":
            command = ["tasklist", "/FO", "CSV", "/NH"]
        else:
            command = ["ps", "-eo", "comm="]
        try:
            listing = subprocess.run(command, capture_output=True, text=True, check=False).stdout
        except OSError:
            return []
    found = set()
    for line in listing.splitlines():
        name = line.split(",")[0].strip().strip('"')
        stem = Path(name).stem.lower() if name else ""
        if stem in BUILDERS:
            found.add(stem)
    return sorted(found)


def build_items(folder, builders):
    """(items, notes) for the kit's build folder: its development profiles, unless a build is running."""
    folder = Path(folder)
    present = [folder / p for p in BUILD_PROFILES if (folder / p).is_dir()]
    if not present:
        return [], []
    if builders:
        return [], [f"Left the kit's build folder alone: {', '.join(builders)} is running. Run this again when it has finished."]
    why = "the kit's development build, for its own tests; the next test run rebuilds it, and the tools' programs stay"
    return [Item("Kit build folder", p, size_of(p), why) for p in present], []


# ---------------------------------------------------------------- a repository's rules

def load_rules(root, config=None):
    """The repository's rules, or [] when it has no config/cleanup.json."""
    path = Path(config) if config else Path(root) / CONFIG
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise CleanupError(f"{path} could not be read: {error}") from None
    if data.get("schemaVersion") != SCHEMA_VERSION:
        raise CleanupError(f"{path}: schemaVersion must be {SCHEMA_VERSION}.")
    rules = data.get("rules", [])
    for rule in rules:
        missing = [k for k in ("name", "folder", "match", "why") if not rule.get(k)]
        if missing:
            raise CleanupError(f"{path}: rule {rule.get('name', '?')!r} lacks {', '.join(missing)}.")
        if any(p.strip("*?") == "" for p in rule["match"]):
            raise CleanupError(f"{path}: rule {rule['name']!r} matches everything; name what it clears.")
        if rule.get("group") and "(?P<group>" not in rule["group"]:
            raise CleanupError(f"{path}: rule {rule['name']!r}: group must hold a (?P<group>...) part.")
    return rules


def expand(folder, root, environ):
    """A rule's folder as a path: {temp}, {env:NAME}, and paths relative to the repository. None when a variable is unset."""
    missing = []

    def token(match):
        name = match.group(1)
        if name == "temp":
            return tempfile.gettempdir()
        value = environ.get(name[4:])
        if not value:
            missing.append(name[4:])
        return value or ""

    text = _TOKEN.sub(token, folder)
    if missing:
        return None
    path = Path(text)
    return path if path.is_absolute() else Path(root) / path


def _matches(name, patterns):
    return any(fnmatch.fnmatch(name, p) for p in patterns)


def rule_items(rule, root, environ, now):
    """(items, notes) for one rule: direct children of its folder that match, past keep-newest and the minimum age."""
    folder = expand(rule["folder"], root, environ)
    if folder is None:
        return [], [f"{rule['name']}: skipped, its folder names an unset environment variable."]
    if not folder.is_dir():
        return [], []
    if folder.parent == folder or folder == Path.home():
        return [], [f"{rule['name']}: refused, {folder} is a drive or home folder itself."]
    kinds = rule.get("kinds", "any")
    candidates = []
    for entry in folder.iterdir():
        if not _matches(entry.name, rule["match"]):
            continue
        if (kinds == "folders" and not entry.is_dir()) or (kinds == "files" and not entry.is_file()):
            continue
        candidates.append(entry)
    group_pattern = re.compile(rule["group"]) if rule.get("group") else None
    groups = {}
    for entry in candidates:
        if group_pattern:
            match = group_pattern.match(entry.name)
            if not match:
                continue
            key = match.group("group")
        else:
            key = ""
        groups.setdefault(key, []).append(entry)
    keep = int(rule.get("keepNewest", 0))
    live = rule.get("liveGroups")
    min_age = float(rule.get("olderThanDays", 0)) * DAY
    by_name = rule.get("order") == "name"
    items = []
    for key, entries in groups.items():
        entries.sort(key=(lambda p: p.name) if by_name else (lambda p: (modified(p), p.name)))
        kept = keep
        why = rule["why"]
        if live and not (Path(root) / live.replace("{group}", key)).exists():
            kept, why = 0, f"{rule['why']}; {key} is no longer in the repository, so none is kept"
        for entry in entries[:max(0, len(entries) - kept)]:
            if now - modified(entry) < min_age:
                continue
            items.append(Item(rule["name"], entry, size_of(entry), why))
    return sorted(items, key=lambda i: str(i.path)), []


# ---------------------------------------------------------------- git's file-watcher daemons

def watcher_daemons():
    """Process IDs of running git fsmonitor daemons (Windows only; empty elsewhere)."""
    if sys.platform != "win32":
        return []
    command = ("Get-CimInstance Win32_Process -Filter \"Name='git.exe'\" | "
               "Where-Object { $_.CommandLine -match 'fsmonitor--daemon' } | ForEach-Object { $_.ProcessId }")
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", command],
                             capture_output=True, text=True, check=False).stdout
    except OSError:
        return []
    return [int(line) for line in out.split() if line.strip().isdigit()]


def stop_daemons(pids):
    stopped = 0
    for pid in pids:
        if subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True, check=False).returncode == 0:
            stopped += 1
    return stopped


# ---------------------------------------------------------------- the whole survey

def survey(root, older_than_days=14, config=None, environ=None, settings_file=None, now=None, include_build=True,
           policies=None, builders=None, daemons=None):
    """Everything that may go, with why. Reads only."""
    environ = os.environ if environ is None else environ
    now = time.time() if now is None else now
    found = Found()
    rules = load_rules(root, config)
    items, notes = cache_items(cache_root(None, environ, settings_file), cache_policies() if policies is None else policies,
                               older_than_days, now, environ, settings_file)
    found.items += items
    found.notes += notes
    if include_build:
        items, notes = build_items(build_dir(environ), running_builders() if builders is None else builders)
        found.items += items
        found.notes += notes
    for rule in rules:
        items, notes = rule_items(rule, root, environ, now)
        found.items += items
        found.notes += notes
    found.daemons = watcher_daemons() if daemons is None else daemons
    return found


def apply(found, stop=stop_daemons):
    """Delete what the survey found and stop the daemons. Returns (deleted items, failures as text, daemons stopped)."""
    stopped = stop(found.daemons) if found.daemons else 0
    deleted, failed = [], []
    for item in found.items:
        try:
            remove(item.path)
            deleted.append(item)
        except OSError as error:
            failed.append(f"{item.path} ({error.strerror or error})")
    return deleted, failed, stopped
