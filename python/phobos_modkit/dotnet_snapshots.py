"""One-off snapshots of a running .NET program: every thread's call stack, and what its managed heap holds, by type.

The text comes from Microsoft's `dotnet-stack report` and `dotnet-gcdump report` (https://learn.microsoft.com/dotnet/core/diagnostics/).
Their formats, as seen with version 10.0.750501 on 18 November 2026:

- dotnet-stack prints one block per thread: `Thread (0x35C0):`, then one frame a line, innermost first, each named
  `module!Namespace.Type.Method(arguments)`. A block may open with a marker instead of a frame: `CPU_TIME` (running managed
  code) or `[Native Frames]` (in native code: the engine, the operating system, or waiting). Threads have no names.
- dotnet-gcdump's report opens with the heap's total bytes and objects, then one row per type and size class:
  `average bytes of one object, count, type (size class), [module]`. A type's bytes are the average times the count; rows of
  one type in several size classes ("(Bytes > 1K)") are added together here.

Nothing here names a game. A game adapter passes in who owns each module, as for sampled traces (`sampling.Owner`).
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
from pathlib import Path
import re

from .sampling import CPU, FALLBACK_ORDER, GAME, MOD, NATIVE, RUNTIME, UNKNOWN, Owner, split_frame, type_of

_THREAD = re.compile(r"^Thread \((0x[0-9A-Fa-f]+)\):\s*$")
_MARKERS = {"CPU_TIME": CPU, "UNMANAGED_CODE_TIME": NATIVE, "[Native Frames]": NATIVE}
_TOTAL = re.compile(r"^\s*([\d,]+)\s+GC Heap (bytes|objects)\s*$")
_ROW = re.compile(r"^\s*([\d,]+)\s+([\d,]+)\s+(.+?)\s+\[([^\]]*)\]\s*$")
_SIZE_CLASS = re.compile(r"\s*\(Bytes > [\d.,]+\s*[KMG]?B?\)\s*$")
_TYPE_NAMES = re.compile(r"[A-Za-z_][\w.+`]*")
_MODULE_SUFFIX = re.compile(r"\.(dll|exe)$", re.IGNORECASE)


class SnapshotError(ValueError):
    pass


# ---- Stacks ----

@dataclass(frozen=True)
class Frame:
    name: str           # as the tool printed it
    module: str
    method: str         # Namespace.Type.Method, without arguments; a rewritten method by the original's name
    patched: bool       # Harmony rewrote it


@dataclass
class ThreadStack:
    thread: str                                   # the operating system's thread ID, as 0x35C0
    state: str = ""                               # CPU, NATIVE, or "" when the block opened with a frame
    frames: list = field(default_factory=list)    # innermost first


def frame(name):
    module, method, patched = split_frame(name)
    return Frame(name, module, method, patched)


def parse_stacks(text):
    """[ThreadStack] in the order the tool printed them. Raises SnapshotError when the text holds no thread."""
    threads, current = [], None
    for raw in text.splitlines():
        line = raw.strip()
        found = _THREAD.match(line)
        if found:
            current = ThreadStack(found.group(1).upper().replace("0X", "0x"))
            threads.append(current)
            continue
        if current is None or not line:
            continue
        if line in _MARKERS:
            if not current.frames and not current.state:
                current.state = _MARKERS[line]
            continue
        current.frames.append(frame(line))
    if not threads:
        raise SnapshotError("No thread's stack in the text: dotnet-stack printed something else.\n" + text[:500])
    return threads


def collapse(frames):
    """[(Frame, times)]: one row for a method that called itself several times in a row."""
    rows = []
    for item in frames:
        if rows and rows[-1][0].method == item.method:
            rows[-1][1] += 1
        else:
            rows.append([item, 1])
    return [(item, times) for item, times in rows]


def shared_outer(stacks):
    """How many outermost frames every one of the stacks has in common: the part of a call that never moved."""
    columns = zip(*[[f.name for f in reversed(stack)] for stack in stacks])
    shared = 0
    for column in columns:
        if len(set(column)) != 1:
            break
        shared += 1
    return shared


class Owners:
    """Who owns each frame: by its module, or, for a method Harmony rewrote, by the module of its type's other methods."""

    def __init__(self, by_module, frames, game_name="the game"):
        self.by_module = {k.lower(): v for k, v in by_module.items()}
        self.game = Owner(GAME, game_name)
        self.by_type = {}
        for item in frames:
            if not item.patched and item.module.lower() in self.by_module:
                self.by_type.setdefault(type_of(item.method), self.by_module[item.module.lower()])

    def of(self, item):
        if item.patched:
            return self.by_type.get(type_of(item.method)) or self.game
        return self.by_module.get(item.module.lower()) or Owner(UNKNOWN, item.module or "?")

    def caused_by(self, frames):
        """The innermost mod on a stack, else the first kind of FALLBACK_ORDER on it; None for an empty stack."""
        owners = [self.of(item) for item in frames]
        for owner in owners:
            if owner.kind == MOD:
                return owner
        for kind in FALLBACK_ORDER:
            for owner in owners:
                if owner.kind == kind:
                    return owner
        return None


