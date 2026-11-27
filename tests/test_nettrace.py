"""The .nettrace reader and the runtime's events on made-up traces (nettrace_builder): nothing attaches to a program.

The made-up program, in the shape of a RimWorld frame: its main thread (100) waits 5 ms on a lock in a game method that a mod's
code called, held by thread 200; it allocates once in another mod's postfix and once in the engine's drawing.
"""
import struct
import tempfile
import unittest
from pathlib import Path

import support  # noqa: F401  (puts the kit on the path)
from nettrace_builder import Builder, utf16z
from phobos_modkit import dotnet_events as events
from phobos_modkit import nettrace

CORELIB, GAME, MEDICAL, OTHER, ENGINE = 1, 2, 3, 4, 5
MODULES = {CORELIB: r"C:\Game\System.Private.CoreLib.dll", GAME: r"C:\Game\Assembly-CSharp.dll", MEDICAL: r"C:\Mods\ExampleMedical.dll",
           OTHER: r"C:\Mods\OtherMod.dll", ENGINE: r"C:\Game\Waylith.dll"}
# (start address, module, namespace, name, signature)
METHODS = [(0x1000, CORELIB, "System.Threading.Monitor", "Enter_Slowpath", "void  (class System.Object)"),
           (0x2000, GAME, "Verse.PawnCapacityUtility", "CalculateCapacityLevel", "float32  (class Verse.HediffSet,class Verse.PawnCapacityDef)"),
           (0x3000, MEDICAL, "Example.Dosing.DoseService", "MakeJob", "class Verse.AI.Job  (class Verse.Pawn,class Verse.Pawn,bool)"),
           (0x4000, GAME, "Verse.TickManager", "DoSingleTick", "void  ()"),
           (0x5000, GAME, "Verse.Root_Play", "Update", "void  ()"),
           (0x6000, CORELIB, "System.Collections.Generic.List`1[System.__Canon]", "Add", "void  (!0)"),
           (0x7000, OTHER, "Other.Patches.Pawn_Tick", "Postfix", "void  (class Verse.Pawn)"),
           (0x8000, ENGINE, "Waylith.Rendering", "Submit", "void  ()"),
           (0x9000, GAME, "Verse.Map", "MapUpdate", "void  ()")]
SIZE = 0x100


def made_up_trace(sequence_point=True):
    """Bytes of a trace: modules and methods (as the end-of-trace rundown gives them), one lock wait, two allocations."""
    b = Builder()
    module = b.kind(events.RUNDOWN, 154, version=2)
    method = b.kind(events.RUNDOWN, 144, version=1)
    start = b.kind(events.RUNTIME, events.CONTENTION_START, version=2)
    stop = b.kind(events.RUNTIME, events.CONTENTION_STOP, version=1)
    tick = b.kind(events.RUNTIME, events.ALLOCATION_TICK, version=4)
    waiting = b.stack(0x1010, 0x2020, 0x3030, 0x4040, 0x5050)
    b.events([(start, 100, waiting, 10.0, struct.pack("<BHQQQ", 0, 0, 0xAB00, 0xCD00, 200)),
              (stop, 100, 0, 15.0, struct.pack("<BHd", 0, 0, 5_000_000.0))])
    if sequence_point:
        b.sequence_point()              # the next stack is number 1 again, with other addresses
    postfix = b.stack(0x6010, 0x7010, 0x4010, 0x5010)
    drawing = b.stack(0x8010, 0x9010, 0x5020)

    def allocation(type_name, amount):
        return struct.pack("<IIHQQ", amount, 0, 0, amount, 0x77) + utf16z(type_name) + struct.pack("<IQQ", 0, 0, 0)
    b.events([(tick, 100, postfix, 50.0, allocation("Example.Dose", 102_400)),
              (tick, 100, drawing, 80.0, allocation("System.String", 204_800))])
    b.events([(module, 1, 0, 110.0, struct.pack("<QQII", number, 0, 0, 0) + utf16z(path) + utf16z("") + struct.pack("<H", 0))
              for number, path in MODULES.items()])
    b.events([(method, 1, 0, 110.0, struct.pack("<QQQIII", i, mod, address, SIZE, 0, 0) + utf16z(namespace) + utf16z(name)
               + utf16z(signature) + struct.pack("<H", 0)) for i, (address, mod, namespace, name, signature) in enumerate(METHODS)])
    return b.bytes()


