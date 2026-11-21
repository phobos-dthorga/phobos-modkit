"""safe-copies: copies of what cannot be made again, kept apart by kind, so nothing made from a game's files reaches a shared place
(1.66.0).

    safe-copies plan    [--root REPO] [--set NAME]            what a run would copy, where each kind may go, and what is refused
    safe-copies run     [--root REPO] [--set NAME] [--no-push]
                                                              copies what changed; commits and pushes the repository's copy
    safe-copies status  [--root REPO]                         each set's copies, what changed since, and anything never copied
    safe-copies verify  [--root REPO]                         hashes every copy again against its record
    safe-copies restore --set NAME [--unit NAME] --to FOLDER [--from local|repository] [--overwrite] [--overwrite-newer]
    safe-copies mark    --to FOLDER (--local | --private-local | --repository)
    safe-copies let-go  [--root REPO] (--file COPY ... | --all) [--apply]
                                                              removes copies the list no longer takes; a preview without --apply

The owner asked for it on 21 Nov 2026 ("backup functionality for our training sets, models, etc."), after the first style model of
our own art took 158 minutes of the graphics card to train. A repository lists what to copy in config/safe-copies.json: sets of
files under a folder its settings name, each of a kind:

- own: ours alone. It may go to every destination.
- game-derived: made from a game's or another author's files. Only a destination marked private and local takes it, and never one
  that looks synced or shared. A git repository never takes it.
- personal (1.67.0): the owner's own, but private: notes about them, a game's settings. The same rule as game-derived: a folder
  marked private and local only, never a repository.
- proven: own only when a manifest's hashes prove every picture in it is ours; anything unproven is game-derived. A set of loose
  files (installed models) can follow the kind of the training each was made from (unitOf).

Two destinations, both the owner's choice: safeCopiesPath, a plain folder (the owner chose K:, a separate disk in the PC, 21 Nov
2026), and safeCopiesRepositoryPath, a clone of a private git repository (dthorga-safe-copies), committed and pushed after each run.
Each is marked once with `mark`, on the owner's word. Copies go to <game>/<set>/[<unit>/]<path> in each, as plain files anyone can
open; each destination's _safe-copies folder holds the record of every file (state.json) and of every run (runs/).

Nothing at a source is ever deleted, and no copy in use. A changed file's earlier copy moves to _safe-copies/earlier/<time>/ in the
plain folder; git keeps the repository's. A file gone from its source keeps its copy, marked gone. The one thing that goes (1.68.0,
the owner's word of 22 Nov 2026): a set that names keepEarlier, such as the saves, keeps that many earlier copies of each file in
the plain folder, and the oldest beyond them are let go, each named in the run's record.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import fnmatch
from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

from . import __version__, file_lock, history, kit_settings
from .files import is_link
from .manifest import READS, WRITES
from .paths import resolve
from .progress import Progress, silent
from .report import Bullets, Report, Table, envelope_text, home_redactor, keep, render_markdown

EXIT_OK, EXIT_PROBLEMS, EXIT_USAGE, EXIT_REFUSED = 0, 1, 2, 3
LOCAL = ("safeCopiesPath", "PHOBOS_SAFE_COPIES")
REPOSITORY = ("safeCopiesRepositoryPath", "PHOBOS_SAFE_COPIES_REPOSITORY")
DESTINATIONS = (("local", LOCAL), ("repository", REPOSITORY))
# Where Claude Code keeps its notes about the owner (1.67.0): CLAUDE_CONFIG_DIR is Claude Code's own way to move it.
CLAUDE_HOME = ("claudeHomePath", "CLAUDE_CONFIG_DIR")
CONFIG = Path("config") / "safe-copies.json"
MARK = ".safe-copies.json"
BOOK = "_safe-copies"
PARTIAL = ".safe-copies-partial"
FORMAT = 1
OWN, GAME_DERIVED, PERSONAL, PROVEN = "own", "game-derived", "personal", "proven"
KINDS = (OWN, GAME_DERIVED, PERSONAL, PROVEN)
# Why each kind that stays private may not go somewhere, in words.
PRIVATE_WHY = {GAME_DERIVED: "made from a game's or another's files", PERSONAL: "personal"}
REPOSITORY_ROOT = "@repository"
# GitHub refuses a file over 100 MB; stay under it.
MAX_REPOSITORY_FILE = 95 * 1024 * 1024
# A folder holding one of these, or any folder above it, is synced or shared: never private and local.
SYNC_MARKERS = (".SynologyWorkingDirectory", ".git", ".dropbox", ".sync", ".stfolder")
SYNC_NAMES = ("synologydrive", "cloudstation drive", "onedrive", "dropbox", "google drive", "googledrive", "icloud drive",
              "iclouddrive", "nextcloud", "owncloud")
NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,80}$")
LOCK_STALE_S = 6 * 3600
CHUNK = 1024 * 1024
SHOWN = 20


class SafeCopiesError(ValueError):
    """A request this command refuses, with the reason in words."""


# ---------------------------------------------------------------- patterns

_COMPILED = {}


def _pattern(glob):
    """A glob as a regular expression: * and ? stay within one folder, ** crosses folders."""
    if glob not in _COMPILED:
        out, i = [], 0
        while i < len(glob):
            if glob.startswith("**/", i):
                out.append("(?:.*/)?")
                i += 3
            elif glob.startswith("**", i):
                out.append(".*")
                i += 2
            elif glob[i] == "*":
                out.append("[^/]*")
                i += 1
            elif glob[i] == "?":
                out.append("[^/]")
                i += 1
            else:
                out.append(re.escape(glob[i]))
                i += 1
        _COMPILED[glob] = re.compile("".join(out) + r"\Z", re.IGNORECASE)
    return _COMPILED[glob]


def matches(relative, patterns):
    """Whether a slash-separated relative path matches one of the globs."""
    return any(_pattern(p).match(relative) for p in patterns)


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _now(now=None):
    return (now or datetime.now(timezone.utc)).astimezone(timezone.utc)


def _iso(now=None):
    return _now(now).isoformat(timespec="seconds")


def _stamp(now=None):
    return _now(now).astimezone().strftime("%Y%m%d-%H%M%S")


# ---------------------------------------------------------------- what to copy

@dataclass
class SetSpec:
    name: str
    root: str
    env: str = ""
    folder: str = ""
    include: list = field(default_factory=lambda: ["**"])
    exclude: list = field(default_factory=list)
    local_only: list = field(default_factory=list)
    kind: object = OWN                # "own", "game-derived", "proven" or {"unitOf": set, "pattern": "...{unit}..."}
    units: bool = False               # each folder directly under the set's folder is a unit of its own
    proof: dict = None
    newest: int = None                # 1.68.0: only the newest N files it takes, by when each was last written (a save rotation)
    keep_earlier: int = None          # 1.68.0: earlier copies kept of each file; older ones go (the owner's word, 22 Nov 2026)


@dataclass
class Config:
    game: str
    sets: list
    provenance: list


def load_config(root):
    """The repository's config/safe-copies.json, checked."""
    path = Path(root) / CONFIG
    if not path.is_file():
        raise SafeCopiesError(f"{CONFIG.as_posix()} is missing in {Path(root).resolve().name}: it lists what to copy")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as error:
        raise SafeCopiesError(f"{CONFIG.as_posix()} could not be read: {error}") from None
    game = data.get("game")
    if not isinstance(game, str) or not NAME.match(game):
        raise SafeCopiesError(f"{CONFIG.as_posix()} must name its game (\"game\": \"rimworld\")")
    sets, seen = [], set()
    for item in data.get("sets", []):
        spec = SetSpec(name=item.get("name", ""), root=item.get("root", ""), env=item.get("env", ""),
                       folder=item.get("folder", ""), include=list(item.get("include", ["**"])),
                       exclude=list(item.get("exclude", [])), local_only=list(item.get("localOnly", [])),
                       kind=item.get("kind", OWN), units=bool(item.get("units", False)), proof=item.get("proof"),
                       newest=item.get("newest"), keep_earlier=item.get("keepEarlier"))
        for field_name, value in (("newest", spec.newest), ("keepEarlier", spec.keep_earlier)):
            if value is not None and (not isinstance(value, int) or isinstance(value, bool) or value < 1 or value > 1000):
                raise SafeCopiesError(f"set {spec.name}: {field_name} must be a whole number from 1 to 1000")
        if not NAME.match(spec.name) or spec.name in seen:
            raise SafeCopiesError(f"a set needs a name of letters, digits, dots and dashes, each used once: {spec.name!r}")
        seen.add(spec.name)
        if not spec.root:
            raise SafeCopiesError(f"set {spec.name} names no root (a settings key, or {REPOSITORY_ROOT})")
        if ".." in Path(spec.folder).parts or Path(spec.folder).is_absolute():
            raise SafeCopiesError(f"set {spec.name}: its folder must be relative to its root, without ..")
        if isinstance(spec.kind, dict):
            if not spec.kind.get("unitOf") or "{unit}" not in str(spec.kind.get("pattern", "")):
                raise SafeCopiesError(f"set {spec.name}: unitOf needs a set and a pattern holding {{unit}}")
        elif spec.kind not in KINDS:
            raise SafeCopiesError(f"set {spec.name}: kind must be one of {', '.join(KINDS)}, or unitOf")
        if spec.kind == PROVEN and not (isinstance(spec.proof, dict) and spec.proof.get("manifest") and spec.proof.get("files")):
            raise SafeCopiesError(f"set {spec.name}: a proven set needs a proof with a manifest and the files it covers")
        sets.append(spec)
    for spec in sets:
        if isinstance(spec.kind, dict):
            followed = next((s for s in sets if s.name == spec.kind["unitOf"]), None)
            if followed is None or followed.kind != PROVEN or not followed.units:
                raise SafeCopiesError(f"set {spec.name} follows {spec.kind['unitOf']}, which is not a proven set of units")
    if not sets:
        raise SafeCopiesError(f"{CONFIG.as_posix()} lists no sets")
    return Config(game, sets, list(data.get("provenance", [])))


