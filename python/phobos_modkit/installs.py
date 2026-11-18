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
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

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

    @property
    def save_notes(self):
        return [e for e in self.gain + self.lose if e.about_saves]


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
            "commit": head(root), "uncommitted": changed[:50], "uncommittedCount": len(changed),
            "installed": (now or datetime.now(timezone.utc)).isoformat(timespec="seconds")}


def write_record(target, record):
    with open(Path(target) / RECORD, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(record, handle, indent=2)
        handle.write("\n")


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
    """A mod's backup folder names, newest first."""
    try:
        names = [p.name for p in Path(backups).iterdir() if p.is_dir()]
    except OSError:
        return []
    found = [n for n in names if (m := BACKUP_NAME.match(n)) and m.group("mod") == mod]
    return sorted(found, key=lambda n: n[-15:], reverse=True)


@dataclass
class Place:
    """Where one repository's mods come from, go to and are backed up."""
    root: Path
    config: dict
    game: object
    target: Path              # the game's folder of installed mods
    backups: Path
    settings: Path = None

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
    return Place(root, config, game, target, root / config["backups"], named)


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
        backups = [read_copy("backup", where.backups / name, where.game, measure, name) for name in backups_of(where.backups, mod)]
        changed = uncommitted(where.root, [f"{where.config['mods']}/{mod}", *where.config.get("sharedSources", [])])
        commit, exact = installed_commit(where, installed)
        since = commits_since(where.root, commit, f"{where.config['mods']}/{mod}")
        state = ModState(mod, repository, installed, backups, changed, since, builds=builds.get(mod, []), commit=commit,
                         commit_exact=exact, changelog=f"{where.config['mods']}/{mod}/{CHANGELOG}")
        if installed is not None:
            state.files = checks.compare_files(installed.folder, repository.folder, install_only)
            checks.mark_rebuilt(state.files, state.builds, where.root, commit)
            state.look_out = checks.look_out(where.root, repository.name, installed.version, repository.version)
        states.append(state)
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
    if (Path(folder) / name).exists():
        raise InstallsError(f"A backup named {name} already exists; wait a second and try again. Nothing was changed.")
    return name


def backup(where, mod, now=None):
    """Copies the installed mod into the backups folder. Returns the new backup's name. Safe while the game runs: it only reads."""
    _known_mod(where, mod)
    installed = where.installed(mod)
    if not installed.is_dir():
        raise InstallsError(f"{mod} is not installed, so there is nothing to back up.")
    _need_space(where.backups, size_of(installed), "The backup")
    name = _free_name(where.backups, mod, now)
    where.backups.mkdir(parents=True, exist_ok=True)
    partial = where.backups / f"{name}.partial"
    try:
        shutil.copytree(installed, partial)
        partial.rename(where.backups / name)
    except OSError as error:
        if partial.exists():
            remove(partial)
        raise InstallsError(f"The backup could not be made ({error}). Nothing was changed.") from None
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
    source, target = where.backups / name, where.installed(mod)
    _need_space(where.target, size_of(source), "Going back to the backup")
    if target.is_dir():
        _need_space(where.backups, size_of(target), "Keeping the replaced install as a backup")
    replaced = _free_name(where.backups, mod, now) if target.is_dir() else None
    stamp = _stamp(now)
    staging = where.target.parent / f"{mod}-restoring-{stamp}"
    aside = where.target.parent / f"{mod}-replaced-{stamp}"
    try:
        shutil.copytree(source, staging)
    except OSError as error:
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
    return _run_command(where, [sys.executable if part == "{python}" else part for part in command], "build", run, progress)
