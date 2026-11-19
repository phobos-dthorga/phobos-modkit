"""rimworld-perf's memory watch: how much memory the running game holds over minutes or hours, what kind, and when it jumps.

A heap snapshot shows one instant of .NET's heap and pauses the game to take it; a watch follows the whole program for as long
as it is asked, without pausing it, and says whether memory climbs steadily or in jumps, and what the log says happened at
each jump (a save loaded, a burst of errors). Every few seconds it takes:

- **from Windows** (`process_memory`): what the game has claimed (private bytes, the figure Task Manager's "commit size" shows)
  and what of it sits in RAM;
- **from the runtime** (Microsoft's dotnet-counters, attached once for the whole watch): what the collector holds from
  Windows, the .NET heap after its last collection, and the gaps inside it (the heap's size counts its gaps, so live objects
  are the heap less the gaps: Microsoft's runtime metrics reference, learn.microsoft.com/dotnet/core/diagnostics/built-in-metrics-runtime);
- and, every minute or so, **the memory map**: private memory by block and block size, loaded code files and mapped files.
  A block that keeps growing shows itself between two maps; the one whose size matches the collector's own figure is .NET's.

The difference between what the game claimed and what .NET's collector holds is everything else: the engine, graphics
drivers, native code, and .NET's own bookkeeping (compiled code, type data). Nothing in the game is changed or paused; the
counters attach once at the start, which can hitch the game for a moment.

Watches are kept in the kit's cache (`rimworld-memory/<start>-<label>/watch.sqlite`), outside every repository.

A program can follow a watch while it runs and steer it without a console (1.47.0, for D'thorga Companion): `status` reads it as
it fills, with the runtime's counters from dotnet-counters' own file as far as that has been written; a `stop` file in its folder
ends it within a second, the counters too; and `add_mark` puts the owner's own words beside the figures ("reloading now"), so
what was meant to happen can be checked against what the log shows did.
"""
from __future__ import annotations

from bisect import bisect_right
from contextlib import closing
from datetime import datetime
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import time

from ... import __version__
from ... import cache as derived
from ... import dotnet_diagnostics as dd
from ... import process_memory as pm
from ...report import Bullets, Chart, ChartSeries, Report, Table
from ...sampling import UNKNOWN
from . import log as rimworld_log
from . import paths

WATCH_FOLDER = "rimworld-memory"
DATABASE, COUNTERS_FILE, COUNTERS_LOG = "watch.sqlite", "counters.json", "counters.log"
DEFAULT_MINUTES, MAX_MINUTES = 60, 24 * 60
DEFAULT_EVERY, MIN_EVERY = 5, 1
DEFAULT_MAP_EVERY, MIN_MAP_EVERY = 60, 10
JUMP_WINDOW = 60                    # seconds: a rise inside one minute counts as one jump
JUMP_SIZE = 250_000_000             # bytes: the smallest rise that counts as a jump
JUMPS_SHOWN = 10
NEARBY = 60                         # seconds either side of a jump in which a logged event counts as near it
TIMELINE_POINTS = 24
STOP_SECONDS = 60                   # how long dotnet-counters may take to close its file once the watch ends
HEAP_MATCH = 0.10                   # a block within 10 % of the collector's committed figure is taken to be .NET's heap
GB = 1e9
STOP_FILE = "stop"                  # a file of this name in a running watch's folder ends it at its next look
STOP_LOOK = 1.0                     # seconds: how often a waiting watch looks for the stop file
STOP_COUNTERS = 15                  # seconds dotnet-counters is given to close its file once asked to stop early
OWNER_MARK = "owner-mark"           # the event kind of the owner's own words
MAX_MARK = 200                      # characters in one mark
MARK_SLACK = 60                     # seconds before a watch's start or after its end that a mark may still name
ALIVE_LOOKS = 3                     # a running watch has sampled within this many of its intervals...
ALIVE_SECONDS = 30                  # ...or this many seconds, whichever is longer; else it was cut off
LIVE_POINTS = 120                   # points in a running watch's chart
KEPT_LISTED = 20                    # watches listed by status
RUNNING, FINISHING, ENDED, CUT_OFF = "running", "finishing", "ended", "cut-off"
RELOAD_WORDS = ("reload", "load")   # a mark naming one of these expects a save to be loaded soon after it
RELOAD_WITHIN = 180                 # seconds after such a mark in which the log should show the save loaded
SCHEMA = """
CREATE TABLE IF NOT EXISTS sample (t REAL, private INTEGER, working_set INTEGER, free_ram INTEGER);
CREATE TABLE IF NOT EXISTS counter (t REAL, name TEXT, tags TEXT, value REAL);
CREATE TABLE IF NOT EXISTS map_total (t REAL, kind TEXT, committed INTEGER, reserved INTEGER);
CREATE TABLE IF NOT EXISTS map_block (t REAL, base INTEGER, committed INTEGER, size INTEGER);
CREATE TABLE IF NOT EXISTS map_rest (t REAL, committed INTEGER);
CREATE TABLE IF NOT EXISTS map_size (t REAL, class TEXT, blocks INTEGER, committed INTEGER);
CREATE TABLE IF NOT EXISTS map_file (t REAL, kind TEXT, name TEXT, committed INTEGER);
CREATE TABLE IF NOT EXISTS event (t REAL, kind TEXT, text TEXT);
"""
CAVEAT = ("A watch measures memory while the game runs; it is not an in-game test. Nothing in the game is paused or changed; "
          "the runtime's counters attach once at the start, which can hitch the game for a moment.")