@dataclass
class Item:
    game: str
    set: str
    unit: str
    relative: str
    source: Path
    size: int
    mtime_ns: int
    kind: str
    local_only: bool
    keep_earlier: int = None          # 1.68.0: how many earlier copies of this file to keep; None keeps every one

    @property
    def key(self):
        return "/".join(p for p in (self.game, self.set, self.unit, self.relative) if p)


@dataclass
class Unit:
    set: str
    unit: str
    kind: str
    why: str
    files: int = 0
    bytes: int = 0


@dataclass
class Collection:
    game: str
    items: list
    units: list
    notes: list                       # problems in words: a root not set, a folder missing, a link skipped
    walked: set                       # (set, unit) pairs read in full, whose missing files are really gone
    provenance: list
    rotating: dict = field(default_factory=dict)   # 1.69.0: sets that take only their newest N files, by name


def _settings_file(root):
    return kit_settings.repository_settings_file(root) if root else None


def _environment_names(root):
    try:
        return {s.key: s.env for s in kit_settings.registry([root])}
    except kit_settings.SettingsError:
        return {}


def _declared_default(key, root, environ):
    """The default a setting the kit knows gives (1.67.0: RimWorld's Config folder, the notes folder), or None."""
    try:
        setting = next((s for s in kit_settings.registry([root]) if s.key == key), None)
    except kit_settings.SettingsError:
        return None
    if setting is None or setting.default is None:
        return None
    try:
        found = setting.default(os.environ if environ is None else environ)
    except (OSError, RuntimeError, KeyError, ValueError):
        return None
    return Path(found) if found else None


def set_base(spec, root, environ=None):
    """The folder a set reads, or None when its root is not set and has no default."""
    if spec.root == REPOSITORY_ROOT:
        base = Path(root)
    else:
        env = spec.env or _environment_names(root).get(spec.root, "")
        base = resolve(spec.root, env, None, None, environ, _settings_file(root)) or _declared_default(spec.root, root, environ)
        if base is None:
            return None
    return base / spec.folder if spec.folder else base


def could_hold(folder, patterns):
    """Whether a folder (a slash-separated relative path) could hold a file one of the globs takes (1.67.0), so the walk skips
    folders the list never reaches, such as a tool's logs and caches beside the notes it keeps."""
    parts = folder.split("/")
    for pattern in patterns:
        segments = pattern.split("/")
        for depth, part in enumerate(parts):
            if depth < len(segments) and segments[depth].startswith("**"):
                return True                             # ** reaches every folder beneath
            if depth >= len(segments) - 1:
                break                                   # the pattern's last segment names files, not this folder
            if not fnmatch.fnmatch(part.casefold(), segments[depth].casefold()):
                break
        else:
            return True
    return False


def _walk(base, spec, notes, label):
    """(relative path, path, stat) of every file under base the set takes. Links are skipped and noted, never followed; a folder
    the list could never take a file from is not walked at all."""
    found = []
    for current, folders, names in os.walk(base):
        here = Path(current)
        inside = here.relative_to(base).as_posix()
        inside = "" if inside == "." else inside
        kept = []
        for name in sorted(folders):
            relative = f"{inside}/{name}" if inside else name
            if name == BOOK or matches(relative, spec.exclude) or not could_hold(relative, spec.include):
                continue
            if is_link(here / name):
                notes.append(f"{label}: {relative} is a link, not followed")
            else:
                kept.append(name)
        folders[:] = kept
        for name in sorted(names):
            relative = f"{inside}/{name}" if inside else name
            path = here / name
            if name == MARK or name.endswith(PARTIAL):
                continue
            if is_link(path):
                notes.append(f"{label}: {relative} is a link, not followed")
                continue
            if matches(relative, spec.exclude) or not matches(relative, spec.include):
                continue
            found.append((relative, path, path.stat()))
    return found


