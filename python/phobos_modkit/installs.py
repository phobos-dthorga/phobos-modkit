"""Installed copies of a repository's mods: what each install, the repository and every backup hold, what moving between them
would gain or lose by their changelogs, and the three ways to move (back up, go back to a backup, install from the repository).

This is the install helper the kit's rules name as its one writer: it writes only when asked, never while the game runs, and the
install it replaces always becomes a backup first. The core names no game. A repository's config/installs.json names its game, and
the game's adapter (games/<game>/installs.py) says where installed mods live, how to read a mod's name and version, and which
processes mean the game is running.

    {"schemaVersion": 1, "game": "rimworld", "mods": "mods", "backups": ".local/deploy-backups",
     "settings": ".local/install-settings.json",
     "install": ["{python}", "scripts/deploy.py", "--build", "--apply", "{mod}"]}

What a move gains or loses is read from the two changelogs themselves, each install carrying its own: an entry in one and not the
other, matched by its text wherever it sits, so an Unreleased entry that later gains a version is neither gained nor lost.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from importlib import import_module
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import zipfile

from . import backup_archive as archives
from . import install_checks as checks
from .cleanup import remove, size_of
from .progress import run_streaming

CONFIG = Path("config") / "installs.json"
SCHEMA_VERSION = 1
CHANGELOG = "CHANGELOG.md"
RECORD = "InstallRecord.json"
RECORD_FORMAT = 1
STAMP = "%Y%m%d-%H%M%S"
BACKUP_NAME = re.compile(r"^(?P<mod>.+)-(?P<day>\d{8})-(?P<time>\d{6})$")
SPARE_BYTES = 1024 ** 3          # a backup or a move must leave at least this much free on its drive (agent default)
OUTPUT_LINES = 40                # lines of an install's output kept in its answer
INSTALL_TIMEOUT = 60 * 60        # seconds: a build and install that takes longer is stopped
SAVE_SECTION = "save compatibility"
UNRELEASED = "Unreleased"

_VERSION_HEADING = re.compile(r"^## \[(?P<version>[^\]]+)\](?P<rest>.*)$")
_HISTORY = re.compile(r"^## [^\[].* history$")
_BOLD_LEAD = re.compile(r"^\*\*(?P<lead>.+?)\*\*")
_VERSION_NUMBERS = re.compile(r"^\d+(?:\.\d+){1,3}$")


class InstallsError(ValueError):
    """A request this helper refuses, with the reason in words."""


# ---------------------------------------------------------------- changelogs

@dataclass(frozen=True)
class Entry:
    version: str          # the heading it sits under: a version number, or Unreleased
    section: str          # Added, Fixed, Save compatibility...; empty when the entry sits under no section
    text: str             # the entry as written, its lines joined
    lead: str             # its bold opening, or its first words
    first: str = ""       # its first line as the file holds it, for finding the commit that wrote it (changes.entry_commits)

    @property
    def key(self):
        return " ".join(self.text.split()).lower()

    @property
    def about_saves(self):
        return self.section.strip().lower() == SAVE_SECTION


@dataclass
class Changelog:
    title: str = ""
    summaries: dict = field(default_factory=dict)    # version -> the line under its heading, when it has one
    entries: list = field(default_factory=list)
    headings: dict = field(default_factory=dict)     # version -> what follows it in its heading ("2026-11-18 - Draft"), in order


def _lead(text):
    bold = _BOLD_LEAD.match(text)
    if bold:
        return bold.group("lead").strip()
    words = text.split()
    return " ".join(words[:12]) + (" ..." if len(words) > 12 else "")


def parse_changelog(text):
    """Every entry of a changelog, forgivingly: a structure fault only drops what it cannot place, never the whole file.

    A heading ending in "history" after the first version closes the mod's own log (merged mods' old logs follow it)."""
    log = Changelog()
    version, section, current, seen_version = None, "", None, False

    def finish():
        nonlocal current
        if current is not None and version is not None:
            joined = " ".join(part.strip() for part in current).strip()
            if joined:
                log.entries.append(Entry(version, section, joined, _lead(joined), current[0].strip()))
        current = None

    for line in text.lstrip("﻿").splitlines():
        if line.startswith("# ") and not log.title:
            log.title = line[2:].strip()
            continue
        if line.startswith("## "):
            finish()
            if seen_version and _HISTORY.match(line.strip()):
                break
            heading = _VERSION_HEADING.match(line.strip())
            version = heading.group("version").strip() if heading else line[3:].strip()
            if version.lower() == UNRELEASED.lower():
                version = UNRELEASED
            log.headings.setdefault(version, heading.group("rest").strip(" -") if heading else "")
            section, seen_version = "", True
            continue
        if line.startswith("### "):
            finish()
            section = line[4:].strip()
            continue
        if line.startswith(("- ", "* ")):
            finish()
            current = [line[2:]]
            continue
        if current is not None and line.startswith((" ", "\t")) and line.strip():
            current.append(line)
            continue
        finish()
        if version and not section and line.strip() and version not in log.summaries and version != UNRELEASED:
            log.summaries[version] = line.strip()
    finish()
    return log


def read_changelog(folder):
    path = Path(folder) / CHANGELOG
    try:
        return parse_changelog(path.read_text(encoding="utf-8", errors="replace"))
    except OSError:
        return None


@dataclass
class Delta:
    """Moving from one copy of a mod to another: entries only the other has (gained), entries only this one has (lost), and
    entries rewritten between them (the same version, section and opening, different words)."""
    gain: list = field(default_factory=list)
    lose: list = field(default_factory=list)
    reworded: list = field(default_factory=list)    # (as it is now, as it would be)
    unlisted: list = field(default_factory=list)    # taken out of lose by set_aside: not a removal the changelogs can show
    unlisted_why: dict = field(default_factory=dict)    # version -> REUSED or UNCOMMITTED

    @property
    def save_notes(self):
        return [e for e in self.gain + self.lose if e.about_saves]


REUSED = "reused"              # both changelogs hold this version, each with different entries under it
UNCOMMITTED = "uncommitted"    # installed from uncommitted work, under a version newer than any the repository's changelog holds


def set_aside(delta, current, other, record=None):
    """Takes out of a move's losses the entries a changelog cannot call lost: the installed copy's against the repository's.

    Two cases, each a fact the changelogs and the install record show. **A version number used twice**: both changelogs have the
    version, with no entry under it in common, so the number now names other work (one session renumbered, another took it).
    **Uncommitted work the repository's changelog does not hold now**: the install record says the copy was built with changes not
    yet committed, and the entry sits under a version newer than every one the repository's changelog has. In both the changelog is
    silent on whether the code went: it may have been renumbered, not yet written up again, or set aside. Moving to a backup is
    never set aside: a backup's changelog is what it holds. Returns the delta, changed in place."""
    if current is None or other is None or not delta.lose:
        return delta
    mine, theirs = _by_version(current), _by_version(other)
    newest = max((version_tuple(v) for v in other.headings if version_tuple(v)), default=None)
    built_unsaved = bool((record or {}).get("uncommittedCount"))
    for version in sorted({e.version for e in delta.lose}):
        why = None
        if version in theirs and mine.get(version) and theirs[version]:
            shared = ({e.key for e in mine[version]} & {e.key for e in theirs[version]}
                      or {e.lead for e in mine[version]} & {e.lead for e in theirs[version]})
            why = None if shared else REUSED
        elif version not in theirs and built_unsaved and version_tuple(version) and newest and version_tuple(version) > newest:
            why = UNCOMMITTED
        if why:
            delta.unlisted_why[version] = why
            delta.unlisted += [e for e in delta.lose if e.version == version]
            delta.lose = [e for e in delta.lose if e.version != version]
    return delta


