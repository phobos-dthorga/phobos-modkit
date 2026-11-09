"""Read a Windows crash dump (a minidump, .dmp) without a debugger: what failed, on which thread, and whether a call loop ran away.

Reads only the file, and needs no symbols. The format facts follow Microsoft's published minidump structures (minidumpapiset.h).
A stack overflow is the case this is for: the faulting thread's stack is always in the dump, so a loop shows as the same return
addresses at a steady spacing, however little else the dump holds.
"""
from __future__ import annotations

import bisect
from collections import Counter
from dataclasses import dataclass, field
import mmap
from pathlib import Path
import struct

SIGNATURE = 0x504D444D
STREAM_THREADS, STREAM_MODULES, STREAM_MEMORY, STREAM_EXCEPTION, STREAM_MEMORY64 = 3, 4, 5, 6, 9
FLAG_FULL_MEMORY = 0x2
THREAD_SIZE, MODULE_SIZE = 48, 108
WORD = 8
# Where 64-bit Windows puts code: images and, close to them, the code a runtime compiles.
CODE_LOW, CODE_HIGH = 0x7FF000000000, 0x7FFF00000000
# A loop must repeat this often, with most repeats at one spacing, before it is called one.
LOOP_MIN_REPEATS = 50
LOOP_MIN_SHARE = 0.9
LEVELS_COMPARED = 40
STACK_OVERFLOW = 0xC00000FD

EXCEPTION_NAMES = {
    STACK_OVERFLOW: "stack overflow",
    0xC0000005: "access violation",
    0xC0000409: "stack buffer overrun or fail-fast",
    0xC0000374: "heap corruption",
    0xC000001D: "illegal instruction",
    0xC0000094: "integer divide by zero",
    0xC0000602: "fail-fast",
    0xE0434352: ".NET exception that was never caught",
    0x80000003: "breakpoint",
}
RUNTIMES = ("coreclr.dll", "clr.dll")


class DumpError(Exception):
    """The file is not a dump this can read."""


@dataclass
class Loop:
    repeats: int
    spacing_words: int
    # Offset within one level, in bytes, and the code address found there.
    return_addresses: list
    same_arguments: bool
    values_compared: int
    values_changing: int


@dataclass
class DumpSummary:
    path: Path
    size: int
    timestamp: int
    full_memory: bool
    exception_code: int | None
    exception_address: int | None
    thread_id: int | None
    stack_bytes: int
    module_count: int
    runtime: str | None
    loop: Loop | None
    code_modules: list = field(default_factory=list)    # (module or None, return-address-like words)

    @property
    def exception_name(self):
        return EXCEPTION_NAMES.get(self.exception_code, "unknown") if self.exception_code is not None else "none recorded"


def _streams(view):
    if len(view) < 32 or struct.unpack_from("<I", view, 0)[0] != SIGNATURE:
        raise DumpError("This is not a minidump: it does not start with the MDMP signature.")
    count, directory = struct.unpack_from("<II", view, 8)
    found = {}
    for i in range(count):
        kind, size, rva = struct.unpack_from("<III", view, directory + i * 12)
        found[kind] = (size, rva)
    return found


def _modules(view, streams):
    if STREAM_MODULES not in streams:
        return []
    _, rva = streams[STREAM_MODULES]
    count = struct.unpack_from("<I", view, rva)[0]
    modules = []
    for i in range(count):
        at = rva + 4 + i * MODULE_SIZE
        base, size = struct.unpack_from("<QI", view, at)
        name_rva = struct.unpack_from("<I", view, at + 20)[0]
        length = struct.unpack_from("<I", view, name_rva)[0]
        name = bytes(view[name_rva + 4:name_rva + 4 + length]).decode("utf-16-le", "replace").replace("/", "\\").rsplit("\\", 1)[-1]
        modules.append((base, base + size, name))
    modules.sort()
    return modules


def _stack_of(view, streams, thread_id):
    """The faulting thread's stack as (start address, words); the first thread when the dump names none."""
    if STREAM_THREADS not in streams:
        return 0, ()
    _, rva = streams[STREAM_THREADS]
    count = struct.unpack_from("<I", view, rva)[0]
    for i in range(count):
        at = rva + 4 + i * THREAD_SIZE
        if thread_id is None or struct.unpack_from("<I", view, at)[0] == thread_id:
            start, size, data = struct.unpack_from("<QII", view, at + 24)
            return start, struct.unpack_from(f"<{size // WORD}Q", view, data)
    return 0, ()