CAVEAT_ALONE = ("A watch measures memory while the game runs; it is not an in-game test. This one read Windows' figures only: "
                "nothing attached to the game.")
LIMITS = ["**Outside .NET** is what the game claimed less what .NET's collector holds: the engine (textures, meshes, sound), "
          "graphics drivers, native code and .NET's own bookkeeping (compiled code, type data) together. Windows cannot say "
          "which mod asked for native memory.",
          "The .NET heap is as the runtime counted it after its last collection, so it lags the moment by up to one collection. "
          "Its size counts the gaps between objects; live objects are that size less the gaps.",
          "Blocks are named by their address only. The block taken to be .NET's heap is the one whose size matches the "
          "collector's own figure; the rest are not named.",
          "Events come from Player.log as it stood when the watch ended. After about 4,000 messages the game stops writing its "
          "own messages, so a long session's later events can be missing."]


class WatchError(RuntimeError):
    pass


def size(value):
    for unit, scale in (("GB", 1e9), ("MB", 1e6), ("KB", 1e3)):
        if abs(value) >= scale:
            return f"{value / scale:,.1f} {unit}" if unit != "GB" else f"{value / scale:,.2f} {unit}"
    return f"{value:,.0f} bytes"


def signed(value):
    return ("+" if value > 0 else "") + size(value) if value else "0"


def clock(t):
    return datetime.fromtimestamp(t).strftime("%H:%M:%S")


# ---- Kept watches ----

def root(cache_arg, environ, settings_file):
    return derived.folder(WATCH_FOLDER, cache_arg, environ, settings_file)


def new_folder(where, label, now):
    slug = re.sub(r"[^a-z0-9]+", "-", (label or "").lower()).strip("-")[:40]
    name = now.strftime("%Y%m%d-%H%M%S") + (f"-{slug}" if slug else "")
    folder = Path(where) / name
    if folder.exists():
        raise WatchError(f"A watch named {name} already exists; wait a second and try again.")
    folder.mkdir(parents=True)
    return folder


def kept(where):
    where = Path(where)
    return sorted(p for p in where.iterdir() if (p / DATABASE).is_file()) if where.is_dir() else []


def find(where, text, prefer_running=False, now=None):
    """The watch named by its ID (its start is enough) or label; with no name, the newest, or the newest still running."""
    found = kept(where)
    if not found:
        raise WatchError(f"No memory watches kept in {where}. Start one with: rimworld-perf watch")
    if not text:
        if prefer_running:
            alive = [p for p in found if state(p, now) in (RUNNING, FINISHING)]
            if alive:
                return alive[-1]
        return found[-1]
    wanted = text.lower()
    matches = [p for p in found if p.name.lower().startswith(wanted)] or \
              [p for p in found if wanted in (derived.read_meta(p / DATABASE).get("label") or "").lower()]
    if len(matches) != 1:
        raise WatchError(f'"{text}" matches {len(matches)} watches. Kept: ' + ", ".join(p.name for p in found) + ".")
    return matches[0]


def _last_sample(folder):
    try:
        with closing(sqlite3.connect(Path(folder) / DATABASE, timeout=10)) as conn:
            return conn.execute("SELECT MAX(t) FROM sample").fetchone()[0]
    except sqlite3.Error:
        return None


def state(folder, now=None, meta=None):
    """Whether a kept watch is running, finishing (its counters and log being read in), ended, or was cut off: its watcher
    stopped without saying why (closed, killed, the machine slept)."""
    meta = derived.read_meta(Path(folder) / DATABASE) if meta is None else meta
    if meta.get("ended"):
        return ENDED
    now = time.time() if now is None else now
    if meta.get("finishing"):
        return FINISHING if now - float(meta["finishing"]) <= STOP_SECONDS + ALIVE_SECONDS + 60 else CUT_OFF
    last = _last_sample(folder) or float(meta.get("started") or 0)
    every = float(meta.get("every") or DEFAULT_EVERY)
    return RUNNING if now - last <= max(ALIVE_LOOKS * every, ALIVE_SECONDS) else CUT_OFF


def ask_to_stop(folder, now=None):
    """Asks a running watch to end at its next look, as Ctrl+C would in its console. Raises WatchError when it is not running."""
    folder = Path(folder)
    found = state(folder, now)
    if found not in (RUNNING, FINISHING):
        raise WatchError(f"The watch {folder.name} is not running ({found.replace('-', ' ')}), so there is nothing to stop.")
    (folder / STOP_FILE).write_text("stop\n", encoding="utf-8")
    return found


