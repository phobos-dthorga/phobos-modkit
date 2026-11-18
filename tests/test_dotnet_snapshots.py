"""Stack and heap snapshots: dotnet-stack's and dotnet-gcdump's text, who owns what, and rimworld-perf's stack and heap reports.

The texts are written by hand in the shape version 10.0.750501 printed for a small test program on 18 November 2026; nothing here
reads a real game.
"""
import io
from datetime import datetime
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock

import support  # noqa: F401  (the package on the import path)
from phobos_modkit import dotnet_diagnostics as dd
from phobos_modkit.dotnet_snapshots import (Owners, SnapshotError, collapse, heap_owners, parse_heapstat, parse_stacks,
                                            shared_outer)
from phobos_modkit.games.rimworld import perf, perf_cli
from phobos_modkit.games.rimworld import perf_snapshots as snap
from phobos_modkit.sampling import GAME, MOD, RUNTIME, UNKNOWN, Owner

MAIN_STUCK = """Thread (0x35C0):
  CPU_TIME
  ExampleMedical!Example.Dosing.DoseService.Loop(int32)
  ExampleMedical!Example.Dosing.DoseService.MakeJob()
  Assembly-CSharp!Verse.TickManager.DoSingleTick()
  Assembly-CSharp!Verse.Root_Play.Update()

Thread (0xC9E8):
  [Native Frames]
  System.Private.CoreLib.il!System.Threading.Thread.Sleep(int32)
  System.Private.CoreLib.il!System.Threading.Thread.StartCallback()

Thread (0x1111):
  [Native Frames]
  Assembly-CSharp!Verse.LongEventHandler.ExecuteToExecuteWhenFinished()
"""
MAIN_MOVING = MAIN_STUCK.replace("Example.Dosing.DoseService.Loop(int32)", "Example.Dosing.DoseService.Score(int32)")
HEAPSTAT = """     21,696,794  GC Heap bytes
         44,028  GC Heap objects

   Object Bytes     Count  Type
        262,168         1  Example.Dosing.Dose[] (Bytes > 100K)  [ExampleMedical.dll]
          1,024    20,000  System.Byte[] (Bytes > 1K)  [System.Private.CoreLib.dll]
             32    20,000  Example.Dosing.Dose  [ExampleMedical.dll]
             32         1  System.Collections.Generic.List<Example.Dosing.Dose>  [System.Private.CoreLib.dll]
             24        61  System.Byte[]  [System.Private.CoreLib.dll]
             40       100  Verse.Thing  [Assembly-CSharp.dll]
"""
OWNERS = {"ExampleMedical": Owner(MOD, "Example Medical"), "Assembly-CSharp": Owner(GAME, "RimWorld"),
          "System.Private.CoreLib": Owner(RUNTIME, ".NET")}


class StackTextTests(unittest.TestCase):
    def test_threads_frames_and_states(self):
        threads = parse_stacks(MAIN_STUCK)
        self.assertEqual(["0x35C0", "0xC9E8", "0x1111"], [t.thread for t in threads])
        self.assertEqual("cpu", threads[0].state)
        self.assertEqual("native", threads[1].state)
        self.assertEqual("Example.Dosing.DoseService.Loop", threads[0].frames[0].method)
        self.assertEqual("ExampleMedical", threads[0].frames[0].module)
        self.assertEqual("System.Private.CoreLib", threads[1].frames[0].module)

    def test_text_without_threads_is_refused(self):
        with self.assertRaises(SnapshotError):
            parse_stacks("Unable to connect to the process.")

    def test_repeated_calls_collapse(self):
        frames = parse_stacks("Thread (0x1):\n  A!X.Y.Recurse()\n  A!X.Y.Recurse()\n  A!X.Y.Main()\n")[0].frames
        self.assertEqual([("X.Y.Recurse", 2), ("X.Y.Main", 1)], [(f.method, n) for f, n in collapse(frames)])

    def test_shared_outer_frames(self):
        a, b = parse_stacks(MAIN_STUCK)[0].frames, parse_stacks(MAIN_MOVING)[0].frames
        self.assertEqual(3, shared_outer([a, b]))
        self.assertEqual(4, shared_outer([a, a]))

    def test_the_innermost_mod_causes_it(self):
        frames = parse_stacks(MAIN_STUCK)[0].frames
        self.assertEqual(Owner(MOD, "Example Medical"), Owners(OWNERS, frames).caused_by(frames))

    def test_a_rewritten_method_belongs_to_its_types_module(self):
        frames = parse_stacks("Thread (0x1):\n  Unknown!dynamicClass.Example.Dosing.DoseService.MakeJob_Patch2(pMT)\n"
                              "  ExampleMedical!Example.Dosing.DoseService.Loop(int32)\n")[0].frames
        self.assertEqual(Owner(MOD, "Example Medical"), Owners(OWNERS, frames).of(frames[0]))