def find_loop(words, is_code=lambda value: CODE_LOW <= value < CODE_HIGH):
    """The repeating pattern on a stack, or None. The two words that bound a level change by a fixed step; everything else is what the level holds."""
    positions = {}
    for i, value in enumerate(words):
        if is_code(value):
            positions.setdefault(value, []).append(i)
    if not positions:
        return None
    top = max(sorted(positions), key=lambda value: len(positions[value]))
    places = positions[top]
    if len(places) < LOOP_MIN_REPEATS:
        return None
    gaps = Counter(b - a for a, b in zip(places, places[1:]))
    spacing, times = gaps.most_common(1)[0]
    if spacing <= 0 or times / (len(places) - 1) < LOOP_MIN_SHARE:
        return None
    start = places[len(places) // 2]
    if start + spacing * LEVELS_COMPARED > len(words):
        start = places[0]
    levels = min(LEVELS_COMPARED, (len(words) - start) // spacing)
    returns, compared, changing = [], 0, 0
    for k in range(spacing):
        seen = {words[start + k + spacing * level] for level in range(levels)}
        value = words[start + k]
        if is_code(value) and len(seen) == 1:
            returns.append((k * WORD, value))
            continue
        if len(seen) == 1 and value < 0x10000:
            continue    # zeros and small numbers say nothing about which object this is
        # Saved stack pointers change by exactly one level's size; they are the stack's own bookkeeping, not arguments.
        ordered = [words[start + k + spacing * level] for level in range(levels)]
        steps = {b - a for a, b in zip(ordered, ordered[1:])}
        if len(steps) == 1 and abs(next(iter(steps))) == spacing * WORD:
            continue
        compared += 1
        if len(seen) > 1:
            changing += 1
    return Loop(len(places), spacing, returns, changing == 0, compared, changing)


def read_dump(path):
    path = Path(path)
    try:
        with open(path, "rb") as handle:
            view = mmap.mmap(handle.fileno(), 0, access=mmap.ACCESS_READ)
    except (OSError, ValueError) as failed:
        raise DumpError(f"Cannot read {path}: {failed}") from failed
    try:
        return _summarise(path, view)
    except struct.error as failed:
        raise DumpError(f"{path} is cut short or damaged: {failed}") from failed
    finally:
        view.close()


def _summarise(path, view):
    streams = _streams(view)
    timestamp, flags = struct.unpack_from("<IQ", view, 20)
    code = address = thread_id = None
    if STREAM_EXCEPTION in streams:
        _, rva = streams[STREAM_EXCEPTION]
        thread_id = struct.unpack_from("<I", view, rva)[0]
        code = struct.unpack_from("<I", view, rva + 8)[0]
        address = struct.unpack_from("<Q", view, rva + 24)[0]
    modules = _modules(view, streams)
    starts = [m[0] for m in modules]

    def module_of(value):
        i = bisect.bisect_right(starts, value) - 1
        return modules[i][2] if i >= 0 and modules[i][0] <= value < modules[i][1] else None

    _, words = _stack_of(view, streams, thread_id)
    tally = Counter(module_of(w) for w in words if CODE_LOW <= w < CODE_HIGH)
    names = {m[2].lower() for m in modules}
    runtime = next((name for name in RUNTIMES if name in names), None)
    return DumpSummary(path, len(view), timestamp, bool(flags & FLAG_FULL_MEMORY), code, address, thread_id, len(words) * WORD, len(modules), runtime,
                       find_loop(words), sorted(tally.items(), key=lambda item: (-item[1], item[0] or "")))


def newest_dump(folder, program=None):
    """The newest .dmp in a folder, for one program when named; None if there are none."""
    pattern = f"{program}*.dmp" if program else "*.dmp"
    found = sorted(Path(folder).glob(pattern), key=lambda p: (p.stat().st_mtime_ns, p.name))
    return found[-1] if found else None