def add_mark(folder, text, at=None, now=None):
    """Puts the owner's own words beside a watch's figures, at `at` (seconds since 1970; now when left out). Returns (t, text).

    The watch may be running (its watcher commits between samples, so this waits its turn) or kept: a mark may name a moment
    up to a minute either side of it.
    """
    folder = Path(folder)
    text = " ".join((text or "").split())
    if not text:
        raise WatchError("A mark needs a few words, such as what you are about to do.")
    if len(text) > MAX_MARK:
        raise WatchError(f"A mark is at most {MAX_MARK} characters; this one has {len(text)}.")
    now = time.time() if now is None else now
    at = now if at is None else float(at)
    meta = derived.read_meta(folder / DATABASE)
    started = float(meta.get("started") or 0)
    ended = float(meta["ended"]) if meta.get("ended") else max(now, _last_sample(folder) or started)
    if not started - MARK_SLACK <= at <= ended + MARK_SLACK:
        raise WatchError(f"{clock(at)} is outside the watch {folder.name} ({clock(started)} to {clock(ended)}).")
    with closing(sqlite3.connect(folder / DATABASE, timeout=30)) as conn:
        conn.execute("INSERT INTO event VALUES (?, ?, ?)", (at, OWNER_MARK, text))
        conn.commit()
    return at, text


# ---- Watching ----

def _store_map(conn, t, found):
    conn.executemany("INSERT INTO map_total VALUES (?, ?, ?, ?)",
                     [(t, kind, found.committed.get(kind, 0), found.reserved.get(kind, 0)) for kind in pm.KINDS])
    conn.executemany("INSERT INTO map_block VALUES (?, ?, ?, ?)", [(t, base, c, s) for base, c, s in found.blocks])
    conn.execute("INSERT INTO map_rest VALUES (?, ?)", (t, found.blocks_rest))
    conn.executemany("INSERT INTO map_size VALUES (?, ?, ?, ?)", [(t, label, n, c) for label, (n, c) in found.sizes.items()])
    conn.executemany("INSERT INTO map_file VALUES (?, ?, ?, ?)", [(t, kind, name, c) for (kind, name), c in sorted(found.files.items())])


def log_events(text, start, end):
    """[(t, kind, text)] from a Player.log's text between start and end (seconds since 1970): saves loaded, the game
    stopping its own messages, the engine holding allocations, and errors."""
    log = rimworld_log.parse(text)
    found = []

    def when(stamp):
        try:
            return datetime.strptime(stamp, "%Y-%m-%d %H:%M:%S.%f").timestamp()
        except (TypeError, ValueError):
            return None
    for notice in log.notices:
        t = when(notice.data.get("time")) if notice.kind in ("save-loaded", "logging-stopped") else None
        if t is not None and start <= t <= end:
            text = f'save "{notice.data.get("save")}" loaded' if notice.kind == "save-loaded" else "the game stopped writing its messages"
            found.append((t, notice.kind, text))
    for entry in log.entries:
        t = when(entry.time)
        if t is None or not start <= t <= end:
            continue
        if entry.category == rimworld_log.ENGINE_LEAK_CATEGORY:
            found.append((t, "engine-held", entry.headline[:160]))
        elif entry.level == "ERROR":
            found.append((t, "error", entry.headline[:160]))
    return sorted(found)


def _wait(folder, until, end, clock_, sleep):
    """Waits until the next sample is due (or the watch's end), looking for the stop file every second. True when asked to stop."""
    stop = Path(folder) / STOP_FILE
    while True:
        if stop.exists():
            return True
        left = min(until, end) - clock_()
        if left <= 0:
            return False
        sleep(min(STOP_LOOK, left))


