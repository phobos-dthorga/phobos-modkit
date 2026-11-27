"""Writes small .nettrace files for tests, in format V5 as nettrace.py reads it (PerfView's EventPipeFormat.md). Made-up events
only: a header, metadata, stacks and compressed events, laid out as .NET 5 to 10 runtimes write them."""
import struct

TICKS_PER_SECOND = 10_000_000
START_TICKS = 1_000_000_000


def _i32(value):
    return struct.pack("<i", value)


def _i64(value):
    return struct.pack("<q", value)


def _varint(value):
    out = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        if value:
            out.append(byte | 0x80)
        else:
            out.append(byte)
            return bytes(out)


def utf16z(text):
    return text.encode("utf-16-le") + b"\0\0"


def _type(name, version):
    return bytes([5, 5, 1]) + _i32(version) + _i32(version) + _i32(len(name)) + name.encode("ascii") + bytes([6])


class Builder:
    """Build one trace: add metadata, stacks and events in order, then bytes()."""

    def __init__(self, pointer_size=8):
        self.pointer_size = pointer_size
        self.out = bytearray(b"Nettrace" + _i32(20) + b"!FastSerialization.1")
        self.out += _type("Trace", 4)
        self.out += struct.pack("<8H", 2026, 11, 2, 28, 1, 2, 3, 0)
        self.out += _i64(START_TICKS) + _i64(TICKS_PER_SECOND) + _i32(pointer_size) + _i32(4242) + _i32(8) + _i32(1_000_000)
        self.out.append(6)
        self._next_metadata = 1
        self._next_stack = 1

    def _block(self, name, payload):
        self.out += _type(name, 2) + _i32(len(payload))
        self.out += b"\0" * ((-len(self.out)) % 4)
        self.out += payload
        self.out.append(6)

    @staticmethod
    def _events(records):
        """A compressed event block: records are (metadata id, thread, stack, ticks, payload)."""
        body = bytearray(struct.pack("<HH", 20, 1) + _i64(0) + _i64(0))
        last = 0
        for metadata, thread, stack, ticks, payload in records:
            flags = 2 | 4 | 8 | 128 | (1 if metadata else 0)
            body.append(flags)
            if metadata:
                body += _varint(metadata)
            body += _varint(0) + _varint(thread) + _varint(0)     # sequence step, capture thread, processor
            body += _varint(thread) + _varint(stack)
            body += _varint((ticks - last) & ((1 << 64) - 1))
            last = ticks
            body += _varint(len(payload)) + payload
        return bytes(body)

    def kind(self, provider, event_id, version=0, name=""):
        """Declares an event kind; returns its metadata number."""
        number = self._next_metadata
        self._next_metadata += 1
        payload = (_i32(number) + utf16z(provider) + _i32(event_id) + utf16z(name) + _i64(0) + _i32(version) + _i32(4) + _i32(0))
        self._block("MetadataBlock", self._events([(0, 0, 0, 0, payload)]))
        return number

    def stack(self, *addresses):
        """Declares a stack, innermost address first; returns its number."""
        number = self._next_stack
        self._next_stack += 1
        code = "<Q" if self.pointer_size == 8 else "<I"
        raw = b"".join(struct.pack(code, a) for a in addresses)
        self._block("StackBlock", _i32(number) + _i32(1) + _i32(len(raw)) + raw)
        return number

    def sequence_point(self):
        """A sequence point: the runtime starts its stack numbers again after one."""
        self._block("SPBlock", _i64(START_TICKS) + _i32(0))
        self._next_stack = 1

    def events(self, records):
        """records: (metadata number, thread, stack number, milliseconds after the start, payload)."""
        self._block("EventBlock", self._events([(m, t, s, START_TICKS + int(ms * TICKS_PER_SECOND / 1000), p)
                                                for m, t, s, ms, p in records]))

    def bytes(self):
        return bytes(self.out) + bytes([1])
