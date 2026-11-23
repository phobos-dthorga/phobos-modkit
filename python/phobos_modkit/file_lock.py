"""One lock file shared by separate runs of the kit, so two runs never change the same thing at once (1.70.2). Game-free.

A lock is a file created only if it is not there; whoever created it holds it until it is deleted. A run waits up to `wait_s` for
another to let go, and breaks a lock older than `stale_s`, which a run that stopped without letting go left behind. The claims
board, safe copies' destinations, the build of the kit's C# tools and a repository's builds (build_lock, 1.103.0) each hold one.
"""
from __future__ import annotations

from contextlib import contextmanager
import os
from pathlib import Path
import time

POLL_S = 0.05
# Windows can refuse a rename or a delete for a moment while a virus scanner or the indexer holds a file just written.
HELD_TRIES = 50
HELD_WAIT_S = 0.02


class LockBusy(RuntimeError):
    """Another run held the lock for longer than this one would wait."""


def patiently(step, sleep=time.sleep):
    """Runs a file step, trying again for up to a second while Windows says another program holds the file."""
    for attempt in range(HELD_TRIES):
        try:
            return step()
        except PermissionError:
            if attempt == HELD_TRIES - 1:
                raise
            sleep(HELD_WAIT_S)
    return None


@contextmanager
def held(lock, wait_s, stale_s, poll_s=POLL_S, clock=time.monotonic, now=time.time, sleep=time.sleep):
    """Holds the lock file `lock` while the block runs; raises LockBusy when another run holds it past `wait_s`."""
    lock = Path(lock)
    lock.parent.mkdir(parents=True, exist_ok=True)
    deadline = clock() + wait_s
    while True:
        try:
            os.close(os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY))
            break
        except (FileExistsError, PermissionError):
            # Windows answers PermissionError, not FileExistsError, while a lock just let go is still being deleted: busy either way.
            try:
                if now() - lock.stat().st_mtime > stale_s:
                    lock.unlink(missing_ok=True)
                    continue
            except OSError:
                continue
            if clock() >= deadline:
                raise LockBusy(str(lock)) from None
            sleep(poll_s)
    try:
        yield
    finally:
        patiently(lambda: lock.unlink(missing_ok=True), sleep)