def watch(pid, folder, minutes, every, map_every, counters_tool, label="", progress=None, clock_=time.time, sleep=time.sleep,
          popen=subprocess.Popen, process=pm.Process, log_file=None):
    """Watch a running program until `minutes` pass, it closes, Ctrl+C, or a stop file appears in the folder; store everything
    in folder. Returns notes."""
    if not 1 <= minutes <= MAX_MINUTES:
        raise WatchError(f"--minutes must be between 1 and {MAX_MINUTES}.")
    if every < MIN_EVERY:
        raise WatchError(f"--every must be at least {MIN_EVERY} second.")
    if map_every and map_every < MIN_MAP_EVERY:
        raise WatchError(f"--map-every must be 0 (never) or at least {MIN_MAP_EVERY} seconds.")
    folder = Path(folder)
    notes, reason, asked = [], "the time asked for ran out", False
    (folder / STOP_FILE).unlink(missing_ok=True)
    start = clock_()
    end = start + minutes * 60
    seconds = int(minutes * 60)
    with closing(sqlite3.connect(folder / DATABASE)) as conn:
        conn.executescript(SCHEMA)
        derived.write_meta(conn, {"kit_version": __version__, "label": label or "", "pid": pid, "started": start,
                                  "minutes": minutes, "every": every, "map_every": map_every, "tools_version": dd.TOOLS_VERSION,
                                  "counters": bool(counters_tool), "watcher_pid": os.getpid()})
        conn.commit()
        counting = None
        with open(folder / COUNTERS_LOG, "w", encoding="utf-8") as counters_log, process(pid) as target:
            if counters_tool:
                counting = dd.start_counters(pid, folder / COUNTERS_FILE, counters_tool, seconds, every, counters_log, popen)
            samples = maps = 0
            next_map = start
            try:
                while True:
                    now = clock_()
                    if now >= end:
                        break
                    if not target.running():
                        reason = "the game closed"
                        break
                    try:
                        figures = target.figures()
                        conn.execute("INSERT INTO sample VALUES (?, ?, ?, ?)",
                                     (now, figures.private, figures.working_set, figures.free_ram))
                        samples += 1
                        if map_every and now >= next_map:
                            _store_map(conn, now, pm.summarise(target.regions()))
                            maps += 1
                            next_map = now + map_every
                        conn.commit()
                    except pm.MemoryError_ as gone:
                        reason = f"the game could not be read any more ({gone})"
                        break
                    if progress:
                        progress("Watching the game's memory", int(now - start), seconds,
                                 f"{size(figures.private)} claimed, {size(figures.working_set)} in RAM")
                    if _wait(folder, now + every, end, clock_, sleep):
                        reason, asked = "it was asked to stop", True
                        break
            except KeyboardInterrupt:
                reason = "stopped with Ctrl+C"
            derived.write_meta(conn, {"finishing": clock_()})
            conn.commit()
            if counting is not None:
                try:
                    if asked:
                        # Asked to stop early: dotnet-counters would run on to its own duration, so end it; whatever it wrote
                        # up to then is read (counter_events reads a file cut off mid-write).
                        counting.terminate()
                    counting.wait(timeout=STOP_COUNTERS if asked else STOP_SECONDS)
                except subprocess.TimeoutExpired:
                    counting.kill()
                    notes.append("dotnet-counters did not stop on time and was cut off; its figures up to then are kept.")
                except KeyboardInterrupt:
                    counting.kill()
        (folder / STOP_FILE).unlink(missing_ok=True)
        ended = clock_()
        events = dd.counter_events(folder / COUNTERS_FILE)
        conn.executemany("INSERT INTO counter VALUES (?, ?, ?, ?)", events)
        if counters_tool and not events:
            notes.append("dotnet-counters wrote nothing, so the watch has no .NET figures: see counters.log beside it.")
        if log_file and Path(log_file).is_file():
            text = Path(log_file).read_text(encoding="utf-8", errors="replace")
            conn.executemany("INSERT INTO event VALUES (?, ?, ?)", log_events(text, start, ended))
        derived.write_meta(conn, {"ended": ended, "reason": reason, "samples": samples, "maps": maps,
                                  "notes": "\n".join(notes)})
        conn.commit()
    return notes


# ---- Reading a watch back ----

class Watch:
    """A kept watch, read whole."""

    def __init__(self, folder):
        self.folder = Path(folder)
        self.meta = derived.read_meta(self.folder / DATABASE)
        with closing(sqlite3.connect(self.folder / DATABASE, timeout=10)) as conn:
            self.samples = conn.execute("SELECT t, private, working_set, free_ram FROM sample ORDER BY t").fetchall()
            series = {}
            counted = conn.execute("SELECT t, name, tags, value FROM counter ORDER BY t").fetchall()
            if not counted and not self.meta.get("ended"):
                # Still running: the counters are read in at the end, so take them from dotnet-counters' own file as far as
                # it has written it (a file cut off mid-write gives every whole event before the cut).
                counted = sorted(dd.counter_events(self.folder / COUNTERS_FILE))
            for t, name, tags, value in counted:
                series.setdefault((name, tags), ([], []))
                series[(name, tags)][0].append(t)
                series[(name, tags)][1].append(value)
            self.series = series
            self.map_times = [r[0] for r in conn.execute("SELECT DISTINCT t FROM map_total ORDER BY t")]
            self.events = conn.execute("SELECT t, kind, text FROM event ORDER BY t").fetchall()
            self._conn_rows = {
                "total": conn.execute("SELECT t, kind, committed FROM map_total").fetchall(),
                "block": conn.execute("SELECT t, base, committed, size FROM map_block").fetchall(),
                "rest": conn.execute("SELECT t, committed FROM map_rest").fetchall(),
                "size": conn.execute("SELECT t, class, blocks, committed FROM map_size").fetchall(),
                "file": conn.execute("SELECT t, kind, name, committed FROM map_file").fetchall(),
            }

    def counter_at(self, name, t):
        """The sum over tags of one counter's latest value at or before t; None when it had none yet."""
        total, seen = 0.0, False
        for (found, _), (times, values) in self.series.items():
            if found != name:
                continue
            at = bisect_right(times, t)
            if at:
                total += values[at - 1]
                seen = True
        return total if seen else None

    def has_counters(self):
        return any(name == dd.HEAP_COMMITTED for name, _ in self.series)

    def rows(self, which, t):
        return [r[1:] for r in self._conn_rows[which] if r[0] == t]


