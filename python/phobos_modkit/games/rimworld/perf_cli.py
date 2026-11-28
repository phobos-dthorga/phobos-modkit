"""rimworld-perf: where a running RimWorld spends its time and memory, by mod, by method and by part of the main loop, from outside.

    rimworld-perf record                     record the running game for 30 seconds, then report it
    rimworld-perf record --seconds 60 --label "many wounded"
    rimworld-perf report                     the newest recording again (or name one: 20261117-1845, or its label)
    rimworld-perf mod "Combat Extended"      one mod in a recording: its busiest methods and where its time went
    rimworld-perf callers GenTypes.IsSealedWithCache   what calls one method, the mods above it, and where its time goes
    rimworld-perf compare                    the last two recordings, as shares of the main thread and of ticking
    rimworld-perf trend                      our own mods' share of ticking in every recording kept, and where it rose
    rimworld-perf reindex --all              rebuild recordings indexed before 1.151.0 from their kept traces, with timelines
    rimworld-perf list                       every recording and snapshot kept
    rimworld-perf pack                       pack the large files of recordings and heaps kept before 1.149.0 (--apply)
    rimworld-perf unpack 20261117-1900       write a recording's trace or a heap's .gcdump out plain, for PerfView
    rimworld-perf index FILE.speedscope.json [--counters FILE.json]   a trace recorded by hand
    rimworld-perf stack --label "frozen"     a frozen or stuck game: every thread's stack, 3 times, 2 s apart
    rimworld-perf stack-report               the newest stack snapshots again
    rimworld-perf heap --label "day 40"      what holds the game's memory, by type and by mod (a snapshot; --gcdump the old way)
    rimworld-perf heap-report                the newest heap again
    rimworld-perf heap-compare               the last two heaps: who grew
    rimworld-perf watch --minutes 120 --label "reloads"   the game's memory over time: average or bursts, .NET's or not
    rimworld-perf watch-report               the newest watch again (or name one)
    rimworld-perf watch-status               a running watch as it stands (for a program to read every few seconds)
    rimworld-perf watch-mark "reloading now"  your own words beside the running watch's figures
    rimworld-perf watch-stop                 end the running watch early, from another console
    rimworld-perf look --label "day 40"      inside the running game from a snapshot: every object by type and by mod
    rimworld-perf look-kind Verse.Pawn --open   one kind's objects, each described (--match TEXT, --largest)
    rimworld-perf look-why System.Xml.XmlDocument   why a kind is still in memory: paths from a root to its largest
    rimworld-perf look-check --checks config/checks.json   a repository's live checks, all from one snapshot
    rimworld-perf look-serve                 hold a snapshot and answer JSON requests a line at a time (for a program's page)

Recording attaches Microsoft's dotnet-trace and dotnet-counters to the game through its .NET diagnostics pipe; stack uses
dotnet-stack and heap dotnet-gcdump the same way, and watch dotnet-counters with Windows' own figures. Nothing is installed in the
game and nothing of it is changed, but heap forces a full garbage collection, which pauses the game until it is done. The first use of each tool installs it (a pinned version) into the
kit's build folder, which needs the .NET SDK. Everything is kept in the kit's cache, outside every repository. A recording's
trace and a heap's .gcdump cannot be made again but are seldom opened, so they are kept packed with zstd once read (1.149.0; the
owner's choice by card, 28 Nov 2026): a trace came out 11 times smaller. unpack gives one back plain, for PerfView or Visual Studio.

look takes a Windows snapshot of the game instead (a pause of about half a second) and reads it with the kit's heap reader: every
object, with no limit on how many, but garbage not yet collected included. It reads the game's own memory-reading library from its
install folder, and nothing else; nothing is written to the game.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from contextlib import closing
from datetime import datetime, timedelta, timezone
import fnmatch
import json
from pathlib import Path
import re
import shutil
import sqlite3
import subprocess
import sys
import time

from ... import __version__
from ... import cache as derived
from ... import dotnet_diagnostics as dd
from ... import packed
from ...dotnet_snapshots import SnapshotError
from ... import process_memory as pm
from ...manifest import READS, RUNS, WRITES
from ...progress import Progress
from ...report import (Chart, ChartSeries, Fact, Finding, Findings, Ref, Report, Table, envelope_text, finding_json,
                       home_redactor, keep, render_markdown)
from ...sampling import (CPU, ENGINE, GAME, MOD, NATIVE, NO_MOD, UNKNOWN, Recording, SamplingError, Share, index_events,
                         index_speedscope, method_matcher, modules,
                         read_counters, write_counters, write_owners)
from ... import dotnet_events
from ... import history
from ... import heap_reader as hreader
from ...nettrace import NettraceError
from ... import checks as check_engine
from ... import checks_live
from . import installs
from . import look
from . import perf
from . import perf_snapshots as snap
from . import perf_watch as pw

EXIT_OK, EXIT_FAILED, EXIT_USAGE = 0, 1, 2
REPORTS = ("report", "record", "index", "reindex", "mod", "callers", "compare", "trend", "costs", "list", "stack", "stack-report", "heap", "heap-report", "heap-compare",
           "watch", "watch-report", "watch-status", "watch-stop", "watch-mark", "look", "look-kind", "look-why", "look-serve",
           "look-check", "look-thaw", "pack", "unpack")
FREEZE_HELP = ("freeze the game and read it in place instead of a snapshot, when Windows has no room to copy it (error 1450); it "
               f"stands still while it is read, {hreader.FREEZE_SECONDS} s at most")
MEMORY_SURFACE = "memory-watch"     # D'thorga Companion's Memory page finds the watch's commands by this, never by the game's name
PERFORMANCE_SURFACE = "performance" # and its Performance page finds recordings' reports by this (1.152.0)
SUMMARY_NAME = "summary.json"       # beside each recording's index: its figures, findings and mods' shares, for reading at once
SUMMARY_FORMAT = 2                  # 2 (1.153.0): methods, versions, settings prints, errors logged
SUMMARY_METHODS = 100               # the busiest methods a summary keeps, for a code map's badges
CACHE_FOLDER = "rimworld-perf"
INDEX_NAME = "index.sqlite"
DEFAULT_SECONDS = 30
MIN_SECONDS, MAX_SECONDS = 5, 600
PAUSED_SHARE = 0.01                 # ticking under 1 % of the main thread: the game was paused or not in play
ATTRIBUTION = ("**Caused by** is the innermost mod on the stack: a mod's code calling the game's counts for the mod, and a Harmony "
               "prefix or postfix counts for the mod that wrote it. Work a transpiler adds inside a game method counts as the game's.")
CAVEAT = ("A recording shows what the game did while it ran: what was on screen, the game speed and pausing all change it. It "
          "measures; it is not an in-game test of whether anything works.")
SHARE_NOTE = ("Compared as shares, not milliseconds: a faster game ticks more often, so a mod's milliseconds per second can rise "
              "when the game speeds up.")


class PerfError(RuntimeError):
    pass


def _parser():
    common = argparse.ArgumentParser(add_help=False)
    w = common.add_argument_group("where things are")
    w.add_argument("--cache", help="where recordings are kept (else PHOBOS_MODKIT_CACHE, the settings file, the temp folder)")
    w.add_argument("--game", help="the RimWorld folder (else RIMWORLD_PATH, the settings file, Steam's default)")
    w.add_argument("--workshop", help="the Workshop content folder (else RIMWORLD_WORKSHOP_PATH, settings, beside the game)")
    w.add_argument("--config", help="the folder holding ModsConfig.xml (else RIMWORLD_CONFIG_PATH, settings, default)")
    w.add_argument("--settings", help="a JSON settings file with the paths above")
    o = common.add_argument_group("output")
    o.add_argument("--top", type=int, default=15, help="rows per table (default 15)")
    o.add_argument("--json", action="store_true", help="print JSON instead of Markdown")
    o.add_argument("--no-redact", action="store_true", help="show the home folder instead of ~")
    p = argparse.ArgumentParser(prog="rimworld-perf", description=__doc__.split("\n\n")[0],
                                formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__.split("\n\n", 1)[1])
    sub = p.add_subparsers(dest="report", metavar="report")
    r = sub.add_parser("report", parents=[common], help="a recording: phases, who caused the time, busiest methods, garbage collection")
    r.add_argument("recording", nargs="?", help="a recording's ID (its start is enough) or label; the newest when left out")
    c = sub.add_parser("record", parents=[common], help="record the running game, then report it")
    c.add_argument("--seconds", type=int, default=DEFAULT_SECONDS, help=f"how long to record (default {DEFAULT_SECONDS})")
    c.add_argument("--label", help="a few words to find the recording by, such as what was happening")
    c.add_argument("--pid", type=int, help="the game's process ID, when more than one RimWorld runs")
    c.add_argument("--keep-speedscope", action="store_true", help="keep the converted trace beside the index (large)")
    c.add_argument("--alloc", action="store_true",
                   help="also sample allocations (about every 100 KB): who allocates what; the runtime writes more events")
    i = sub.add_parser("index", parents=[common], help="index a speedscope file recorded by hand with dotnet-trace")
    i.add_argument("file", help="a .speedscope.json file from dotnet-trace")
    i.add_argument("--counters", help="dotnet-counters' JSON file from the same time")
    i.add_argument("--label", help="a few words to find the recording by")
    ri = sub.add_parser("reindex", parents=[common], help="rebuild a recording's index from its kept trace, with its timeline")
    ri.add_argument("recording", nargs="?", help="a recording's ID or label; the newest when left out")
    ri.add_argument("--all", action="store_true", help="every recording kept")
    m = sub.add_parser("mod", parents=[common], help="one mod in a recording")
    m.add_argument("name", help="a mod's name; * and ? are wildcards")
    m.add_argument("recording", nargs="?", help="a recording's ID or label; the newest when left out")
    cl = sub.add_parser("callers", parents=[common], help="how the stacks running one method reach it, and the mods above it")
    cl.add_argument("method", help="Namespace.Type.Method, or its end (GenTypes.IsSealedWithCache); * and ? are wildcards")
    cl.add_argument("recording", nargs="?", help="a recording's ID or label; the newest when left out")
    cl.add_argument("--all-threads", action="store_true", help="every thread, not only the main one")
    k = sub.add_parser("compare", parents=[common], help="two recordings, as shares of the main thread and of ticking")
    k.add_argument("first", nargs="?", help="the earlier recording; the second newest when both are left out")
    k.add_argument("second", nargs="?", help="the later recording; the newest when both are left out")
    tr = sub.add_parser("trend", parents=[common], help="some mods' share of ticking in every recording kept, and where it rose")
    tr.add_argument("name", nargs="?", default=perf.OWN_MODS,
                    help=f"the mods to follow, by name; * and ? are wildcards (default {perf.OWN_MODS!r}: our own)")
    co = sub.add_parser("costs", parents=[common], help="each mod's share in the newest recording against the earlier ones")
    co.add_argument("name", nargs="?", default=perf.OWN_MODS,
                    help=f"the mods counted as ours, by name; * and ? are wildcards (default {perf.OWN_MODS!r})")
    sub.add_parser("list", parents=[common], help="every recording and snapshot kept")
    pk = sub.add_parser("pack", parents=[common], help="pack the large files of recordings and heaps kept plain (before 1.149.0)")
    pk.add_argument("--apply", action="store_true", help="pack them; without this, only say which and how large")
    up = sub.add_parser("unpack", parents=[common], help="write a recording's trace or a heap's .gcdump out plain, for PerfView")
    up.add_argument("name", help="a recording's or a heap's ID (its start is enough) or label")
    s = sub.add_parser("stack", parents=[common], help="a frozen or stuck game: every thread's stack, a few times")
    s.add_argument("--times", type=int, default=snap.DEFAULT_TIMES, help=f"how many snapshots (default {snap.DEFAULT_TIMES})")
    s.add_argument("--every", type=float, default=snap.DEFAULT_EVERY, help=f"seconds between them (default {snap.DEFAULT_EVERY:g})")
    s.add_argument("--label", help="a few words to find the snapshots by, such as what the game was doing")
    s.add_argument("--pid", type=int, help="the game's process ID, when more than one RimWorld runs")
    s.add_argument("--frames", type=int, default=snap.DEFAULT_FRAMES, help=f"frames of the main thread shown (default {snap.DEFAULT_FRAMES})")
    sr = sub.add_parser("stack-report", parents=[common], help="stack snapshots taken earlier")
    sr.add_argument("snapshot", nargs="?", help="its ID (its start is enough) or label; the newest when left out")
    sr.add_argument("--frames", type=int, default=snap.DEFAULT_FRAMES, help=f"frames of the main thread shown (default {snap.DEFAULT_FRAMES})")
    h = sub.add_parser("heap", parents=[common], help="what holds the game's memory, by type and by mod (a snapshot, as look)")
    h.add_argument("--label", help="a few words to find the heap by, such as the in-game day")
    h.add_argument("--pid", type=int, help="the game's process ID, when more than one RimWorld runs")
    h.add_argument("--gcdump", action="store_true",
                   help="the heap as dotnet-gcdump takes it instead: a full garbage collection first, which pauses the game until done")
    h.add_argument("--freeze", action="store_true", help=FREEZE_HELP)
    hr = sub.add_parser("heap-report", parents=[common], help="a heap taken earlier")
    hr.add_argument("snapshot", nargs="?", help="its ID (its start is enough) or label; the newest when left out")
    hc = sub.add_parser("heap-compare", parents=[common], help="two heaps: who grew")
    hc.add_argument("first", nargs="?", help="the earlier heap; the second newest when both are left out")
    hc.add_argument("second", nargs="?", help="the later heap; the newest when both are left out")
    wt = sub.add_parser("watch", parents=[common], help="the game's memory over time, without pausing it; Ctrl+C ends it early")
    wt.add_argument("--minutes", type=float, default=pw.DEFAULT_MINUTES, help=f"how long to watch (default {pw.DEFAULT_MINUTES})")
    wt.add_argument("--every", type=float, default=pw.DEFAULT_EVERY, help=f"seconds between samples (default {pw.DEFAULT_EVERY})")
    wt.add_argument("--map-every", type=float, default=pw.DEFAULT_MAP_EVERY,
                    help=f"seconds between memory maps, 0 for none (default {pw.DEFAULT_MAP_EVERY}; Windows only)")
    wt.add_argument("--no-counters", action="store_true", help="leave .NET's counters out: nothing attaches to the game at all")
    wt.add_argument("--label", help="a few words to find the watch by, such as what you plan to do")
    wt.add_argument("--pid", type=int, help="the game's process ID, when more than one RimWorld runs")
    wt.add_argument("--logs", help="the folder holding Player.log (else RIMWORLD_LOGS_PATH, settings, default)")
    wr = sub.add_parser("watch-report", parents=[common], help="a memory watch taken earlier")
    wr.add_argument("watch", nargs="?", help="its ID (its start is enough) or label; the newest when left out")
    ws = sub.add_parser("watch-status", parents=[common], help="a running or kept watch as it stands, light enough to read every few seconds")
    ws.add_argument("watch", nargs="?", help="its ID or label; the one running, else the newest, when left out")
    wp = sub.add_parser("watch-stop", parents=[common], help="end a running watch early, from another console or a program")
    wp.add_argument("watch", nargs="?", help="its ID or label; the one running when left out")
    wm = sub.add_parser("watch-mark", parents=[common], help="put a few words of your own beside a watch's figures")
    wm.add_argument("text", help='what you are doing or about to do, such as "reloading now" (at most 200 characters)')
    wm.add_argument("--watch", help="its ID or label; the one running, else the newest, when left out")
    wm.add_argument("--at", type=float, help="the moment it names, in seconds since 1970; now when left out")
    lk = sub.add_parser("look", parents=[common], help="inside the running game from a snapshot: every object by type and by mod")
    lk.add_argument("--label", help="a few words to find it by, such as the in-game day")
    lk.add_argument("--pid", type=int, help="the game's process ID, when more than one RimWorld runs")
    lk.add_argument("--freeze", action="store_true", help=FREEZE_HELP)
    lt = sub.add_parser("look-kind", parents=[common], help="one kind's objects in the running game, each described")
    lt.add_argument("type", help="the type's full name, as look lists it (Verse.Pawn)")
    lt.add_argument("--match", help="only objects whose description holds this text (a pawn's name, a defName)")
    lt.add_argument("--largest", action="store_true", help="largest first")
    lt.add_argument("--open", action="store_true", help="also show the first one with every value it holds")
    lt.add_argument("--pid", type=int, help="the game's process ID, when more than one RimWorld runs")
    lt.add_argument("--freeze", action="store_true", help=FREEZE_HELP)
    lw = sub.add_parser("look-why", parents=[common], help="why a kind is still in memory: paths from a root to its largest objects")
    lw.add_argument("type", help="the type's full name, as look lists it (System.Xml.XmlDocument)")
    lw.add_argument("--sample", type=int, default=hreader.WHY_SAMPLE,
                    help=f"paths to show, each to a different object (default {hreader.WHY_SAMPLE})")
    lw.add_argument("--pid", type=int, help="the game's process ID, when more than one RimWorld runs")
    lc = sub.add_parser("look-check", parents=[common], help="a repository's live checks, all answered from one snapshot of the "
                                                             "running game: states its rules say should never be")
    lc.add_argument("--checks", dest="checks_file",
                    help="the check file (default: config/checks.json here, else in RimWorld's repositories on the games list)")
    lc.add_argument("--check", help="only checks whose id matches; * and ? are wildcards")
    lc.add_argument("--pid", type=int, help="the game's process ID, when more than one RimWorld runs")
    lc.add_argument("--freeze", action="store_true", help=FREEZE_HELP)
    lh = sub.add_parser("look-thaw", parents=[common], help="let the game run on if a look inside left it frozen (it stopped "
                                                            "before it could); changes nothing when the game is running")
    lh.add_argument("--pid", type=int, help="the game's process ID, when more than one RimWorld runs")
    lv = sub.add_parser("look-serve", parents=[common], help="hold a snapshot and answer JSON requests a line at a time, for a program")
    lv.add_argument("--label", help="a few words to keep its overview by")
    lv.add_argument("--pid", type=int, help="the game's process ID, when more than one RimWorld runs")
    lv.add_argument("--limit-seconds", type=int, default=hreader.LIMIT_SECONDS,
                    help=f"let the snapshot go after this long (default {hreader.LIMIT_SECONDS}: it costs memory while held)")
    return p


# ---- Numbers ----

def ms(value):
    return f"{value:,.0f}"


def pct(part, whole):
    return f"{100 * part / whole:.1f}%" if whole else "0.0%"


def points(value):
    return f"{value:+.1f}"


def size(value):
    """Bytes in the largest unit that keeps a figure of at least 1."""
    for unit, scale in (("GB", 1e9), ("MB", 1e6), ("KB", 1e3)):
        if abs(value) >= scale:
            return f"{value / scale:,.1f} {unit}"
    return f"{value:,.0f} bytes"


# ---- Recordings on disk ----

def recordings_root(args, environ, settings_file):
    return derived.folder(CACHE_FOLDER, args.cache, environ, settings_file)


def recordings(root):
    root = Path(root)
    if not root.is_dir():
        return []
    return sorted(p for p in root.iterdir() if (p / INDEX_NAME).is_file())


def find(root, text):
    found = recordings(root)
    if not found:
        raise PerfError(f"No recordings in {root}. Make one with: rimworld-perf record")
    if not text:
        return found[-1]
    wanted = text.lower()
    matches = [p for p in found if p.name.lower().startswith(wanted)]
    if not matches:
        matches = [p for p in found if wanted in (derived.read_meta(p / INDEX_NAME).get("label") or "").lower()]
    if len(matches) != 1:
        raise PerfError(f'"{text}" matches {len(matches)} recordings. Recordings: ' + ", ".join(p.name for p in found) + ".")
    return matches[0]


def new_folder(root, label, now):
    slug = re.sub(r"[^a-z0-9]+", "-", (label or "").lower()).strip("-")[:40]
    name = now.strftime("%Y%m%d-%H%M%S") + (f"-{slug}" if slug else "")
    folder = Path(root) / name
    if folder.exists():
        raise PerfError(f"A recording named {name} already exists; wait a second and try again.")
    return folder


def _owners(names, args, environ, settings_file):
    return perf.module_owners(names, args.game, args.workshop, args.config, environ, settings_file)


def add_events(index, trace_file):
    """The runtime's lock waits and allocations from a recording's .nettrace into its index; a note when they cannot be read."""
    if trace_file is None or not Path(trace_file).is_file():
        return []
    try:
        index_events(trace_file, index)
    except (NettraceError, OSError, ValueError) as error:
        return [f"The runtime's own events (lock waits, allocations) could not be read from the trace: {error}"]
    return []


def build_index(folder, speedscope, counters_file, meta, args, environ, settings_file, trace_file=None):
    """Index a trace into folder, add the runtime's events, record who owns each module against today's mod list, and add the
    counters. Returns notes."""
    index = Path(folder) / INDEX_NAME
    index_speedscope(speedscope, index, meta)
    event_notes = add_events(index, trace_file)
    owners, notes = _owners(modules(index), args, environ, settings_file)
    notes = event_notes + notes
    write_owners(index, owners)
    write_counters(index, read_counters(counters_file) if counters_file else {})
    packages = perf.mod_packages(args.game, args.workshop, args.config, environ, settings_file)
    used = {o.name for o in owners.values() if o.kind == MOD}
    with closing(sqlite3.connect(index)) as conn:
        derived.write_meta(conn, {"notes": "\n".join(notes), "mods_matched": sum(1 for owner in owners.values() if owner.kind == MOD),
                                  "mod_packages": json.dumps({n: i for n, i in sorted(packages.items()) if n in used})})
        conn.commit()
    return notes


# ---- What a row or a finding is about (1.152.0) ----

def packages_of(rec):
    """{mod name: package ID} kept when the recording was made; {} for one from before 1.152.0."""
    try:
        found = json.loads(rec.meta.get("mod_packages") or "{}")
    except ValueError:
        return {}
    return found if isinstance(found, dict) else {}


def mod_ref(owner, packages=None):
    """A Ref to a mod, or None for anything that is not one."""
    if owner is None or owner == NO_MOD or owner.kind != MOD:
        return None
    return Ref("mod", owner.name, package=(packages or {}).get(owner.name, ""))


def method_ref(method, owner=None):
    """A Ref to a method, with who owns it; None for no method."""
    if not method:
        return None
    return Ref("method", method, of=owner.name if owner else "", of_kind=owner.kind if owner else "")


def row_refs(**columns):
    """{column position: Ref} for one row, from c0=..., c3=...; Nones left out."""
    return {int(key[1:]): ref for key, ref in columns.items() if ref is not None}


# ---- Reports ----

def _owner_rows(shares, whole, top, packages=None):
    ordered = sorted(shares.items(), key=lambda kv: (-kv[1].total, kv[0].name))
    rows = [(o.name, o.kind, ms(s.total), pct(s.total, whole), ms(s.cpu), ms(s.native)) for o, s in ordered[:top]]
    return rows, len(ordered), [row_refs(c0=mod_ref(o, packages)) for o, _ in ordered[:top]]


OWNER_HEADERS = ["Caused by", "Kind", "ms", "Share", "Running managed code (ms)", "In native code or waiting (ms)"]


def _method_rows(methods, whole, top, show_owner=True, packages=None):
    ordered = sorted(methods.items(), key=lambda kv: (-kv[1].total, kv[0][0]))
    rows, refs = [], []
    for (method, owner, patched), share in ordered[:top]:
        name = method + (" (patched)" if patched else "")
        rows.append((name, owner.name, ms(share.total), pct(share.total, whole)) if show_owner else (name, ms(share.total), pct(share.total, whole)))
        refs.append(row_refs(c0=method_ref(method, owner), c1=mod_ref(owner, packages) if show_owner else None))
    return rows, len(ordered), refs


def _counter_rows(rec):
    rows = []
    pause = rec.counter("dotnet.gc.pause.time")
    if pause:
        rows.append(("Time paused for garbage collection", f"{100 * pause[0]:.1f}% of the time", f"worst second {100 * pause[1]:.1f}%"))
    for tags, (mean, worst, _) in sorted(rec.counters_named("dotnet.gc.collections").items()):
        generation = tags.split("=", 1)[-1] if tags else "all"
        rows.append((f"Collections, {generation}", f"{mean:.1f} a second", f"most in a second {worst:.0f}"))
    allocated = rec.counter("dotnet.gc.heap.total_allocated")
    if allocated:
        rows.append(("Memory allocated", f"{size(allocated[0])} a second", f"most in a second {size(allocated[1])}"))
    jit = rec.counter("dotnet.jit.compilation.time")
    if jit:
        rows.append(("Compiling code (JIT)", f"{100 * jit[0]:.1f}% of the time", f"worst second {100 * jit[1]:.1f}%"))
    locks = rec.counter("dotnet.monitor.lock_contentions")
    if locks:
        rows.append(("Threads waiting on a lock", f"{locks[0]:,.0f} a second", f"most in a second {locks[1]:,.0f}"))
    cpu = rec.counter("dotnet.process.cpu.time")
    if cpu:
        rows.append(("Processor cores busy", f"{cpu[0]:.1f} on average", f"most {cpu[1]:.1f}"))
    memory = rec.counter("dotnet.process.memory.working_set")
    if memory:
        rows.append(("Memory in use (working set)", f"{size(memory[0])} on average", f"most {size(memory[1])}"))
    return rows


HOT_SPOT_SHARE = 0.02               # a hot spot is listed when it took at least 2 % of ticking
HOT_SPOT_NOTE = ("Time in one game or engine method, or in .NET code it called, put back together. **Caused by** gives this time "
                 "to whichever mod is innermost above it, a little to each, so a slow game method many mods call shows nowhere "
                 "else. `rimworld-perf callers METHOD` follows one further.")
NO_MOD_TEXT = "no mod on the stack"
START_TEXT = "(the start of the thread)"
MODS_SHOWN = 3


def _who(owner):
    return NO_MOD_TEXT if owner == NO_MOD else owner.name


def _largest(shares, whole):
    """'method (share)' of the largest entry of {(method, Owner): Share}, or '-'."""
    if not shares:
        return "-"
    (method, _), share = max(shares.items(), key=lambda kv: (kv[1].total, kv[0][0]))
    return f"{method or START_TEXT} ({pct(share.total, whole)})"


def _mods_text(shares):
    ordered = sorted(shares.items(), key=lambda kv: (-kv[1].total, kv[0].name))
    parts = [f"{_who(o)} {ms(s.total)} ms" for o, s in ordered[:MODS_SHOWN]]
    if len(ordered) > MODS_SHOWN:
        parts.append(f"{len(ordered) - MODS_SHOWN} more")
    return ", ".join(parts)


def _top_mod(shares):
    """The Owner with the most time in {Owner: Share}, leaving out "no mod"; None when there is none."""
    mods = [(o, s) for o, s in shares.items() if o != NO_MOD and o.kind == MOD]
    return max(mods, key=lambda kv: (kv[1].total, kv[0].name))[0] if mods else None


def _listed_hot_spots(spots, whole):
    return sorted(((key, spot) for key, spot in spots.items() if spot.total.total >= HOT_SPOT_SHARE * whole),
                  key=lambda kv: (-kv[1].total.total, kv[0][0]))


def _hot_spot_rows(spots, whole, top, packages=None):
    listed = _listed_hot_spots(spots, whole)
    rows, refs = [], []
    for (method, owner), spot in listed[:top]:
        total = spot.total.total
        rows.append((method, owner.name, ms(total), pct(total, whole), _largest(spot.leaf, total), _largest(spot.caller, total),
                     _mods_text(spot.mods)))
        refs.append(row_refs(c0=method_ref(method, owner), c6=mod_ref(_top_mod(spot.mods), packages)))
    return rows, len(listed), refs


def _site_rows(shares, whole, top, packages=None):
    ordered = sorted(shares.items(), key=lambda kv: (-kv[1].total, kv[0][0]))
    return ([(method or START_TEXT, owner.name if owner else "-", ms(s.total), pct(s.total, whole))
             for (method, owner), s in ordered[:top]], len(ordered),
            [row_refs(c0=method_ref(method, owner), c1=mod_ref(owner, packages)) for (method, owner), _ in ordered[:top]])


def _mod_rows(shares, whole, top, packages=None):
    ordered = sorted(shares.items(), key=lambda kv: (-kv[1].total, kv[0].name))
    return ([(_who(o), ms(s.total), pct(s.total, whole)) for o, s in ordered[:top]], len(ordered),
            [row_refs(c0=mod_ref(o, packages)) for o, _ in ordered[:top]])


def callers_report(rec, folder, pattern, top, all_threads=False):
    """callers: how the stacks running one method reach it, and where its time goes."""
    matches = method_matcher(pattern)
    main = rec.main_thread()
    threads = sorted(rec.threads) if all_threads else [main]
    by_thread = {t: rec.callers(rec.thread_samples(t), matches) for t in threads}
    found = rec.callers([s for t in threads for s in rec.thread_samples(t)], matches)
    total = found.total.total
    if not total:
        raise PerfError(f'No stack in {folder.name} ran a method matching "{pattern}"' +
                        (" on the main thread; add --all-threads to look at every thread." if not all_threads else "."))
    report = Report(f"rimworld-perf: callers of {pattern} in {folder.name}", [CAVEAT])
    packages = packages_of(rec)
    where = "on all threads" if all_threads else f"on the main thread ({pct(total, rec.duration_ms(main))} of it)"
    report.lines.append(f"**{ms(total)} ms {where}**, {ms(found.total.cpu)} ms of it running managed code. A method on a stack "
                        "twice counts from its outermost call.")
    if len(found.targets) > 1:
        rows, count, refs = _site_rows(found.targets, total, top, packages)
        report.section("The methods the name matched", Table(["Method", "Owner", "ms", "Share"], rows, count, refs=refs))
    if not all_threads:
        phases, _ = perf.phases()
        cache, parts = {}, defaultdict(Share)
        for node, share in found.nodes.items():
            parts[rec.phase_of(node, phases, cache)].add(CPU, share.cpu)
            parts[rec.phase_of(node, phases, cache)].add(NATIVE, share.native)
        report.section("By part of the game loop", Table(["Part", "ms", "Share"], [
            (name or "other (outside the named parts)", ms(s.total), pct(s.total, total))
            for name, s in sorted(parts.items(), key=lambda kv: (-kv[1].total, kv[0] or "~"))]))
    else:
        rows = [(rec.thread_label(t), ms(c.total.total), pct(c.total.total, total))
                for t, c in sorted(by_thread.items(), key=lambda kv: (-kv[1].total.total, kv[0])) if c.total.total]
        report.section("By thread", Table(["Thread", "ms", "Share"], rows[:top], len(rows)))
    for title, shares in (("Called directly by", found.direct),
                          ("The first game, engine or mod method above it (passing over .NET and libraries)", found.owned)):
        rows, count, refs = _site_rows(shares, total, top, packages)
        report.section(title, Table(["Method", "Owner", "ms", "Share"], rows, count, refs=refs))
    rows, count, refs = _mod_rows(found.inner, total, top, packages)
    report.section("The mods that lead to it (the innermost mod above it)", Table(["Mod", "ms", "Share"], rows, count, refs=refs))
    rows, count, refs = _mod_rows(found.outer, total, top, packages)
    report.section("The mods whose code it starts from (the outermost mod above it)",
                   "The first mod on the stack from the thread's start decides when and how often; the innermost does the work.",
                   Table(["Mod", "ms", "Share"], rows, count, refs=refs))
    rows, count, refs = _site_rows(found.leaf, total, top, packages)
    report.section("Where its time goes (where the thread was, at or below it)",
                   Table(["Method", "Owner", "ms", "Share"], rows, count, refs=refs))
    if rec.has_timeline and not all_threads:
        width = window_width(rec.duration_ms(main) / 1000)
        windows = rec.windows(main, width * 1000, lambda node: rec._call_site(node, matches) is not None)
        report.section("Over time", f"Its time on the main thread in each {width} s.", Table(["Window", "ms", "Share of the window"], [
            (_window_text(start, width), ms(shares[True].total if True in shares else 0.0),
             pct(shares[True].total if True in shares else 0.0, sum(s.total for s in shares.values()))) for start, shares in windows]))
    return report


def reindex_one(folder, tool, run):
    """Rebuilds one recording's index from its kept trace, keeping its owners (the mod list of its day), counters and meta.
    Returns what happened, in words."""
    index = Path(folder) / INDEX_NAME
    plain = Path(folder) / dd.TRACE_FILE
    unpacked = False
    if not plain.is_file():
        if not packed.packed_of(plain).is_file():
            return "no trace kept, so it cannot be rebuilt"
        packed.unpack(packed.packed_of(plain), plain)
        unpacked = True
    fresh = index.with_name("index.new.sqlite")
    speedscope = None
    try:
        speedscope = dd.convert(plain, tool, run)
        meta = {k: v for k, v in derived.read_meta(index).items() if k != "index_format"}
        meta.update(reindexed_by=__version__)
        threads = index_speedscope(speedscope, fresh, meta)
        columns = ", ".join(c for c in ("name", "tags", "mean", "max", "samples", "min") if c in _counter_columns(index))
        with closing(sqlite3.connect(fresh)) as conn:
            conn.execute("ATTACH DATABASE ? AS old", (str(index),))
            conn.execute("INSERT INTO owner SELECT module, kind, name FROM old.owner")
            conn.execute(f"INSERT INTO counter ({columns}) SELECT {columns} FROM old.counter")
            conn.commit()
            conn.execute("DETACH DATABASE old")
        add_events(fresh, plain)
        derived.remove(index)
        fresh.replace(index)
    finally:
        derived.remove(fresh)
        if speedscope is not None:
            derived.remove(speedscope)
        if unpacked:
            derived.remove(plain)
    return f"rebuilt: {threads} threads, with its timeline"


def _counter_columns(index):
    with closing(derived.open_read_only(index)) as conn:
        return {r[1] for r in conn.execute("PRAGMA table_info(counter)")}


def reindex_report(args, root, environ, run):
    targets = recordings(root) if args.all else [find(root, args.recording)]
    if not targets:
        raise PerfError(f"No recordings in {root}.")
    found, _ = dd.ensure([dd.TRACE], environ, run)
    rows = [(folder.name, reindex_one(folder, found[dd.TRACE], run)) for folder in targets]
    report = Report(f"rimworld-perf: {len(rows)} recordings rebuilt" if len(rows) != 1 else f"rimworld-perf: {rows[0][0]} rebuilt",
                    ["Each index was made again from the recording's kept trace with dotnet-trace's own converter, keeping who owned "
                     "each module on the day it was recorded, its counters and its label. The trace itself is untouched."])
    report.section("Recordings", Table(["Recording", "Result"], rows))
    return report, {"rebuilt": [name for name, said in rows if said.startswith("rebuilt")]}


STRETCH_MIN_MS = 50                 # an unbroken stretch is listed from 50 ms: three frames at 60 a second
SPIKE_TIMES, SPIKE_POINTS = 2.0, 10.0   # a window's busiest mod is marked at twice its average share and 10 points over it
NO_TIMELINE = ("This recording was indexed before 1.151.0, so it keeps no timeline: `rimworld-perf reindex {name}` rebuilds it "
               "from its kept trace in a few seconds, with the tables over time.")
STRETCH_NOTE = ("How long a method stayed on the main thread's stack with no sample outside it: the main thread did nothing else "
                "for at least that long, so a stretch over a frame's length is a hitch. Back-to-back calls with no sample between "
                "them look like one stretch. Methods on the stack for a fifth of the time or more are the loop itself and left "
                "out; listed from {min} ms.")


def window_width(seconds):
    """Seconds a row of the tables over time covers: about a dozen to twenty rows."""
    return 5 if seconds <= 90 else 15 if seconds <= 300 else 30


def _window_text(start_ms, width_s):
    return f"{start_ms / 1000:g}-{start_ms / 1000 + width_s:g} s"


TIMELINE_MODS = 4                   # mods drawn by name in the chart over time; the rest are "other mods"


def timeline_sections(rec, report, main, top, found=None, packages=None):
    """The tables over time: the main loop by window, and the longest unbroken stretches. `found` gathers findings."""
    phases, ticking = perf.phases()
    whole = rec.duration_ms(main)
    width = window_width(whole / 1000)
    cache = {}
    windows = rec.windows(main, width * 1000, lambda node: (rec.phase_of(node, phases, cache), rec.label(node)))
    overall = defaultdict(float)
    tick_total = 0.0
    for _, shares in windows:
        for (phase, owner), share in shares.items():
            if phase == ticking:
                tick_total += share.total
                if owner.kind == MOD:
                    overall[owner] += share.total
    named = [o for o, _ in sorted(overall.items(), key=lambda kv: (-kv[1], kv[0].name))[:TIMELINE_MODS]]
    rows, refs, categories, drawn = [], [], [], defaultdict(list)
    for start, shares in windows:
        span = sum(s.total for s in shares.values())
        if span < width * 1000 / 2:
            continue                       # the recording's last few moments: too short to say anything
        ticks = sum(s.total for (phase, _), s in shares.items() if phase == ticking)
        mods = defaultdict(float)
        for (phase, owner), share in shares.items():
            if phase == ticking and owner.kind == MOD:
                mods[owner] += share.total
        busiest, note, top_owner = "-", "", None
        if mods and ticks:
            owner, value = max(mods.items(), key=lambda kv: (kv[1], kv[0].name))
            here, average = 100 * value / ticks, 100 * overall[owner] / tick_total if tick_total else 0.0
            busiest, top_owner = f"{owner.name} ({here:.0f}% of its ticking)", owner
            if here >= SPIKE_TIMES * average and here - average >= SPIKE_POINTS:
                note = f"**{here / average:.1f} times its average**" if average else "**only here**"
        rows.append((_window_text(start, width), pct(ticks, span), busiest, note))
        refs.append(row_refs(c2=mod_ref(top_owner, packages)))
        categories.append(_window_text(start, width))
        for owner in named:
            drawn[owner.name].append(round(100 * mods.get(owner, 0.0) / span, 1))
        drawn["Other mods"].append(round(100 * sum(v for o, v in mods.items() if o not in named) / span, 1))
        drawn["The game, the engine and .NET"].append(round(100 * (ticks - sum(mods.values())) / span, 1))
    blocks = [f"Each row is {width} s of the main thread: its share spent ticking, and the mod that caused the most of that "
              "ticking. A mark means that mod took at least twice its usual share there: work it does now and then."]
    if categories:
        roles = ["accent", "comparison", "observed", "risk"]
        series = [ChartSeries(owner.name, drawn[owner.name], roles[i % len(roles)]) for i, owner in enumerate(named)]
        series += [ChartSeries("Other mods", drawn["Other mods"], "success"),
                   ChartSeries("The game, the engine and .NET", drawn["The game, the engine and .NET"], "neutral")]
        blocks.append(Chart("Ticking over time, by who caused it",
                            f"Each bar is {width} s of the main thread: the share of it spent ticking, split by the mod that "
                            f"caused it (the {len(named)} busiest by name), the rest of the mods, and the game itself.",
                            categories, series, unit="%", value_label="Share of the main thread", stacked=True))
    blocks.append(Table(["Window", "Ticking", "Busiest mod while ticking", "Note"], rows, refs=refs))
    report.section("Over time: the main thread, window by window", *blocks)
    stretches = rec.stretches(main, lambda method, owner: owner.kind in (MOD, GAME, ENGINE))
    listed = rec.innermost_stretches(stretches, STRETCH_MIN_MS)
    if listed:
        rows, refs = [], []
        for (method, owner), (longest, began, count, _), above in listed[:top]:
            text, cause = _stall_text(rec, main, method, began, longest)
            rows.append((method, owner.name, ms(longest), f"{began / 1000:.1f}", f"{count:,}", f"{above:,}", text))
            refs.append(row_refs(c0=method_ref(method, owner), c1=mod_ref(owner, packages), c6=mod_ref(cause, packages)))
        report.section("The longest unbroken stretches on the main thread", STRETCH_NOTE.format(min=STRETCH_MIN_MS),
                       Table(["Method (the innermost of the stall)", "Owner", "Longest (ms)", "At (s into the recording)",
                              "Times on the stack", "Methods above it in the same stall", "Caused by, inside the stall"],
                             rows, len(listed), refs=refs))
        (method, owner), (longest, began, _, _), _ = listed[0]
        if found is not None and longest >= FINDING_STALL_MS:
            cause = refs[0].get(6)
            found.append((longest * STALL_POINTS_PER_MS, Finding(
                f"The main thread stalled for {longest:,.0f} ms in {method}, {began / 1000:.1f} s in"
                + (f"; caused by {rows[0][6]}" if rows[0][6] != "-" else "") + ".",
                "risk" if longest >= FINDING_STALL_RISK_MS else "observed", longest, "ms",
                [r for r in (method_ref(method, owner), cause) if r is not None])))


def _stall_text(rec, thread, method, began, longest):
    """(who caused a stall, in words; the Owner of the mod that caused most of it, or None)."""
    node = _node_of(rec, thread, method, began)
    if node is None:
        return "-", None
    shares = rec.stall_owners(thread, node, began, longest)
    whole = sum(shares.values())
    ordered = sorted(shares.items(), key=lambda kv: (-kv[1], kv[0].name))[:MODS_SHOWN]
    cause = next((o for o, _ in ordered if o.kind == MOD and o != NO_MOD), None)
    return ", ".join(f"{o.name} {pct(v, whole)}" for o, v in ordered), cause


def _node_of(rec, thread, method, at_ms):
    """The stack's node where method was on the thread at a moment: the first span from then that holds it."""
    for start, end, node, _ in rec.spans(thread):
        if end <= at_ms:
            continue
        for n in rec.nodes_up(node):
            if rec.method_at(n)[0] == method:
                return n
        return None
    return None