class HeapTextTests(unittest.TestCase):
    def test_totals_and_merged_size_classes(self):
        heap = parse_heapstat(HEAPSTAT)
        self.assertEqual((21_696_794, 44_028), (heap.total_bytes, heap.total_objects))
        byte_arrays = [t for t in heap.types if t.type == "System.Byte[]"]
        self.assertEqual(1, len(byte_arrays))
        self.assertEqual((1024 * 20000 + 24 * 61, 20061), (byte_arrays[0].bytes, byte_arrays[0].count))
        self.assertEqual("System.Byte[]", heap.types[0].type)
        self.assertEqual("ExampleMedical", heap.types[1].module)

    def test_round_trip(self):
        heap = parse_heapstat(HEAPSTAT)
        self.assertEqual(heap, type(heap).from_json(heap.to_json()))

    def test_text_without_a_heap_is_refused(self):
        with self.assertRaises(SnapshotError):
            parse_heapstat("Writing gcdump to 'x'...")

    def test_a_collection_of_a_mods_type_is_the_mods(self):
        owners = heap_owners(parse_heapstat(HEAPSTAT), lambda m: OWNERS.get(m) or Owner(UNKNOWN, m))
        owner, through = owners[("System.Collections.Generic.List<Example.Dosing.Dose>", "System.Private.CoreLib")]
        self.assertEqual((Owner(MOD, "Example Medical"), "Example.Dosing.Dose"), (owner, through))
        self.assertEqual((Owner(RUNTIME, ".NET"), ""), owners[("System.Byte[]", "System.Private.CoreLib")])