def _by_version(log):
    found = {}
    for entry in log.entries:
        found.setdefault(entry.version, []).append(entry)
    return found


def compare(current, other):
    """What moving from the current changelog to the other gains and loses. Either may be None (no changelog): nothing is known."""
    if current is None or other is None:
        return Delta()
    have = {e.key for e in current.entries}
    would = {e.key for e in other.entries}
    gain = [e for e in other.entries if e.key not in have]
    lose = [e for e in current.entries if e.key not in would]
    reworded = []
    for old in list(lose):
        match = next((new for new in gain if (new.version, new.section, new.lead) == (old.version, old.section, old.lead)), None)
        if match is not None:
            reworded.append((old, match))
            lose.remove(old)
            gain.remove(match)
    return Delta(gain, lose, reworded)


def version_tuple(version):
    return tuple(int(n) for n in version.split(".")) if version and _VERSION_NUMBERS.match(version) else None


def direction(current, other):
    """"newer", "older", "same" or "unknown": the other copy's version against the current one's."""
    a, b = version_tuple(current), version_tuple(other)
    if a is None or b is None:
        return "unknown"
    return "newer" if b > a else "older" if b < a else "same"


# ---------------------------------------------------------------- configuration and the game's adapter

def load_config(root):
    path = Path(root) / CONFIG
    if not path.is_file():
        raise InstallsError(f"{path} does not exist: this repository does not say where its mods are installed.")
    try:
        config = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise InstallsError(f"{path} could not be read: {error}") from None
    if config.get("schemaVersion") != SCHEMA_VERSION:
        raise InstallsError(f"{path} has schemaVersion {config.get('schemaVersion')!r}; this kit reads {SCHEMA_VERSION}.")
    for key in ("game", "mods", "backups"):
        if not isinstance(config.get(key), str) or not config[key]:
            raise InstallsError(f"{path} names no {key}.")
    return config


def adapter(config):
    try:
        return import_module(f".games.{config['game']}.installs", __package__)
    except ImportError:
        raise InstallsError(f"The kit has no install adapter for the game {config['game']!r}.") from None


def settings_file(root, config, explicit=None):
    if explicit:
        return Path(explicit)
    named = config.get("settings")
    return Path(root) / named if named else None


def game_running(names, listing=None):
    """The names of the game's processes running now (Windows tasklist; ps elsewhere)."""
    if listing is None:
        command = ["tasklist", "/FO", "CSV", "/NH"] if sys.platform == "win32" else ["ps", "-eo", "comm="]
        try:
            listing = subprocess.run(command, capture_output=True, text=True, check=False).stdout
        except OSError:
            return []
    wanted = {n.lower() for n in names}
    found = set()
    for line in listing.splitlines():
        name = Path(line.split(",")[0].strip().strip('"')).name.lower()
        if name in wanted:
            found.add(name)
    return sorted(found)