WAIT_NOTE = ("Every wait the runtime reported, not a sample: **waited in** is the first game, engine or mod method above the "
             "wait, the code that took the lock. **Held by** is the thread holding the lock as the wait began and, from its "
             "timeline, the first game, engine or mod method it was running then.")
NO_WAITS = ("Lock waits were not recorded: this recording is from before 1.151.0. `record` again to see which code waits on a "
            "lock and which thread holds it.")
ALLOCATION_NOTE = ("Sampled by the runtime about every 100 KB: each sample stands for the bytes allocated since the last one, put "
                   "down to the type and the stack of the allocation that crossed the line, so large objects stand out more than "
                   "they should. Estimates over many samples, not counts.")


def _held_by(rec, wait, roles, role_cache, holders=None):
    """Who held the lock a wait began on, in words; with `holders`, each text's method is kept there as a ref (1.153.0)."""
    owner_thread = rec.thread_of_os(wait[6]) if wait[6] else None
    if owner_thread is None:
        return "not said" if not wait[6] else f"thread {wait[6]}"
    if owner_thread not in role_cache:
        role_cache[owner_thread] = rec.thread_role(owner_thread, roles) or rec.thread_label(owner_thread)
    method, owner = rec.owned_at(rec.node_at(owner_thread, wait[2]))
    text = role_cache[owner_thread] + (f", in {method}" if method else "")
    if holders is not None and method:
        holders.setdefault(text, method_ref(method, owner))
    return text


