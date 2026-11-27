"""The .NET runtime's own events in a .nettrace file, decoded: where methods' code lies (to name a stack), a thread waiting on a
lock, and an allocation sampled about every 100 KB. Game-free.

The layouts are Microsoft's, from the runtime's event manifest (ClrEtwAll.man in dotnet/runtime) and its documentation
(https://learn.microsoft.com/dotnet/fundamentals/diagnostics/runtime-events), checked on 28 November 2026 against a trace of a small
program of our own on .NET 10 (two threads taking one lock in turns) with the providers rimworld-perf asks for:

- **Methods**: MethodLoadVerbose (runtime event 143) while tracing and MethodDCEndVerbose (rundown event 144) at the end, each
  version 1 or 2: method ID, module ID, start address, size, token, flags, namespace, name and signature. Modules: ModuleLoad
  (runtime 152) and ModuleDCEnd (rundown 154), version 2: module ID, assembly ID, flags, a reserved word, then the module's path.
- **ContentionStart**, runtime event 81, version 2 (.NET 8 on): flags, instance, the lock's ID, the object locked, and the thread
  holding it. **ContentionStop**, 91, version 1: flags, instance, and the wait in nanoseconds.
- **GCAllocationTick**, runtime event 10, version 2 to 4: the bytes allocated since the last tick (about 100 KB), the kind, the
  instance, the same as 64 bits, the type's ID and its name.
"""
from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass
from pathlib import PureWindowsPath
import struct

from .nettrace import utf16z

RUNTIME = "Microsoft-Windows-DotNETRuntime"
RUNDOWN = "Microsoft-Windows-DotNETRuntimeRundown"
SAMPLER = "Microsoft-DotNETCore-SampleProfiler"
METHOD_EVENTS = {(RUNTIME, 143), (RUNTIME, 144), (RUNDOWN, 143), (RUNDOWN, 144)}
MODULE_EVENTS = {(RUNTIME, 152), (RUNDOWN, 153), (RUNDOWN, 154)}
CONTENTION_START, CONTENTION_STOP, ALLOCATION_TICK = 81, 91, 10

# dotnet-trace's runtime provider for a recording: its default profile's keywords (0x100003801D, "dotnet-common"), with lock
# contention (0x4000) added; Verbose (5) adds the allocation tick (GC keyword 0x1 at verbose level).
CONTENTION_KEYWORD = 0x4000
COMMON_KEYWORDS = 0x100003801D
INFORMATIONAL, VERBOSE = 4, 5


def runtime_provider(allocations=False):
    """dotnet-trace's --providers text for the runtime: its common events, lock contention, and allocations when asked."""
    return f"{RUNTIME}:0x{COMMON_KEYWORDS | CONTENTION_KEYWORD:X}:{VERBOSE if allocations else INFORMATIONAL}"


@dataclass(frozen=True)
class Wait:
    thread: int                # the waiting thread (the operating system's ID)
    start_ms: float
    ms: float
    lock_id: int
    object_id: int
    owner_thread: int          # the thread holding the lock as the wait began; 0 when the runtime did not say
    stack: tuple               # frame names, innermost first


@dataclass(frozen=True)
class Allocation:
    thread: int
    at_ms: float
    type: str
    bytes: int                 # allocated since the last tick, all of it put down to this type (the one that crossed the line)
    stack: tuple


class Methods:
    """Where each method's compiled code lies, from the trace's method and module events: names a stack's addresses."""

    def __init__(self):
        self.modules = {}            # module ID -> module name
        self._ranges = []            # (start, end, namespace, name, signature, module ID)
        self._starts = None

    def add_module(self, payload):
        module_id = struct.unpack_from("<Q", payload, 0)[0]
        path, _ = utf16z(payload, 24)
        if path:
            self.modules[module_id] = PureWindowsPath(path).stem

    def add_method(self, payload):
        _, module_id, start, size = struct.unpack_from("<QQQI", payload, 0)
        namespace, at = utf16z(payload, 36)
        name, at = utf16z(payload, at)
        signature, _ = utf16z(payload, at)
        if size:
            self._ranges.append((start, start + size, namespace, name, signature, module_id))
            self._starts = None

    def name(self, address):
        """'module!Namespace.Type.Method(arguments)' for an address in compiled code, as dotnet-trace's speedscope names it, or None."""
        if self._starts is None:
            self._ranges.sort()
            self._starts = [r[0] for r in self._ranges]
        i = bisect_right(self._starts, address) - 1
        if i < 0:
            return None
        start, end, namespace, name, signature, module_id = self._ranges[i]
        if address >= end:
            return None
        arguments = signature[signature.find("("):] if "(" in signature else "()"
        method = f"{namespace}.{name}" if namespace else name
        return f"{self.modules.get(module_id, '?')}!{method}{arguments}"

    def stack(self, addresses):
        """Frame names, innermost first, for a stack's addresses; addresses outside compiled .NET code are left out."""
        return tuple(n for n in (self.name(a) for a in addresses) if n is not None)


def read(trace):
    """(waits, allocations, methods) from a nettrace.Trace, in one pass. A wait is a ContentionStart and the same thread's next
    ContentionStop; its length is the runtime's own when it gives one, else the time between them."""
    methods = Methods()
    pending, raw_waits, raw_allocations = {}, [], []
    pointer = trace.header.pointer_size
    code = "<Q" if pointer == 8 else "<I"
    for event in trace.events():
        kind = (event.kind.provider, event.kind.event_id)
        if kind in METHOD_EVENTS:
            methods.add_method(event.payload)
        elif kind in MODULE_EVENTS:
            methods.add_module(event.payload)
        elif kind == (RUNTIME, CONTENTION_START):
            lock_id = object_id = owner = 0
            if event.kind.version >= 2 and len(event.payload) >= 3 + 2 * pointer + 8:
                lock_id = struct.unpack_from(code, event.payload, 3)[0]
                object_id = struct.unpack_from(code, event.payload, 3 + pointer)[0]
                owner = struct.unpack_from("<Q", event.payload, 3 + 2 * pointer)[0]
            pending[event.thread] = (event.timestamp, lock_id, object_id, owner, event.addresses)
        elif kind == (RUNTIME, CONTENTION_STOP):
            started = pending.pop(event.thread, None)
            if started is None:
                continue
            timestamp, lock_id, object_id, owner, stack = started
            if event.kind.version >= 1 and len(event.payload) >= 11:
                ms = struct.unpack_from("<d", event.payload, 3)[0] / 1e6
            else:
                ms = (event.timestamp - timestamp) * 1000.0 / trace.header.ticks_per_second
            raw_waits.append((event.thread, trace.ms(timestamp), ms, lock_id, object_id, owner, stack))
        elif kind == (RUNTIME, ALLOCATION_TICK) and event.kind.version >= 2:
            amount = struct.unpack_from("<Q", event.payload, 10)[0]
            type_name, _ = utf16z(event.payload, 18 + pointer)
            raw_allocations.append((event.thread, trace.ms(event.timestamp), type_name, amount, event.addresses))
    names = {}

    def stack_of(addresses):
        if addresses not in names:
            names[addresses] = methods.stack(addresses)
        return names[addresses]

    waits = [Wait(t, start, ms, lock, obj, owner, stack_of(s)) for t, start, ms, lock, obj, owner, s in raw_waits]
    allocations = [Allocation(t, at, name, amount, stack_of(s)) for t, at, name, amount, s in raw_allocations]
    return waits, allocations, methods
