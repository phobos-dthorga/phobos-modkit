"""Lean local clones of other authors' public source, and a watch on what they and their drive cost.

Game-free. A clone keeps the repository's whole commit history but fetches file contents only for what is checked out
(git's partial clone, --filter=blob:none), and checks out only source and project files (a sparse checkout), never
textures, sounds or binaries. git runs as a program; nothing in a clone is ever run (clones carry no hooks, and Git LFS
downloads are skipped). Never deletes anything: when a clone budget or the drive's free space runs short, the report says
so and leaves the choice to a person.
"""
from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import re
import shutil
import subprocess

# What a clone checks out: source, project files and the papers that say what the source is. Patterns in git's
# sparse-checkout (gitignore) form, matched at any depth.
SPARSE_PATTERNS = ("*.cs", "*.csproj", "*.sln", "*.props", "*.targets", "About.xml", "README*", "LICENSE*", "LICENCE*",
                   "CHANGELOG*", "COPYING*")
# Below these the drive counts as short of space: a clone is refused and the report warns.
FLOOR_BYTES = 10 * 1000 ** 3
FLOOR_FRACTION = 0.03
# Above this the clones together are worth a look.
BUDGET_BYTES = 3 * 1000 ** 3
SUFFIX = "-src"
GIT_ENV = {"GIT_LFS_SKIP_SMUDGE": "1", "GIT_TERMINAL_PROMPT": "0"}
SAFE = ["-c", "core.fsmonitor=false"]


class CloneError(RuntimeError):
    pass


@dataclass
class Outcome:
    name: str
    folder: Path
    action: str          # "cloned", "updated", "unchanged", "kept", "refused", "failed"
    detail: str = ""
    size: int = 0


def folder_name(title):
    """A clone's folder name from a mod's title: its letters and digits in CamelCase, then -src."""
    words = re.findall(r"[A-Za-z0-9]+", re.sub(r"\[[^\]]*\]", " ", title))
    return "".join(w[:1].upper() + w[1:] for w in words) + SUFFIX if words else ""


def folder_size(path):
    """Bytes on disk under path, .git included; unreadable files are skipped."""
    total = 0
    for current, _, files in os.walk(path):
        for name in files:
            try:
                total += os.lstat(os.path.join(current, name)).st_size
            except OSError:
                continue
    return total


def drive(path):
    """(free bytes, total bytes) of the drive holding path (or its nearest existing parent)."""
    path = Path(path)
    while not path.exists() and path.parent != path:
        path = path.parent
    usage = shutil.disk_usage(path)
    return usage.free, usage.total


def short_of_space(free, total, floor=FLOOR_BYTES, fraction=FLOOR_FRACTION):
    return free < floor or (total and free / total < fraction)


def _git(args, run, cwd=None):
    env = dict(os.environ, **GIT_ENV)
    result = run(["git", *SAFE, *args], cwd=cwd, capture_output=True, text=True, env=env, check=False)
    if result.returncode != 0:
        raise CloneError((result.stderr or result.stdout or "git failed").strip().splitlines()[-1][:300])
    return result.stdout


def clone(url, folder, run=subprocess.run):
    """A partial, sparse clone of url into folder."""
    folder = Path(folder)
    _git(["clone", "--quiet", "--filter=blob:none", "--no-checkout", url, str(folder)], run)
    _git(["config", "core.fsmonitor", "false"], run, folder)
    _git(["sparse-checkout", "set", "--no-cone", *SPARSE_PATTERNS], run, folder)
    _git(["checkout", "--quiet"], run, folder)


def update(folder, run=subprocess.run):
    """Fetch new history and move forward if that needs no merge; True when anything changed. Never discards work."""
    before = _git(["rev-parse", "HEAD"], run, folder).strip()
    _git(["fetch", "--quiet", "--tags", "--filter=blob:none"], run, folder)
    try:
        _git(["merge", "--ff-only", "--quiet", "@{upstream}"], run, folder)
    except CloneError as error:
        raise CloneError(f"could not move forward without a merge ({error}); left as it was") from None
    return _git(["rev-parse", "HEAD"], run, folder).strip() != before


def ensure(repos, into, refresh=False, run=subprocess.run, space=drive, floor=FLOOR_BYTES, fraction=FLOOR_FRACTION):
    """Clone each (title, url) not yet in `into`; with refresh, update those that are. Returns [Outcome].

    A new clone is refused while the drive is short of space; updates still run, as they are small.
    """
    into = Path(into)
    outcomes = []
    for title, url in repos:
        name = folder_name(title)
        if not name:
            continue
        folder = into / name
        try:
            if (folder / ".git").is_dir():
                if refresh:
                    outcomes.append(Outcome(title, folder, "updated" if update(folder, run) else "unchanged"))
                else:
                    outcomes.append(Outcome(title, folder, "kept"))
            elif folder.exists():
                outcomes.append(Outcome(title, folder, "failed", "a folder of that name is there and is not a clone; left alone"))
            elif short_of_space(*space(into), floor, fraction):
                outcomes.append(Outcome(title, folder, "refused", "the drive is short of space"))
            else:
                into.mkdir(parents=True, exist_ok=True)
                clone(url, folder, run)
                outcomes.append(Outcome(title, folder, "cloned"))
        except CloneError as error:
            outcomes.append(Outcome(title, folder, "failed", str(error)))
    for outcome in outcomes:
        if outcome.folder.is_dir():
            outcome.size = folder_size(outcome.folder)
    return outcomes


def existing(into):
    """Every clone folder already in `into` (name ending -src with a .git inside), with its size."""
    into = Path(into)
    if not into.is_dir():
        return []
    return sorted(((p.name, folder_size(p)) for p in into.iterdir() if p.name.endswith(SUFFIX) and (p / ".git").is_dir()),
                  key=lambda item: -item[1])