def wait_sections(rec, report, main, top, roles, found=None, packages=None):
    """Lock waits, from the runtime's own events (recorded from 1.151.0). `found` gathers findings."""
    if not rec.waits:
        if rec.meta.get("lock_events") == "yes":
            report.section("Lock waits", "No thread waited on a lock while recording.")
        elif rec.counter("dotnet.monitor.lock_contentions"):
            report.lines.append(NO_WAITS)
        return
    total = sum(w[3] for w in rec.waits)
    mine = [w for w in rec.waits if w[0] == main]
    main_ms = sum(w[3] for w in mine)
    blocks = [f"**{len(rec.waits):,} waits on locks, {ms(total)} ms in all; the main thread waited {len(mine):,} times, "
              f"{ms(main_ms)} ms ({pct(main_ms, rec.duration_ms(main))} of it)**, the longest {max(w[3] for w in rec.waits):,.1f} ms.",
              WAIT_NOTE]
    rows_by = defaultdict(lambda: [0, 0.0, 0.0, defaultdict(int), defaultdict(float)])
    role_cache, holders = {}, {}
    for wait in mine:
        method, owner = rec.owned_at(wait[7])
        row = rows_by[(method, owner)]
        row[0] += 1
        row[1] += wait[3]
        row[2] = max(row[2], wait[3])
        row[3][_held_by(rec, wait, roles, role_cache, holders)] += 1
        mod = rec.label(wait[7]) if wait[7] >= 0 else NO_MOD
        row[4][mod if mod.kind == MOD else NO_MOD] += wait[3]
    rows, refs = [], []
    for (method, owner), (count, spent, longest, held, mods) in sorted(rows_by.items(), key=lambda kv: (-kv[1][1], kv[0][0])):
        holder, times = max(held.items(), key=lambda kv: (kv[1], kv[0]))
        ordered = sorted(mods.items(), key=lambda kv: (-kv[1], kv[0].name))[:MODS_SHOWN]
        rows.append((method or "(no game or mod code on its stack)", owner.name if owner else "-", f"{count:,}", ms(spent),
                     f"{longest:,.1f}", f"{holder} ({100 * times / count:.0f}% of its waits)",
                     ", ".join(f"{_who(o)} {ms(v)} ms" for o, v in ordered)))
        lead = next((o for o, _ in ordered if o != NO_MOD and o.kind == MOD), None)
        refs.append(row_refs(c0=method_ref(method, owner), c1=mod_ref(owner, packages), c5=holders.get(holder),
                             c6=mod_ref(lead, packages)))
    if rows:
        blocks.append(Table(["The main thread waited in", "Owner", "Waits", "ms", "Longest (ms)", "Mostly held by",
                             "Mods that lead to it"], rows[:top], len(rows), refs=refs[:top]))
        share = main_ms / rec.duration_ms(main) if rec.duration_ms(main) else 0.0
        if found is not None and share >= FINDING_WAIT_SHARE:
            first = rows[0]
            found.append((100 * share, Finding(
                f"The main thread spent {pct(main_ms, rec.duration_ms(main))} of its time waiting on locks, most in {first[0]} "
                f"(held mostly by {first[5].split(' (')[0]}).",
                "risk" if share >= FINDING_WAIT_RISK else "observed", round(100 * share, 1), "%",
                [r for r in (refs[0].get(0), refs[0].get(6)) if r is not None])))
    others = defaultdict(lambda: [0, 0.0])
    for wait in rec.waits:
        if wait[0] != main:
            key = wait[0] if wait[0] >= 0 else None
            others[key][0] += 1
            others[key][1] += wait[3]
    if others:
        rows = [(rec.thread_label(t) if t is not None else "a thread not sampled",
                 (rec.thread_role(t, roles) or "-") if t is not None else "-", f"{n:,}", ms(v))
                for t, (n, v) in sorted(others.items(), key=lambda kv: (-kv[1][1], str(kv[0])))]
        blocks.append(Table(["Other threads that waited", "What it is", "Waits", "ms"], rows[:top], len(rows)))
    report.section("Lock waits", *blocks)


