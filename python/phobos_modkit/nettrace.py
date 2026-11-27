"""Microsoft's .nettrace files: the events a .NET runtime wrote while dotnet-trace recorded it, read in plain Python.

dotnet-trace keeps every event it was sent in a `.nettrace` file (EventPipe's own format; Microsoft documents it in PerfView's
repository, `src/TraceEvent/EventPipe/EventPipeFormat.md`, https://github.com/microsoft/perfview). Its speedscope export, which
`sampling` reads, keeps only the sampled stacks; the runtime's other events (a thread waiting on a lock, an allocation sampled
every 100 KB or so, a method compiled) are only here. This reads the file's own layout, version 4 of its "Trace" object (format V5,
what .NET 5 to 10 runtimes write; RimWorld 1.7's runtime wrote it, seen 28 November 2026), and nothing else:

- a header: when the trace began (UTC and the processor's high-resolution clock), the clock's ticks a second, the pointer size;
- metadata: which provider, event number, version and level each later event is;
- stacks: the instruction addresses of each stack, shared by number between events. **The numbers start again after every
  sequence point** (an SPBlock): seen in a trace of our own, 28 November 2026, where resolving them late gave half the lock waits
  another event's stack. So each event is given its addresses as it is read;
- events: their metadata, thread, time, stack and payload bytes. Payloads are decoded by the caller (`dotnet_events`), which knows
  the runtime's events.

Nothing here names a game, and nothing is run: the file is read as bytes.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import struct

MAGIC = b"Nettrace"
SERIALIZATION = b"!FastSerialization.1"
TRACE_VERSION = 4                      # the "Trace" object's version in format V5; V6 files (a later runtime's) are refused in words

# FastSerialization's tags
NULL_REFERENCE, BEGIN_OBJECT, END_OBJECT = 1, 5, 6

# The compressed event header's flags (EventPipeFormat.md, "Compressed header")
F_METADATA, F_CAPTURE, F_THREAD, F_STACK, F_ACTIVITY, F_RELATED, F_SORTED, F_LENGTH = 1, 2, 4, 8, 16, 32, 64, 128
MASK64 = (1 << 64) - 1


class NettraceError(ValueError):
    """A file this module cannot read, with the reason in words."""


@dataclass(frozen=True)
class EventKind:
    """What one metadata entry says a later event is."""
    provider: str
    event_id: int
    name: str
    version: int
    level: int
    keywords: int


@dataclass(frozen=True)
class Event:
    kind: EventKind
    thread: int                        # the operating system's thread ID
    timestamp: int                     # the high-resolution clock's ticks
    stack: int                         # a stack's number, good only until the next sequence point; 0 for none
    payload: bytes
    addresses: tuple = ()              # the stack's instruction addresses, innermost first, taken as the event was read


@dataclass(frozen=True)
class Header:
    start_utc: datetime
    start_ticks: int
    ticks_per_second: int
    pointer_size: int
    pid: int
    processors: int
    sampling_ns: int


class _Reader:
    __slots__ = ("data", "at")

    def __init__(self, data, at=0):
        self.data, self.at = data, at

    def take(self, n):
        if self.at + n > len(self.data):
            raise NettraceError("The trace ends in the middle of a record: it was cut off.")
        piece = self.data[self.at:self.at + n]
        self.at += n
        return piece

    def u8(self):
        return self.take(1)[0]

    def i32(self):
        return struct.unpack_from("<i", self.take(4))[0]

    def u16(self):
        return struct.unpack_from("<H", self.take(2))[0]

    def i64(self):
        return struct.unpack_from("<q", self.take(8))[0]

    def varint(self):
        result, shift = 0, 0
        while True:
            byte = self.u8()
            result |= (byte & 0x7F) << shift
            if byte < 0x80:
                return result
            shift += 7
            if shift > 63:
                raise NettraceError("A number in the trace is longer than any the format allows.")

    def utf16z(self):
        """A UTF-16 string ended by a zero character."""
        data, start = self.data, self.at
        end = start
        while end + 1 < len(data) and (data[end] or data[end + 1]):
            end += 2
        if end + 1 >= len(data):
            raise NettraceError("A name in the trace has no end.")
        self.at = end + 2
        return bytes(data[start:end]).decode("utf-16-le", errors="replace")


def utf16z(payload, at):
    """(text, the offset after it) of a zero-ended UTF-16 string in a payload; for decoders."""
    reader = _Reader(payload, at)
    return reader.utf16z(), reader.at


class Trace:
    """One .nettrace file, read whole into memory. `events()` walks it in file order; stacks are kept as they are met."""

    def __init__(self, data):
        self.data = memoryview(data)
        self.kinds = {}                      # metadata number -> EventKind
        self.stacks = {}                     # stack number -> addresses, innermost first, since the last sequence point
        reader = _Reader(self.data)
        if bytes(reader.take(len(MAGIC))) != MAGIC:
            raise NettraceError("This is not a .nettrace file: it does not start with Nettrace.")
        length = reader.i32()
        if bytes(reader.take(length)) != SERIALIZATION:
            raise NettraceError("This .nettrace file uses a serialization this reader does not know.")
        name, version = self._object_type(reader)
        if name != "Trace":
            raise NettraceError(f"The file's first object is {name!r}, not the trace's header.")
        if version != TRACE_VERSION:
            raise NettraceError(f"This .nettrace file is version {version} of the format; this reader knows version {TRACE_VERSION} "
                                "(format V5, what .NET 5 to 10 write).")
        y, mo, _, d, h, mi, s, msec = struct.unpack_from("<8H", reader.take(16))
        start_ticks, per_second = reader.i64(), reader.i64()
        pointer, pid, processors, sampling = reader.i32(), reader.i32(), reader.i32(), reader.i32()
        if reader.u8() != END_OBJECT:
            raise NettraceError("The trace's header does not end where the format says.")
        self.header = Header(datetime(y, mo, d, h, mi, s, msec * 1000, tzinfo=timezone.utc), start_ticks, per_second,
                             pointer, pid, processors, sampling)
        self._body = reader.at

    @classmethod
    def open(cls, path):
        """A trace from a file, plain or packed with zstd (`.zst`, as rimworld-perf keeps them)."""
        path = Path(path)
        if path.suffix == ".zst":
            from compression import zstd
            return cls(zstd.decompress(path.read_bytes()))
        return cls(path.read_bytes())

    def ms(self, timestamp):
        """Milliseconds from the trace's start to a timestamp."""
        return (timestamp - self.header.start_ticks) * 1000.0 / self.header.ticks_per_second

    @staticmethod
    def _object_type(reader):
        if reader.u8() != BEGIN_OBJECT or reader.u8() != BEGIN_OBJECT or reader.u8() != NULL_REFERENCE:
            raise NettraceError("An object in the trace does not start where the format says.")
        version, _minimum = reader.i32(), reader.i32()
        name = bytes(reader.take(reader.i32())).decode("ascii", errors="replace")
        if reader.u8() != END_OBJECT:
            raise NettraceError("An object's type in the trace does not end where the format says.")
        return name, version

    def blocks(self):
        """(name, block bytes) for every block after the header, in file order."""
        reader = _Reader(self.data, self._body)
        while True:
            if reader.at >= len(self.data):
                return                       # cut off after a whole block: read what there is
            if self.data[reader.at] == NULL_REFERENCE:
                return
            name, _ = self._object_type(reader)
            size = reader.i32()
            reader.at += (-reader.at) % 4    # blocks are aligned to four bytes from the start of the file
            block = reader.take(size)
            if reader.u8() != END_OBJECT:
                raise NettraceError(f"A {name} in the trace does not end where its size says.")
            yield name, block

    def events(self, wanted=None):
        """Every event in file order (by thread, then time within a thread's buffer); `wanted(kind)` skips others unread."""
        for name, block in self.blocks():
            if name == "MetadataBlock":
                for event in self._block_events(block, None):
                    self._metadata(event.payload)
            elif name == "StackBlock":
                self._stack_block(block)
            elif name == "SPBlock":
                self.stacks.clear()                # stack numbers start again after a sequence point
            elif name == "EventBlock":
                yield from self._block_events(block, wanted)

    def _stack_block(self, block):
        reader = _Reader(block)
        first, count = reader.i32(), reader.i32()
        size = self.header.pointer_size
        code = "<Q" if size == 8 else "<I"
        for number in range(first, first + count):
            raw = reader.take(reader.i32())
            self.stacks[number] = tuple(struct.unpack_from(code, raw, i)[0] for i in range(0, len(raw) - size + 1, size))

    def _metadata(self, payload):
        reader = _Reader(payload)
        number = reader.i32()
        provider = reader.utf16z()
        event_id = reader.i32()
        name = reader.utf16z()
        keywords, version, level = reader.i64(), reader.i32(), reader.i32()
        self.kinds[number] = EventKind(provider, event_id, name, version, level, keywords)

    def _block_events(self, block, wanted):
        reader = _Reader(block)
        header_size, flags = reader.u16(), reader.u16()
        reader.at = header_size
        if not flags & 1:
            raise NettraceError("This trace's events are written uncompressed, which this reader does not read.")
        metadata = sequence = thread = stack = timestamp = length = 0
        unknown = EventKind("?", 0, "", 0, 0, 0)
        data, end = reader.data, len(reader.data)
        while reader.at < end:
            bits = reader.u8()
            if bits & F_METADATA:
                metadata = reader.varint()
            if bits & F_CAPTURE:
                sequence += reader.varint() + 1
                reader.varint()                    # the thread that captured it
                reader.varint()                    # processor number
            elif metadata:
                sequence += 1
            if bits & F_THREAD:
                thread = reader.varint()
            if bits & F_STACK:
                stack = reader.varint()
            # A delta wraps at 64 bits: one thread's buffer can follow a later one's in a block, so time may step back (seen in
            # the owner's trace of 18 November 2026: a step of 2**64 - 963,673 ticks, 96 ms back).
            timestamp = (timestamp + reader.varint()) & MASK64
            if bits & F_ACTIVITY:
                reader.at += 16
            if bits & F_RELATED:
                reader.at += 16
            if bits & F_LENGTH:
                length = reader.varint()
            start = reader.at
            reader.at += length
            if reader.at > end:
                raise NettraceError("An event in the trace runs past the end of its block: the file was cut off.")
            kind = self.kinds.get(metadata, unknown) if metadata else None
            if wanted is not None and kind is not None and not wanted(kind):
                continue
            yield Event(kind or unknown, thread, timestamp, stack, bytes(data[start:reader.at]), self.stacks.get(stack, ()))