def _jumps(samples, window=JUMP_WINDOW, smallest=JUMP_SIZE, limit=JUMPS_SHOWN):
    """[(start index, end index, rise)]: the largest rises of private memory, each within `window` seconds, none overlapping."""
    candidates = []
    for i, (t, private, *_) in enumerate(samples):
        best, best_j = 0, None
        for j in range(i + 1, len(samples)):
            if samples[j][0] - t > window:
                break
            rise = samples[j][1] - private
            if rise > best:
                best, best_j = rise, j
        if best_j is not None and best >= smallest:
            candidates.append((best, i, best_j))
    taken = []
    # The largest rise first; of equal rises, the shortest span, so a jump is reported where it happened.
    for rise, i, j in sorted(candidates, key=lambda c: (-c[0], c[2] - c[1], c[1])):
        if any(not (j < a or i > b) for a, b, _ in taken):
            continue
        taken.append((i, j, rise))
        if len(taken) == limit:
            break
    return sorted(taken)


def _near(events, start, end, around=NEARBY):
    """What the log says between start - around and end + around: saves and stops by name, errors and held allocations counted."""
    picked = [e for e in events if start - around <= e[0] <= end + around]
    said = [f'you marked "{text}" at {clock(t)}' if kind == OWNER_MARK else f"{text} at {clock(t)}"
            for t, kind, text in picked if kind in ("save-loaded", "logging-stopped", OWNER_MARK)]
    errors = sum(1 for e in picked if e[1] == "error")
    held = sum(1 for e in picked if e[1] == "engine-held")
    if errors:
        said.append(f"{errors:,} error{'s' if errors != 1 else ''} logged")
    if held:
        said.append(f"{held:,} engine allocation warnings")
    return "; ".join(said) or "nothing logged"


def _happened(events, ended):
    """What happened during a watch, said before any figure: the saves the log shows loaded, the owner's marks, errors, and a
    mark that promised a reload the log never showed. A watch read before it ended has no log events yet."""
    saves = [(t, text) for t, kind, text in events if kind == "save-loaded"]
    marks = [(t, text) for t, kind, text in events if kind == OWNER_MARK]
    errors = sum(1 for e in events if e[1] == "error")
    lines = []
    if not ended:
        lines.append("**What happened** is read from the log when the watch ends; until then only your marks show.")
    elif saves:
        lines.append("Saves loaded during the watch: " + "; ".join(f"{text} at {clock(t)}" for t, text in saves) + ".")
    else:
        lines.append("**No save was loaded during the watch**, by the log: it shows no reload.")
    if marks:
        lines.append("Your marks: " + "; ".join(f'"{text}" at {clock(t)}' for t, text in marks) + ".")
    if ended:
        for t, text in marks:
            if any(word in text.lower() for word in RELOAD_WORDS) and not any(t <= s <= t + RELOAD_WITHIN for s, _ in saves):
                lines.append(f'**You marked "{text}" at {clock(t)}, but the log shows no save loaded in the {RELOAD_WITHIN // 60} '
                             "minutes after it**: the load may not have happened, or was done in a way the log does not "
                             "record. Read the figures around it with that in mind.")
        if errors:
            lines.append(f"{errors:,} error{'s' if errors != 1 else ''} logged during the watch.")
    return lines


def _verdict(private, jumps):
    """One bold line: how memory ended against how it began, and whether its climbing came in jumps or steadily."""
    change = private[-1] - private[0]
    climbed = sum(max(0, b - a) for a, b in zip(private, private[1:]))
    jumped = sum(rise for _, _, rise in jumps)
    ended = (f"it ended {size(change)} higher than it began" if change > 0 else
             f"it ended {size(-change)} lower than it began" if change < 0 else "it ended where it began")
    if climbed < JUMP_SIZE:
        return f"**It held steady**: {ended} ({size(private[0])}, then {size(private[-1])}), and never climbed {size(JUMP_SIZE)} in all."
    count = f"{len(jumps)} jump{'s' if len(jumps) != 1 else ''}"
    how = "mostly in jumps" if jumped >= climbed / 2 else "mostly as a steady climb"
    return (f"**It climbed {size(climbed)} in all, {how}**: {count} of {size(JUMP_SIZE)} or more within a minute made "
            f"{size(jumped)} of it; with what was freed along the way, {ended} ({size(private[0])}, then {size(private[-1])}).")


def _row(label, values, times):
    values = [(v, t) for v, t in zip(values, times) if v is not None]
    if not values:
        return (label, "-", "-", "-", "-", "-")
    numbers = [v for v, _ in values]
    high, at = max(values, key=lambda vt: vt[0])
    return (label, size(numbers[0]), size(numbers[-1]), size(min(numbers)), size(sum(numbers) / len(numbers)),
            f"{size(high)} at {clock(at)}")