def _mb(value):
    return f"{value / 1e6:,.1f}"


def allocation_sections(rec, report, main, top, packages=None):
    """Allocations sampled by the runtime (record --alloc, 1.151.0). Returns (the type allocated most, its MB a second), or None."""
    if not rec.allocations:
        if rec.meta.get("allocation_events") == "yes":
            report.section("Allocations, sampled", "The runtime reported no allocation samples while recording.")
        return None
    seconds = rec.duration_ms(main) / 1000 or 1.0
    total = sum(a[4] for a in rec.allocations)
    main_bytes = sum(a[4] for a in rec.allocations if a[0] == main)
    blocks = [f"**About {_mb(total)} MB allocated, {_mb(total / seconds)} MB a second; the main thread "
              f"{_mb(main_bytes / seconds)} MB a second**, from {len(rec.allocations):,} samples.", ALLOCATION_NOTE]
    by_mod, by_type, by_method = defaultdict(float), defaultdict(lambda: [0.0, defaultdict(float)]), defaultdict(float)
    for _, _, _, type_name, amount, node in rec.allocations:
        mod = rec.label(node) if node >= 0 else NO_MOD
        by_mod[mod if mod.kind == MOD else NO_MOD] += amount
        method, owner = rec.owned_at(node)
        by_type[type_name][0] += amount
        by_type[type_name][1][method] += amount
        by_method[(method, owner)] += amount
    ordered = sorted(by_mod.items(), key=lambda kv: (-kv[1], kv[0].name))
    rows = [(_who(o), _mb(v), pct(v, total)) for o, v in ordered]
    blocks.append(Table(["Allocated by (the innermost mod on the stack)", "MB", "Share"], rows[:top], len(rows),
                        refs=[row_refs(c0=mod_ref(o, packages)) for o, _ in ordered[:top]]))
    rows, refs = [], []
    for type_name, (amount, methods) in sorted(by_type.items(), key=lambda kv: (-kv[1][0], kv[0])):
        method = max(methods.items(), key=lambda kv: (kv[1], kv[0]))[0]
        rows.append((type_name, _mb(amount), pct(amount, total), method or "-"))
        refs.append(row_refs(c0=Ref("type", type_name) if type_name else None, c3=method_ref(method)))
    blocks.append(Table(["Type", "MB", "Share", "Mostly allocated in"], rows[:top], len(rows), refs=refs[:top]))
    heaviest = (rows[0][0], sorted(by_type.items(), key=lambda kv: (-kv[1][0], kv[0]))[0][1][0] / seconds / 1e6) if rows else None
    ordered = sorted(by_method.items(), key=lambda kv: (-kv[1], kv[0][0]))
    rows = [(method or "(no game or mod code on its stack)", owner.name if owner else "-", _mb(v), pct(v, total))
            for (method, owner), v in ordered]
    blocks.append(Table(["Allocated in (the first game, engine or mod method above it)", "Owner", "MB", "Share"],
                        rows[:top], len(rows),
                        refs=[row_refs(c0=method_ref(m, o), c1=mod_ref(o, packages)) for (m, o), _ in ordered[:top]]))
    report.section("Allocations, sampled", *blocks)
    return heaviest


PATCHED_NOTE = ("**Mods seen running inside it** are those whose code ran directly inside the rewritten method in this recording: "
                "its prefixes and postfixes among them. **A transpiler rewrites the method itself**, so its work counts as the "
                "game's and no sample can tell it apart: transpilers are named from the patch list (`rimworld-patches`), which "
                "reads today's mods, not the recording's day's.")
NO_PATCH_LIST = "The patch list has not been made yet: run `rimworld-patches` once to name transpilers here."


def patch_lookup_for(args, environ, settings_file):
    """A function naming the transpilers and counting the other patches on a method from rimworld-patches' index, read only;
    None when the index has not been made."""
    from . import patches
    index = derived.folder(patches.CACHE_FOLDER, args.cache, environ, settings_file) / patches.INDEX_NAME
    if not index.is_file():
        return None
    try:
        with closing(derived.open_read_only(index)) as conn:
            rows = conn.execute("SELECT p.target_type, p.target_member, p.kind, o.mod FROM patches p JOIN owners o ON o.path = p.path "
                                "ORDER BY o.position").fetchall()
    except sqlite3.Error:
        return None
    known = defaultdict(list)
    for target_type, member, kind, mod in rows:
        known[(target_type, member)].append((kind, mod))

    def lookup(method):
        target_type, _, member = method.rpartition(".")
        found = known.get((target_type, member), []) + (known.get((target_type, member[4:]), [])
                                                        if member.startswith(("get_", "set_")) else [])
        transpilers = sorted({mod for kind, mod in found if kind == "transpiler"})
        others = len([1 for kind, _ in found if kind != "transpiler"])
        text = ", ".join(transpilers) if transpilers else "none listed"
        return text + (f"; {others} other patch{'es' if others != 1 else ''} listed" if others else "")
    return lookup


def _patched_rows(rec, samples, whole, top, patch_lookup, packages=None):
    patched = rec.inclusive_methods(samples, lambda o, p: p)
    runners = rec.patch_runners(samples)
    ordered = sorted(patched.items(), key=lambda kv: (-kv[1].total, kv[0][0]))
    rows, refs = [], []
    for (method, owner, _), share in ordered[:top]:
        seen = sorted(runners.get(method, {}).items(), key=lambda kv: (-kv[1].total, kv[0].name))
        seen_text = ", ".join(o.name for o, _ in seen[:MODS_SHOWN]) + (f", {len(seen) - MODS_SHOWN} more" if len(seen) > MODS_SHOWN else "")
        rows.append((method + " (patched)", ms(share.total), pct(share.total, whole), seen_text or "-",
                     patch_lookup(method) if patch_lookup else "-"))
        refs.append(row_refs(c0=method_ref(method, owner), c3=mod_ref(seen[0][0], packages) if seen else None))
    return rows, len(ordered), refs


NO_GAME_COUNTERS = ("The game's own figures (ticks and frames a second) were not recorded: they need D'thorga Framework 0.380.0 or "
                    "newer running, and rimworld-perf 1.151.0 or newer recording.")


def ticks_per_second(rec):
    found = rec.counter("rimworld.ticks")
    return found[0] if found else None


def ms_per_tick(rec, tick_ms, main):
    """Main-thread milliseconds of ticking a tick, from the game's own tick count; None without it."""
    rate = ticks_per_second(rec)
    ticks = rate * rec.duration_ms(main) / 1000 if rate else 0
    return tick_ms / ticks if ticks else None


def context_text(meta):
    parts = []
    if meta.get("game_version"):
        parts.append(f"RimWorld {meta['game_version']}")
    if meta.get("save"):
        parts.append(f'save "{meta["save"]}"' + (f" (loaded with {meta['mods_loaded']} mods)" if meta.get("mods_loaded") else ""))
    if meta.get("mods_active"):
        parts.append(f"{meta['mods_active']} mods active")
    return "Context: " + ", ".join(parts) + "." if parts else ""


def game_section(rec, report, main, tick_ms):
    """The game's own figures from D'thorga Framework's meter, when it ran (1.151.0)."""
    rate = rec.counter("rimworld.ticks")
    if not rate:
        report.lines.append(NO_GAME_COUNTERS)
        return
    rows = [("Ticks a second", f"{rate[0]:,.0f}", f"slowest second {rec.counter_low('rimworld.ticks') or 0:,.0f}")]
    frames = rec.counter("rimworld.frames")
    if frames:
        rows.append(("Frames a second", f"{frames[0]:,.0f}", f"slowest second {rec.counter_low('rimworld.frames') or 0:,.0f}"))
    worst = rec.counter("rimworld.frame.worst")
    if worst:
        rows.append(("Each second's longest frame", f"{worst[0]:,.1f} ms on average", f"longest {worst[1]:,.1f} ms"))
    speed = rec.counter("rimworld.speed")
    if speed:
        rows.append(("Game speed", perf.SPEEDS.get(round(speed[0]), f"{speed[0]:.1f}"), f"fastest {perf.SPEEDS.get(round(speed[1]), '?')}"))
    pawns = rec.counter("rimworld.pawns")
    if pawns:
        rows.append(("Spawned pawns", f"{pawns[0]:,.0f}", f"most {pawns[1]:,.0f}"))
    maps = rec.counter("rimworld.maps")
    if maps:
        rows.append(("Maps", f"{maps[0]:,.0f}", f"most {maps[1]:,.0f}"))
    per_tick = ms_per_tick(rec, tick_ms, main)
    if per_tick is not None:
        rows.append(("The main thread's ticking, a tick", f"{per_tick:,.2f} ms", "-"))
    report.section("The game, as it counts itself", "From D'thorga Framework's own meter, read once a second beside the runtime's "
                   "counters: what the player feels, and what makes two recordings fair to compare.",
                   Table(["Measure", "Average", "Worst or most"], rows))


LOG_ERRORS_FINDING = 10             # errors logged while recording are a finding from 10, ranked a point for each 10, to 30
LOG_LEVELS = ("FATAL", "ERROR", "EXCEPTION")


def logged_during(rec):
    """The log's messages kept with the recording (1.153.0), or None for a recording made before."""
    try:
        found = json.loads(rec.meta.get("log_during") or "null")
    except ValueError:
        return None
    return found if isinstance(found, list) else None


def log_section(rec, report, top, found=None):
    """What the game logged while recording (1.153.0): an error storm costs time too. Each message links to the Logs page."""
    messages = logged_during(rec)
    if messages is None:
        return
    if not messages:
        report.section("The log while recording", "The game logged nothing while recording.")
        return
    errors = sum(m["count"] for m in messages if m["level"] in LOG_LEVELS)
    rows = [(m["level"], m["signature"], f"{m['count']:,}") for m in messages[:top]]
    refs = [row_refs(c1=Ref("signature", m["id"])) for m in messages[:top]]
    report.section("The log while recording",
                   f"{sum(m['count'] for m in messages):,} messages, {errors:,} of them errors, while recording; most severe "
                   "first. The Logs page has each in full, while the game has not restarted since.",
                   Table(["Level", "Message", "Times"], rows, len(messages), refs=refs))
    if found is not None and errors >= LOG_ERRORS_FINDING:
        first = next(m for m in messages if m["level"] in LOG_LEVELS)
        found.append((min(errors / 10, 30), Finding(
            f"The game logged {errors:,} errors while recording, the most often: {first['signature'][:120]}",
            "risk", errors, "", [Ref("signature", first["id"])])))


FINDINGS_SHOWN = 5                  # findings at the top of a report, most important first
FINDING_MOD_SHARE = 0.05            # a mod is a finding from 5 % of ticking
FINDING_HOT_SPOT = 0.05             # a hot spot from 5 % of ticking; a risk from a quarter
FINDING_HOT_SPOT_RISK = 0.25
FINDING_WAIT_SHARE = 0.02           # lock waits from 2 % of the main thread; a risk from 10 %
FINDING_WAIT_RISK = 0.10
FINDING_STALL_MS = 100              # a stall from 100 ms (six frames at 60 a second); a risk from 250 ms
FINDING_STALL_RISK_MS = 250
STALL_POINTS_PER_MS = 0.1           # ranked as if each 10 ms of one stall were 1 % of the main thread
FINDING_CORE_SHARE = 0.5            # another thread from half of one core, ranked at a quarter of its share: it slows the game
THREAD_POINTS = 0.25                # only when cores run short, so the main thread's own findings come first
FINDING_GC_PAUSE = 0.02             # garbage collection from 2 % of the time paused
NOT_RUNNING_POINTS = 1000.0         # "the game hardly ran" outranks everything
OWNERS_CHARTED = 8


def _sentence(text):
    """Text with its first letter made a capital, the rest left as it is."""
    return text[:1].upper() + text[1:]


def _finding_list(found):
    """The FINDINGS_SHOWN most important of [(rank, Finding)]."""
    return [f for _, f in sorted(found, key=lambda pair: -pair[0])[:FINDINGS_SHOWN]]


def report_facts(rec, main, tick_ms):
    """The strip above a report: the recording, and the game's own figures where its meter ran."""
    meta = rec.meta
    facts = [Fact("Recorded", str(meta.get("recorded_at", "?")))]
    seconds = meta.get("seconds") or rec.duration_ms(main) / 1000
    facts.append(Fact("Length", f"{float(seconds):.0f} s" if float(seconds) >= 10 else f"{float(seconds):.1f} s"))
    if meta.get("label"):
        facts.append(Fact("Label", meta["label"]))
    ticks = rec.counter("rimworld.ticks")
    if ticks:
        facts.append(Fact("Ticks a second", f"{ticks[0]:,.0f}"))
    frames = rec.counter("rimworld.frames")
    if frames:
        facts.append(Fact("Frames a second", f"{frames[0]:,.0f}"))
    per_tick = ms_per_tick(rec, tick_ms, main)
    if per_tick is not None:
        facts.append(Fact("Ticking, a tick", f"{per_tick:,.2f} ms"))
    worst = rec.counter("rimworld.frame.worst")
    if worst:
        facts.append(Fact("Longest frame", f"{worst[1]:,.0f} ms"))
    speed = rec.counter("rimworld.speed")
    if speed:
        facts.append(Fact("Speed", perf.SPEEDS.get(round(speed[0]), f"{speed[0]:.1f}")))
    for label, name in (("Pawns", "rimworld.pawns"), ("Maps", "rimworld.maps")):
        found = rec.counter(name)
        if found:
            facts.append(Fact(label, f"{found[0]:,.0f}"))
    for label, key in (("Save", "save"), ("RimWorld", "game_version"), ("Mods active", "mods_active")):
        if meta.get(key):
            facts.append(Fact(label, str(meta[key])))
    return facts


