"""rimworld-perf's snapshots: where a frozen or stuck game is (every thread's stack), and what holds its memory (the heap by type).

A recording samples time; a snapshot shows one instant. `stack` takes a few snapshots of every thread's stack a moment apart
with Microsoft's dotnet-stack: a main thread whose stack never moves is stuck, and its frames say where and whose code it is.
`heap` writes the managed heap with dotnet-gcdump, which forces a full garbage collection first, and reports it by type and by
the mod each type belongs to; `heap-compare` sets two heaps side by side, the way to see memory that keeps growing.

Snapshots are kept in the kit's cache (`rimworld-stacks/`, `rimworld-heaps/`), outside every repository. The .gcdump file stays
beside its report, for PerfView or Visual Studio, which can show what holds what.
"""
from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
import re
import time

from ... import __version__
from ... import cache as derived
from ... import dotnet_diagnostics as dd
from ...dotnet_snapshots import Heap, Owners, collapse, heap_owners, parse_heapstat, parse_stacks, shared_outer
from ...report import Bullets, Report, Table
from ...sampling import CPU, GAME, MOD, NATIVE, RUNTIME, UNKNOWN, Owner
from . import perf

STACKS_FOLDER, HEAPS_FOLDER = "rimworld-stacks", "rimworld-heaps"
META, HEAP_DATA, HEAP_TEXT, HEAP_FILE = "meta.json", "heap.json", "heapstat.txt", "heap.gcdump"
SNAPSHOT = "snapshot-{n}.txt"
DEFAULT_TIMES, DEFAULT_EVERY, DEFAULT_FRAMES = 3, 2.0, 40
MAX_TIMES = 10
STACK_CAVEAT = ("A snapshot shows where each thread was at one instant; taking one stops the game for a moment. It is not an "
                "in-game test of whether anything works.")
STACK_LIMITS = ["A small method the compiler folded into its caller does not show as a frame of its own, and work a "
                "transpiler adds inside a game method counts as the game's.",
                "Native code (the engine, the operating system) shows only as [Native Frames]: a thread waiting there "
                "shows where it waits, not what for."]
HEAP_CAVEAT = ("Taking it forced a full garbage collection, so the game paused until it was done. It measures memory; it is not "
               "an in-game test.")
HEAP_LIMITS = ["Memory counts under the type that is it: the arrays and strings a mod's objects hold count as .NET's. Where a "
               ".NET collection names a mod's type (a list or dictionary of that mod's things), it is put down to that mod.",
               "What holds what is not in this report: open the .gcdump file kept beside it in PerfView or Visual Studio for "
               "the paths from the roots."]
LOSSY_NOTE = ("dotnet-gcdump warned that this runtime can drop events on a large heap, so the counts can come out low and differ "
              "between two heaps for that reason alone. Trust a difference that repeats.")
LEAK_NOTE = ("A heap that keeps growing across several snapshots of the same game, minutes apart and with the same thing on "
             "screen, is the sign of a leak. Two snapshots can mislead: take a third.")


class SnapshotsError(RuntimeError):
    pass


def size(value):
    for unit, scale in (("GB", 1e9), ("MB", 1e6), ("KB", 1e3)):
        if abs(value) >= scale:
            return f"{value / scale:,.1f} {unit}"
    return f"{value:,.0f} bytes"


def signed_size(value):
    return ("+" if value > 0 else "") + size(value) if value else "0"


def pct(part, whole):
    return f"{100 * part / whole:.1f}%" if whole else "0.0%"


# ---- Kept snapshots ----

def new_folder(root, label, now):
    slug = re.sub(r"[^a-z0-9]+", "-", (label or "").lower()).strip("-")[:40]
    name = now.strftime("%Y%m%d-%H%M%S") + (f"-{slug}" if slug else "")
    folder = Path(root) / name
    if folder.exists():
        raise SnapshotsError(f"A snapshot named {name} already exists; wait a second and try again.")
    folder.mkdir(parents=True)
    return folder


def kept(root):
    root = Path(root)
    return sorted(p for p in root.iterdir() if (p / META).is_file()) if root.is_dir() else []


def meta_of(folder):
    return json.loads((Path(folder) / META).read_text(encoding="utf-8"))