# ---- The heap ----

@dataclass(frozen=True)
class HeapType:
    type: str
    module: str
    bytes: int
    count: int


@dataclass
class Heap:
    total_bytes: int
    total_objects: int
    types: list           # [HeapType], most bytes first

    def to_json(self):
        return json.dumps({"total_bytes": self.total_bytes, "total_objects": self.total_objects,
                           "types": [asdict(t) for t in self.types]}, indent=1)

    @staticmethod
    def from_json(text):
        data = json.loads(text)
        return Heap(data["total_bytes"], data["total_objects"], [HeapType(**t) for t in data["types"]])

    @staticmethod
    def read(path):
        return Heap.from_json(Path(path).read_text(encoding="utf-8"))


def _number(text):
    return int(text.replace(",", ""))


def parse_heapstat(text):
    """Heap from dotnet-gcdump's report. Raises SnapshotError when the text is not one."""
    totals, merged = {}, {}
    for line in text.splitlines():
        found = _TOTAL.match(line)
        if found:
            totals[found.group(2)] = _number(found.group(1))
            continue
        found = _ROW.match(line)
        if not found:
            continue
        average, count = _number(found.group(1)), _number(found.group(2))
        name = _SIZE_CLASS.sub("", found.group(3)).strip()
        module = _MODULE_SUFFIX.sub("", found.group(4).strip())
        key = (name, module)
        size, number = merged.get(key, (0, 0))
        merged[key] = (size + average * count, number + count)
    if "bytes" not in totals or not merged:
        raise SnapshotError("No heap totals or types in the text: dotnet-gcdump printed something else.\n" + text[:500])
    types = [HeapType(name, module, size, count) for (name, module), (size, count) in merged.items()]
    types.sort(key=lambda t: (-t.bytes, t.type, t.module))
    return Heap(totals["bytes"], totals.get("objects", sum(t.count for t in types)), types)


def _bare(type_name):
    """A type's name without its generic arguments or array marks."""
    return type_name.split("<", 1)[0].split("[", 1)[0].strip()


def heap_owners(heap, owner_of_module):
    """{(type, module): (Owner, through)}: who each row of the heap belongs to.

    A type belongs to its module's owner. A .NET collection whose generic arguments name a mod's type (a list or dictionary
    of that mod's things) is put down to that mod, `through` naming the type that decided it; otherwise `through` is "".
    """
    owners = {(t.type, t.module): owner_of_module(t.module) for t in heap.types}
    mod_types = {}
    for t in heap.types:
        owner = owners[(t.type, t.module)]
        if owner.kind == MOD:
            mod_types.setdefault(_bare(t.type), owner)
    result = {}
    for t in heap.types:
        owner, through = owners[(t.type, t.module)], ""
        if owner.kind in (RUNTIME, UNKNOWN) and "<" in t.type:
            inner = t.type[t.type.index("<"):]
            for name in _TYPE_NAMES.findall(inner):
                if name in mod_types:
                    owner, through = mod_types[name], name
                    break
        result[(t.type, t.module)] = (owner, through)
    return result