def summary_report(rec, folder, top, patch_lookup=None, keep_summary=None):
    """The whole report of one recording. When `keep_summary` is a dict, it is filled with what the summary file keeps."""
    phases, ticking = perf.phases()
    main = rec.main_thread()
    samples = rec.thread_samples(main)
    whole = rec.duration_ms(main)
    meta = rec.meta
    report = Report(f"rimworld-perf: {folder.name}")
    label = f' ("{meta["label"]}")' if meta.get("label") else ""
    roles = perf.thread_roles()
    packages = packages_of(rec)
    found = []
    report.lines.append(f"Recorded {float(meta.get('seconds') or whole / 1000):.0f} s{label} at {meta.get('recorded_at', '?')}: "
                        f"{len(rec.threads)} threads; the main thread is {rec.thread_label(main)}"
                        f"{' (' + role + ')' if (role := rec.thread_role(main, roles)) else ''}, the busiest running managed code.")
    report.lines.append(CAVEAT)
    said = context_text(meta)
    if said:
        report.lines.append(said)
    by_phase = rec.by_phase(samples, phases)
    tick_share = by_phase.get(ticking)
    if tick_share is None or tick_share.total < PAUSED_SHARE * whole:
        report.lines.append("**The simulation hardly ran in this recording: was the game paused, or on the main menu?** Record "
                            "again with the game running at the speed that feels slow.")
        found.append((NOT_RUNNING_POINTS, Finding("The game hardly ticked while recording: it was paused or on the main menu, so "
                                                  "nothing below says what slows play.", "risk")))
    for note in (meta.get("notes") or "").splitlines():
        report.lines.append(note)
    phase_rows = [(name or "other (outside the named parts)", ms(s.total), pct(s.total, whole), pct(s.cpu, s.total) if s.total else "-")
                  for name, s in sorted(by_phase.items(), key=lambda kv: (-kv[1].total, kv[0] or "~"))]
    report.section("The main thread, by part of the game loop", Table(["Part", "ms", "Share of the main thread", "Of it, running managed code"], phase_rows))
    mod_shares, method_shares = {}, {}
    if tick_share and tick_share.total:
        tick_samples = rec.in_phase(samples, phases, ticking)
        by_owner = rec.by_owner(tick_samples)
        mod_shares = {o.name: s.total / tick_share.total for o, s in by_owner.items() if o.kind == MOD and o != NO_MOD}
        rows, total, refs = _owner_rows(by_owner, tick_share.total, top, packages)
        charted = sorted(by_owner.items(), key=lambda kv: (-kv[1].total, kv[0].name))[:OWNERS_CHARTED]
        report.section("Ticking: who caused the time", ATTRIBUTION,
                       Chart("Who caused the ticking time", f"The {len(charted)} largest shares of ticking, by who caused it.",
                             [o.name for o, _ in charted],
                             [ChartSeries("Share of ticking", [round(100 * s.total / tick_share.total, 1) for _, s in charted])],
                             unit="%", value_label="Share of ticking"),
                       Table(OWNER_HEADERS, rows, total, refs=refs))
        busiest = _top_mod(by_owner)
        if busiest is not None and by_owner[busiest].total >= FINDING_MOD_SHARE * tick_share.total:
            share = by_owner[busiest].total / tick_share.total
            found.append((100 * share * tick_share.total / whole, Finding(
                f"{busiest.name} caused {100 * share:.0f}% of ticking, the most of any mod.", "observed", round(100 * share, 1),
                "%", [mod_ref(busiest, packages)])))
        calls = sorted(rec.mod_calls(tick_samples).items(), key=lambda kv: (-kv[1].total, kv[0][0].name, kv[0][1].name))
        if calls:
            report.section("Ticking: one mod's code running another's",
                           "Time a mod caused while called from another mod's code. The first mod decides when and how often; "
                           "the second does the work. Look at both before blaming either.",
                           Table(["Called from", "Ran in", "ms", "Share of ticking"],
                                 [(o.name, i.name, ms(s.total), pct(s.total, tick_share.total)) for (o, i), s in calls[:top]], len(calls)))
        mod_methods = rec.inclusive_methods(tick_samples, lambda o, p: o.kind == MOD)
        for (method, owner, _), share in sorted(mod_methods.items(), key=lambda kv: -kv[1].total)[:SUMMARY_METHODS]:
            method_shares[method] = {"share": round(share.total / tick_share.total, 5), "of": owner.name, "of_kind": owner.kind}
        rows, total, refs = _method_rows(mod_methods, tick_share.total, top, packages=packages)
        report.section("Ticking: mods' busiest methods (including what they call)",
                       Table(["Method", "Mod", "ms", "Share of ticking"], rows, total, refs=refs))
        rows, total, refs = _method_rows(rec.self_methods(tick_samples), tick_share.total, top, packages=packages)
        report.section("Ticking: where the thread was when sampled",
                       Table(["Method", "Owner", "ms", "Share of ticking"], rows, total, refs=refs))
        spots = rec.hot_spots(tick_samples)
        for (method, owner), spot in _listed_hot_spots(spots, tick_share.total)[:SUMMARY_METHODS]:
            method_shares.setdefault(method, {"share": round(spot.total.total / tick_share.total, 5), "of": owner.name,
                                              "of_kind": owner.kind})
        rows, total, refs = _hot_spot_rows(spots, tick_share.total, top, packages)
        if rows:
            report.section("Ticking: hot spots in the game's and the engine's code, and the mods that lead to them", HOT_SPOT_NOTE,
                           Table(["Game or engine method", "Owner", "ms", "Share of ticking", "Mostly in", "Called from",
                                  "Mods that lead to it"], rows, total, refs=refs))
            (method, owner), spot = _listed_hot_spots(spots, tick_share.total)[0]
            share = spot.total.total / tick_share.total
            if share >= FINDING_HOT_SPOT:
                found.append((100 * share * tick_share.total / whole, Finding(
                    f"{method} ({owner.name}) took {100 * share:.0f}% of ticking; the mods that lead to it: {_mods_text(spot.mods)}.",
                    "risk" if share >= FINDING_HOT_SPOT_RISK else "observed", round(100 * share, 1), "%",
                    [r for r in (method_ref(method, owner), mod_ref(_top_mod(spot.mods), packages)) if r is not None])))
        rows, total, refs = _patched_rows(rec, tick_samples, tick_share.total, top, patch_lookup, packages)
        if rows:
            report.section("Ticking: game methods other mods have patched (including what they call)",
                           PATCHED_NOTE + ("" if patch_lookup else " " + NO_PATCH_LIST),
                           Table(["Method", "ms", "Share of ticking", "Mods seen running inside it",
                                  "Transpilers (the patch list, as of today)"], rows, total, refs=refs))
    rows, total, refs = _owner_rows(rec.by_owner(samples), whole, top, packages)
    report.section("The whole main thread: who caused the time", Table(OWNER_HEADERS, rows, total, refs=refs))
    if rec.has_timeline:
        timeline_sections(rec, report, main, top, found, packages)
    else:
        report.lines.append(NO_TIMELINE.format(name=folder.name))
    tick_ms = tick_share.total if tick_share else 0.0
    game_section(rec, report, main, tick_ms)
    report.facts = report_facts(rec, main, tick_ms)
    wait_sections(rec, report, main, top, roles, found, packages)
    heaviest = allocation_sections(rec, report, main, top, packages)
    log_section(rec, report, top, found)
    pause = rec.counter("dotnet.gc.pause.time")
    if pause and pause[0] >= FINDING_GC_PAUSE:
        text = f"Garbage collection paused the game {100 * pause[0]:.1f}% of the time"
        found.append((100 * pause[0], Finding(
            text + (f"; the type allocated most was {heaviest[0]}, {heaviest[1]:,.0f} MB a second." if heaviest else
                    ". `record --alloc` says who allocates."), "observed", round(100 * pause[0], 1), "%",
            [Ref("type", heaviest[0])] if heaviest else [])))
    counters = _counter_rows(rec)
    report.section("Garbage collection and the runtime", Table(["Measure", "Average", "Worst"], counters) if counters
                   else "No counters were recorded.")
    others = sorted((t for t in rec.threads if t != main), key=lambda t: (-rec.threads[t][3], t))
    rows, refs = [], []
    for thread in others[:top]:
        cpu_ms = rec.threads[thread][3]
        if cpu_ms <= 0:
            continue
        shares = rec.by_owner(rec.thread_samples(thread))
        owner = max(shares.items(), key=lambda kv: (kv[1].cpu, kv[0].name))[0] if shares else None
        role = rec.thread_role(thread, roles)
        rows.append((rec.thread_label(thread), role or "-", ms(cpu_ms), pct(cpu_ms, whole), owner.name if owner else "-"))
        refs.append(row_refs(c0=Ref("thread", rec.thread_label(thread)), c4=mod_ref(owner, packages)))
        if whole and cpu_ms / whole >= FINDING_CORE_SHARE and len([f for f in found if f[1].refs and f[1].refs[0].kind == "thread"]) < 1:
            found.append((100 * THREAD_POINTS * cpu_ms / whole, Finding(
                f"{_sentence(role or rec.thread_label(thread))} kept {pct(cpu_ms, whole)} of one processor core busy, mostly "
                f"{owner.name if owner else 'unknown code'}.", "observed", round(100 * cpu_ms / whole, 1), "%",
                [r for r in (Ref("thread", rec.thread_label(thread)), mod_ref(owner, packages)) if r is not None])))
    if rows:
        report.section("Other threads running managed code",
                       "**Of one core** is the thread's time running managed code against the recording's length: near 100% keeps a "
                       "whole processor core busy. Names come from what a thread's stacks hold (perf-threads.json, then .NET's own).",
                       Table(["Thread", "What it is", "Running managed code (ms)", "Of one core", "Mostly caused by"], rows, refs=refs))
    outside = rec.in_phase(samples, phases, None)
    if outside:
        firsts = {}
        for node, kind, value in outside:
            first = next((rec.frames[f][2] for f in rec.path(node) if rec.owner_of_frame(f).kind != "runtime"), "(only .NET frames)")
            firsts[first] = firsts.get(first, 0.0) + value
        rows = [(name, ms(v), pct(v, whole)) for name, v in sorted(firsts.items(), key=lambda kv: (-kv[1], kv[0]))[:top]]
        report.section("Outside the named parts: the first method of ours, the game's or a mod's on the stack",
                       "If a large share sits here, the list of parts (perf-phases.json) needs another entry.",
                       Table(["Method", "ms", "Share of the main thread"], rows, len(firsts)))
    unknown = {o.name: s for o, s in rec.by_owner([(n, k, v) for _, n, k, v in rec.samples]).items() if o.kind == UNKNOWN}
    if unknown:
        rows = [(name, ms(s.total)) for name, s in sorted(unknown.items(), key=lambda kv: (-kv[1].total, kv[0]))[:top]]
        report.section("Modules no mod or game file was matched to", Table(["Module", "ms, all threads"], rows, len(unknown)))
    findings = _finding_list(found)
    report.blocks.insert(0, Findings(findings) if findings else "Nothing stood out: no lock, stall, mod or thread passed the "
                                                                "marks for the findings (docs/rimworld-perf.md).")
    if keep_summary is not None:
        keep_summary.update(summary_data(rec, folder, main, whole, tick_ms, mod_shares, packages, report.facts, findings,
                                         method_shares))
    return report


def _meta_json(rec, key, empty):
    try:
        found = json.loads(rec.meta.get(key) or "null")
    except ValueError:
        return empty
    return found if isinstance(found, type(empty)) else empty


def summary_data(rec, folder, main, whole, tick_ms, mod_shares, packages, facts, findings, method_shares=None):
    """What the summary file keeps of one recording: enough for a list, a mod's cost and a home panel, without the index."""
    def figure(name, at=0):
        found = rec.counter(name)
        return round(found[at], 3) if found else None
    meta = rec.meta
    return {"format": SUMMARY_FORMAT, "kit_version": __version__, "recording": folder.name, "label": meta.get("label", ""),
            "recorded_at": meta.get("recorded_at", ""), "seconds": float(meta.get("seconds") or whole / 1000),
            "context": {k: meta[k] for k in ("game_version", "save", "mods_loaded", "mods_active") if meta.get(k)},
            "game": {"ticks_a_second": figure("rimworld.ticks"), "frames_a_second": figure("rimworld.frames"),
                     "ms_a_tick": None if (v := ms_per_tick(rec, tick_ms, main)) is None else round(v, 4),
                     "longest_frame_ms": figure("rimworld.frame.worst", 1), "speed": figure("rimworld.speed"),
                     "pawns": figure("rimworld.pawns"), "maps": figure("rimworld.maps"),
                     "gc_paused": figure("dotnet.gc.pause.time")},
            "ticking_share": round(tick_ms / whole, 4) if whole else 0.0,
            "mods": {name: round(share, 5) for name, share in sorted(mod_shares.items(), key=lambda kv: (-kv[1], kv[0]))},
            "packages": {name: packages[name] for name in sorted(mod_shares) if name in packages},
            "facts": [{"label": f.label, "value": f.value} for f in facts],
            "findings": [finding_json(f) for f in findings], "timeline": rec.has_timeline,
            "methods": method_shares or {}, "versions": _meta_json(rec, "mod_versions", {}),
            "settings_prints": _meta_json(rec, "settings_prints", {}),
            "log_errors": sum(m["count"] for m in (logged_during(rec) or []) if m["level"] in LOG_LEVELS),
            "lock_events": meta.get("lock_events") == "yes", "allocation_events": meta.get("allocation_events") == "yes"}


def write_summary(folder, summary):
    """Writes the summary file beside the index, whole, stamped with the index it was made from."""
    index = Path(folder) / INDEX_NAME
    stamped = dict(summary, index_mtime=index.stat().st_mtime_ns if index.is_file() else 0)
    fresh = Path(folder) / (SUMMARY_NAME + ".new")
    fresh.write_text(json.dumps(stamped, indent=1, ensure_ascii=False), encoding="utf-8")
    fresh.replace(Path(folder) / SUMMARY_NAME)
    return stamped


def read_summary(folder):
    """The summary file when it is current (same format and index), else None."""
    try:
        found = json.loads((Path(folder) / SUMMARY_NAME).read_text(encoding="utf-8"))
        index = Path(folder) / INDEX_NAME
    except (OSError, ValueError):
        return None
    if not isinstance(found, dict) or found.get("format") != SUMMARY_FORMAT:
        return None
    if not index.is_file() or found.get("index_mtime") != index.stat().st_mtime_ns:
        return None
    return found


def summary_of(folder, top=15, patch_lookup=None):
    """A recording's summary, made and kept when it is missing or older than its index."""
    found = read_summary(folder)
    if found is not None:
        return found
    kept = {}
    summary_report(Recording(Path(folder) / INDEX_NAME), Path(folder), top, patch_lookup, kept)
    return write_summary(folder, kept)


def mod_report(rec, folder, pattern, top):
    phases, ticking = perf.phases()
    main = rec.main_thread()
    samples = rec.thread_samples(main)
    whole = rec.duration_ms(main)
    names = sorted({o.name for o in rec.owners.values() if o.kind == MOD and fnmatch.fnmatchcase(o.name.lower(), pattern.lower())})
    if not names:
        raise PerfError(f'No mod in this recording matches "{pattern}". A mod whose code never ran while recording is not in it.')
    report = Report(f"rimworld-perf: {pattern} in {folder.name}", [ATTRIBUTION])
    for name in names[:top]:
        mine = [s for s in samples if rec.label(s[0]).name == name and rec.label(s[0]).kind == MOD]
        total = sum(v for _, _, v in mine)
        tick = sum(v for _, _, v in rec.in_phase(mine, phases, ticking))
        everywhere = sum(v for _, n, _, v in rec.samples if rec.label(n).kind == MOD and rec.label(n).name == name)
        section = report.section(name, f"Caused {ms(total)} ms on the main thread ({pct(total, whole)} of it), {ms(tick)} ms of it while "
                                        f"ticking; {ms(everywhere)} ms on all threads.")
        rows, count, refs = _method_rows(rec.inclusive_methods(samples, lambda o, p, n=name: o.kind == MOD and o.name == n), whole,
                                         top, show_owner=False)
        section.blocks.append(Table(["Its methods (including what they call)", "ms", "Share of the main thread"], rows, count,
                                    refs=refs))
        rows, count, refs = _method_rows(rec.self_methods(mine), whole, top, packages=packages_of(rec))
        section.blocks.append(Table(["Where its time was spent", "Owner", "ms", "Share of the main thread"], rows, count,
                                    refs=refs))
    return report


