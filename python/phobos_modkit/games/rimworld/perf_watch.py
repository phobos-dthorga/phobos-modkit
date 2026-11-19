"""rimworld-perf's memory watch: how much memory the running game holds over minutes or hours, what kind, and when it jumps.

A heap snapshot shows one instant of .NET's heap and pauses the game to take it; a watch follows the whole program for as long
as it is asked, without pausing it, and says whether memory climbs steadily or in jumps, and what the log says happened at
each jump (a save loaded, a burst of errors). Every few seconds it takes:

- **from Windows** (`process_memory`): what the game has claimed (private bytes, the figure Task Manager's "commit size" shows)
  and what of it sits in RAM;
- **from the runtime** (Microsoft's dotnet-counters, attached once for the whole watch): the .NET heap after its last
  collection, what the collector holds from Windows, and the gaps inside the heap;
- and, every minute or so, **the memory map**: private memory by block and block size, loaded code files and mapped files.
  A block that keeps growing shows itself between two maps; the one whose size matches the collector's own figure is .NET's.

The difference between what the game claimed and what .NET's collector holds is everything else: the engine, graphics
drivers, native code, and .NET's own bookkeeping (compiled code, type data). Nothing in the game is changed or paused; the
counters attach once at the start, which can hitch the game for a moment.

Watches are kept in the kit's cache (`rimworld-memory/<start>-<label>/watch.sqlite`), outside every repository.
"""
from __future__ import annotations

from bisect import bisect_right
from contextlib import closing
from datetime import datetime
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
          "The .NET heap is as the runtime counted it after its last collection, so it lags the moment by up to one collection.",
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


def find(where, text):
    found = kept(where)
    if not found:
        raise WatchError(f"No memory watches kept in {where}. Start one with: rimworld-perf watch")
    if not text:
        return found[-1]
    wanted = text.lower()
    matches = [p for p in found if p.name.lower().startswith(wanted)] or \
              [p for p in found if wanted in (derived.read_meta(p / DATABASE).get("label") or "").lower()]
    if len(matches) != 1:
        raise WatchError(f'"{text}" matches {len(matches)} watches. Kept: ' + ", ".join(p.name for p in found) + ".")
    return matches[0]


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