def find(root, text, what):
    found = kept(root)
    if not found:
        raise SnapshotsError(f"No {what} kept in {root}.")
    if not text:
        return found[-1]
    wanted = text.lower()
    matches = [p for p in found if p.name.lower().startswith(wanted)] or \
              [p for p in found if wanted in (meta_of(p).get("label") or "").lower()]
    if len(matches) != 1:
        raise SnapshotsError(f'"{text}" matches {len(matches)} {what}. Kept: ' + ", ".join(p.name for p in found) + ".")
    return matches[0]


def _write_meta(folder, meta):
    (Path(folder) / META).write_text(json.dumps(meta, indent=1), encoding="utf-8")


# ---- Stacks ----

def take_stacks(pid, folder, tool, times, every, run, sleep=time.sleep, now=None, label=""):
    """Write `times` snapshots of every thread's stack into folder, `every` seconds apart. Returns their texts."""
    if not 1 <= times <= MAX_TIMES:
        raise SnapshotsError(f"--times must be between 1 and {MAX_TIMES}.")
    texts = []
    for n in range(1, times + 1):
        if n > 1:
            sleep(every)
        text = dd.stack_text(pid, tool, run)
        (Path(folder) / SNAPSHOT.format(n=n)).write_text(text, encoding="utf-8")
        texts.append(text)
    _write_meta(folder, {"kit_version": __version__, "taken_at": (now or datetime.now()).strftime("%Y-%m-%d %H:%M:%S"),
                         "label": label or "", "pid": pid, "times": times, "every": every, "tools_version": dd.TOOLS_VERSION})
    return texts


def read_stacks(folder):
    meta = meta_of(folder)
    texts = [(Path(folder) / SNAPSHOT.format(n=n)).read_text(encoding="utf-8") for n in range(1, int(meta["times"]) + 1)]
    return meta, [parse_stacks(text) for text in texts]


def _main(snapshot, owners):
    """(the thread running the game's loop, how it was chosen)."""
    for stack in snapshot:
        if perf.is_main_loop(stack):
            return stack, "it runs the game's loop"
    best = max(snapshot, key=lambda s: (sum(1 for f in s.frames if owners.of(f).kind in (GAME, MOD, UNKNOWN)), s.state == CPU,
                                        len(s.frames)), default=None)
    return best, ("no thread was in the game's loop, so this is the thread with the most frames from the game and its mods, "
                  "a running one first")