def _shares(rec):
    phases, ticking = perf.phases()
    main = rec.main_thread()
    samples = rec.thread_samples(main)
    whole = rec.duration_ms(main)
    by_phase = {name: s.total / whole if whole else 0.0 for name, s in rec.by_phase(samples, phases).items()}
    tick_samples = rec.in_phase(samples, phases, ticking)
    tick_total = sum(v for _, _, v in tick_samples)
    owners = {o: s.total / tick_total for o, s in rec.by_owner(tick_samples).items()} if tick_total else {}
    pause = rec.counter("dotnet.gc.pause.time")
    return by_phase, owners, pause[0] if pause else None, ms_per_tick(rec, tick_total, main)


LIKE_FOR_LIKE = 0.2                 # pawns or ticks a second differing by more than a fifth make two recordings unlike


def _context_rows(before, after):
    """Rows of what each recording was of, and the ways they differ enough to matter."""
    def figure(rec, name):
        found = rec.counter(name)
        return found[0] if found else None
    rows, unlike = [], []
    for label, key in (("RimWorld", "game_version"), ("Save", "save"), ("Mods active", "mods_active")):
        a, b = before.meta.get(key) or "-", after.meta.get(key) or "-"
        rows.append((label, a, b))
        if a != "-" and b != "-" and a != b:
            unlike.append(f"{label.lower()} {a} against {b}")
    prints_a, prints_b = _meta_json(before, "settings_prints", {}), _meta_json(after, "settings_prints", {})
    if prints_a and prints_b:
        changed = sorted(k for k in set(prints_a) | set(prints_b) if prints_a.get(k) != prints_b.get(k))
        rows.append(("Mods' settings files changed", "-", f"{len(changed):,}" + (f" ({', '.join(changed[:3])}"
                                                                                 + (", ..." if len(changed) > 3 else "") + ")"
                                                                                 if changed else "")))
        if changed:
            unlike.append(f"{len(changed)} mods' settings changed")
    versions_a, versions_b = _meta_json(before, "mod_versions", {}), _meta_json(after, "mod_versions", {})
    for name in sorted(set(versions_a) | set(versions_b)):
        if versions_a.get(name) != versions_b.get(name):
            rows.append((name, versions_a.get(name, "-"), versions_b.get(name, "-")))
    for label, name in (("Game speed", "rimworld.speed"), ("Spawned pawns", "rimworld.pawns"), ("Ticks a second", "rimworld.ticks")):
        a, b = figure(before, name), figure(after, name)
        text = (lambda v: perf.SPEEDS.get(round(v), f"{v:.1f}")) if name == "rimworld.speed" else (lambda v: f"{v:,.0f}")
        rows.append((label, text(a) if a is not None else "-", text(b) if b is not None else "-"))
        if a is None or b is None:
            continue
        if name == "rimworld.speed" and round(a) != round(b):
            unlike.append(f"game speed {text(a)} against {text(b)}")
        elif name == "rimworld.pawns" and max(a, b) and abs(a - b) > LIKE_FOR_LIKE * max(a, b):
            unlike.append(f"{a:,.0f} pawns against {b:,.0f}")
    return rows, unlike


def compare_report(before, after, names, top):
    phases_before, owners_before, pause_before, tick_before = _shares(before)
    phases_after, owners_after, pause_after, tick_after = _shares(after)
    report = Report(f"rimworld-perf: {names[0]} against {names[1]}", [SHARE_NOTE, CAVEAT])
    report.facts = [Fact("Before", names[0]), Fact("After", names[1])]
    rows, unlike = _context_rows(before, after)
    if unlike:
        report.lines.insert(0, "**Not like for like: " + "; ".join(unlike) + ".** Differences below may come from that, not from a "
                               "change.")
    report.section("What each recording was of", Table(["", "Before", "After"], rows))
    keys = sorted(set(phases_before) | set(phases_after), key=lambda k: k or "~")
    report.section("Parts of the main loop, as shares of the main thread", Table(["Part", "Before", "After", "Change (points)"], [
        (k or "other", f"{100 * phases_before.get(k, 0):.1f}%", f"{100 * phases_after.get(k, 0):.1f}%",
         points(100 * (phases_after.get(k, 0) - phases_before.get(k, 0)))) for k in keys]))
    owners = set(owners_before) | set(owners_after)
    changes = sorted(owners, key=lambda o: (-abs(owners_after.get(o, 0) - owners_before.get(o, 0)), o.name))
    packages = {**packages_of(before), **packages_of(after)}
    report.section("Who caused the ticking time, largest changes first", Table(["Caused by", "Kind", "Before", "After", "Change (points)"], [
        (o.name, o.kind, f"{100 * owners_before.get(o, 0):.1f}%", f"{100 * owners_after.get(o, 0):.1f}%",
         points(100 * (owners_after.get(o, 0) - owners_before.get(o, 0)))) for o in changes[:top]], len(changes),
        refs=[row_refs(c0=mod_ref(o, packages)) for o in changes[:top]]))
    if tick_before is not None and tick_after is not None:
        report.lines.append(f"**The main thread's ticking took {tick_before:,.2f} ms a tick, then {tick_after:,.2f} ms** "
                            f"({points(100 * (tick_after - tick_before) / tick_before) if tick_before else '?'}%), from the game's "
                            "own tick count.")
        per_tick = sorted(owners, key=lambda o: (-abs(owners_after.get(o, 0) * tick_after - owners_before.get(o, 0) * tick_before), o.name))
        report.section("Who caused the ticking time, in milliseconds a tick", "A mod's share of ticking times the main thread's "
                       "ticking a tick: unlike shares, it does not move when another mod gets cheaper.",
                       Table(["Caused by", "Kind", "Before (ms a tick)", "After (ms a tick)", "Change (ms)"], [
                           (o.name, o.kind, f"{owners_before.get(o, 0) * tick_before:.3f}", f"{owners_after.get(o, 0) * tick_after:.3f}",
                            f"{owners_after.get(o, 0) * tick_after - owners_before.get(o, 0) * tick_before:+.3f}") for o in per_tick[:top]],
                             len(per_tick)))
    if pause_before is not None and pause_after is not None:
        report.lines.append(f"Time paused for garbage collection: {100 * pause_before:.1f}%, then {100 * pause_after:.1f}%.")
    return report


TREND_POINTS = 2.0                  # a share this many points from the earlier recordings' middle value is marked


def _median(values):
    ordered = sorted(values)
    if not ordered:
        return None
    middle = len(ordered) // 2
    return ordered[middle] if len(ordered) % 2 else (ordered[middle - 1] + ordered[middle]) / 2


def trend_note(share, earlier):
    """A mark for a share (in %) against the earlier recordings' middle value, or ''."""
    middle = _median(earlier)
    if middle is None:
        return ""
    change = share - middle
    if change >= TREND_POINTS:
        return f"**up {change:.1f} points** on the earlier middle ({middle:.1f}%)"
    if change <= -TREND_POINTS:
        return f"down {-change:.1f} points on the earlier middle ({middle:.1f}%)"
    return ""


def trend_report(root, pattern, top):
    """trend: the share of ticking the mods matching pattern caused in each recording kept, oldest first."""
    found = recordings(root)
    if not found:
        raise PerfError(f"No recordings in {root}. Make one with: rimworld-perf record")
    wanted = pattern.lower()
    phases, ticking = perf.phases()
    rows, refs, shares, per_mod, earlier_mod, packages = [], [], [], {}, {}, {}
    for position, folder in enumerate(found):
        rec = Recording(folder / INDEX_NAME)
        main = rec.main_thread()
        samples = rec.in_phase(rec.thread_samples(main), phases, ticking)
        tick_total = sum(v for _, _, v in samples)
        mods = {o.name: s.total for o, s in rec.by_owner(samples).items()
                if o.kind == MOD and fnmatch.fnmatchcase(o.name.lower(), wanted)}
        share = 100 * sum(mods.values()) / tick_total if tick_total else 0.0
        per_tick = ms_per_tick(rec, tick_total, main)
        ours_per_tick = f"{per_tick * share / 100:.3f}" if per_tick is not None else "-"
        busiest = max(mods.items(), key=lambda kv: (kv[1], kv[0]))[0] if mods else "-"
        packages.update(packages_of(rec))
        rows.append((folder.name, rec.meta.get("label", ""), pct(tick_total, rec.duration_ms(main)), f"{share:.1f}%", ours_per_tick,
                     busiest, trend_note(share, shares)))
        refs.append(row_refs(c0=Ref("recording", folder.name),
                             c5=Ref("mod", busiest, package=packages.get(busiest, "")) if mods else None))
        shares.append(share)
        mod_shares = {name: 100 * value / tick_total for name, value in mods.items()} if tick_total else {}
        if position < len(found) - 1:
            for name, value in mod_shares.items():
                earlier_mod.setdefault(name, []).append(value)
        else:
            per_mod = mod_shares
    report = Report(f"rimworld-perf: trend of {pattern}", [
        f"{len(found)} recordings, oldest first: the share of ticking the mods matching \"{pattern}\" caused (the innermost mod on "
        f"the stack), marked where it moved {TREND_POINTS:g} points or more from the earlier recordings' middle value. Recordings "
        "differ in what was on screen, the save and the speed: a mark is a place to look, not a verdict.", CAVEAT])
    report.section("Recordings", Chart(f"The share of ticking {pattern} caused",
                                       "Each recording kept, oldest first: the share of ticking the mods followed caused.",
                                       [row[1] or row[0] for row in rows], [ChartSeries("Their share of ticking", shares)],
                                       kind="line", unit="%", value_label="Share of ticking"),
                   Table(["Recording", "Label", "Ticking (of the main thread)", "Their share of ticking",
                          "Their ms a tick", "Busiest of them", "Note"], rows, refs=refs))
    if len(found) > 1:
        names = sorted(set(per_mod) | set(earlier_mod), key=lambda n: (-(per_mod.get(n, 0.0)), n))
        rows = []
        for name in names:
            newest = per_mod.get(name, 0.0)
            middle = _median(earlier_mod.get(name, [])) or 0.0
            rows.append((name, f"{newest:.1f}%", f"{middle:.1f}%", points(newest - middle)))
        report.section("Each of them in the newest recording, against the earlier middle",
                       Table(["Mod", "Newest", "Earlier middle", "Change (points)"], rows[:top], len(rows),
                             refs=[row_refs(c0=Ref("mod", row[0], package=packages.get(row[0], ""))) for row in rows[:top]]))
    return report


COSTS_RECORDINGS = 10               # recordings costs reads, newest first


def costs_report(root, pattern, top, patch_lookup=None):
    """costs (1.153.0): each mod's share of ticking in the newest recording against the earlier ones' middle, and the busiest
    methods, from the recordings' summaries alone, for a program's tags and badges. Returns (report, data)."""
    found = list(reversed(recordings(root)))[:COSTS_RECORDINGS]
    if not found:
        raise PerfError(f"No recordings in {root}. Make one with: rimworld-perf record")
    summaries = []
    for folder in found:
        try:
            summaries.append(summary_of(folder, patch_lookup=patch_lookup))
        except (SamplingError, sqlite3.Error, OSError, ValueError):
            continue
    if not summaries:
        raise PerfError("No recording could be read.")
    newest, earlier = summaries[0], summaries[1:]
    names = sorted(set(newest.get("mods", {})) | {n for s in earlier for n in s.get("mods", {})})
    packages = {}
    for summary in reversed(summaries):
        packages.update(summary.get("packages", {}))
    wanted = pattern.lower()
    mods, rows, refs = [], [], []
    for name in names:
        share = 100 * newest.get("mods", {}).get(name, 0.0)
        middle = _median([100 * s.get("mods", {}).get(name, 0.0) for s in earlier])
        change = share - middle if middle is not None else None
        ours = fnmatch.fnmatchcase(name.lower(), wanted)
        mods.append({"name": name, "package": packages.get(name, ""), "share": round(share, 2),
                     "earlier_middle": None if middle is None else round(middle, 2),
                     "change": None if change is None else round(change, 2), "ours": ours,
                     "flagged": change is not None and abs(change) >= TREND_POINTS,
                     "version": newest.get("versions", {}).get(name, "")})
    mods.sort(key=lambda m: (-m["share"], m["name"]))
    for mod in mods[:top]:
        rows.append((mod["name"], f"{mod['share']:.1f}%", "-" if mod["earlier_middle"] is None else f"{mod['earlier_middle']:.1f}%",
                     "-" if mod["change"] is None else points(mod["change"])))
        refs.append(row_refs(c0=Ref("mod", mod["name"], package=mod["package"])))
    own_share = sum(m["share"] for m in mods if m["ours"])
    own_earlier = _median([100 * sum(v for n, v in s.get("mods", {}).items() if fnmatch.fnmatchcase(n.lower(), wanted))
                           for s in earlier])
    own = {"pattern": pattern, "share": round(own_share, 2),
           "earlier_middle": None if own_earlier is None else round(own_earlier, 2),
           "note": trend_note(own_share, [100 * sum(v for n, v in s.get("mods", {}).items()
                                                    if fnmatch.fnmatchcase(n.lower(), wanted)) for s in earlier])}
    report = Report("rimworld-perf: what each mod costs", [
        f"Each mod's share of ticking in the newest recording ({newest['recording']}) against the middle of the "
        f"{len(earlier)} before it, from the recordings' summaries. A share moves with what was on screen and the save: a "
        "change is a place to look, not a verdict.", CAVEAT])
    report.facts = [Fact("Newest", newest["recording"]), Fact("Recordings", f"{len(summaries)}"),
                    Fact(f"Ours ({pattern})", f"{own_share:.1f}% of ticking")]
    report.section("Mods, costliest first", Table(["Mod", "Newest", "Earlier middle", "Change (points)"], rows, len(mods),
                                                  refs=refs))
    methods = [{"name": name, **value} for name, value in sorted(newest.get("methods", {}).items(),
                                                                 key=lambda kv: -kv[1].get("share", 0))]
    return report, {"newest": newest["recording"], "recorded_at": newest.get("recorded_at", ""),
                    "label": newest.get("label", ""), "first_finding": (newest.get("findings") or [{}])[0],
                    "recordings": len(summaries), "own": own, "mods": mods, "methods": methods,
                    "game": newest.get("game", {})}


def _plain_files(args, environ, settings_file):
    """[(kind, folder, file)] of every large file kept plain: each recording's trace and each heap's own files."""
    found = [("recording", folder, folder / dd.TRACE_FILE) for folder in recordings(recordings_root(args, environ, settings_file))]
    _, heaps = snap.roots(args.cache, environ, settings_file)
    found += [("heap", folder, folder / name) for folder in snap.kept(heaps) for name in snap.PACKED_FILES]
    return [(kind, folder, path) for kind, folder, path in found if path.is_file()]


def pack_report(args, environ, settings_file):
    plain = _plain_files(args, environ, settings_file)
    before = sum(path.stat().st_size for _, _, path in plain)
    rows, after, failed = [], 0, []
    for kind, folder, path in plain:
        size_before = path.stat().st_size
        if args.apply:
            try:
                target = packed.pack(path)
            except (OSError, packed.PackError) as error:
                failed.append(f"{folder.name}/{path.name}: {error}")
                continue
            after += target.stat().st_size
            rows.append((kind, folder.name, path.name, size(size_before), size(target.stat().st_size)))
        else:
            rows.append((kind, folder.name, path.name, size(size_before), ""))
    if not plain:
        report = Report("rimworld-perf: nothing left to pack", ["Every recording's trace and every heap's own files are packed."])
    elif args.apply:
        report = Report(f"rimworld-perf: packed {len(rows)} files, {size(before)} down to {size(after)}",
                        ["Each was read back and checked before its plain file was removed. `rimworld-perf unpack NAME` gives "
                         "one back plain."])
    else:
        report = Report(f"rimworld-perf: {len(plain)} files kept plain, {size(before)}",
                        ["`rimworld-perf pack --apply` packs them with zstd, checking each before its plain file goes."])
    if rows:
        report.section("Files", Table(["Kind", "Kept as", "File", "Plain", "Packed"], rows))
    for line in failed:
        report.lines.append(f"Not packed, left as it was: {line}")
    return report, {"files": len(plain), "plainBytes": before, "packed": len(rows) if args.apply else 0, "failed": failed}