def watch(pid, folder, minutes, every, map_every, counters_tool, label="", progress=None, clock_=time.time, sleep=time.sleep,
          popen=subprocess.Popen, process=pm.Process, log_file=None):
    """Watch a running program until `minutes` pass, it closes, or Ctrl+C; store everything in folder. Returns notes."""
    if not 1 <= minutes <= MAX_MINUTES:
        raise WatchError(f"--minutes must be between 1 and {MAX_MINUTES}.")
    if every < MIN_EVERY:
        raise WatchError(f"--every must be at least {MIN_EVERY} second.")
    if map_every and map_every < MIN_MAP_EVERY:
        raise WatchError(f"--map-every must be 0 (never) or at least {MIN_MAP_EVERY} seconds.")
    folder = Path(folder)
    notes, reason = [], "the time asked for ran out"
    start = clock_()
    end = start + minutes * 60
    seconds = int(minutes * 60)
    with closing(sqlite3.connect(folder / DATABASE)) as conn:
        conn.executescript(SCHEMA)
        derived.write_meta(conn, {"kit_version": __version__, "label": label or "", "pid": pid, "started": start,
                                  "minutes": minutes, "every": every, "map_every": map_every, "tools_version": dd.TOOLS_VERSION,
                                  "counters": bool(counters_tool)})
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
                    sleep(max(0.0, min(every - (clock_() - now), end - clock_())))
            except KeyboardInterrupt:
                reason = "stopped with Ctrl+C"
            if counting is not None:
                try:
                    counting.wait(timeout=STOP_SECONDS)
                except subprocess.TimeoutExpired:
                    counting.kill()
                    notes.append("dotnet-counters did not stop on time and was cut off; its figures up to then are kept.")
                except KeyboardInterrupt:
                    counting.kill()
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
        with closing(sqlite3.connect(self.folder / DATABASE)) as conn:
            self.samples = conn.execute("SELECT t, private, working_set, free_ram FROM sample ORDER BY t").fetchall()
            series = {}
            for t, name, tags, value in conn.execute("SELECT t, name, tags, value FROM counter ORDER BY t"):
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
    said = [f"{text} at {clock(t)}" for t, kind, text in picked if kind in ("save-loaded", "logging-stopped")]
    errors = sum(1 for e in picked if e[1] == "error")
    held = sum(1 for e in picked if e[1] == "engine-held")
    if errors:
        said.append(f"{errors:,} error{'s' if errors != 1 else ''} logged")
    if held:
        said.append(f"{held:,} engine allocation warnings")
    return "; ".join(said) or "nothing logged"


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
    report.lines.append(f"Watched the game for **{minutes:,.0f} minutes**{label}, {clock(times[0])} to {clock(times[-1])} on "
                        f"{datetime.fromtimestamp(times[0]).strftime('%Y-%m-%d')}: {len(samples):,} samples every "
                        f"{meta.get('every', '?')} s and {len(watch.map_times):,} memory maps. It ended because "
                        f"{meta.get('reason', 'it was cut off')}.")
    counters = watch.has_counters()
    report.lines.append(CAVEAT if meta.get("counters", str(counters)) == "True" else CAVEAT_ALONE)
    for note in (meta.get("notes") or "").splitlines():
        report.lines.append(note)
    private = [s[1] for s in samples]
    heap = [watch.counter_at(dd.HEAP_SIZE, t) for t in times]
    committed = [watch.counter_at(dd.HEAP_COMMITTED, t) for t in times]
    gaps = [watch.counter_at(dd.HEAP_FRAGMENTATION, t) for t in times]
    outside = [p - c if c is not None else None for p, c in zip(private, committed)]

    jumps = _jumps(samples)
    report.lines.append(_verdict(private, jumps))
    if counters and committed[-1] is not None:
        report.lines.append(f"At the end, .NET's collector held **{size(committed[-1])}** of the {size(private[-1])} the game "
                            f"had claimed, and everything outside .NET came to **{size(outside[-1])}**.")
    elif not counters:
        report.lines.append("No .NET figures were recorded, so memory cannot be split into .NET's and the rest.")

    rows = [_row("Claimed by the game (private bytes)", private, times),
            _row("In RAM (working set)", [s[2] for s in samples], times)]
    if counters:
        rows += [_row(".NET heap, live after the last collection", heap, times),
                 _row(".NET's collector holds from Windows", committed, times),
                 _row("Gaps inside the .NET heap", gaps, times),
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
                       f"Rises of {size(JUMP_SIZE)} or more within a minute, with what the log says from a minute before to a "
                       "minute after.",
                       Table(["When", "Claimed", ".NET's collector", "Outside .NET", "What the log says"], rows))

    step = max(1, -(-len(samples) // TIMELINE_POINTS))
    picks = list(range(0, len(samples), step))
    if picks[-1] != len(samples) - 1:
        picks.append(len(samples) - 1)
    series = [ChartSeries("Claimed", [round(private[i] / GB, 2) for i in picks], "accent")]
    if counters:
        series += [ChartSeries(".NET's collector", [round(committed[i] / GB, 2) if committed[i] is not None else None for i in picks], "comparison"),
                   ChartSeries("Outside .NET", [round(outside[i] / GB, 2) if outside[i] is not None else None for i in picks], "observed")]
    series.append(ChartSeries("In RAM", [round(samples[i][2] / GB, 2) for i in picks], "neutral"))
    report.section("Over time", Chart("Memory over the watch", "What the game claimed, split into .NET's collector and the rest, "
                                      "with what sat in RAM, in GB.", [clock(times[i]) for i in picks], series, kind="line",
                                      unit=" GB", value_label="GB"))
    saves = [(t, text) for t, kind, text in watch.events if kind == "save-loaded"]
    if saves:
        report.lines.append("Saves loaded during the watch: " + "; ".join(f"{text} at {clock(t)}" for t, text in saves) + ".")

    if watch.map_times:
        _map_sections(report, watch, committed, times, owner_map, top)
    report.section("What a watch cannot say", Bullets(LIMITS))
    return report


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
