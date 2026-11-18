"""What a passing gate checked, and whether a commit's staged files are exactly that.

After a full run passes (no --only or --skip), the gate notes every file that differs from HEAD in the working tree, by the blob
git would store for it, in the repository's own .git folder (`phobos-gate/passes.json`, the last 20 passes). A pre-commit hook
then runs `gate --verify-staged`: the commit goes ahead only when one passing run saw every staged file with exactly the content
staged. A file that changed while the gate ran is left out of its note, since the gate may have read either version.

So a commit chained after a failed gate, or made after an edit the gate never saw, is refused (seen 18 November 2026: a gate piped
through `tail` lost its exit code and a broken commit went in). Several sessions may share a tree: one session's failing run
leaves another's earlier pass standing, and a pass covers any of the files it saw, whoever commits them.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess

FOLDER, FILE = "phobos-gate", "passes.json"
KEPT = 20
DELETED = "deleted"
SUBMODULE = "160000"


class StampError(RuntimeError):
    pass


REPOSITORY_VARIABLES = ("GIT_DIR", "GIT_INDEX_FILE", "GIT_WORK_TREE", "GIT_PREFIX")


def _git(root, args, run, data=None, own=False):
    """git in root. own=True drops the variables a hook inherits, for a submodule, which is a repository of its own."""
    env = {k: v for k, v in os.environ.items() if not (own and k in REPOSITORY_VARIABLES)}
    env["GIT_OPTIONAL_LOCKS"] = "0"
    try:
        result = run(["git", "-C", str(root), "-c", "core.quotepath=false", *args], input=data, capture_output=True,
                     check=False, env=env)
    except OSError as failed:
        raise StampError(f"git could not be started: {failed}") from failed
    if result.returncode != 0:
        raise StampError(f"git {' '.join(args[:2])} failed: {result.stderr.decode('utf-8', 'replace').strip()[:500]}")
    return result.stdout


def is_top(root, run=subprocess.run):
    """True when root is the top folder of a git working tree (not a folder somewhere inside one, nor outside any)."""
    try:
        top = _git(root, ["rev-parse", "--show-toplevel"], run).decode("utf-8").strip()
    except StampError:
        return False
    return bool(top) and os.path.normcase(os.path.realpath(top)) == os.path.normcase(os.path.realpath(str(root)))


def git_dir(root, run=subprocess.run):
    return Path(_git(root, ["rev-parse", "--absolute-git-dir"], run).decode("utf-8").strip())


def _nul(raw):
    return [item for item in raw.decode("utf-8", "replace").split("\0") if item]


def working_state(root, run=subprocess.run):
    """{path: blob ID, "deleted", or "commit:<ID>" for a submodule} for every path that differs from HEAD in the working tree."""
    root = Path(root)
    paths = sorted({entry[3:] for entry in _nul(_git(root, ["status", "--porcelain=v1", "-z", "--untracked-files=all",
                                                            "--no-renames", "--ignore-submodules=none"], run))})
    modes = {}
    for entry in _nul(_git(root, ["ls-files", "-s", "-z"], run)):
        info, _, path = entry.partition("\t")
        modes[path] = info.split(" ", 1)[0]
    state, files = {}, []
    for path in paths:
        local = root / path
        if modes.get(path) == SUBMODULE or (local.is_dir() and (local / ".git").exists()):
            state[path] = "commit:" + _git(local, ["rev-parse", "HEAD"], run, own=True).decode().strip() if local.is_dir() else DELETED
        elif local.is_file():
            files.append(path)
        else:
            state[path] = DELETED
    if files:
        blobs = _git(root, ["hash-object", "--stdin-paths"], run, ("\n".join(files) + "\n").encode("utf-8")).decode().split()
        state.update(zip(files, blobs))
    return state


def staged_state(root, run=subprocess.run):
    """{path: blob ID, "deleted" or "commit:<ID>"} for every path the commit would change against HEAD."""
    paths = _nul(_git(root, ["diff", "--cached", "--name-only", "-z", "--no-renames"], run))
    if not paths:
        return {}
    index = {}
    for entry in _nul(_git(root, ["ls-files", "-s", "-z"], run)):
        info, _, path = entry.partition("\t")
        mode, blob = info.split(" ")[:2]
        index[path] = ("commit:" + blob) if mode == SUBMODULE else blob
    return {path: index.get(path, DELETED) for path in paths}


def _file(root, run):
    return git_dir(root, run) / FOLDER / FILE


def _passes(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8")).get("passes", [])
    except (OSError, ValueError):
        return []


def record(root, before, after, run=subprocess.run, now=None):
    """Note a passing run: the files whose content was the same when it started and when it ended. Returns how many."""
    steady = {path: value for path, value in after.items() if before.get(path) == value}
    path = _file(root, run)
    passes = _passes(path)
    head = _git(root, ["rev-parse", "HEAD"], run).decode().strip()
    passes.append({"at": (now or datetime.now(timezone.utc)).strftime("%Y-%m-%d %H:%M:%S UTC"), "head": head, "files": steady})
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps({"passes": passes[-KEPT:]}, indent=1), encoding="utf-8")
    os.replace(temporary, path)
    return len(steady)


def verify(root, run=subprocess.run):
    """(covered, the staged paths no passing run saw as staged, when the newest pass was). Nothing staged is covered."""
    staged = staged_state(root, run)
    if not staged:
        return True, [], None
    passes = _passes(_file(root, run))
    for entry in reversed(passes):
        files = entry.get("files", {})
        if all(files.get(path) == value for path, value in staged.items()):
            return True, [], entry.get("at")
    newest = passes[-1] if passes else {}
    files = newest.get("files", {})
    missing = sorted(path for path, value in staged.items() if files.get(path) != value)
    return False, missing, newest.get("at")