def prove(files, unit_path, proof):
    """(True, why) when every file the proof covers carries a hash its manifest lists; (False, why) when anything is unproven."""
    marker = proof.get("marker")
    if marker and not (unit_path / marker).is_file():
        return False, f"no {marker}"
    try:
        manifest = json.loads((unit_path / proof["manifest"]).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False, f"no readable {proof['manifest']}"
    entries = manifest if isinstance(manifest, list) else manifest.get("files") if isinstance(manifest, dict) else None
    key = proof.get("hashKey", "sha256")
    hashes = {e.get(key) for e in entries or [] if isinstance(e, dict) and isinstance(e.get(key), str)}
    covered = [(relative, path) for relative, path, _ in files if matches(relative, proof["files"])]
    if not covered:
        return False, "nothing its proof covers"
    unproven = [relative for relative, path in covered if sha256_file(path) not in hashes]
    if unproven:
        return False, f"{len(unproven)} of {len(covered)} pictures not in {proof['manifest']} (first: {unproven[0]})"
    return True, f"all {len(covered)} pictures in {proof['manifest']} by hash"


def collect(root, environ=None, only=None):
    """Every file the repository's sets take, with its kind. `only` limits the items to those sets; proofs are still read for
    the sets others follow."""
    config = load_config(root)
    items, units, notes, walked, kinds, rotating = [], [], [], set(), {}, {}
    ordered = sorted(config.sets, key=lambda s: isinstance(s.kind, dict))
    for spec in ordered:
        wanted = not only or spec.name in only
        base = set_base(spec, root, environ)
        if base is None:
            notes.append(f"{spec.name}: its root {spec.root} is not set")
            continue
        if not base.is_dir():
            notes.append(f"{spec.name}: {base} is not there")
            continue
        if is_link(base):
            notes.append(f"{spec.name}: {base} is a link, not followed")
            continue
        if spec.units:
            parts = [(child.name, child) for child in sorted(base.iterdir(), key=lambda p: p.name.lower())
                     if child.is_dir() and not is_link(child) and child.name != BOOK and NAME.match(child.name)]
        else:
            parts = [(None, base)]
        for unit, folder in parts:
            files = _walk(folder, spec, notes, f"{spec.name}/{unit}" if unit else spec.name)
            if spec.kind == PROVEN:
                if not wanted and not spec.units:
                    continue
                proven, why = prove(files, folder, spec.proof)
                kind = OWN if proven else GAME_DERIVED
                if unit:
                    kinds[(spec.name, unit)] = (kind, why)
            elif isinstance(spec.kind, dict):
                kind, why = None, None
            else:
                kind, why = spec.kind, "named so in the list"
            if not wanted:
                continue
            if spec.newest:
                # Only the newest few, by when each was last written. A file that falls out of them still exists at its source,
                # so this set never says a file is gone: its copies simply stay.
                files = sorted(files, key=lambda found: (found[2].st_mtime_ns, found[0]), reverse=True)[:spec.newest]
                files = sorted(files, key=lambda found: found[0])
                rotating[spec.name] = spec.newest
                if why:
                    why = f"{why}; the newest {spec.newest}"
            else:
                walked.add((spec.name, unit))
            follows = isinstance(spec.kind, dict)
            shown = {}
            for relative, path, info in files:
                file_kind, file_why = _follow(spec, relative, kinds) if follows else (kind, why)
                items.append(Item(config.game, spec.name, unit, relative, path, info.st_size, info.st_mtime_ns, file_kind,
                                  matches(relative, spec.local_only), spec.keep_earlier))
                # A unit of a set of units; each file of a set that follows trainings; else the set as one.
                label = relative if follows else unit
                group = shown.setdefault(label, Unit(spec.name, label, file_kind, file_why))
                group.files += 1
                group.bytes += info.st_size
            if not files:
                units.append(Unit(spec.name, unit, kind or GAME_DERIVED, "nothing to copy"))
            units.extend(shown.values())
    return Collection(config.game, items, units, notes, walked, config.provenance, rotating)


def _follow(spec, relative, kinds):
    """The kind of a loose file that follows the training it was made from; game-derived when no proven training matches."""
    pattern = re.escape(spec.kind["pattern"]).replace(re.escape("{unit}"), "(?P<unit>[^/]+)")
    found = re.fullmatch(pattern, relative, re.IGNORECASE)
    if not found:
        return GAME_DERIVED, f"matches no {spec.kind['unitOf']} name"
    unit = found.group("unit")
    kind, why = kinds.get((spec.kind["unitOf"], unit), (None, None))
    if kind is None:
        return GAME_DERIVED, f"no {spec.kind['unitOf']} unit named {unit}"
    return kind, f"follows {spec.kind['unitOf']}/{unit}: {why}"


# ---------------------------------------------------------------- where copies go

@dataclass
class Destination:
    name: str
    path: Path = None
    mark: dict = None
    shared: list = field(default_factory=list)
    problem: str = None

    @property
    def private_local(self):
        return bool(self.mark and self.mark.get("privateLocal")) and not self.shared


def shared_signs(path):
    """Why a folder may be synced or shared, in words: a sync tool's or git's folder in it or above it, or a synced folder's name."""
    path = Path(os.path.abspath(path))
    reasons = []
    for folder in (path, *path.parents):
        for marker in SYNC_MARKERS:
            if (folder / marker).exists():
                reasons.append(f"{folder / marker} is there")
        name = folder.name.casefold()
        if name in SYNC_NAMES or name.startswith("onedrive - "):
            reasons.append(f"{folder} is named as a synced folder")
    return reasons


def read_mark(path):
    try:
        data = json.loads((Path(path) / MARK).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def destinations(environ=None, settings_file=None):
    """Both destinations, each with its problem in words when it cannot take copies."""
    found = []
    for name, setting in DESTINATIONS:
        destination = Destination(name)
        destination.path = resolve(*setting, None, None, environ, settings_file)
        if destination.path is None:
            destination.problem = f"not chosen yet ({setting[0]})"
        elif not destination.path.is_absolute():
            destination.problem = "must be a full path"
        elif not destination.path.is_dir():
            destination.problem = "cannot be reached (a drive not connected?)"
        else:
            destination.mark = read_mark(destination.path)
            expected = "repository" if name == "repository" else "local"
            if not destination.mark or destination.mark.get("kind") != expected:
                destination.problem = f"not marked as a {expected} destination: safe-copies mark --to FOLDER --" + (
                    "repository" if name == "repository" else "local or --private-local")
            elif name == "repository" and not (destination.path / ".git").exists():
                destination.problem = "is not a git clone's top folder"
            if name == "local":
                destination.shared = shared_signs(destination.path)
        found.append(destination)
    return found


def refusal(destination, item):
    """Why a destination will not take an item, or None when it will."""
    why = PRIVATE_WHY.get(item.kind, item.kind)
    if destination.name == "repository":
        if item.kind != OWN:
            return f"{why}: never in a repository"
        if item.local_only:
            return "kept in the local copy only (checkpoints and resume files)"
        if item.size > MAX_REPOSITORY_FILE:
            return "over 95 MB, too big for GitHub"
        return None
    if item.kind != OWN and not destination.private_local:
        return (f"{why}: only a folder marked private and local takes it"
                + (f" ({destination.shared[0]})" if destination.shared else ""))
    return None


def read_state(path):
    """{key: record} of every file a destination holds."""
    try:
        data = json.loads((Path(path) / BOOK / "state.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    files = data.get("files") if isinstance(data, dict) else None
    return files if isinstance(files, dict) else {}


def _write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_name(path.name + PARTIAL)
    partial.write_text(json.dumps(data, indent=1, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    os.replace(partial, path)


@contextmanager
def _locked(path):
    """Holds a destination's lock while a run changes it; a lock left by a run that stopped is broken after six hours."""
    try:
        with file_lock.held(Path(path) / BOOK / "lock", 0, LOCK_STALE_S):
            yield
    except file_lock.LockBusy:
        raise SafeCopiesError(f"another run is copying to {path}; try again when it ends") from None


def _copy(source, target, digest, mtime_ns=None):
    """Copies a file through a partial file beside the target, checking it read the bytes it hashed."""
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_name(target.name + PARTIAL)
    hashed = hashlib.sha256()
    try:
        with open(source, "rb") as reading, open(partial, "wb") as writing:
            for chunk in iter(lambda: reading.read(CHUNK), b""):
                hashed.update(chunk)
                writing.write(chunk)
            writing.flush()
            os.fsync(writing.fileno())
        if hashed.hexdigest() != digest:
            raise SafeCopiesError(f"{Path(source).name} changed while it was copied, or its copy is damaged")
        if mtime_ns is not None:
            os.utime(partial, ns=(mtime_ns, mtime_ns))
        os.replace(partial, target)
    finally:
        if partial.exists():
            partial.unlink()


# ---------------------------------------------------------------- git, for the repository destination

def _git(folder, *arguments, runner=None):
    runner = runner or subprocess.run
    return runner(["git", "-c", "core.fsmonitor=false", "-C", str(folder), *arguments], capture_output=True, text=True,
                  encoding="utf-8", errors="replace")


def head_of(folder, runner=None):
    """A folder's git commit, or None when it is not a git clone."""
    if folder is None or not Path(folder).is_dir():
        return None
    found = _git(folder, "rev-parse", "HEAD", runner=runner)
    return found.stdout.strip() if found.returncode == 0 else None


def commit_and_push(folder, message, push=True, runner=None):
    """Commits everything in the repository's copy and pushes whatever is not on its remote yet. Never raises for git's answer."""
    result = {"committed": False, "pushed": None, "error": None}
    done = _git(folder, "add", "-A", "--", ".", f":(exclude){BOOK}/lock", f":(exclude)*{PARTIAL}", runner=runner)
    if done.returncode:
        result["error"] = done.stderr.strip() or "git add failed"
        return result
    if _git(folder, "diff", "--cached", "--quiet", runner=runner).returncode:
        done = _git(folder, "commit", "-q", "-m", message, runner=runner)
        if done.returncode:
            result["error"] = done.stderr.strip() or done.stdout.strip() or "git commit failed"
            return result
        result["committed"] = True
    if not push:
        return result
    ahead = _git(folder, "rev-list", "--count", "@{u}..HEAD", runner=runner)
    if ahead.returncode == 0 and ahead.stdout.strip() == "0":
        result["pushed"] = False
        return result
    pushing = _git(folder, *(("push", "-q") if ahead.returncode == 0 else ("push", "-q", "-u", "origin", "HEAD")), runner=runner)
    result["pushed"] = pushing.returncode == 0
    if pushing.returncode:
        result["error"] = pushing.stderr.strip() or "git push failed"
    return result


def provenance(root, entries, environ=None, runner=None):
    """What rebuilds the copies: this repository's commit, and the commit or hash of each tool or file the list names."""
    found = {Path(root).resolve().name: head_of(root, runner)}
    for entry in entries:
        name = entry.get("name")
        if not name:
            continue
        if entry.get("file"):
            path = Path(root) / entry["file"]
            found[name] = sha256_file(path) if path.is_file() else None
        elif entry.get("root"):
            env = entry.get("env") or _environment_names(root).get(entry["root"], "")
            found[name] = head_of(resolve(entry["root"], env, None, None, environ, _settings_file(root)), runner)
    return found


# ---------------------------------------------------------------- plan, run, status, verify, restore, mark

def _same(record, item, target):
    return (bool(record) and record.get("size") == item.size and record.get("mtime_ns") == item.mtime_ns
            and target.is_file() and target.stat().st_size == item.size)


def plan(root, environ=None, only=None):
    """What a run would copy to each destination, what it would leave as it is, and what each refuses and why."""
    collection = collect(root, environ, only)
    found = []
    for destination in destinations(environ, _settings_file(root)):
        entry = {"destination": destination, "copy": [], "same": 0, "refused": {}}
        if not destination.problem:
            state = read_state(destination.path)
            for item in collection.items:
                why = refusal(destination, item)
                if why:
                    entry["refused"].setdefault(why, []).append(item)
                elif _same(state.get(item.key), item, destination.path / item.key):
                    entry["same"] += 1
                else:
                    entry["copy"].append(item)
        found.append(entry)
    return collection, found


def run(root, environ=None, only=None, push=True, now=None, progress=None, runner=None):
    """Copies what changed to every destination that is ready, and commits and pushes the repository's copy. Returns one result
    per destination; refuses when none is ready."""
    progress = progress or silent()
    collection = collect(root, environ, only)
    ready = [d for d in destinations(environ, _settings_file(root)) if not d.problem]
    if not ready:
        raise SafeCopiesError("no destination is ready: " + "; ".join(f"{d.name} {d.problem}"
                                                                     for d in destinations(environ, _settings_file(root))))
    stamp, when = _stamp(now), _iso(now)
    made = provenance(root, collection.provenance, environ, runner)
    results = []
    for destination in ready:
        with _locked(destination.path):
            results.append(_run_one(destination, collection, stamp, when, made, push, progress, runner, root))
    copied = sum(len(r["copied"]) for r in results)
    if copied:
        history.record(collection.game, "safe-copies", environ, _settings_file(root), now,
                       files=copied, bytes=sum(c["bytes"] for r in results for c in r["copied"]),
                       destinations=[r["destination"] for r in results if r["copied"]])
    return collection, results


def prune_earlier(folder, key, keep):
    """Lets go of a file's oldest earlier copies in a destination, keeping the newest `keep` (1.68.0; the owner's word of 22 Nov
    2026, for a set that names keepEarlier, such as saves). Deletes only inside the destination's own earlier folder, never a copy
    in use and never anything at a source. Returns what it let go, as paths under that folder."""
    earlier_root = Path(folder) / BOOK / "earlier"
    if not earlier_root.is_dir():
        return []
    found = []
    for moment in earlier_root.iterdir():
        candidate = moment / key
        if moment.is_dir() and not is_link(moment) and candidate.is_file() and not is_link(candidate):
            found.append((moment.name, candidate))
    found.sort()
    gone = []
    for moment, candidate in found[:max(0, len(found) - keep)]:
        if not candidate.resolve().is_relative_to(earlier_root.resolve()):
            continue
        candidate.unlink()
        gone.append(f"{moment}/{key}")
        # Folders the copy leaves empty go too, up to the moment's own folder.
        parent = candidate.parent
        while parent != earlier_root and parent.is_dir() and not any(parent.iterdir()):
            parent.rmdir()
            parent = parent.parent
    return gone


def _run_one(destination, collection, stamp, when, made, push, progress, runner, root):
    state = read_state(destination.path)
    copied, same, refused, failed, warnings, let_go = [], 0, {}, [], [], []
    total = len(collection.items)
    for number, item in enumerate(collection.items, 1):
        progress(f"Copying to {destination.name}", number, total, item.key)
        why = refusal(destination, item)
        if why:
            refused.setdefault(why, []).append(item.key)
            if destination.name == "repository" and item.key in state:
                warnings.append(f"{item.key} is refused now ({why}) but an earlier run put it in the repository: look at it")
            continue
        record, target = state.get(item.key), destination.path / item.key
        if _same(record, item, target):
            same += 1
            continue
        try:
            digest = sha256_file(item.source)
            if target.is_file() and ((record or {}).get("sha256") == digest or sha256_file(target) == digest):
                state[item.key] = _record(item, digest, (record or {}).get("copied", when))
                same += 1
                continue
            if target.exists() and destination.name == "local":
                earlier = destination.path / BOOK / "earlier" / stamp / item.key
                earlier.parent.mkdir(parents=True, exist_ok=True)
                os.replace(target, earlier)
            _copy(item.source, target, digest, item.mtime_ns)
            state[item.key] = _record(item, digest, when)
            copied.append({"path": item.key, "bytes": item.size, "sha256": digest, "kind": item.kind})
            if item.keep_earlier and destination.name == "local":
                let_go.extend(prune_earlier(destination.path, item.key, item.keep_earlier))
        except (OSError, SafeCopiesError) as error:
            failed.append({"path": item.key, "error": str(error)})
    present = {i.key for i in collection.items}
    gone = 0
    for key, record in state.items():
        parts = key.split("/")
        if len(parts) < 3 or parts[0] != collection.game or key in present or record.get("gone"):
            continue
        # Only a set or unit read in full this run can say a file is gone; one whose folder was missing says nothing.
        if (parts[1], parts[2]) in collection.walked or (parts[1], None) in collection.walked:
            record["gone"] = when
            gone += 1
    _write_json(destination.path / BOOK / "state.json", {"format": FORMAT, "files": state})
    result = {"destination": destination.name, "folder": str(destination.path), "time": when, "kit": __version__,
              "from": Path(root).resolve().name, "game": collection.game, "copied": copied, "same": same,
              "refused": {why: {"files": len(keys), "first": keys[:SHOWN]} for why, keys in refused.items()},
              "failed": failed, "gone": gone, "warnings": warnings, "letGo": let_go, "provenance": made, "git": None}
    record_path = destination.path / BOOK / "runs" / f"{stamp}-{collection.game}.json"
    # The repository keeps a run's record only when the run changed something, so a quiet night makes no commit.
    if destination.name != "repository" or copied or gone or failed or let_go:
        _write_json(record_path, result)
        result["record"] = str(record_path)
    if destination.name == "repository":
        result["git"] = commit_and_push(destination.path, f"Safe copies {stamp} from {result['from']}: {len(copied)} files",
                                        push, runner)
        if result["git"].get("error"):
            failed.append({"path": "(git)", "error": result["git"]["error"]})
    return result


def _record(item, digest, copied):
    return {"size": item.size, "mtime_ns": item.mtime_ns, "sha256": digest, "kind": item.kind, "set": item.set,
            "unit": item.unit, "copied": copied}


def last_run(path):
    """The newest run record's file name and time in a destination, or None."""
    runs = sorted((Path(path) / BOOK / "runs").glob("*.json")) if path else []
    if not runs:
        return None
    try:
        return {"name": runs[-1].name, "time": json.loads(runs[-1].read_text(encoding="utf-8")).get("time")}
    except (OSError, ValueError):
        return {"name": runs[-1].name, "time": None}


def unsent(folder, runner=None):
    """How many commits the repository's copy holds that its remote has not had yet (1.69.0): a push that failed stays counted until
    a later run sends it. None when git cannot say."""
    ahead = _git(folder, "rev-list", "--count", "@{u}..HEAD", runner=runner)
    if ahead.returncode != 0:
        ahead = _git(folder, "rev-list", "--count", "HEAD", runner=runner)   # no remote branch yet: every commit is unsent
    try:
        return int(ahead.stdout.strip()) if ahead.returncode == 0 else None
    except ValueError:
        return None


def _earlier_of(folder, key):
    """A copy's earlier copies in a destination's earlier folder, oldest first."""
    earlier_root = Path(folder) / BOOK / "earlier"
    if not earlier_root.is_dir():
        return []
    found = [moment / key for moment in sorted(earlier_root.iterdir()) if moment.is_dir() and not is_link(moment)]
    return [path for path in found if path.is_file() and not is_link(path)]


def kept_only(collection, destination):
    """Copies a plain-folder destination keeps of files the list no longer takes (1.69.0): a file gone from its source, or a save
    that left a rotation's newest few. Each with its size and its earlier copies'; only what the run can account for."""
    if destination.problem or destination.name != "local":
        return []
    present = {item.key for item in collection.items}
    found = []
    for key, record in sorted(read_state(destination.path).items()):
        parts = key.split("/")
        if len(parts) < 3 or parts[0] != collection.game or key in present:
            continue
        if record.get("gone"):
            why = "gone from its source"
        elif parts[1] in collection.rotating:
            why = f"no longer among the newest {collection.rotating[parts[1]]}"
        else:
            continue
        earlier = _earlier_of(destination.path, key)
        found.append({"key": key, "set": parts[1], "why": why, "bytes": int(record.get("size") or 0),
                      "earlier": len(earlier), "earlierBytes": sum(p.stat().st_size for p in earlier)})
    return found


def let_go(root, keys, environ=None, apply=False, now=None):
    """Lets go of copies the list no longer takes, by name, from the plain-folder destination (1.69.0; on the owner's word for each
    run): the copy, its earlier copies and its record. Only a name kept_only lists may go; nothing at a source, never a copy in use.
    Without apply it only says what would go."""
    collection = collect(root, environ)
    destination = next(d for d in destinations(environ, _settings_file(root)) if d.name == "local")
    if destination.problem:
        raise SafeCopiesError(f"the local copy {destination.problem}")
    listed = {entry["key"]: entry for entry in kept_only(collection, destination)}
    unknown = [key for key in keys if key not in listed]
    if unknown:
        raise SafeCopiesError(f"{unknown[0]} is not a copy the list no longer takes; safe-copies status lists those")
    chosen = [listed[key] for key in keys]
    if not apply:
        return {"applied": False, "chosen": chosen,
                "bytes": sum(entry["bytes"] + entry["earlierBytes"] for entry in chosen)}
    with _locked(destination.path):
        state = read_state(destination.path)
        gone = []
        for entry in chosen:
            for path in [destination.path / entry["key"], *_earlier_of(destination.path, entry["key"])]:
                if path.is_file() and path.resolve().is_relative_to(Path(destination.path).resolve()):
                    path.unlink()
                    gone.append(str(path.relative_to(destination.path)).replace("\\", "/"))
            state.pop(entry["key"], None)
        _write_json(destination.path / BOOK / "state.json", {"format": FORMAT, "files": state})
        _write_json(destination.path / BOOK / "runs" / f"{_stamp(now)}-{collection.game}-let-go.json",
                    {"time": _iso(now), "kit": __version__, "game": collection.game, "letGo": gone, "chosen": chosen})
    return {"applied": True, "chosen": chosen, "letGo": gone,
            "bytes": sum(entry["bytes"] + entry["earlierBytes"] for entry in chosen)}


def status(root, environ=None):
    """Each set and unit with its kind, and for each destination whether it is copied, refused, changed since, or never copied."""
    collection = collect(root, environ)
    dests = destinations(environ, _settings_file(root))
    states = {d.name: read_state(d.path) if not d.problem else {} for d in dests}
    rows = []
    for unit in collection.units:
        members = [i for i in collection.items if i.set == unit.set and unit.unit in (i.unit, i.relative)]
        row = {"set": unit.set, "unit": unit.unit, "kind": unit.kind, "why": unit.why, "files": unit.files, "bytes": unit.bytes,
               "destinations": {}}
        for d in dests:
            if d.problem:
                row["destinations"][d.name] = {"state": "not ready", "problem": d.problem}
                continue
            taken = [i for i in members if not refusal(d, i)]
            if members and not taken:
                row["destinations"][d.name] = {"state": "refused", "why": refusal(d, members[0])}
                continue
            state = states[d.name]
            copied = [state[i.key] for i in taken if i.key in state]
            changed = [i.key for i in taken if not _same(state.get(i.key), i, d.path / i.key)]
            last = max((c.get("copied", "") for c in copied), default=None)
            row["destinations"][d.name] = {"state": "never copied" if taken and not copied else "changed since" if changed
                                           else "copied", "lastCopied": last, "changed": len(changed), "files": len(taken)}
        row["neverCopied"] = bool(members) and all(v.get("state") in ("never copied", "not ready", "refused")
                                                   for v in row["destinations"].values()) and any(
            v.get("state") == "never copied" for v in row["destinations"].values())
        rows.append(row)
    return collection, dests, rows


def verify(environ=None, settings_file=None, progress=None):
    """Hashes every copy again against its record; returns (checked, problems) for each ready destination."""
    progress = progress or silent()
    found = []
    for d in destinations(environ, settings_file):
        if d.problem:
            continue
        state = read_state(d.path)
        problems = []
        for number, (key, record) in enumerate(sorted(state.items()), 1):
            progress(f"Checking {d.name}", number, len(state), key)
            target = d.path / key
            if not target.is_file():
                problems.append({"path": key, "problem": "missing"})
            elif target.stat().st_size != record.get("size"):
                problems.append({"path": key, "problem": "wrong size"})
            elif sha256_file(target) != record.get("sha256"):
                problems.append({"path": key, "problem": "damaged: its hash differs"})
        found.append({"destination": d.name, "folder": str(d.path), "checked": len(state), "problems": problems})
    return found


def restore(game, set_name, to, unit=None, source="local", overwrite=False, overwrite_newer=False, environ=None,
            settings_file=None):
    """Copies a set (or one unit) back out of a destination into a folder the owner names. Refuses to write over a different
    file there unless overwrite, and over one newer than the copy unless overwrite_newer too."""
    destination = next(d for d in destinations(environ, settings_file) if d.name == source)
    if destination.problem:
        raise SafeCopiesError(f"the {source} copy {destination.problem}")
    to = Path(to)
    if not to.is_absolute():
        raise SafeCopiesError("restore needs a full path to copy into")
    if os.path.abspath(to).startswith(os.path.abspath(destination.path)):
        raise SafeCopiesError("restore cannot write inside the copies themselves")
    prefix = "/".join(p for p in (game, set_name, unit) if p) + "/"
    state = read_state(destination.path)
    # 1.70.1: a unit may also name one file of a set, as status names an installed model; that file comes back on its own.
    chosen = {k: r for k, r in state.items() if k.startswith(prefix) or (unit and k == prefix[:-1])}
    if not chosen:
        raise SafeCopiesError(f"nothing is copied under {prefix} in the {source} copy")
    work, conflicts, same = [], [], 0
    for key, record in sorted(chosen.items()):
        target = to / (key[len(prefix):] if key.startswith(prefix) else key.rsplit("/", 1)[-1])
        if target.exists():
            if target.is_file() and sha256_file(target) == record.get("sha256"):
                same += 1
                continue
            newer = target.stat().st_mtime_ns > int(record.get("mtime_ns") or 0)
            conflicts.append({"path": str(target), "newer": newer})
            if not overwrite or (newer and not overwrite_newer):
                continue
        work.append((destination.path / key, target, record))
    blocked = [c for c in conflicts if not overwrite or (c["newer"] and not overwrite_newer)]
    if blocked:
        raise SafeCopiesError(f"{len(blocked)} files there differ from the copy ({blocked[0]['path']} first"
                              + (", newer than the copy" if blocked[0]["newer"] else "") + "): nothing was written. "
                              "--overwrite replaces older ones; --overwrite-newer newer ones too")
    for copy, target, record in work:
        _copy(copy, target, record["sha256"], record.get("mtime_ns"))
    return {"from": source, "to": str(to), "restored": len(work), "same": same, "replaced": len(conflicts)}


def mark(to, kind, now=None):
    """Marks a folder as a destination: "local" (own files only), "private-local" (game-derived files too) or "repository"."""
    to = Path(to)
    if not to.is_absolute():
        raise SafeCopiesError("mark needs a full path")
    if kind == "repository":
        if not (to / ".git").exists():
            raise SafeCopiesError(f"{to} is not a git clone's top folder: clone the private repository there first")
        data = {"format": FORMAT, "kind": "repository", "marked": _iso(now)}
    else:
        signs = shared_signs(to)
        if kind == "private-local" and signs:
            raise SafeCopiesError(f"{to} looks synced or shared ({signs[0]}): choose a folder on a local, unsynced disk")
        to.mkdir(parents=True, exist_ok=True)
        data = {"format": FORMAT, "kind": "local", "privateLocal": kind == "private-local", "marked": _iso(now)}
    _write_json(to / MARK, data)
    return data


# ---------------------------------------------------------------- the command

def _parser():
    p = argparse.ArgumentParser(prog="safe-copies", description=__doc__.split("\n\n")[0],
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="report", required=True)
    commands = {
        "plan": sub.add_parser("plan", help="what a run would copy, where each kind may go, and what is refused"),
        "run": sub.add_parser("run", help="copies what changed, then commits and pushes the repository's copy"),
        "status": sub.add_parser("status", help="each set's copies, what changed since, and anything never copied"),
        "verify": sub.add_parser("verify", help="hashes every copy again against its record"),
        "restore": sub.add_parser("restore", help="copies a set back out into a folder you name"),
        "mark": sub.add_parser("mark", help="marks a folder as a destination, on the owner's word"),
        "let-go": sub.add_parser("let-go", help="removes copies the list no longer takes, on request; a preview without --apply"),
    }
    for name in ("plan", "run", "status", "verify", "restore", "let-go"):
        commands[name].add_argument("--root", default=".", help="the repository whose config/safe-copies.json to read")
    for name in ("plan", "run"):
        commands[name].add_argument("--set", action="append", default=[], help="only this set (repeatable)")
    commands["run"].add_argument("--no-push", action="store_true", help="commit the repository's copy but do not push it")
    restore_parser = commands["restore"]
    restore_parser.add_argument("--set", required=True, help="the set to restore")
    restore_parser.add_argument("--unit", help="one unit of the set (a training)")
    restore_parser.add_argument("--game", help="the game the set belongs to (default: the repository's)")
    restore_parser.add_argument("--to", required=True, help="the folder to copy into (a new or empty one is safest)")
    restore_parser.add_argument("--from", dest="source", choices=("local", "repository"), default="local",
                                help="which copy to restore from")
    restore_parser.add_argument("--overwrite", action="store_true", help="replace files there that are older than the copy")
    restore_parser.add_argument("--overwrite-newer", action="store_true", help="with --overwrite, replace newer files too")
    let_go_parser = commands["let-go"]
    let_go_parser.add_argument("--file", action="append", default=[],
                               help="a copy as status lists it, such as rimworld/saves/PG15.rws (repeatable)")
    let_go_parser.add_argument("--all", action="store_true", help="every copy status lists as no longer taken")
    let_go_parser.add_argument("--apply", action="store_true", help="remove them; without it, only say what would go")
    mark_parser = commands["mark"]
    mark_parser.add_argument("--to", required=True, help="the folder to mark")
    which = mark_parser.add_mutually_exclusive_group(required=True)
    which.add_argument("--local", action="store_true", help="a plain folder for our own files only")
    which.add_argument("--private-local", action="store_true", help="a plain folder on a local, unsynced disk: game-derived too")
    which.add_argument("--repository", action="store_true", help="a clone of a private git repository: our own files only")
    for parser in commands.values():
        parser.add_argument("--json", action="store_true", help="print JSON instead of Markdown")
        parser.add_argument("--no-redact", action="store_true", help="show the home folder instead of ~")
    return p


def _size(size):
    if size < 1024 * 1024:
        return f"{size / 1024:,.1f} KB"
    if size < 1024 ** 3:
        return f"{size / (1024 * 1024):,.1f} MB"
    return f"{size / 1024 ** 3:,.2f} GB"


def _local_time(text):
    try:
        return datetime.fromisoformat(text).astimezone().strftime("%d %b %H:%M")
    except (TypeError, ValueError):
        return text or ""


def _destination_rows(dests):
    rows = []
    for d in dests:
        takes = ("own files" if d.name == "repository" else
                 "own, game-derived and personal files" if d.private_local else "own files only")
        rows.append([d.name, str(d.path or ""), takes if not d.problem else "", d.problem or "ready"])
    return Table(["Destination", "Folder", "Takes", "Ready"], rows)


def _unit_label(unit):
    return f"{unit.set}/{unit.unit}" if unit.unit else unit.set


def _plan_report(collection, entries):
    copying = sum(len(e["copy"]) for e in entries)
    report = Report(f"Safe copies: {copying} files to copy" if copying else "Safe copies: nothing to copy")
    report.section("Destinations", _destination_rows([e["destination"] for e in entries]))
    report.section("What the list takes", Table(["Set", "Kind", "Why", "Files", "Size"],
                                                [[_unit_label(u), u.kind, u.why, u.files, _size(u.bytes)]
                                                 for u in collection.units]))
    rows = []
    for e in entries:
        if not e["destination"].problem:
            rows.append([e["destination"].name, len(e["copy"]), _size(sum(i.size for i in e["copy"])), e["same"],
                         sum(len(v) for v in e["refused"].values())])
    if rows:
        report.section("A run would", Table(["Destination", "Copy", "Size", "Leave as it is", "Refuse"], rows))
    refused = [[e["destination"].name, why, len(items)] for e in entries for why, items in sorted(e["refused"].items())]
    if refused:
        report.section("Refused, and why", Table(["Destination", "Why", "Files"], refused))
    if collection.notes:
        report.section("Notes", Bullets(collection.notes[:SHOWN]))
    return report


def _plan_data(collection, entries):
    return {"game": collection.game, "units": [u.__dict__ for u in collection.units], "notes": collection.notes,
            "destinations": [{"name": e["destination"].name, "folder": str(e["destination"].path or ""),
                              "problem": e["destination"].problem, "privateLocal": e["destination"].private_local,
                              "shared": e["destination"].shared, "copy": [i.key for i in e["copy"]],
                              "copyBytes": sum(i.size for i in e["copy"]), "same": e["same"],
                              "refused": {why: len(items) for why, items in e["refused"].items()}} for e in entries]}


def _run_report(results, notes):
    copied = sum(len(r["copied"]) for r in results)
    failed = sum(len(r["failed"]) for r in results)
    report = Report(f"Safe copies: {copied} files copied" + (f", {failed} failed" if failed else ""))
    rows = []
    for r in results:
        git = r["git"]
        sent = ("" if git is None else "pushed" if git.get("pushed") else "committed, not pushed" if git.get("committed")
                else "nothing new" if not git.get("error") else "git failed")
        rows.append([r["destination"], len(r["copied"]), _size(sum(c["bytes"] for c in r["copied"])), r["same"],
                     sum(v["files"] for v in r["refused"].values()), len(r["failed"]), r["gone"], sent])
    report.section("Copied", Table(["Destination", "Copied", "Size", "Unchanged", "Refused", "Failed", "Gone from source",
                                    "Repository"], rows))
    problems = [f"{r['destination']}: {f['path']}: {f['error']}" for r in results for f in r["failed"]]
    problems += [w for r in results for w in r["warnings"]]
    if problems:
        report.section("Problems", Bullets(problems[:SHOWN]))
    let_go = [f"{r['destination']}: {path}" for r in results for path in r.get("letGo", [])]
    if let_go:
        report.section("Older copies let go (each set keeps its number of earlier copies)", Bullets(let_go[:SHOWN]))
    if notes:
        report.section("Notes", Bullets(notes[:SHOWN]))
    return report


def _status_report(collection, dests, rows):
    never = [r for r in rows if r["neverCopied"]]
    changed = [r for r in rows if any(v.get("state") == "changed since" for v in r["destinations"].values())]
    title = ("Safe copies: " + (f"{len(never)} never copied" if never else f"{len(changed)} changed since their copy" if changed
                                else "everything copied"))
    report = Report(title)
    report.section("Destinations", _destination_rows(dests))

    def cell(value):
        if value["state"] == "copied":
            return f"copied {_local_time(value['lastCopied'])}"
        if value["state"] == "changed since":
            return f"{value['changed']} changed since {_local_time(value['lastCopied'])}" if value["lastCopied"] else "never copied"
        return value["state"]

    report.section("Sets", Table(["Set", "Kind", "Files", "Size", *[d.name.capitalize() for d in dests]],
                                 [[f"{r['set']}/{r['unit']}" if r["unit"] else r["set"], r["kind"], r["files"], _size(r["bytes"]),
                                   *[cell(r["destinations"][d.name]) for d in dests]] for r in rows]))
    runs = [[d.name, (last_run(d.path) or {}).get("time") and _local_time(last_run(d.path)["time"]) or "never"]
            for d in dests if not d.problem]
    if runs:
        report.section("Last run", Table(["Destination", "When"], runs))
    if collection.notes:
        report.section("Notes", Bullets(collection.notes[:SHOWN]))
    return report


def main(argv=None, out=None, environ=None):
    out = out or sys.stdout
    try:
        args = _parser().parse_args(list(sys.argv[1:] if argv is None else argv))
    except SystemExit as stop:
        return EXIT_USAGE if stop.code else EXIT_OK
    redact = keep if args.no_redact else home_redactor()

    def answer(report, data):
        out.write((envelope_text("safe-copies", report, redact, data) if args.json else render_markdown(report, redact)) + "\n")

    try:
        if args.report == "mark":
            kind = "repository" if args.repository else "private-local" if args.private_local else "local"
            data = mark(args.to, kind)
            answer(Report(f"Marked {args.to} as a {kind} destination"), {"ok": True, "mark": data})
            return EXIT_OK
        root = Path(args.root)
        settings_file = _settings_file(root)
        if args.report == "plan":
            collection, entries = plan(root, environ, set(args.set) or None)
            answer(_plan_report(collection, entries), _plan_data(collection, entries))
            return EXIT_OK
        if args.report == "run":
            collection, results = run(root, environ, set(args.set) or None, push=not args.no_push,
                                      progress=Progress(environ))
            answer(_run_report(results, collection.notes), {"ok": True, "game": collection.game, "results": results})
            record = next((r["record"] for r in results if r.get("record")), None)
            if record and not args.json:
                out.write(f"report: {record}\n")
            return EXIT_PROBLEMS if any(r["failed"] or r["warnings"] for r in results) else EXIT_OK
        if args.report == "status":
            collection, dests, rows = status(root, environ)
            waiting = {d.name: unsent(d.path) for d in dests if d.name == "repository" and not d.problem}
            kept = [entry for d in dests for entry in kept_only(collection, d)]
            data = {"game": collection.game, "notes": collection.notes, "sets": rows, "keptOnly": kept,
                    "destinations": [{"name": d.name, "folder": str(d.path or ""), "problem": d.problem,
                                      "privateLocal": d.private_local, "shared": d.shared,
                                      "lastRun": last_run(d.path) if not d.problem else None,
                                      "unsent": waiting.get(d.name)} for d in dests]}
            report = _status_report(collection, dests, rows)
            for name, count in waiting.items():
                if count:
                    report.lines.append(f"The {name} copy holds {count} commits not sent yet: the next run tries again.")
            if kept:
                report.section("Kept, no longer taken (safe-copies let-go lists and removes them on request)",
                               Table(["Copy", "Why", "Size", "Earlier copies"],
                                     [[e["key"], e["why"], _size(e["bytes"]), f"{e['earlier']} ({_size(e['earlierBytes'])})"]
                                      for e in kept]))
            answer(report, data)
            return EXIT_OK
        if args.report == "let-go":
            if not args.file and not args.all:
                raise SafeCopiesError("name each copy with --file, or --all for every copy status lists as no longer taken")
            keys = args.file
            if args.all:
                keys = [entry["key"] for entry in kept_only(collect(root, environ), next(
                    d for d in destinations(environ, settings_file) if d.name == "local"))]
            done = let_go(root, keys, environ, apply=args.apply)
            title = (f"Let go of {len(done['chosen'])} copies ({_size(done['bytes'])})" if done["applied"]
                     else f"Would let go of {len(done['chosen'])} copies ({_size(done['bytes'])}); add --apply")
            report = Report(title)
            if done["chosen"]:
                report.section("Copies", Table(["Copy", "Why", "Earlier copies"],
                                               [[e["key"], e["why"], e["earlier"]] for e in done["chosen"]]))
            answer(report, {"ok": True, **done})
            return EXIT_OK
        if args.report == "verify":
            found = verify(environ, settings_file, Progress(environ))
            bad = sum(len(f["problems"]) for f in found)
            report = Report(f"Safe copies: {sum(f['checked'] for f in found)} checked, "
                            + (f"{bad} problems" if bad else "all whole") if found else "Safe copies: no destination is ready")
            report.section("Checked", Table(["Destination", "Folder", "Files", "Problems"],
                                            [[f["destination"], f["folder"], f["checked"], len(f["problems"])] for f in found]))
            listed = [f"{f['destination']}: {p['path']}: {p['problem']}" for f in found for p in f["problems"]]
            if listed:
                report.section("Problems", Bullets(listed[:SHOWN]))
            answer(report, {"destinations": found})
            return EXIT_PROBLEMS if bad else EXIT_OK
        if args.report == "restore":
            game = args.game or load_config(root).game
            done = restore(game, args.set, args.to, args.unit, args.source, args.overwrite, args.overwrite_newer, environ,
                           settings_file)
            report = Report(f"Restored {done['restored']} files to {done['to']}")
            report.lines.append(f"{done['same']} were already there unchanged; {done['replaced']} replaced.")
            answer(report, {"ok": True, **done})
            return EXIT_OK
    except SafeCopiesError as refused:
        answer(Report(f"Refused: {refused}"), {"ok": False, "refusal": str(refused)})
        return EXIT_REFUSED
    return EXIT_USAGE


MANIFEST = {"game": None, "parser": _parser, "effect": READS,
            "reports": {"plan": {"question": "What would a safe copy take, and where may each kind go?"},
                        "status": {"question": "What has been copied safely, and what never has?"},
                        "verify": {"question": "Are the safe copies still whole?"},
                        "run": {"effect": WRITES, "note": "copies what changed to the chosen destinations, then commits and pushes "
                                "the repository's copy; lets go only earlier copies beyond a set's keepEarlier"},
                        "restore": {"effect": WRITES, "note": "copies a set into a folder the owner names; never over a "
                                    "different file unasked"},
                        "mark": {"effect": WRITES, "note": "writes .safe-copies.json in the folder named, on the owner's word"},
                        "let-go": {"effect": WRITES, "when": "--apply", "note": "removes copies the list no longer takes, each "
                                   "named, from the plain folder; never a source and never a copy in use"}}}