def watch_report(watch, owner_map, top=15):
    meta, samples = watch.meta, watch.samples
    report = Report(f"rimworld-perf: memory watch {watch.folder.name}")
    if not samples:
        report.lines.append("**The watch holds no samples**: the game closed or could not be read as it started.")
        return report
    times = [s[0] for s in samples]
    label = f' ("{meta["label"]}")' if meta.get("label") else ""
    minutes = (times[-1] - times[0]) / 60
    found = state(watch.folder, meta=meta)
    how = {RUNNING: "It is still running.", FINISHING: "It is finishing: reading in the counters and the log."}.get(
        found, f"It ended because {meta.get('reason', 'it was cut off')}.")
    report.lines.append(f"Watched the game for **{minutes:,.0f} minutes**{label}, {clock(times[0])} to {clock(times[-1])} on "
                        f"{datetime.fromtimestamp(times[0]).strftime('%Y-%m-%d')}: {len(samples):,} samples every "
                        f"{meta.get('every', '?')} s and {len(watch.map_times):,} memory maps. {how}")
    counters = watch.has_counters()
    report.lines.append(CAVEAT if meta.get("counters", str(counters)) == "True" else CAVEAT_ALONE)
    for note in (meta.get("notes") or "").splitlines():
        report.lines.append(note)
    report.lines += _happened(watch.events, found == ENDED)
    # The runtime's heap size counts the gaps between objects too (Microsoft's metrics reference), so live objects are the rest.
    private, committed, heap, gaps, live, outside = _figures(watch)

    jumps = _jumps(samples)
    report.lines.append(_verdict(private, jumps))
    if counters and committed[-1] is not None:
        report.lines.append(f"At the end, .NET's collector held **{size(committed[-1])}** of the {size(private[-1])} the game "
                            f"had claimed, and everything outside .NET came to **{size(outside[-1])}**."
                            + (f" Of .NET's share, {size(live[-1])} was live objects and {size(gaps[-1])} gaps between them."
                               if live[-1] is not None else ""))
    elif not counters:
        report.lines.append("No .NET figures were recorded, so memory cannot be split into .NET's and the rest.")

    rows = [_row("Claimed by the game (private bytes)", private, times),
            _row("In RAM (working set)", [s[2] for s in samples], times)]
    if counters:
        rows += [_row(".NET's collector holds from Windows", committed, times),
                 _row(".NET heap after the last collection, gaps included", heap, times),
                 _row("Of it, live objects", live, times),
                 _row("Of it, gaps between objects", gaps, times),
                 _row("Outside .NET (claimed less the collector's)", outside, times)]
    rows.append(_row("Free RAM on the machine", [s[3] for s in samples], times))
    report.section("Average or bursts", Table(["Measure", "Start", "End", "Lowest", "Average", "Highest"], rows))

    if jumps:
        rows = []
        for i, j, rise in jumps:
            ti, tj = times[i], times[j]
            dnet = (committed[j] - committed[i]) if committed[i] is not None and committed[j] is not None else None
            dout = (outside[j] - outside[i]) if outside[i] is not None and outside[j] is not None else None
            rows.append((f"{clock(ti)} to {clock(tj)}", signed(rise), signed(dnet) if dnet is not None else "-",
                         signed(dout) if dout is not None else "-", _near(watch.events, ti, tj)))
        report.section("The largest jumps, in time order",
                       f"Rises of {size(JUMP_SIZE)} or more within a minute, with what the log and your marks say from a minute before to a "
                       "minute after.",
                       Table(["When", "Claimed", ".NET's collector", "Outside .NET", "What the log and your marks say"], rows))

    report.section("Over time", _chart(samples, committed, outside, counters, TIMELINE_POINTS, "Memory over the watch"))
    if watch.map_times:
        _map_sections(report, watch, committed, times, owner_map, top)
    report.section("What a watch cannot say", Bullets(LIMITS))
    return report