# ---------------------------------------------------------------- the install record

def _git(root, *arguments):
    command = ["git", "--no-optional-locks", "-c", "core.fsmonitor=false", "-C", str(root), *arguments]
    try:
        result = subprocess.run(command, capture_output=True, text=True, check=False, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout if result.returncode == 0 else None


def uncommitted(root, paths):
    """Files with changes not yet committed under any of the paths (relative to the repository), as git names them."""
    out = _git(root, "status", "--porcelain", "--untracked-files=all", "--", *paths)
    return [] if out is None else sorted(line[3:].strip().strip('"') for line in out.splitlines() if len(line) > 3)


def head(root):
    out = _git(root, "rev-parse", "HEAD")
    return out.strip() if out else None


def commits_since(root, commit, path):
    """Commits since commit that touched path; None when git cannot say (an unknown commit, no git)."""
    if not commit:
        return None
    out = _git(root, "rev-list", "--count", f"{commit}..HEAD", "--", path)
    try:
        return int(out.strip()) if out else None
    except ValueError:
        return None


def record_for(root, config, mod, version, now=None):
    """What an install record says: where the copy came from and when. Written into the installed copy by the install itself."""
    mods = config["mods"]
    changed = uncommitted(root, [f"{mods}/{mod}", *config.get("sharedSources", [])])
    return {"format": RECORD_FORMAT, "mod": mod, "version": version, "repository": Path(root).resolve().name,
            "game": config.get("game"), "product": _product_of(root, config, mod), "changelog": f"{mods}/{mod}/{CHANGELOG}",
            "commit": head(root), "uncommitted": changed[:50], "uncommittedCount": len(changed),
            "installed": (now or datetime.now(timezone.utc)).isoformat(timespec="seconds")}


def _product_of(root, config, mod):
    """A mod's name as its changelog gives it, for the history log; its folder's name when it has none."""
    log = read_changelog(Path(root) / config["mods"] / mod)
    from .changes import product_name
    return product_name(log.title, f"{config['mods']}/{mod}/{CHANGELOG}", root) if log and log.title else mod


def write_record(target, record, settings=None, environ=None):
    """Writes the install record into the installed copy, and notes the install in the game's history log."""
    with open(Path(target) / RECORD, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(record, handle, indent=2)
        handle.write("\n")
    if record.get("game"):
        from . import history
        history.record(record["game"], "installed", environ, settings, repository=record.get("repository"), mod=record.get("mod"),
                       product=record.get("product"), version=record.get("version"), commit=record.get("commit"),
                       uncommittedCount=record.get("uncommittedCount") or None, changelog=record.get("changelog"))


def note(where, kind, **fields):
    """Notes a move in the game's history log (the install helper's moves: backed up, went back, built). Never raises."""
    from . import history
    return history.record(where.config["game"], kind, where.environ, where.settings, repository=where.root.name, **fields)


def read_record(folder):
    try:
        record = json.loads((Path(folder) / RECORD).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return record if isinstance(record, dict) and record.get("format") == RECORD_FORMAT else None


# ---------------------------------------------------------------- what is where

@dataclass
class Copy:
    """One copy of a mod: the repository's, the installed one, or a backup."""
    kind: str                 # "repository", "installed" or "backup"
    folder: Path
    name: str = ""
    version: str = ""
    changelog: Changelog = None
    record: dict = None
    backup: str = ""          # a backup's folder name
    taken: str = ""           # a backup's time, from its name
    size: int = None
    same_as: str = ""         # a backup's older twin: the oldest backup of the run it repeats (duplicates)
    same_kind: str = ""       # how it repeats it: identical, or rebuilt only
    archive: Path = None      # a backup kept as a zip (1.96.0): the zip, while folder holds the files read from it


def stored_path(copy):
    """Where a copy is kept: a zipped backup's zip, else its folder."""
    return copy.archive or copy.folder


def read_copy(kind, folder, game, measure=False, backup=""):
    folder = Path(folder)
    name, version = game.identity(folder)
    copy = Copy(kind, folder, name, version, read_changelog(folder), read_record(folder), backup)
    if backup:
        found = BACKUP_NAME.match(backup)
        if found:
            stamp = datetime.strptime(found.group("day") + found.group("time"), "%Y%m%d%H%M%S")
            copy.taken = stamp.isoformat(timespec="seconds")
    if measure:
        copy.size = size_of(folder)
    return copy


def mods_of(root, config):
    folder = Path(root) / config["mods"]
    try:
        return sorted(p.name for p in folder.iterdir() if p.is_dir() and (p / CHANGELOG).is_file())
    except OSError:
        return []


def backups_of(backups, mod):
    """A mod's backup names, newest first: folders, and zips (1.96.0) without their suffix."""
    found = [n for n in archives.names(backups) if (m := BACKUP_NAME.match(n)) and m.group("mod") == mod]
    return sorted(found, key=lambda n: n[-15:], reverse=True)


PEEKS = "backup-peeks"
# The kinds of changed file a program sets beside a backup's copy (D'thorga Companion's Mods page draws pictures, decoded textures
# among them, and plays sounds): only these are copied out of a zipped backup with its name and version (1.149.0). Before, every
# changed file was, and 200 peeks held 150 MB of assemblies and XML that nothing compared.
COMPARED_KINDS = frozenset({"picture", "texture", "sound"})


def _peek_folder(where, name):
    from . import cache as derived
    return derived.folder(DIGEST_CACHE, None, where.environ, where.settings) / PEEKS / name


def compared(relative):
    """Whether a changed file is one a program compares with a backup's copy, by its kind (changes.MEDIA)."""
    from .changes import MEDIA          # changes reads this module's changelog helpers, so not at import time
    return MEDIA.get(Path(relative).suffix.lower()) in COMPARED_KINDS


def _identity_files(game):
    """The files a copy's name, version, changelog and install record are read from, in lower case."""
    return {CHANGELOG.lower(), RECORD.lower(), str(getattr(game, "VERSION_FILE", "")).lower()} - {""}


def read_backup(where, name, measure=False, also=()):
    """One backup, kept as a folder or a zip. A zip's name, version, changelog and install record (and the files named in also,
    such as a changed picture to compare) are read from a copy of just those files in the kit's cache, which its folder names."""
    path = archives.stored(where.backups, name)
    if path is None or not archives.is_archive(path):
        return read_copy("backup", where.backups / name, where.game, measure, name)
    wanted, extra = _identity_files(where.game), {relative for relative in also if compared(relative)}
    folder = archives.peek(path, lambda relative: relative.lower() in wanted or relative in extra, _peek_folder(where, name))
    copy = read_copy("backup", folder, where.game, False, name)
    copy.archive = path
    if measure:
        copy.size = path.stat().st_size
    return copy


def _forget_peek(where, name):
    folder = _peek_folder(where, name)
    if folder.is_dir():
        shutil.rmtree(folder, ignore_errors=True)


# ---------------------------------------------------------------- duplicate backups

DIGEST_CACHE = "installs"
DIGEST_FILE = "backup-digests.json"
DIGEST_FORMAT = 2
_CHUNK = 1024 * 1024
ASSEMBLY = ".dll"
IDENTICAL, REBUILT = "identical", "rebuilt"


def content_digests(path):
    """(full, lean): hashes of every file in a folder or a backup's zip, by path and bytes, leaving out the install record, and
    for lean the assemblies too. Two copies with the same full digest hold the same mod file for file, whenever and from whichever
    commit each was installed, and a folder and its zip give the same digests. One reading makes both."""
    full, lean = hashlib.sha256(), hashlib.sha256()
    opened = zipfile.ZipFile(path) if archives.is_archive(path) else None
    if opened is not None:
        entries = [(relative, lambda info=info: opened.open(info)) for relative, info in archives.members(path)]
    else:
        entries = [(relative, lambda found=found: open(found, "rb")) for relative, found in archives.files_of(path)]
    try:
        for relative, open_it in entries:
            if relative == RECORD:
                continue
            both = [full] if relative.lower().endswith(ASSEMBLY) else [full, lean]
            for digest in both:
                digest.update(relative.encode("utf-8") + b"\0")
            with open_it() as handle:
                while chunk := handle.read(_CHUNK):
                    for digest in both:
                        digest.update(chunk)
            for digest in both:
                digest.update(b"\0")
    finally:
        if opened is not None:
            opened.close()
    return full.hexdigest(), lean.hexdigest()


def content_digest(path, leave_out_assemblies=False):
    """content_digests' full digest, or its lean one."""
    return content_digests(path)[1 if leave_out_assemblies else 0]


def _digest_store(environ=None, settings=None):
    from . import cache as derived
    return derived.folder(DIGEST_CACHE, None, environ, settings) / DIGEST_FILE


def backup_digests(copies, environ=None, settings=None, progress=None):
    """{backup name: {"full": digest, "lean": digest without assemblies}} for these backups. A backup never changes once made, so
    its digests are kept in the kit's cache by its folder and size, and only new backups are read."""
    store = _digest_store(environ, settings)
    try:
        kept = json.loads(store.read_text(encoding="utf-8"))
        if kept.get("format") != DIGEST_FORMAT:
            kept = {}
    except (OSError, ValueError, AttributeError):
        kept = {}
    folders = kept.setdefault("folders", {})
    kept["format"] = DIGEST_FORMAT
    found, fresh = {}, False
    sizes = {c.backup: c.size if c.size is not None else size_of(stored_path(c)) for c in copies}
    unread = sum(1 for c in copies if folders.get(str(stored_path(c)), {}).get("size") != sizes[c.backup])
    for position, copy in enumerate(copies, 1):
        key = str(stored_path(copy))
        entry = folders.get(key)
        if not entry or entry.get("size") != sizes[copy.backup]:
            if progress:
                progress(f"Comparing backups file for file ({unread:,} not read before)", position, len(copies), copy.backup)
            full, lean = content_digests(stored_path(copy))
            entry = folders[key] = {"size": sizes[copy.backup], "full": full, "lean": lean}
            fresh = True
        found[copy.backup] = entry
    if fresh:
        _keep_digests(store, kept)
    return found


def _keep_digests(store, kept):
    """Writes the digests kept, letting go of those whose backup has gone."""
    try:
        store.parent.mkdir(parents=True, exist_ok=True)
        kept["folders"] = {k: v for k, v in kept.get("folders", {}).items() if Path(k).exists()}
        store.write_text(json.dumps(kept), encoding="utf-8")
    except OSError:
        pass


def _remember_digests(where, path, size, digests):
    """Keeps the digests of a backup just written or packed, so the next reading need not read it again."""
    store = _digest_store(where.environ, where.settings)
    try:
        kept = json.loads(store.read_text(encoding="utf-8"))
        if kept.get("format") != DIGEST_FORMAT:
            kept = {}
    except (OSError, ValueError, AttributeError):
        kept = {}
    kept["format"] = DIGEST_FORMAT
    kept.setdefault("folders", {})[str(path)] = {"size": size, "full": digests[0], "lean": digests[1]}
    _keep_digests(store, kept)


def _commit_of(copy):
    record = copy.record or {}
    return record.get("commit") if not record.get("uncommittedCount") else None


def sources_unchanged(root, older, newer, inputs, asked=None):
    """Whether none of a mod's own sources (its projects' inputs) changed between two commits; False when git cannot say."""
    if not older or not newer or not inputs:
        return False
    if older == newer:
        return True
    key = (older, newer)
    if asked is not None and key in asked:
        return asked[key]
    out = checks._git(root, "diff", "--name-only", older, newer, "--", *inputs)
    same = out is not None and not out.strip()
    if asked is not None:
        asked[key] = same
    return same


def mark_duplicates(backups, digests, rebuilt_check=None):
    """Sets same_as and same_kind on every backup that repeats the one before it in time, naming the oldest of its run.

    Identical: the same file for file. Rebuilt: the same version, every file but the assemblies the same, and rebuilt_check (given
    the two copies) says the mod's own sources did not change between their commits, so only a rebuild against newer code it uses
    tells them apart. Only a run counts: A, A, B, A keeps the last A, because it is the newest backup from after B, and "the newest
    backup from before a moment" must still find it. The oldest of each run is kept."""
    keeper = None
    for copy in sorted(backups, key=lambda c: c.backup[-15:]):
        mine, theirs = digests.get(copy.backup) or {}, digests.get(keeper.backup) if keeper else None
        kind = ""
        if theirs and mine:
            if mine.get("full") == theirs.get("full"):
                kind = IDENTICAL
            elif (rebuilt_check and copy.version and copy.version == keeper.version
                  and mine.get("lean") == theirs.get("lean") and rebuilt_check(keeper, copy)):
                kind = REBUILT
        if kind:
            copy.same_as, copy.same_kind = keeper.backup, kind
        else:
            copy.same_as, copy.same_kind = "", ""
            keeper = copy
    return [c for c in backups if c.same_as]


def _rebuilt_check(where, mod, builds=None, asked=None):
    builds = builds if builds is not None else checks.build_states(where.root, where.config)
    inputs = sorted({path for build in builds.get(mod, []) for path in build.get("inputs", [])})
    asked = {} if asked is None else asked
    return lambda older, newer: sources_unchanged(where.root, _commit_of(older), _commit_of(newer), inputs, asked)


def dedupe(where, mods=None, kinds=(IDENTICAL, REBUILT), progress=None):
    """Removes every backup that repeats the one before it (identical, or only rebuilt, as kinds allow), keeping the oldest of each
    run. Each is read again and compared with the one kept just before it is removed. Returns [{mod, backup, sameAs, kind, size}]."""
    removed = []
    names = list(mods or mods_of(where.root, where.config))
    builds = checks.build_states(where.root, where.config)
    for mod in names:
        if mods:
            _known_mod(where, mod)
        copies = [read_backup(where, name, True) for name in backups_of(where.backups, mod)]
        doubles = [c for c in mark_duplicates(copies, backup_digests(copies, where.environ, where.settings, progress),
                                              _rebuilt_check(where, mod, builds)) if c.same_kind in kinds]
        kept = {}
        for position, copy in enumerate(sorted(doubles, key=lambda c: c.backup), 1):
            if progress:
                progress(f"Removing repeated backups of {mod}", position, len(doubles), copy.backup)
            keeper = archives.stored(where.backups, copy.same_as)
            lean = copy.same_kind == REBUILT
            if (copy.same_as, lean) not in kept:
                kept[(copy.same_as, lean)] = content_digest(keeper, lean) if keeper else None
            if kept[(copy.same_as, lean)] is None or content_digest(stored_path(copy), lean) != kept[(copy.same_as, lean)]:
                continue    # no longer a twin of something that is still there: leave it alone
            remove(stored_path(copy))
            _forget_peek(where, copy.backup)
            removed.append({"mod": mod, "backup": copy.backup, "sameAs": copy.same_as, "kind": copy.same_kind,
                            "size": copy.size or 0})
    if removed:
        note(where, "duplicates-removed", count=len(removed), size=sum(r["size"] for r in removed),
             mods=sorted({r["mod"] for r in removed}))
    return removed


PACKED = "packed"


def pack(where, mods=None, progress=None):
    """Turns every backup still kept as a folder into a zip (1.96.0; the owner's choice of 23 Nov 2026), each checked file for
    file against its folder before the folder goes; one that fails a check, or would leave the drive short, stays a folder.
    Returns (packed, left): [{mod, backup, kind: "packed", before, after}], and [{backup, problem}] for those left as they were."""
    packed, left = [], []
    names = list(mods or mods_of(where.root, where.config))
    folders = [(mod, name) for mod in names for name in backups_of(where.backups, mod)
               if (where.backups / name).is_dir() and not archives.archive_of(where.backups, name).exists()]
    for position, (mod, name) in enumerate(folders, 1):
        folder, archive = where.backups / name, archives.archive_of(where.backups, name)
        before = size_of(folder)
        if progress:
            progress(f"Packing backups as zips ({before / 1024 ** 2:,.0f} MB)", position, len(folders), name)
        try:
            _need_space(where.backups, before, f"Packing {name}")
            wanted = content_digests(folder)
            after = archives.write(folder, archive)
            if content_digests(archive) != wanted:
                remove(archive)
                raise InstallsError("the zip did not hold the same files as the folder")
        except (InstallsError, archives.ArchiveError, OSError) as error:
            left.append({"backup": name, "problem": str(error)})
            continue
        _remember_digests(where, archive, after, wanted)
        remove(folder)
        packed.append({"mod": mod, "backup": name, "kind": PACKED, "before": before, "after": after})
    if packed:
        note(where, "backups-packed", count=len(packed), before=sum(p["before"] for p in packed),
             after=sum(p["after"] for p in packed), mods=sorted({p["mod"] for p in packed}))
    return packed, left


def tidy(where, mods, progress=None):
    """The last step of an install or a go-back (owner, 20 Nov 2026: removing repeated backups "should be part of the normal
    process"): removes the repeated backups of the mods just moved, both kinds, as dedupe does, then packs those mods' backups
    still kept as folders (1.96.0). The move itself has already succeeded, so this never raises. Returns (done, problem): what was
    removed, then what was packed (each marked kind "packed"), and why it could not finish, or None."""
    try:
        removed = dedupe(where, mods, progress=progress)
        packed, left = pack(where, mods, progress)
    except Exception as error:  # noqa: BLE001 (the install or go-back has already succeeded; only the tidying goes without)
        return [], str(error)
    problem = "; ".join(f"{item['backup']}: {item['problem']}" for item in left) or None
    return removed + packed, problem


def tidy_lines(done, problem):
    """A person's lines for what tidy did, for an install or a go-back to print after its own."""
    removed = [r for r in done if r["kind"] != PACKED]
    packed = [p for p in done if p["kind"] == PACKED]
    lines = [f"Removed the backup {r['backup']}: it repeated {r['sameAs']}" + (" (only rebuilt)" if r["kind"] == REBUILT else "")
             + ", which is kept." for r in removed]
    if packed:
        before, after = sum(p["before"] for p in packed), sum(p["after"] for p in packed)
        lines.append(f"Packed {len(packed):,} backup{'s' if len(packed) != 1 else ''} as zips: {before / 1024 ** 2:,.0f} MB "
                     f"became {after / 1024 ** 2:,.0f} MB, each checked file for file first.")
    if problem:
        lines.append(f"The backups were not all tidied ({problem}); Remove repeated backups can do it later, and the next install "
                     "packs what is left.")
    return lines


@dataclass
class Place:
    """Where one repository's mods come from, go to and are backed up."""
    root: Path
    config: dict
    game: object
    target: Path              # the game's folder of installed mods
    backups: Path
    settings: Path = None
    environ: dict = None       # the environment the caller gave, for every path worked out later (the history log)

    def installed(self, mod):
        return self.target / mod

    def source(self, mod):
        return self.root / self.config["mods"] / mod


def place(root, settings=None, environ=None):
    root = Path(root).resolve()
    config = load_config(root)
    game = adapter(config)
    named = settings_file(root, config, settings)
    target = Path(game.installed_mods(named, environ))
    return Place(root, config, game, target, root / config["backups"], named, environ)


@dataclass
class ModState:
    mod: str
    repository: Copy
    installed: Copy = None
    backups: list = field(default_factory=list)
    uncommitted: list = field(default_factory=list)
    commits_since: int = None
    files: dict = None               # install_checks.compare_files, installed against the repository's copy
    builds: list = field(default_factory=list)   # install_checks.build_states for this mod's projects
    commit: str = None               # the installed commit
    commit_exact: bool = False       # from the install record, not worked out from the version
    settings: list = None            # settings changes since the installed commit; None when unknown
    settings_note: str = None
    look_out: list = field(default_factory=list)
    changelog: str = ""              # the repository copy's changelog, as a path in the repository (for the changes tool)

    @property
    def needs_build(self):
        return any(b["needsBuild"] for b in self.builds)


def installed_commit(where, installed):
    """(commit, exact): the install record's commit, or the commit that first gave the mod its installed version."""
    if installed is None:
        return None, False
    recorded = (installed.record or {}).get("commit")
    if recorded:
        return recorded, True
    marker = getattr(where.game, "version_marker", None)
    if not installed.version or marker is None:
        return None, False
    version_file = f"{where.config['mods']}/{installed.folder.name}/{where.game.VERSION_FILE}"
    return checks.version_commit(where.root, version_file, marker(installed.version)), False


def survey(where, mods=None, measure=True, run=subprocess.run, progress=None):
    states = []
    progress = progress or (lambda *a, **k: None)
    progress("Looking at what needs a build")
    builds = checks.build_states(where.root, where.config)
    install_only = [RECORD, *where.config.get("installOnly", [])]
    names = list(mods or mods_of(where.root, where.config))
    for position, mod in enumerate(names, 1):
        repository = read_copy("repository", where.source(mod), where.game)
        progress(f"Comparing {repository.name or mod} with its installed copy and backups", position, len(names) + 1)
        installed_folder = where.installed(mod)
        installed = read_copy("installed", installed_folder, where.game) if installed_folder.is_dir() else None
        files = checks.compare_files(installed.folder, repository.folder, install_only) if installed is not None else None
        # A zipped backup's changed pictures and sounds are copied out beside its name and version, so they can be compared.
        changed_paths = [p["path"] for p in (files or {}).get("paths", [])]
        backups = [read_backup(where, name, measure, changed_paths) for name in backups_of(where.backups, mod)]
        changed = uncommitted(where.root, [f"{where.config['mods']}/{mod}", *where.config.get("sharedSources", [])])
        commit, exact = installed_commit(where, installed)
        since = commits_since(where.root, commit, f"{where.config['mods']}/{mod}")
        state = ModState(mod, repository, installed, backups, changed, since, builds=builds.get(mod, []), commit=commit,
                         commit_exact=exact, changelog=f"{where.config['mods']}/{mod}/{CHANGELOG}")
        if installed is not None:
            state.files = files
            checks.mark_rebuilt(state.files, state.builds, where.root, commit)
            state.look_out = checks.look_out(where.root, repository.name, installed.version, repository.version)
        states.append(state)
    every = [b for s in states for b in s.backups]
    if measure and every:
        digests = backup_digests(every, where.environ, where.settings, progress)
        asked = {}
        for state in states:
            mark_duplicates(state.backups, digests, _rebuilt_check(where, state.mod, builds, asked))
    progress("Reading what settings an install would change", len(names) + 1, len(names) + 1)
    _add_settings(where, states, run)
    return states


def _add_settings(where, states, run):
    """Settings changes since each installed commit, read once per commit, for mods not already in step."""
    by_commit = {}
    for state in states:
        in_step = state.files is not None and state.files["total"] == 0 and not state.needs_build and not state.uncommitted
        if state.commit and not in_step:
            by_commit.setdefault(state.commit, []).append(state)
    for commit, group in by_commit.items():
        found, note = checks.settings_changes(where.root, where.config, commit, run)
        for state in group:
            state.settings_note = note
            if found is not None:
                state.settings = [c for c in found if c.get("mod") == state.mod]


def free_bytes(folder):
    """Free space on the drive holding folder (or its nearest existing parent); None when it cannot be read."""
    folder = Path(folder)
    while not folder.exists() and folder.parent != folder:
        folder = folder.parent
    try:
        return shutil.disk_usage(folder).free
    except OSError:
        return None


# ---------------------------------------------------------------- moving between copies

def _stamp(now=None):
    return (now or datetime.now()).strftime(STAMP)


def _need_space(folder, size, what):
    free = free_bytes(folder)
    if free is not None and free - size < SPARE_BYTES:
        raise InstallsError(f"{what} needs {size / 1024 ** 2:,.0f} MB and would leave less than {SPARE_BYTES // 1024 ** 3} GB free "
                            f"on the drive holding {folder} ({free / 1024 ** 2:,.0f} MB free now). Nothing was changed.")


def _refuse_while_running(where, running):
    names = running(where.game.PROCESSES)
    if names:
        raise InstallsError(f"The game is running ({', '.join(names)}). Close it, then try again. Nothing was changed.")


def _known_mod(where, mod):
    if mod not in mods_of(where.root, where.config):
        raise InstallsError(f"{mod!r} is not one of this repository's mods.")


def _free_name(folder, mod, now):
    stamp = _stamp(now)
    name = f"{mod}-{stamp}"
    if (Path(folder) / name).exists() or archives.archive_of(folder, name).exists():
        raise InstallsError(f"A backup named {name} already exists; wait a second and try again. Nothing was changed.")
    return name


def backup(where, mod, now=None):
    """Packs the installed mod into a zip in the backups folder (a plain folder until 1.96.0), checked file for file. Returns the
    new backup's name. Safe while the game runs: it only reads."""
    _known_mod(where, mod)
    installed = where.installed(mod)
    if not installed.is_dir():
        raise InstallsError(f"{mod} is not installed, so there is nothing to back up.")
    _need_space(where.backups, size_of(installed), "The backup")
    name = _free_name(where.backups, mod, now)
    where.backups.mkdir(parents=True, exist_ok=True)
    archive = archives.archive_of(where.backups, name)
    try:
        wanted = content_digests(installed)
        after = archives.write(installed, archive)
        if content_digests(archive) != wanted:
            remove(archive)
            raise archives.ArchiveError("it did not hold the same files as the install")
    except (archives.ArchiveError, OSError) as error:
        raise InstallsError(f"The backup could not be made ({error}). Nothing was changed.") from None
    _remember_digests(where, archive, after, wanted)
    copy = read_backup(where, name)
    note(where, "backed-up", mod=mod, product=copy.name or mod, version=copy.version, backup=name)
    return name


def restore(where, mod, name, now=None, running=game_running):
    """Puts a backup back as the installed mod. The install it replaces becomes a new backup first, and the backup itself is kept.

    The backup is copied beside the game's mods folder first, so the swap is two renames on one drive: a folder something holds
    open stops it before anything changes. Returns the name of the backup the replaced install became, or None if nothing was
    installed."""
    _known_mod(where, mod)
    if name not in backups_of(where.backups, mod):
        raise InstallsError(f"{name!r} is not a backup of {mod}.")
    _refuse_while_running(where, running)
    source, target = archives.stored(where.backups, name), where.installed(mod)
    zipped = archives.is_archive(source)
    _need_space(where.target, archives.unpacked_size(source) if zipped else size_of(source), "Going back to the backup")
    if target.is_dir():
        _need_space(where.backups, size_of(target), "Keeping the replaced install as a backup")
    replaced = _free_name(where.backups, mod, now) if target.is_dir() else None
    stamp = _stamp(now)
    staging = where.target.parent / f"{mod}-restoring-{stamp}"
    aside = where.target.parent / f"{mod}-replaced-{stamp}"
    try:
        if zipped:
            archives.unpack(source, staging)
        else:
            shutil.copytree(source, staging)
    except (OSError, archives.ArchiveError) as error:
        if staging.exists():
            remove(staging)
        raise InstallsError(f"The backup could not be copied beside the game's mods ({error}). Nothing was changed.") from None
    if target.is_dir():
        try:
            target.rename(aside)
        except OSError as error:
            remove(staging)
            raise InstallsError(f"{target} cannot be moved ({error.strerror}): something holds it open. Close any File Explorer "
                                "window, terminal, editor or mod manager showing it, then try again. Nothing was changed.") from None
    try:
        staging.rename(target)
    except OSError as error:
        if aside.exists():
            aside.rename(target)
        remove(staging)
        raise InstallsError(f"The backup could not be put in place ({error}). The install was left as it was.") from None
    if replaced:
        where.backups.mkdir(parents=True, exist_ok=True)
        shutil.move(str(aside), str(where.backups / replaced))
    restored = read_copy("installed", target, where.game)
    replaced_copy = read_backup(where, replaced) if replaced else None
    note(where, "went-back", mod=mod, product=restored.name or mod, version=restored.version, backup=name,
         fromVersion=replaced_copy.version if replaced_copy else None, keptAs=replaced)
    return replaced


def install_command(where, mods):
    """The repository's install command for one or more mods: an element that is exactly {mod} becomes every mod named."""
    command = where.config.get("install")
    if not command:
        raise InstallsError("This repository's installs.json names no install command.")
    mods = [mods] if isinstance(mods, str) else list(mods)
    expanded = []
    for part in command:
        if part == "{python}":
            expanded.append(sys.executable)
        elif part == "{mod}":
            expanded.extend(mods)
        else:
            expanded.append(part.replace("{mod}", mods[0]))
    return expanded


def _run_command(where, command, what, run=None, progress=None):
    """Runs one of the repository's own commands. With a stand-in run (tests) it is run whole; otherwise its output is read as it
    comes, so its progress lines are passed on and its ordinary lines become details."""
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "PYTHONUNBUFFERED": "1"}
    try:
        if run is not None:
            result = run(command, cwd=str(where.root), capture_output=True, text=True, check=False, timeout=INSTALL_TIMEOUT, env=env)
            code, lines = result.returncode, ((result.stdout or "") + (result.stderr or "")).splitlines()
        else:
            code, lines = run_streaming(command, cwd=str(where.root), env=env, timeout=INSTALL_TIMEOUT, progress=progress)
    except subprocess.TimeoutExpired:
        raise InstallsError(f"The {what} was still running after {INSTALL_TIMEOUT // 60} minutes and was stopped. Check the mods' "
                            "installed folders and their backups before playing.") from None
    except OSError as error:
        raise InstallsError(f"The {what} could not start ({error}). Nothing was changed.") from None
    return code, lines[-OUTPUT_LINES:]


def install(where, mods, run=None, running=game_running, progress=None):
    """Runs the repository's own install command for one or more mods (it builds, backs up what it replaces, and copies).

    Returns (exit code, the last lines of its output)."""
    mods = [mods] if isinstance(mods, str) else list(mods)
    if not mods:
        raise InstallsError("Name at least one mod to install.")
    for mod in mods:
        _known_mod(where, mod)
    _refuse_while_running(where, running)
    return _run_command(where, install_command(where, mods), "install", run, progress)


def build(where, run=None, progress=None):
    """Runs the repository's own build command. It writes only inside the repository, so it may run while the game does.

    Returns (exit code, the last lines of its output)."""
    command = (where.config.get("build") or {}).get("command")
    if not command:
        raise InstallsError("This repository's installs.json names no build command.")
    code, lines = _run_command(where, [sys.executable if part == "{python}" else part for part in command], "build", run, progress)
    note(where, "built", ok=code == 0, exitCode=code)
    return code, lines
