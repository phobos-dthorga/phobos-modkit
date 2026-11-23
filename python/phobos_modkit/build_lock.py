"""One build at a time in a repository (1.103.0). Game-free.

The owner's report of 23 Nov 2026: an install's build failed because another session's gate was building the same projects into the
same output folders at the same moment ("being used by another process"). Every tool that builds a repository's code takes this lock
first: the gate, for a step that says it "holds" a build, and a repository's own install script. A second build waits, saying who
holds the lock and since when, and goes on once it is let go; it gives up only after `wait_s`, saying so.

The lock lives in the kit's cache (outside every repository, so it is never committed or synced), one file per repository and name,
on top of `file_lock.held`. The file holds who took it (the process, what for, and when), so the one waiting can say.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import time

from . import cache, file_lock

NAMESPACE = "locks"
DEFAULT_NAME = "build"
# A build waits up to a quarter of an hour for another to finish (a full gate's builds take a minute or two), and a lock older than
# an hour is one a run that stopped without letting go left behind.
DEFAULT_WAIT_S = 15 * 60
DEFAULT_STALE_S = 60 * 60


class BuildBusy(RuntimeError):
    """Another build of the same repository held the lock for longer than this one would wait."""

    def __init__(self, path, holder, waited_s):
        self.path = Path(path)
        self.holder = holder
        self.waited_s = waited_s
        super().__init__(f"another build of this repository held its build lock for {waited_s:.0f} s ({describe(holder)}); "
                         f"try again once it has finished, or remove {self.path} if no build is running")


@dataclass
class Taken:
    """What taking the lock came to: whether this run waited, for how long, and for whom."""
    path: Path
    waited_s: float = 0.0
    waited_for: dict | None = None


def lock_path(root, name=DEFAULT_NAME, folder=None):
    """The lock file for one repository and lock name: in the kit's cache, named by the folder's name and a hash of its full path."""
    resolved = Path(root).resolve()
    digest = hashlib.sha256(os.path.normcase(str(resolved)).encode("utf-8")).hexdigest()[:12]
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", resolved.name)[:40] or "repository"
    base = Path(folder) if folder is not None else cache.folder(NAMESPACE)
    return base / f"{slug}-{digest}-{name}.lock"


def read_holder(path):
    """Who holds a lock, as its file says; empty when it says nothing readable (a lock taken a moment ago is still empty)."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def describe(holder):
    """A holder in a few words: "a gate (process 1234) since 16:53:19"."""
    if not holder:
        return "another build"
    purpose = holder.get("purpose") or "another build"
    pid = holder.get("pid")
    since = holder.get("since", "")
    when = ""
    if since:
        try:
            when = " since " + datetime.fromisoformat(since).astimezone().strftime("%H:%M:%S")
        except ValueError:
            when = ""
    return f"{purpose}" + (f" (process {pid})" if pid else "") + when


@contextmanager
def held(root, purpose, name=DEFAULT_NAME, wait_s=DEFAULT_WAIT_S, stale_s=DEFAULT_STALE_S, log=None, folder=None,
         clock=time.monotonic, now=time.time, sleep=time.sleep, pid=None):
    """
    Holds the repository's build lock while the block runs, yielding a `Taken`. When another build holds it, says so through `log`
    (once), waits, and raises `BuildBusy` after `wait_s`.
    """
    path = lock_path(root, name, folder)
    start = clock()
    lock = file_lock.held(path, 0, stale_s, clock=clock, now=now, sleep=sleep)
    waited_for = None
    try:
        lock.__enter__()
    except file_lock.LockBusy:
        waited_for = read_holder(path)
        if log is not None:
            log(f"Waiting for {describe(waited_for)} to finish building this repository...")
        lock = file_lock.held(path, wait_s, stale_s, clock=clock, now=now, sleep=sleep)
        try:
            lock.__enter__()
        except file_lock.LockBusy:
            raise BuildBusy(path, read_holder(path) or waited_for, clock() - start) from None
    taken = Taken(path, clock() - start, waited_for)
    try:
        holder = {"purpose": purpose, "pid": pid if pid is not None else os.getpid(),
                  "since": datetime.fromtimestamp(now(), timezone.utc).isoformat(timespec="seconds")}
        file_lock.patiently(lambda: path.write_text(json.dumps(holder), encoding="utf-8"), sleep)
        if waited_for is not None and log is not None:
            log(f"Went on after waiting {taken.waited_s:.0f} s.")
        yield taken
    finally:
        lock.__exit__(None, None, None)