def _chart(samples, committed, outside, counters, points, title):
    """The timeline: what the game claimed, split into .NET's collector and the rest, with what sat in RAM, at most `points`
    points along the samples, the last always among them."""
    step = max(1, -(-len(samples) // points))
    picks = list(range(0, len(samples), step))
    if picks[-1] != len(samples) - 1:
        picks.append(len(samples) - 1)
    series = [ChartSeries("Claimed", [round(samples[i][1] / GB, 2) for i in picks], "accent")]
    if counters:
        series += [ChartSeries(".NET's collector", [round(committed[i] / GB, 2) if committed[i] is not None else None for i in picks], "comparison"),
                   ChartSeries("Outside .NET", [round(outside[i] / GB, 2) if outside[i] is not None else None for i in picks], "observed")]
    series.append(ChartSeries("In RAM", [round(samples[i][2] / GB, 2) for i in picks], "neutral"))
    return Chart(title, "What the game claimed, split into .NET's collector and the rest, with what sat in RAM, in GB.",
                 [clock(samples[i][0]) for i in picks], series, kind="line", unit=" GB", value_label="GB")


def _figures(watch):
    """Per sample: claimed, .NET's collector, the heap with its gaps, the gaps, live objects and outside .NET (None when the
    runtime had not counted yet)."""
    times = [s[0] for s in watch.samples]
    private = [s[1] for s in watch.samples]
    heap = [watch.counter_at(dd.HEAP_SIZE, t) for t in times]
    committed = [watch.counter_at(dd.HEAP_COMMITTED, t) for t in times]
    gaps = [watch.counter_at(dd.HEAP_FRAGMENTATION, t) for t in times]
    live = [h - g if h is not None and g is not None else None for h, g in zip(heap, gaps)]
    outside = [p - c if c is not None else None for p, c in zip(private, committed)]
    return private, committed, heap, gaps, live, outside


def _number(value):
    return None if value is None else int(round(value))


def status(where, text=None, now=None):
    """A running or kept watch as it stands, light enough to read every few seconds: its state, its latest figures, its
    timeline so far, the owner's marks, and the watches kept. Returns (report, data)."""
    now = time.time() if now is None else now
    report = Report("rimworld-perf: memory watch status")
    data = {"state": "none", "watch": None, "most_mark": MAX_MARK, "kept": _kept_rows(where, now)}
    if not kept(where):
        report.lines.append("No memory watch is kept yet.")
        return report, data
    folder = find(where, text, prefer_running=True, now=now)
    watched = Watch(folder)
    meta, samples = watched.meta, watched.samples
    found = state(folder, now, meta)
    counters = meta.get("counters") == "True"
    started = float(meta.get("started") or 0)
    seconds = int(float(meta.get("minutes") or 0) * 60)
    last = samples[-1][0] if samples else started
    data.update({"state": found, "watch": folder.name, "label": meta.get("label") or "", "started": started,
                 "minutes": float(meta.get("minutes") or 0), "every": float(meta.get("every") or DEFAULT_EVERY),
                 "seconds": seconds, "elapsed": int(max(0, (now if found == RUNNING else last) - started)),
                 "counters": counters, "reason": meta.get("reason"), "samples": len(samples),
                 "marks": [{"t": t, "text": text} for t, kind, text in watched.events if kind == OWNER_MARK],
                 "saves": [{"t": t, "text": text} for t, kind, text in watched.events if kind == "save-loaded"],
                 "latest": None})
    title = f' ("{meta["label"]}")' if meta.get("label") else ""
    said = {RUNNING: f"**Watching**{title}: {data['elapsed'] // 60} of {seconds // 60} minutes, started {clock(started)}.",
            FINISHING: f"**Finishing**{title}: reading in the counters and the log.",
            ENDED: f"**Ended**{title}, {clock(started)} to {clock(last)}, because {meta.get('reason', 'it was cut off')}.",
            CUT_OFF: f"**Cut off**{title}: its watcher stopped at {clock(last)} without finishing (closed, ended by force, or "
                     "the computer slept). What it saw up to then is kept."}
    report.lines.append(said[found])
    if not samples:
        report.lines.append("No samples yet.")
        return report, data
    private, committed, heap, gaps, live, outside = _figures(watched)
    latest = {"t": last, "claimed": private[-1], "in_ram": samples[-1][2], "free_ram": samples[-1][3],
              "collector": _number(committed[-1]), "heap": _number(heap[-1]), "gaps": _number(gaps[-1]),
              "live": _number(live[-1]), "outside": _number(outside[-1])}
    data["latest"] = latest
    rows = [("Claimed by the game", size(private[-1]), signed(private[-1] - private[0])),
            ("In RAM", size(samples[-1][2]), signed(samples[-1][2] - samples[0][2]))]
    has_counted = committed[-1] is not None
    if has_counted:
        first = next(i for i, c in enumerate(committed) if c is not None)
        rows += [(".NET's collector holds", size(committed[-1]), signed(committed[-1] - committed[first])),
                 ("Outside .NET", size(outside[-1]), signed(outside[-1] - outside[first]))]
        if live[-1] is not None:
            rows.append(("Of .NET's heap, live objects", size(live[-1]), signed(live[-1] - (live[first] or 0))))
    elif counters and found == RUNNING:
        report.lines.append(".NET's figures have not arrived yet: they come as dotnet-counters writes them, and may come only "
                            "when the watch ends.")
    report.lines.append(f"Latest at {clock(last)}.")
    report.section("Now", Table(["Measure", "Now", "Since the start"], rows))
    report.section("So far", _chart(samples, committed, outside, has_counted, LIVE_POINTS, "Memory so far"))
    report.lines += _happened(watched.events, found == ENDED)
    return report, data


def _kept_rows(where, now):
    rows = []
    for folder in reversed(kept(where)[-KEPT_LISTED:]):
        meta = derived.read_meta(folder / DATABASE)
        rows.append({"watch": folder.name, "started": float(meta.get("started") or 0), "label": meta.get("label") or "",
                     "minutes": float(meta.get("minutes") or 0), "samples": int(meta.get("samples") or 0),
                     "state": state(folder, now, meta), "reason": meta.get("reason"), "counters": meta.get("counters") == "True"})
    return rows


def _map_sections(report, watch, committed, times, owner_map, top):
    first, last = watch.map_times[0], watch.map_times[-1]
    kinds = {pm.PRIVATE: "Private memory", pm.IMAGE: "Loaded code files", pm.MAPPED: "Mapped files"}
    a = {k: c for k, c in watch.rows("total", first)}
    b = {k: c for k, c in watch.rows("total", last)}
    rows = [(kinds[k], size(a.get(k, 0)), size(b.get(k, 0)), signed(b.get(k, 0) - a.get(k, 0))) for k in pm.KINDS]
    report.section(f"The memory map, {clock(first)} and {clock(last)}",
                   "Committed memory by kind, from the first and last of the memory maps.",
                   Table(["Kind", "First map", "Last map", "Change"], rows))
    sa = {c: (n, m) for c, n, m in watch.rows("size", first)}
    sb = {c: (n, m) for c, n, m in watch.rows("size", last)}
    rows = [(label, f"{sa.get(label, (0, 0))[0]:,}", f"{sb.get(label, (0, 0))[0]:,}", size(sa.get(label, (0, 0))[1]),
             size(sb.get(label, (0, 0))[1]), signed(sb.get(label, (0, 0))[1] - sa.get(label, (0, 0))[1]))
            for label, _ in pm.SIZE_CLASSES if sa.get(label, (0, 0))[0] or sb.get(label, (0, 0))[0]]
    report.section("Private memory by block size",
                   "Each block is one allocation of the game's, its runtime's, its engine's or a driver's, by the size reserved "
                   "for it. Many small blocks growing points to an allocator handing out more and more; one large block "
                   "growing is one heap.",
                   Table(["Block size", "Blocks, first", "Blocks, last", "Committed, first", "Committed, last", "Change"], rows))
    at = bisect_right(times, last) - 1
    heap_now = committed[at] if at >= 0 else None
    blocks_a = {base: (c, s) for base, c, s in watch.rows("block", first)}
    blocks_b = {base: (c, s) for base, c, s in watch.rows("block", last)}
    keys = sorted(set(blocks_a) | set(blocks_b),
                  key=lambda k: (-abs(blocks_b.get(k, (0, 0))[0] - blocks_a.get(k, (0, 0))[0]), -blocks_b.get(k, (0, 0))[0], k))
    rows = []
    for base in keys[:top]:
        ca, cb = blocks_a.get(base, (0, 0))[0], blocks_b.get(base, (0, 0))[0]
        whole = (blocks_b.get(base) or blocks_a.get(base))[1]
        name = ".NET's heap (its size matches the collector's figure)" if heap_now and abs(cb - heap_now) <= HEAP_MATCH * heap_now else ""
        rows.append((f"0x{base:x}", size(whole), size(ca) if base in blocks_a else "-", size(cb) if base in blocks_b else "-",
                     signed(cb - ca), name))
    rest_a, rest_b = (watch.rows("rest", first) or [(0,)])[0][0], (watch.rows("rest", last) or [(0,)])[0][0]
    report.section("The private blocks that changed most",
                   Table(["Block", "Reserved", "First map", "Last map", "Change", "What it is"], rows, len(keys)),
                   f"Smaller blocks beyond the {pm.BLOCKS_KEPT} largest of each map: {size(rest_a)}, then {size(rest_b)} "
                   f"({signed(rest_b - rest_a)}).")
    fa = {(k, n): c for k, n, c in watch.rows("file", first)}
    fb = {(k, n): c for k, n, c in watch.rows("file", last)}
    keys = sorted(set(fa) | set(fb), key=lambda k: (-fb.get(k, 0), k))
    rows = []
    for kind, name in keys[:top]:
        stem = name.rsplit(".", 1)[0] if name.lower().endswith((".dll", ".exe")) else ""
        owner = owner_map.get(stem) if stem else None
        rows.append((name, "code" if kind == pm.IMAGE else "mapped", owner.name if owner and owner.kind != UNKNOWN else "",
                     size(fa.get((kind, name), 0)), size(fb.get((kind, name), 0)), signed(fb.get((kind, name), 0) - fa.get((kind, name), 0))))
    report.section("Loaded code and mapped files, largest last", Table(["File", "Kind", "Owner", "First map", "Last map", "Change"], rows, len(keys)))


def file_stems(watch):
    """The stems of every code file and mapped .dll the watch saw, for working out their owners."""
    return sorted({name.rsplit(".", 1)[0] for _, _, name, _ in watch._conn_rows["file"] if name.lower().endswith((".dll", ".exe"))})


def summary_rows(where):
    rows = []
    for folder in reversed(kept(where)):
        meta = derived.read_meta(folder / DATABASE)
        started = meta.get("started")
        when = datetime.fromtimestamp(float(started)).strftime("%Y-%m-%d %H:%M") if started else "?"
        rows.append((folder.name, when, meta.get("samples", "?"), meta.get("label", "")))
    return rows


def default_log(explicit=None, environ=None, settings_file=None):
    try:
        return Path(paths.logs_path(explicit, environ, settings_file)) / paths.LOG_NAME
    except Exception:  # noqa: BLE001 - a watch without log events beats no watch
        return None