def stack_report(folder, meta, snapshots, owner_map, notes, frames_shown=DEFAULT_FRAMES, top=15):
    all_frames = [f for snapshot in snapshots for s in snapshot for f in s.frames]
    owners = Owners(owner_map, all_frames, perf.GAME_NAME)
    label = f' ("{meta["label"]}")' if meta.get("label") else ""
    count = len(snapshots)
    report = Report(f"rimworld-perf: stacks {Path(folder).name}")
    report.lines.append(f"{count} snapshot{'s' if count != 1 else ''} of every thread's stack{label}, "
                        f"{meta.get('every', '?')} s apart, at {meta.get('taken_at', '?')}: {len(snapshots[-1])} threads in the last.")
    report.lines.append(STACK_CAVEAT)
    for note in notes:
        report.lines.append(note)
    mains = []
    for snapshot in snapshots:
        stack, why = _main(snapshot, owners)
        mains.append((stack, why))
    stack, why = mains[-1]
    if stack is None:
        report.lines.append("**No thread had a stack of managed code.** The game may have been closing.")
        return report
    report.lines.append(f"The main thread is {stack.thread}: {why}.")
    ids = {s.thread for s, _ in mains if s is not None}
    frames_by_snapshot = [s.frames for s, _ in mains if s is not None]
    shared = shared_outer(frames_by_snapshot) if len(frames_by_snapshot) > 1 else 0
    if count > 1 and len(ids) == 1:
        if all(f == frames_by_snapshot[0] for f in frames_by_snapshot):
            report.lines.append(f"**The main thread did not move: its stack was the same in all {count} snapshots.** It is stuck in "
                                "a loop that never ends or a wait that is never answered, at the frames below.")
        elif shared:
            outer = list(reversed(frames_by_snapshot[-1]))[shared - 1]
            report.lines.append(f"The main thread moved, but its outer {shared} frames were the same every time: it was busy under "
                                f"**{outer.method}** in all {count} snapshots. A very long loop there, or the same slow work again and again.")
        else:
            report.lines.append("The main thread's stack was different in every snapshot: the game was running, not stuck.")
    elif count > 1:
        report.lines.append("A different thread ran the game's loop between snapshots, so they cannot be compared.")
    phases = [perf.phase_of_frames(s.frames) or "outside the named parts" for s, _ in mains if s is not None]
    report.lines.append("Part of the game loop, snapshot by snapshot: " + "; ".join(phases) + ".")
    causes = [owners.caused_by(s.frames) for s, _ in mains if s is not None]
    report.lines.append("Caused by (the innermost mod on its stack, else the game): "
                        + "; ".join(c.name if c else "nothing" for c in causes) + ".")
    depth = len(stack.frames)
    in_shared_from = depth - shared
    table, at = [], 0
    for item, times in collapse(stack.frames)[:frames_shown]:
        owner = owners.of(item)
        still = "yes" if count > 1 and at >= in_shared_from else ""
        name = item.method + (" (patched)" if item.patched else "") + (f" x{times}" if times > 1 else "")
        table.append((at + 1, name, owner.name, still))
        at += times
    more = depth - at
    state = {NATIVE: "in native code", CPU: "running managed code"}.get(stack.state, "")
    heading = f"The main thread {stack.thread}, innermost first (the last snapshot{', ' + state if state else ''})"
    report.section(heading, Table(["#", "Method", "Owner", "In every snapshot"], table))
    if more > 0:
        report.lines.append(f"{more} more frames toward the root are not shown (--frames shows more).")
    others = []
    for other in snapshots[-1]:
        if other is stack or not other.frames:
            continue
        cause = owners.caused_by(other.frames)
        if cause is None or cause.kind == RUNTIME:
            continue
        others.append((other.thread, {NATIVE: "native or waiting", CPU: "running"}.get(other.state, ""),
                       other.frames[0].method, cause.name))
    quiet = len(snapshots[-1]) - 1 - len(others)
    if others:
        report.section("Other threads with the game's or a mod's code on their stack",
                       Table(["Thread", "State", "Innermost method", "Caused by"], others[:top], len(others)))
    report.lines.append(f"{quiet} other threads held only .NET's own code.")
    report.section("What a snapshot cannot say", Bullets(STACK_LIMITS))
    return report


# ---- Heaps ----

def take_heap(pid, folder, tool, run, now=None, label=""):
    """Write the heap's file and its table into folder; return (Heap, the tool's warnings)."""
    warnings = dd.collect_gcdump(pid, Path(folder) / HEAP_FILE, tool, run)
    text = dd.gcdump_text(Path(folder) / HEAP_FILE, tool, run)
    (Path(folder) / HEAP_TEXT).write_text(text, encoding="utf-8")
    heap = parse_heapstat(text)
    (Path(folder) / HEAP_DATA).write_text(heap.to_json(), encoding="utf-8")
    _write_meta(folder, {"kit_version": __version__, "taken_at": (now or datetime.now()).strftime("%Y-%m-%d %H:%M:%S"),
                         "label": label or "", "pid": pid, "warnings": warnings, "tools_version": dd.TOOLS_VERSION})
    return heap, warnings


def read_heap(folder):
    return meta_of(folder), Heap.read(Path(folder) / HEAP_DATA)


def _by_owner(heap, owners):
    totals = {}
    for t in heap.types:
        owner, through = owners[(t.type, t.module)]
        entry = totals.setdefault(owner, [0, 0, 0])
        entry[0] += t.bytes
        entry[1] += t.count
        if through:
            entry[2] += t.bytes
    return totals