def unpack_report(args, environ, settings_file):
    root = recordings_root(args, environ, settings_file)
    _, heaps = snap.roots(args.cache, environ, settings_file)
    try:
        folder, names = find(root, args.name), (dd.TRACE_FILE,)
    except PerfError:
        try:
            folder, names = snap.find(heaps, args.name, "heaps"), (snap.HEAP_FILE,)
        except snap.SnapshotsError:
            raise PerfError(f'"{args.name}" names no single recording or heap. `rimworld-perf list` shows them.') from None
    written = []
    for name in names:
        plain = folder / name
        if plain.is_file():
            written.append(plain)
        elif packed.packed_of(plain).is_file():
            written.append(packed.unpack(packed.packed_of(plain)))
    if not written:
        raise PerfError(f"{folder.name} keeps no {' or '.join(names)}, plain or packed.")
    report = Report(f"rimworld-perf: {folder.name} written out plain",
                    ["Open it in PerfView or Visual Studio. The packed copy stays; delete the plain one when done with it."])
    report.section("Files", Table(["File", "Size"], [(str(p), size(p.stat().st_size)) for p in written]))
    return report, {"files": [str(p) for p in written]}


def list_report(root, patch_lookup=None):
    """Every recording, newest first, with its summary (made and kept the first time it is listed). Returns (report, data)."""
    found = recordings(root)
    report = Report("rimworld-perf: recordings", [f"{len(found)} recordings in {root}."])
    rows, refs, summaries = [], [], []
    for folder in reversed(found):
        try:
            summary = summary_of(folder, patch_lookup=patch_lookup)
        except (SamplingError, sqlite3.Error, OSError, ValueError) as error:
            meta = derived.read_meta(folder / INDEX_NAME)
            summary = {"recording": folder.name, "label": meta.get("label", ""), "recorded_at": meta.get("recorded_at", ""),
                       "seconds": meta.get("seconds", ""), "error": str(error), "findings": [], "game": {}}
        summaries.append(summary)
        ticks = (summary.get("game") or {}).get("ticks_a_second")
        first = (summary.get("findings") or [{}])[0].get("text", "-")
        rows.append((folder.name, summary.get("recorded_at", "?"), summary.get("seconds", "?"), summary.get("label", ""),
                     f"{ticks:,.0f}" if ticks else "-", first))
        refs.append(row_refs(c0=Ref("recording", folder.name)))
    if rows:
        report.section("Newest first", Table(["Recording", "Recorded at", "Seconds", "Label", "Ticks a second", "What matters most"],
                                             rows, refs=refs))
    return report, {"recordings": summaries}


# ---- Running ----

def _pid(args, run, missing):
    if args.pid is not None:
        return args.pid
    running = dd.find_processes(perf.PROCESS_NAME, run)
    if not running:
        raise PerfError(missing)
    if len(running) > 1:
        raise PerfError("More than one RimWorld is running (" + ", ".join(str(p) for p, _ in running) + "); name one with --pid.")
    return running[0][0]


def _record(args, root, environ, settings_file, run, popen, now):
    if not MIN_SECONDS <= args.seconds <= MAX_SECONDS:
        raise PerfError(f"--seconds must be between {MIN_SECONDS} and {MAX_SECONDS}.")
    pid = _pid(args, run, "RimWorld is not running. Start it, load the save, unpause at the speed that feels slow, then record.")
    trace_tool, counters_tool, installed = dd.ensure_tools(environ, run)
    folder = new_folder(root, args.label, now)
    speedscope, counters_file, notes = dd.record(pid, args.seconds, folder, trace_tool, counters_tool, popen,
                                                 providers=dotnet_events.runtime_provider(args.alloc), counters=perf.COUNTER_SETS)
    meta = {"kit_version": __version__, "recorded_at": now.strftime("%Y-%m-%d %H:%M:%S"), "seconds": args.seconds,
            "label": args.label or "", "pid": pid, "game_name": perf.GAME_NAME, "tools_version": dd.TOOLS_VERSION,
            "lock_events": "yes", "allocation_events": "yes" if args.alloc else "",
            **_context(args, environ, settings_file, now)}
    meta.update(_extras(args, environ, settings_file, now, args.seconds))
    notes = notes + build_index(folder, speedscope, counters_file, meta, args, environ, settings_file, folder / dd.TRACE_FILE)
    if not args.keep_speedscope:
        derived.remove(speedscope)
    if (folder / dd.TRACE_FILE).is_file():
        packed.pack(folder / dd.TRACE_FILE)
    if installed:
        notes.insert(0, f"Installed dotnet-trace and dotnet-counters {dd.TOOLS_VERSION} into {dd.tools_folder(environ)} first.")
    return folder, notes


def _extras(args, environ, settings_file, now, seconds):
    """What else a recording keeps for comparing and linking (1.153.0): the log while recording, the mods' settings prints and our
    own mods' versions. Each is JSON text in the index's meta; best effort."""
    from . import paths
    found = {}
    try:
        logs = Path(paths.logs_path(None, environ, settings_file)) / paths.LOG_NAME
        start = now.strftime("%Y-%m-%d %H:%M:%S")
        end = (now + timedelta(seconds=seconds + LOG_TAIL_SECONDS)).strftime("%Y-%m-%d %H:%M:%S")
        found["log_during"] = json.dumps(perf.log_during(logs, start, end)[:LOG_KEPT])
    except Exception:  # noqa: BLE001
        pass
    try:
        found["settings_prints"] = json.dumps(perf.settings_prints(paths.config_path(args.config, environ, settings_file)))
    except Exception:  # noqa: BLE001
        pass
    found["mod_versions"] = json.dumps(perf.mod_versions(perf.OWN_MODS, args.game, args.workshop, args.config, environ,
                                                         settings_file))
    return found


LOG_TAIL_SECONDS = 2                # the log is read to a moment after the recording ends
LOG_KEPT = 200                      # message groups a recording keeps


def _context(args, environ, settings_file, now):
    """The recording's context (perf.context): the game's version, the save, the mods. Best effort."""
    from . import paths
    try:
        logs = Path(paths.logs_path(None, environ, settings_file)) / paths.LOG_NAME
    except Exception:  # noqa: BLE001
        logs = None
    try:
        config = Path(paths.config_path(args.config, environ, settings_file)) / "ModsConfig.xml"
    except Exception:  # noqa: BLE001
        config = None
    return perf.context(logs, config, now.strftime("%Y-%m-%d %H:%M:%S")) if logs or config else {}


def _index(args, root, environ, settings_file, now):
    source = Path(args.file)
    if not source.is_file():
        raise PerfError(f"No file at {source}.")
    folder = new_folder(root, args.label, now)
    folder.mkdir(parents=True)
    meta = {"kit_version": __version__, "recorded_at": now.strftime("%Y-%m-%d %H:%M:%S"), "seconds": "",
            "label": args.label or "", "game_name": perf.GAME_NAME, "source": str(source)}
    try:
        notes = build_index(folder, source, Path(args.counters) if args.counters else None, meta, args, environ, settings_file)
    except Exception:
        shutil.rmtree(folder, ignore_errors=True)
        raise
    return folder, notes


def _snapshots(args, environ, settings_file, run, now, sleep):
    """The report for stack, stack-report, heap, heap-report and heap-compare."""
    stacks_root, heaps_root = snap.roots(args.cache, environ, settings_file)
    notes = []
    if args.report == "stack":
        pid = _pid(args, run, "RimWorld is not running. A stack snapshot needs the game open, frozen or not.")
        found, installed = dd.ensure([dd.STACK], environ, run)
        if installed:
            notes.append(f"Installed dotnet-stack {dd.TOOLS_VERSION} into {dd.tools_folder(environ)} first.")
        folder = snap.new_folder(stacks_root, args.label, now)
        try:
            snap.take_stacks(pid, folder, found[dd.STACK], args.times, args.every, run, sleep, now, args.label)
        except Exception:
            shutil.rmtree(folder, ignore_errors=True)
            raise
    if args.report in ("stack", "stack-report"):
        folder = folder if args.report == "stack" else snap.find(stacks_root, args.snapshot, "stack snapshots")
        meta, snapshots = snap.read_stacks(folder)
        names = sorted({f.module for snapshot in snapshots for s in snapshot for f in s.frames if f.module})
        owners, more = _owners(names, args, environ, settings_file)
        return snap.stack_report(folder, meta, snapshots, owners, notes + more, args.frames, args.top)
    if args.report == "heap":
        pid = _pid(args, run, "RimWorld is not running. Load the save you want to measure first.")
        found, installed = dd.ensure([dd.GCDUMP, dd.COUNTERS], environ, run)
        if installed:
            notes.append(f"Installed Microsoft's diagnostics tools {dd.TOOLS_VERSION} into {dd.tools_folder(environ)} first.")
        folder = snap.new_folder(heaps_root, args.label, now)
        try:
            snap.take_heap(pid, folder, found[dd.GCDUMP], run, now, args.label, found[dd.COUNTERS])
        except Exception:
            shutil.rmtree(folder, ignore_errors=True)
            raise
    if args.report in ("heap", "heap-report"):
        folder = folder if args.report == "heap" else snap.find(heaps_root, args.snapshot, "heaps")
        meta, heap = snap.read_heap(folder)
        owners, more = _owners(sorted({t.module for t in heap.types}), args, environ, settings_file)
        return snap.heap_report(folder, meta, heap, owners, notes + more, args.top)
    if bool(args.first) != bool(args.second):
        raise PerfError("Name two heaps, or none for the last two.")
    kept = snap.kept(heaps_root)
    if not args.first and len(kept) < 2:
        raise PerfError("Fewer than two heaps are kept, so there is nothing to compare.")
    first = snap.find(heaps_root, args.first, "heaps") if args.first else kept[-2]
    second = snap.find(heaps_root, args.second, "heaps") if args.second else kept[-1]
    (meta_a, before), (meta_b, after) = snap.read_heap(first), snap.read_heap(second)
    owners, _ = _owners(sorted({t.module for t in before.types} | {t.module for t in after.types}), args, environ, settings_file)
    return snap.heap_compare((first.name, second.name), before, after, owners, args.top, (meta_a, meta_b))


def _look(args, environ, settings_file, run, now):
    """(report, data) for look, look-kind and look-why: one snapshot, one request, then let go."""
    pid = _pid(args, run, "RimWorld is not running. Load the save you want to look inside first.")
    folder = look.runtime_folder(args.game, environ, settings_file)
    if args.report in ("look", "heap"):
        _, heaps_root = snap.roots(args.cache, environ, settings_file)
        ready, answers = _requests(pid, folder, [{"op": "overview"}], environ, args)
        overview = hreader.answer_data(answers[0])
        kept, heap = look.save_overview(heaps_root, ready, overview, args.label, now)
        meta = snap.meta_of(kept)
        owners, notes = _owners(sorted({t.module for t in heap.types}), args, environ, settings_file)
        report = snap.heap_report(kept, meta, heap, owners, notes, args.top)
        _say_frozen(report, ready)
        # 1.135.0: the overview as data, in the shape look-serve's overview answer has, for a program's page that read it frozen.
        data = {key: overview.get(key) for key in ("totalObjects", "totalBytes", "freeBytes", "untyped", "seconds")}
        data.update(look.owners_data(heap, owners, look.OVERVIEW_TOP), kept=Path(kept).name, notes=notes,
                    frozenMs=ready.get("frozenMs"))
        return report, data
    if args.report == "look-kind":
        request = {"op": "kind", "type": args.type, "take": max(1, args.top), "match": args.match or "",
                   "sort": "size" if args.largest else "", "open": bool(args.open)}
        ready, answers = _requests(pid, folder, [request], environ, args)
        data = dict(hreader.answer_data(answers[0]), sorted=args.largest, frozenMs=ready.get("frozenMs"))
        report = hreader.kind_report(f"rimworld-perf: look-kind {args.type}", data)
        if data.get("opened"):
            opened = hreader.object_report("", data["opened"])
            report.section("The first one, in full", *[block for section in opened.sections for block in section.blocks])
        _say_frozen(report, ready)
        return report, data
    _, answers = hreader.run_requests(pid, folder, [{"op": "why", "type": args.type, "sample": max(1, args.sample)}],
                                 look.DESCRIBE, environ)
    data = hreader.answer_data(answers[0])
    return hreader.why_report(f"rimworld-perf: look-why {args.type}", data), data


HEAP_BY_SNAPSHOT = ("Taken as a Windows snapshot, as `look` takes one (1.151.0): the game paused only while it was copied, nothing was "
                    "forced and there is no limit on how many objects are read, but garbage not yet collected is counted, so "
                    "answer \"is it a leak?\" with `look-why`. `heap --gcdump` takes the heap after a full garbage collection, "
                    "as before, which pauses the game until it is done.")


def _requests(pid, folder, requests, environ, args):
    """The heap reader's run for look and look-kind: frozen with --freeze (1.134.0), else from a snapshot."""
    if getattr(args, "freeze", False):
        return hreader.run_requests(pid, folder, requests, look.DESCRIBE, environ, freeze=True)
    return hreader.run_requests(pid, folder, requests, look.DESCRIBE, environ)


def _say_frozen(report, ready):
    if ready.get("frozenMs") is not None:
        report.lines.insert(1, f"The game was frozen for {ready['frozenMs']:,} ms while it was read, then let go.")


def _installed_version(mod, environ, settings_file):
    """The installed version of the mod named (1.134.0), from its About.xml in the game's Mods folder: what the running game
    loaded, since our mods are installed only with the game closed. Empty when it is not found."""
    try:
        folder = installs.installed_mods(settings_file, environ)
        for about in sorted(folder.glob("*/About/About.xml")):
            name, version = installs.identity(about.parent.parent)
            if name == mod:
                return version
    except OSError:
        pass
    return ""


def _keep_live_notes(results, environ, settings_file, now):
    """Keeps the figures live checks noted (1.134.0); a line for the report saying how many, or None."""
    kept = checks_live.keep_notes(results, checks_live.live_notes_path("rimworld", environ, settings_file),
                                  lambda mod: _installed_version(mod, environ, settings_file),
                                  now.astimezone(timezone.utc).isoformat())
    return f"Noted {kept:,} figures for the test list (test-pass reads them)." if kept else None


def _look_thaw(args, run):
    """(report, data) for look-thaw (1.134.0): the reader's thaw, by hand."""
    pid = _pid(args, run, "RimWorld is not running, so nothing is frozen.")
    found = hreader.thaw(pid)
    if found.get("error"):
        raise PerfError(found["error"])
    report = Report("rimworld-perf: look-thaw", [found.get("says", "")])
    return report, found