class ReaderTests(unittest.TestCase):
    def test_the_header(self):
        trace = nettrace.Trace(made_up_trace())
        self.assertEqual((8, 4242, 10_000_000), (trace.header.pointer_size, trace.header.pid, trace.header.ticks_per_second))
        self.assertEqual(2026, trace.header.start_utc.year)

    def test_events_carry_their_kind_thread_time_and_stack(self):
        trace = nettrace.Trace(made_up_trace())
        found = [e for e in trace.events() if e.kind.event_id == events.CONTENTION_START]
        self.assertEqual(1, len(found))
        self.assertEqual((events.RUNTIME, 2, 100), (found[0].kind.provider, found[0].kind.version, found[0].thread))
        self.assertAlmostEqual(10.0, trace.ms(found[0].timestamp))
        self.assertEqual((0x1010, 0x2020, 0x3030, 0x4040, 0x5050), found[0].addresses)

    def test_stack_numbers_start_again_after_a_sequence_point(self):
        # Seen in a real trace (28 Nov 2026): resolving stack numbers after reading gave half the waits another event's stack.
        trace = nettrace.Trace(made_up_trace())
        ticks = [e for e in trace.events() if e.kind.event_id == events.ALLOCATION_TICK]
        self.assertEqual((0x6010, 0x7010, 0x4010, 0x5010), ticks[0].addresses)
        self.assertEqual(1, ticks[0].stack)

    def test_wanted_skips_other_events(self):
        trace = nettrace.Trace(made_up_trace())
        self.assertEqual({events.CONTENTION_STOP}, {e.kind.event_id for e in trace.events(lambda k: k.event_id == events.CONTENTION_STOP)})

    def test_not_a_trace(self):
        with self.assertRaises(nettrace.NettraceError):
            nettrace.Trace(b"Something else entirely")
        with self.assertRaises(nettrace.NettraceError):
            nettrace.Trace(made_up_trace()[:40])                  # cut off inside its header

    def test_a_packed_trace_opens(self):
        from compression import zstd
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "trace.nettrace.zst"
            path.write_bytes(zstd.compress(made_up_trace()))
            self.assertEqual(4242, nettrace.Trace.open(path).header.pid)


class EventTests(unittest.TestCase):
    def setUp(self):
        self.waits, self.allocations, self.methods = events.read(nettrace.Trace(made_up_trace()))

    def test_a_stack_is_named_as_dotnet_trace_names_it(self):
        self.assertEqual(("System.Private.CoreLib!System.Threading.Monitor.Enter_Slowpath(class System.Object)",
                          "Assembly-CSharp!Verse.PawnCapacityUtility.CalculateCapacityLevel(class Verse.HediffSet,class Verse.PawnCapacityDef)",
                          "ExampleMedical!Example.Dosing.DoseService.MakeJob(class Verse.Pawn,class Verse.Pawn,bool)",
                          "Assembly-CSharp!Verse.TickManager.DoSingleTick()", "Assembly-CSharp!Verse.Root_Play.Update()"),
                         self.waits[0].stack)
        self.assertIsNone(self.methods.name(0x1000 + SIZE))      # past the method's end
        self.assertIsNone(self.methods.name(0x10))

    def test_a_wait_pairs_its_start_and_stop(self):
        wait = self.waits[0]
        self.assertEqual((100, 200, 0xAB00, 0xCD00), (wait.thread, wait.owner_thread, wait.lock_id, wait.object_id))
        self.assertAlmostEqual(10.0, wait.start_ms)
        self.assertAlmostEqual(5.0, wait.ms)                       # the runtime's own nanoseconds

    def test_allocations(self):
        self.assertEqual([("Example.Dose", 102_400, "OtherMod!Other.Patches.Pawn_Tick.Postfix(class Verse.Pawn)"),
                          ("System.String", 204_800, "Waylith!Waylith.Rendering.Submit()")],
                         [(a.type, a.bytes, a.stack[1] if a.type == "Example.Dose" else a.stack[0]) for a in self.allocations])

    def test_the_provider_text(self):
        self.assertEqual("Microsoft-Windows-DotNETRuntime:0x100003C01D:4", events.runtime_provider())
        self.assertEqual("Microsoft-Windows-DotNETRuntime:0x100003C01D:5", events.runtime_provider(allocations=True))


if __name__ == "__main__":
    unittest.main()