def heap_report(folder, meta, heap, owner_map, notes, top=15):
    owners = heap_owners(heap, lambda module: owner_map.get(module) or Owner(UNKNOWN, module or "?"))
    label = f' ("{meta["label"]}")' if meta.get("label") else ""
    report = Report(f"rimworld-perf: heap {Path(folder).name}")
    report.lines.append(f"**{size(heap.total_bytes)} in {heap.total_objects:,} objects** on the managed heap{label}, at "
                        f"{meta.get('taken_at', '?')}.")
    report.lines.append(HEAP_CAVEAT)
    for warning in meta.get("warnings") or []:
        report.lines.append(LOSSY_NOTE if "lossy" in warning.lower() else f"dotnet-gcdump warned: {warning}")
    for note in notes:
        report.lines.append(note)
    totals = _by_owner(heap, owners)
    rows = [(o.name, o.kind, size(b), pct(b, heap.total_bytes), f"{n:,}", size(c) if c else "")
            for o, (b, n, c) in sorted(totals.items(), key=lambda kv: (-kv[1][0], kv[0].name))[:top]]
    report.section("Who the heap belongs to", Table(["Owner", "Kind", "Bytes", "Share", "Objects", "Of it in .NET collections of its types"],
                                                    rows, len(totals)))
    rows = []
    for t in heap.types[:top]:
        owner, through = owners[(t.type, t.module)]
        rows.append((t.type, owner.name + (f" (through {through})" if through else ""), size(t.bytes), pct(t.bytes, heap.total_bytes), f"{t.count:,}"))
    report.section("The largest types", Table(["Type", "Owner", "Bytes", "Share", "Objects"], rows, len(heap.types)))
    mods = sorted((o for o in totals if o.kind == MOD), key=lambda o: -totals[o][0])
    if mods:
        rows = []
        for owner in mods[:top]:
            biggest = max((t for t in heap.types if owners[(t.type, t.module)][0] == owner), key=lambda t: t.bytes)
            rows.append((owner.name, size(totals[owner][0]), biggest.type, size(biggest.bytes)))
        report.section("Each mod's largest type", Table(["Mod", "All its types", "Largest type", "Its bytes"], rows, len(mods)))
    report.lines.append(f"The heap file is kept for PerfView or Visual Studio: {Path(folder) / HEAP_FILE}")
    report.section("What a heap snapshot cannot say", Bullets(HEAP_LIMITS))
    return report


def heap_compare(names, before, after, owner_map, top=15):
    owner_of = lambda module: owner_map.get(module) or Owner(UNKNOWN, module or "?")  # noqa: E731
    owners_a, owners_b = heap_owners(before, owner_of), heap_owners(after, owner_of)
    report = Report(f"rimworld-perf: heap {names[0]} against {names[1]}")
    change = after.total_bytes - before.total_bytes
    report.lines.append(f"**{size(before.total_bytes)}, then {size(after.total_bytes)} ({signed_size(change)})**; objects "
                        f"{before.total_objects:,}, then {after.total_objects:,}.")
    report.lines.append(LEAK_NOTE)
    a, b = _by_owner(before, owners_a), _by_owner(after, owners_b)
    keys = sorted(set(a) | set(b), key=lambda o: (-abs(b.get(o, [0])[0] - a.get(o, [0])[0]), o.name))
    rows = [(o.name, o.kind, size(a.get(o, [0])[0]), size(b.get(o, [0])[0]), signed_size(b.get(o, [0])[0] - a.get(o, [0])[0]))
            for o in keys[:top]]
    report.section("Who changed most", Table(["Owner", "Kind", "Before", "After", "Change"], rows, len(keys)))
    types_a = {(t.type, t.module): t for t in before.types}
    types_b = {(t.type, t.module): t for t in after.types}
    empty = Owner(UNKNOWN, "?")

    def delta(key):
        return (types_b[key].bytes if key in types_b else 0) - (types_a[key].bytes if key in types_a else 0)
    changed = sorted((k for k in set(types_a) | set(types_b) if delta(k)), key=lambda k: (-delta(k), k))
    rows = []
    for key in changed[:top]:
        owner = (owners_b.get(key) or owners_a.get(key) or (empty, ""))[0]
        count = (types_b[key].count if key in types_b else 0) - (types_a[key].count if key in types_a else 0)
        rows.append((key[0], owner.name, size(types_a[key].bytes) if key in types_a else "-",
                     size(types_b[key].bytes) if key in types_b else "-", signed_size(delta(key)), f"{count:+,}"))
    report.section("Types that grew most", Table(["Type", "Owner", "Before", "After", "Change", "Objects"], rows, len(changed)))
    return report


def list_sections(report, stacks_root, heaps_root):
    for title, root in (("Stack snapshots", stacks_root), ("Heap snapshots", heaps_root)):
        found = kept(root)
        if found:
            rows = [(p.name, meta_of(p).get("taken_at", "?"), meta_of(p).get("label", "")) for p in reversed(found)]
            report.section(f"{title}, newest first", Table(["Snapshot", "Taken at", "Label"], rows))


def roots(cache_arg, environ, settings_file):
    return (derived.folder(STACKS_FOLDER, cache_arg, environ, settings_file),
            derived.folder(HEAPS_FOLDER, cache_arg, environ, settings_file))