def _look_check(args, environ, settings_file, run, run_requests=None):
    """(report, data) for look-check: every live check in the file, from one snapshot (1.120.0)."""
    try:
        chosen, files = check_engine.load_files(check_engine.check_files("rimworld", args.checks_file, environ), "live")
    except check_engine.CheckError as problem:
        raise PerfError(str(problem)) from None
    if args.check:
        chosen = [c for c in chosen if fnmatch.fnmatch(c.id.lower(), args.check.lower())]
    if not chosen:
        raise PerfError(", ".join(files) + " hold no live checks" + (f" matching {args.check}" if args.check else "") + ".")
    pid = _pid(args, run, "RimWorld is not running. Load the save you want to check first.")
    ready, results = checks_live.run(pid, look.runtime_folder(args.game, environ, settings_file), chosen, look.DESCRIBE, environ,
                                     run_requests or hreader.run_requests, freeze=bool(getattr(args, "freeze", False)))
    report = checks_live.checks_report(results, files, frozen=ready.get("frozenMs") is not None)
    if ready.get("frozenMs") is not None:
        report.lines.insert(1, f"The game was frozen for {ready['frozenMs']:,} ms while it was read, then let go.")
    elif ready.get("snapshotMs") is not None:
        report.lines.insert(1, f"The snapshot paused the game for {ready['snapshotMs']:,} ms.")
    kept = _keep_live_notes(results, environ, settings_file, datetime.now(timezone.utc))
    if kept:
        report.lines.insert(1, kept)
    return report, check_engine.data(results)


def _held_checks(environ, redact, settings_file=None):
    """look-serve's checks request (1.123.0): every live check, answered from the snapshot already held, as data for a program's
    page: the check data, and the report under "report" as render_json gives it. A check file that cannot be used is a ValueError,
    which serve answers in words."""
    def answer(ask):
        chosen, files = check_engine.load_files(check_engine.check_files("rimworld", None, environ), "live")
        return checks_live.held_answer(chosen, files, ask, redact,
                                       keep=lambda results: _keep_live_notes(results, environ, settings_file,
                                                                             datetime.now(timezone.utc)))
    return answer


def _watch(args, environ, settings_file, run, popen, now, sleep, clock):
    """The report for watch and watch-report."""
    where = pw.root(args.cache, environ, settings_file)
    notes = []
    if args.report == "watch":
        pid = _pid(args, run, "RimWorld is not running. Start it and load the save you want to watch first.")
        counters_tool = None
        if not args.no_counters:
            found, installed = dd.ensure([dd.COUNTERS], environ, run)
            counters_tool = found[dd.COUNTERS]
            if installed:
                notes.append(f"Installed dotnet-counters {dd.TOOLS_VERSION} into {dd.tools_folder(environ)} first.")
        folder = pw.new_folder(where, args.label, now)
        log_file = pw.default_log(args.logs, environ, settings_file)
        print(f"Watching RimWorld ({pid}) for up to {args.minutes:g} minutes; press Ctrl+C to stop early. The report follows.",
              file=sys.stderr)
        notes += pw.watch(pid, folder, args.minutes, args.every, args.map_every, counters_tool, args.label,
                          Progress(environ), clock, sleep, popen, pm.Process, log_file)
        history.record("rimworld", "memory-watched", environ, settings_file, watch=folder.name, label=args.label or "")
    else:
        folder = pw.find(where, args.watch, prefer_running=not args.watch, now=clock())
    watched = pw.Watch(folder)
    owners, more = _owners(pw.file_stems(watched), args, environ, settings_file)
    report = pw.watch_report(watched, owners, args.top)
    for note in notes + more:
        if note not in report.lines:
            report.lines.insert(1, note)
    return report, {"watch": folder.name, "state": pw.state(folder, clock(), watched.meta)}


def _steer(args, environ, settings_file, clock):
    """watch-status, watch-stop and watch-mark: (report, data). A refusal is data with ok false and its reason, as every tool's."""
    where = pw.root(args.cache, environ, settings_file)
    now = clock()
    if args.report == "watch-status":
        return pw.status(where, args.watch, now)
    try:
        if args.report == "watch-stop":
            if args.watch:
                folder = pw.find(where, args.watch)
            else:
                running = [p for p in pw.kept(where) if pw.state(p, now) == pw.RUNNING]
                if not running:
                    raise pw.WatchError("No memory watch is running, so there is nothing to stop.")
                folder = running[-1]
            pw.ask_to_stop(folder, now)
            return (Report("rimworld-perf: watch stopping", [f"Asked the watch {folder.name} to stop: it ends within a second or two, "
                                                             "then reads in its counters and the log."]),
                    {"ok": True, "watch": folder.name})
        folder = pw.find(where, args.watch, prefer_running=not args.watch, now=now)
        at, text = pw.add_mark(folder, args.text, args.at, now)
        return (Report("rimworld-perf: watch marked", [f'Marked "{text}" at {pw.clock(at)} in the watch {folder.name}.']),
                {"ok": True, "watch": folder.name, "t": at, "text": text})
    except pw.WatchError as refused:
        return Report("Refused", [str(refused)]), {"ok": False, "refusal": str(refused)}


def main(argv=None, settings_file=None, environ=None, out=None, run=subprocess.run, popen=subprocess.Popen, now=None, sleep=time.sleep,
         clock=time.time):
    out = out or sys.stdout
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or (argv[0] not in REPORTS and argv[0] not in ("-h", "--help")):
        argv.insert(0, "report")
    try:
        args = _parser().parse_args(argv)
    except SystemExit as stop:
        return EXIT_USAGE if stop.code else EXIT_OK
    settings_file = args.settings or settings_file
    redact = keep if args.no_redact else home_redactor()
    code = EXIT_OK
    data = None
    root = recordings_root(args, environ, settings_file)
    try:
        if args.report in ("watch-status", "watch-stop", "watch-mark"):
            report, data = _steer(args, environ, settings_file, clock)
            if data.get("ok") is False:
                code = EXIT_FAILED
        elif args.report == "list":
            report, data = list_report(root, patch_lookup_for(args, environ, settings_file))
            snap.list_sections(report, *snap.roots(args.cache, environ, settings_file))
            watches = pw.summary_rows(pw.root(args.cache, environ, settings_file))
            if watches:
                report.section("Memory watches, newest first", Table(["Watch", "Started", "Samples", "Label"], watches))
        elif args.report == "pack":
            report, data = pack_report(args, environ, settings_file)
        elif args.report == "unpack":
            report, data = unpack_report(args, environ, settings_file)
        elif args.report == "heap" and not args.gcdump:
            report, data = _look(args, environ, settings_file, run, now or datetime.now())
            report.lines.insert(1, HEAP_BY_SNAPSHOT)
        elif args.report in ("stack", "stack-report", "heap", "heap-report", "heap-compare"):
            report = _snapshots(args, environ, settings_file, run, now or datetime.now(), sleep)
        elif args.report == "look-serve":
            try:
                pid = _pid(args, run, "RimWorld is not running. Load the save you want to look inside first.")
            except PerfError as error:  # a program reads one JSON line first, refusals included
                return look.refuse(str(error), out)
            _, heaps_root = snap.roots(args.cache, environ, settings_file)
            return look.serve(pid, look.runtime_folder(args.game, environ, settings_file), heaps_root,
                              lambda names: _owners(names, args, environ, settings_file), args.label or "", args.limit_seconds,
                              stdout=out, checks_answer=_held_checks(environ, redact, settings_file))
        elif args.report in ("look", "look-kind", "look-why"):
            report, data = _look(args, environ, settings_file, run, now or datetime.now())
        elif args.report == "look-check":
            report, data = _look_check(args, environ, settings_file, run)
        elif args.report == "look-thaw":
            report, data = _look_thaw(args, run)
        elif args.report in ("watch", "watch-report"):
            report, data = _watch(args, environ, settings_file, run, popen, now or datetime.now(), sleep, clock)
        elif args.report == "compare":
            if bool(args.first) != bool(args.second):
                raise PerfError("Name two recordings, or none for the last two.")
            found = recordings(root)
            if not args.first and len(found) < 2:
                raise PerfError("Fewer than two recordings are kept, so there is nothing to compare.")
            first = find(root, args.first) if args.first else found[-2]
            second = find(root, args.second) if args.second else found[-1]
            report = compare_report(Recording(first / INDEX_NAME), Recording(second / INDEX_NAME), (first.name, second.name), args.top)
        elif args.report == "trend":
            report = trend_report(root, args.name, args.top)
        elif args.report == "costs":
            report, data = costs_report(root, args.name, args.top, patch_lookup_for(args, environ, settings_file))
        elif args.report == "reindex":
            report, data = reindex_report(args, root, environ, run)
        elif args.report == "callers":
            folder = find(root, args.recording)
            report = callers_report(Recording(folder / INDEX_NAME), folder, args.method, args.top, args.all_threads)
        elif args.report == "mod":
            folder = find(root, args.recording)
            report = mod_report(Recording(folder / INDEX_NAME), folder, args.name, args.top)
        else:
            notes = []
            if args.report == "record":
                folder, notes = _record(args, root, environ, settings_file, run, popen, now or datetime.now())
            elif args.report == "index":
                folder, notes = _index(args, root, environ, settings_file, now or datetime.now())
            else:
                folder = find(root, args.recording)
            kept = {}
            report = summary_report(Recording(folder / INDEX_NAME), folder, args.top, patch_lookup_for(args, environ, settings_file),
                                    kept)
            data = {"recording": folder.name, "summary": write_summary(folder, kept)}
            if args.report == "record":
                first = (kept.get("findings") or [{}])[0].get("text", "")
                history.record("rimworld", "perf-recorded", environ, settings_file, recording=folder.name,
                               label=kept.get("label", ""), finding=first)
            for note in notes:
                if note not in report.lines:
                    report.lines.insert(1, note)
    except (PerfError, SamplingError, SnapshotError, snap.SnapshotsError, dd.DiagnosticsError, pw.WatchError, pm.MemoryError_,
            hreader.LookError, hreader.HeapReaderError) as error:
        report, code = Report("rimworld-perf: error", [str(error)]), EXIT_FAILED
        data = {"ok": False, "refusal": str(error)}
    print(envelope_text("rimworld-perf", report, redact, data) if args.json else render_markdown(report, redact), file=out)
    return code


CACHE_POLICIES = [{"folder": CACHE_FOLDER,
                   "aged": "a recording of the game, unchanged for {days} days; it cannot be made again, so compare against it first if it matters"},
                  {"folder": snap.STACKS_FOLDER,
                   "aged": "stack snapshots of the game, {days} days old; they cannot be taken again"},
                  {"folder": snap.HEAPS_FOLDER,
                   "aged": "a heap snapshot of the game, {days} days old; it cannot be taken again, so compare against it first if memory matters"},
                  {"folder": pw.WATCH_FOLDER,
                   "aged": "a memory watch of the game, {days} days old; it cannot be taken again, so compare against it first if memory matters"}]

LOOK_NOTE = ("Takes a Windows snapshot of the running game (a pause of about half a second) and reads it with the game's own "
             "memory-reading library from its install folder; nothing is written to the game.")

# Only the reports that run another program attach to the game, and each says how in its own note; the rest read files (1.107.0).
MANIFEST = {"game": "rimworld", "parser": _parser, "effect": READS,
            "reports": {
    "report": {"question": "Where does my game spend its time, and which mods cause it?", "surface": PERFORMANCE_SURFACE},
    "record": {"effect": RUNS, "question": "What is my running game doing right now?", "surface": PERFORMANCE_SURFACE,
               "note": "Attaches Microsoft's dotnet-trace and dotnet-counters to the running game; it changes nothing in it."},
    "index": {"question": "What does a trace I recorded by hand say?"},
    "pack": {"effect": WRITES, "note": "With --apply, packs each recording's trace and each heap's own files with zstd in the "
                                       "kit's cache, removing a plain file only once its packed one reads back the same; without, "
                                       "only says."},
    "unpack": {"effect": WRITES, "note": "Writes one recording's trace or one heap's .gcdump out plain beside its packed copy, in "
                                         "the kit's cache; never writes over a file."},
    "mod": {"question": "What does one mod cost while the game runs?", "surface": PERFORMANCE_SURFACE},
    "callers": {"question": "Which code calls a slow method, and which mods lead to it?", "surface": PERFORMANCE_SURFACE},
    "list": {"question": "Which recordings and snapshots are kept?", "surface": PERFORMANCE_SURFACE,
             "note": "Each recording with its summary file (its figures, findings and mods' shares), made in the kit's cache the "
                     "first time a recording is listed after 1.152.0."},
    "reindex": {"effect": RUNS, "surface": PERFORMANCE_SURFACE, "note": "Runs Microsoft's dotnet-trace convert on a recording's kept trace (a file; no program is "
                                        "attached) and writes a new index for it in the kit's cache; the trace is untouched."},
    "compare": {"question": "Did a change make the game faster?", "surface": PERFORMANCE_SURFACE},
    "trend": {"question": "Have our own mods grown costlier from one recording to the next?", "surface": PERFORMANCE_SURFACE},
    "costs": {"question": "What does each mod cost, by the newest recording?", "surface": PERFORMANCE_SURFACE,
              "note": "Reads the recordings' summaries (made in the kit's cache the first time); the newest ten."},
    "stack": {"effect": RUNS, "question": "My game froze: where is it stuck, and whose code is it?",
              "note": "Attaches Microsoft's dotnet-stack to the running game a few times; it changes nothing in it."},
    "stack-report": {"question": "What did the stack snapshots show?"},
    "heap": {"effect": RUNS, "question": "What is holding my game's memory, and which mods?",
             "note": LOOK_NOTE + " With --gcdump it attaches Microsoft's dotnet-gcdump instead, which forces a full garbage "
                     "collection: the game pauses until it is done."},
    "heap-report": {"question": "What did a heap snapshot show?"},
    "heap-compare": {"question": "Is my game's memory growing, and whose?"},
    "watch": {"effect": RUNS, "question": "Does my game's memory climb steadily or in bursts, and is it .NET's or the engine's?",
              "note": "Reads Windows' memory figures without pausing the game; attaches dotnet-counters once unless --no-counters. "
                      "Ends early when watch-stop asks.", "surface": MEMORY_SURFACE},
    "watch-report": {"question": "What did a memory watch show?", "surface": MEMORY_SURFACE},
    "watch-status": {"question": "Is a memory watch running, and how is it going?", "surface": MEMORY_SURFACE,
                     "note": "Light enough to read every few seconds: the latest figures, the timeline so far, your marks, the watches kept."},
    "watch-stop": {"effect": WRITES, "surface": MEMORY_SURFACE,
                   "note": "Writes a stop file into the running watch's own folder in the kit's cache; the watch ends at its next look."},
    "watch-mark": {"effect": WRITES, "surface": MEMORY_SURFACE,
                   "note": "Adds the owner's words to the watch's own database in the kit's cache; nothing else."},
    "look": {"effect": RUNS, "surface": look.SURFACE, "question": "What is in my running game's memory, by type and by mod?",
             "note": LOOK_NOTE},
    "look-kind": {"effect": RUNS, "surface": look.SURFACE, "question": "Which objects of one kind are in my running game?",
                  "note": LOOK_NOTE},
    "look-why": {"effect": RUNS, "surface": look.SURFACE, "question": "Why is something still in my running game's memory?",
                 "note": LOOK_NOTE},
    "look-check": {"effect": RUNS, "surface": look.SURFACE,
                   "question": "Is anything in my running game in a state it should never be?",
                   "note": LOOK_NOTE + " One snapshot answers every live check in the file (docs/checks.md). Figures a "
                           "check notes are kept in the kit's cache for test-pass."},
    "look-thaw": {"effect": RUNS, "surface": look.SURFACE,
                  "question": "My game stands still after a look inside: can it run on?",
                  "note": "Resumes each of the game's threads once, only when every one of them is suspended (as a freezing "
                          "reader stopped early leaves it); changes nothing when any thread runs."},
    "look-serve": {"effect": RUNS, "surface": look.SURFACE,
                   "note": LOOK_NOTE + " Holds the snapshot and answers one JSON request a line on standard input until it closes "
                           "or the time limit passes; for a program's page, not a person's console."},
}}