class ToolTests(unittest.TestCase):
    def test_ensure_installs_only_what_is_missing(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        (tmp / dd.native.program_name(dd.STACK)).write_bytes(b"")
        calls = []

        def run(command, **_):
            calls.append(command)
            (tmp / dd.native.program_name(command[3])).write_bytes(b"")
            return subprocess.CompletedProcess(command, 0, "", "")
        found, installed = dd.ensure([dd.STACK, dd.GCDUMP], {dd.TOOLS_ENV: str(tmp)}, run, which=lambda name: None)
        self.assertTrue(installed)
        self.assertEqual([dd.GCDUMP], [c[3] for c in calls])
        self.assertEqual({dd.STACK, dd.GCDUMP}, set(found))

    def test_a_failing_tool_says_so(self):
        run = lambda command, **_: subprocess.CompletedProcess(command, 1, "", "no such process")  # noqa: E731
        with self.assertRaises(dd.DiagnosticsError) as raised:
            dd.stack_text(4242, "dotnet-stack", run)
        self.assertIn("no such process", str(raised.exception))


class FakeTools:
    """Stands in for dotnet-stack and dotnet-gcdump: answers from the texts above, the stack moving or not."""

    def __init__(self, stacks):
        self.stacks = list(stacks)

    def __call__(self, command, **_):
        if command[0].endswith(dd.native.program_name("tasklist")) or command[0] == "tasklist":
            return subprocess.CompletedProcess(command, 0, '"RimWorld.exe","4242","Console","1","1 K"\n', "")
        if "report" in command and "-p" in command:
            return subprocess.CompletedProcess(command, 0, self.stacks.pop(0), "")
        if "collect" in command:
            Path(command[command.index("-o") + 1]).write_bytes(b"gcdump")
            return subprocess.CompletedProcess(command, 0, "Warning: the target runtime does not support non-lossy (Block) buffering\n", "")
        if "report" in command:
            return subprocess.CompletedProcess(command, 0, HEAPSTAT, "")
        raise AssertionError(command)


class CommandTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        tools = self.tmp / "tools"
        tools.mkdir()
        for name in (dd.STACK, dd.GCDUMP):
            (tools / dd.native.program_name(name)).write_bytes(b"")
        self.environ = {"PHOBOS_MODKIT_CACHE": str(self.tmp / "cache"), dd.TOOLS_ENV: str(tools)}
        self.common = ["--game", str(self.tmp / "game"), "--config", str(self.tmp / "config")]
        owners = mock.patch.object(perf, "module_owners", side_effect=lambda names, *a, **k: ({n: OWNERS[n] for n in names if n in OWNERS}, []))
        owners.start()
        self.addCleanup(owners.stop)
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def run_cli(self, *argv, run, now=datetime(2026, 11, 18, 21, 0, 0)):
        out = io.StringIO()
        code = perf_cli.main(list(argv), environ=self.environ, out=out, run=run, now=now, sleep=lambda s: None)
        return code, out.getvalue()

    def test_a_stuck_main_thread(self):
        with mock.patch.object(dd, "find_processes", return_value=[(4242, "RimWorld")]):
            code, text = self.run_cli("stack", "--label", "frozen", *self.common, run=FakeTools([MAIN_STUCK] * 3))
        self.assertEqual(perf_cli.EXIT_OK, code, text)
        self.assertIn("The main thread is 0x35C0: it runs the game's loop.", text)
        self.assertIn("**The main thread did not move", text)
        self.assertIn("ticking (the simulation); ticking (the simulation); ticking (the simulation)", text)
        self.assertIn("Example Medical; Example Medical; Example Medical", text)
        self.assertIn("| 1 | Example.Dosing.DoseService.Loop | Example Medical | yes |", text)
        self.assertIn("| 0x1111 |", text)
        code, again = self.run_cli("stack-report", "frozen", *self.common, run=FakeTools([]))
        self.assertEqual(perf_cli.EXIT_OK, code, again)
        self.assertIn("did not move", again)

    def test_a_busy_main_thread_names_the_frame_that_never_moved(self):
        with mock.patch.object(dd, "find_processes", return_value=[(4242, "RimWorld")]):
            code, text = self.run_cli("stack", "--times", "2", *self.common, run=FakeTools([MAIN_STUCK, MAIN_MOVING]))
        self.assertEqual(perf_cli.EXIT_OK, code, text)
        self.assertIn("busy under **Example.Dosing.DoseService.MakeJob** in all 2 snapshots", text)
        self.assertIn("| 1 | Example.Dosing.DoseService.Score | Example Medical |  |", text)

    def test_stack_without_the_game(self):
        with mock.patch.object(dd, "find_processes", return_value=[]):
            code, text = self.run_cli("stack", *self.common, run=FakeTools([]))
        self.assertEqual(perf_cli.EXIT_FAILED, code)
        self.assertIn("RimWorld is not running", text)

    def test_heap_report_compare_and_list(self):
        with mock.patch.object(dd, "find_processes", return_value=[(4242, "RimWorld")]):
            code, text = self.run_cli("heap", "--label", "day 40", *self.common, run=FakeTools([]))
            self.assertEqual(perf_cli.EXIT_OK, code, text)
            self.assertIn("**21.7 MB in 44,028 objects**", text)
            self.assertIn("can drop events on a large heap", text)
            self.assertIn("| Example Medical | mod |", text)
            self.assertIn("System.Collections.Generic.List<Example.Dosing.Dose> | Example Medical (through Example.Dosing.Dose)", text)
            folder = self.tmp / "cache" / snap.HEAPS_FOLDER / "20261118-210000-day-40"
            self.assertTrue((folder / snap.HEAP_FILE).is_file())
            code, text = self.run_cli("heap", *self.common, run=FakeTools([]), now=datetime(2026, 11, 18, 22, 0, 0))
        self.assertEqual(perf_cli.EXIT_OK, code, text)
        code, text = self.run_cli("heap-compare", *self.common, run=FakeTools([]))
        self.assertEqual(perf_cli.EXIT_OK, code, text)
        self.assertIn("(0)**", text)
        code, text = self.run_cli("list", *self.common, run=FakeTools([]))
        self.assertIn("Heap snapshots, newest first", text)
        self.assertLess(text.index("20261118-220000"), text.index("20261118-210000-day-40"))

    def test_compare_needs_two_heaps(self):
        code, text = self.run_cli("heap-compare", *self.common, run=FakeTools([]))
        self.assertEqual(perf_cli.EXIT_FAILED, code)
        self.assertIn("Fewer than two heaps", text)


if __name__ == "__main__":
    unittest.main()
