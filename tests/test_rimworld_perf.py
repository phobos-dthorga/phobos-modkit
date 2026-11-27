"""rimworld-perf and the sampling core on a made-up trace of a game loop (fixtures/rimworld/perf). Nothing attaches to a program.

The fixture's main thread, in milliseconds: 0-40 a mod's method calling a game method from inside a patched Pawn.Tick, while
ticking; 40-60 another mod's postfix calling a .NET list; 60-70 the patched Pawn.Tick itself; 70-100 the engine drawing the map,
in native code; 100-110 the frame update itself. A second thread waits for its whole 100 ms.
"""
import io
from datetime import datetime
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock

from support import FIXTURES
from phobos_modkit import dotnet_diagnostics as dd
from phobos_modkit import packed
from phobos_modkit import sampling
from phobos_modkit.games.rimworld import perf, perf_cli
from phobos_modkit.games.rimworld import perf_snapshots as snap
from phobos_modkit.sampling import ENGINE, GAME, LIBRARY, MOD, RUNTIME, UNKNOWN, Owner

TRACE = FIXTURES / "rimworld" / "perf" / "main-loop.speedscope.json"
COUNTERS = FIXTURES / "rimworld" / "perf" / "counters.json"
MODS = {"examplemedical": "Example Medical", "othermod": "Other Mod"}


def indexed(tmp):
    index = Path(tmp) / "index.sqlite"
    sampling.index_speedscope(TRACE, index, {"game_name": "RimWorld"})
    sampling.write_owners(index, perf.classify(sampling.modules(index), {"waylith"}, MODS))
    sampling.write_counters(index, sampling.read_counters(COUNTERS))
    return sampling.Recording(index)


def named(shares):
    return {owner.name: round(share.total, 3) for owner, share in shares.items()}


class FrameNameTests(unittest.TestCase):
    def test_a_method_frame(self):
        self.assertEqual(("Assembly-CSharp", "Verse.Map.MapUpdate", False), sampling.split_frame("Assembly-CSharp!Verse.Map.MapUpdate()"))

    def test_a_runtime_module_loses_its_suffix(self):
        module, method, _ = sampling.split_frame("System.Private.CoreLib.il!System.Collections.Generic.List`1[System.__Canon].Add(!0)")
        self.assertEqual(("System.Private.CoreLib", "System.Collections.Generic.List`1[System.__Canon].Add"), (module, method))

    def test_a_method_harmony_rewrote(self):
        self.assertEqual(("Assembly-CSharp", "Verse.Pawn.Tick", True),
                         sampling.split_frame("Assembly-CSharp!dynamicClass.DMD<Verse.Pawn::Tick>(class Verse.Pawn)"))

    def test_a_method_harmony_3_rewrote(self):
        # Harmony 3 on .NET: the original's name with a patch count, and the glue it adds for a patched method.
        self.assertEqual(("0Harmony", "Verse.TickManager.DoSingleTick", True),
                         sampling.split_frame("0Harmony!dynamicClass.Verse.TickManager.DoSingleTick_Patch6(pMT: 00007FFBE8CD49D0)"))
        self.assertEqual(("0Harmony", "Verse.AI.Pawn_JobTracker.DetermineNextConstantThinkTreeJob", True),
                         sampling.split_frame("0Harmony!dynamicClass.Glue:AbiFixup<Verse.AI.ThinkResult Verse.AI.Pawn_JobTracker:"
                                              "DetermineNextConstantThinkTreeJob(),Verse.AI.ThinkResult Verse.AI.Pawn_JobTracker."
                                              "DetermineNextConstantThinkTreeJob()>(pMT: 00007FF)"))
        # A method whose own name only ends in a number is not a patch.
        self.assertEqual(("Assembly-CSharp", "Verse.Gen.Patch2", False), sampling.split_frame("Assembly-CSharp!Verse.Gen.Patch2()"))

    def test_the_game_loop_is_found_through_harmony_3s_names(self):
        # The loop's own methods under Harmony 3's names, as in the owner's recording of 18 November 2026.
        phases, ticking = perf.phases()
        for name in ("0Harmony!dynamicClass.Verse.TickManager.DoSingleTick_Patch6(pMT: 1)", "0Harmony!dynamicClass.Verse.Map.MapUpdate_Patch5(pMT: 1)"):
            method = sampling.split_frame(name)[1]
            self.assertTrue(any(__import__("fnmatch").fnmatchcase(method, p) for _, patterns in phases for p in patterns), name)

    def test_a_marker_without_a_module(self):
        self.assertEqual(("", "Threads", False), sampling.split_frame("Threads"))


class ClassifyTests(unittest.TestCase):
    def test_every_kind(self):
        owners = perf.classify(["Assembly-CSharp", "Waylith", "System.Private.CoreLib", "0Harmony", "MonoMod.Core",
                                "ExampleMedical", "Mystery"], {"waylith"}, MODS)
        self.assertEqual(Owner(GAME, "RimWorld"), owners["Assembly-CSharp"])
        self.assertEqual(ENGINE, owners["Waylith"].kind)
        self.assertEqual(Owner(RUNTIME, ".NET"), owners["System.Private.CoreLib"])
        self.assertEqual(Owner(LIBRARY, "Harmony"), owners["0Harmony"])
        self.assertEqual(Owner(LIBRARY, "Harmony"), owners["MonoMod.Core"])
        self.assertEqual(Owner(MOD, "Example Medical"), owners["ExampleMedical"])
        self.assertEqual(Owner(UNKNOWN, "Mystery"), owners["Mystery"])

    def test_the_phases_file_names_the_ticking_phase(self):
        phases, ticking = perf.phases()
        self.assertIn(ticking, [label for label, _ in phases])


class RecordingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.rec = indexed(self.tmp)
        self.main = self.rec.main_thread()
        self.samples = self.rec.thread_samples(self.main)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_the_main_thread_is_the_busiest_in_managed_code(self):
        self.assertEqual("thread 100", self.rec.thread_label(self.main))
        self.assertEqual(110, self.rec.duration_ms(self.main))

    def test_phases(self):
        phases, _ = perf.phases()
        by_phase = {k: round(v.total, 3) for k, v in self.rec.by_phase(self.samples, phases).items()}
        self.assertEqual({"ticking (the simulation)": 70, "map and world drawing": 30, None: 10}, by_phase)

    def test_the_innermost_mod_causes_the_time(self):
        # With no mod on the stack the game caused it, the engine's drawing included; where the thread was says engine.
        self.assertEqual({"Example Medical": 40, "Other Mod": 20, "RimWorld": 50}, named(self.rec.by_owner(self.samples)))

    def test_native_time_is_kept_apart(self):
        game = next(s for o, s in self.rec.by_owner(self.samples).items() if o.kind == GAME)
        self.assertEqual((20, 30), (game.cpu, game.native))
        engine = next(s for (m, o, _), s in self.rec.self_methods(self.samples).items() if o.kind == ENGINE)
        self.assertEqual((0, 30), (engine.cpu, engine.native))

    def test_where_the_thread_was(self):
        found = {(m, o.name, p): round(s.total, 3) for (m, o, p), s in self.rec.self_methods(self.samples).items()}
        self.assertEqual(40, found[("Verse.PawnCapacityUtility.CalculateCapacityLevel", "RimWorld", False)])
        self.assertEqual(20, found[("System.Collections.Generic.List`1[System.__Canon].Add", ".NET", False)])
        self.assertEqual(10, found[("Verse.Pawn.Tick", "RimWorld", True)])

    def test_inclusive_methods_count_each_stack_once(self):
        mods = self.rec.inclusive_methods(self.samples, lambda o, p: o.kind == MOD)
        self.assertEqual({"Example.Dosing.DoseService.MakeJob": 40, "Other.Patches.Pawn_Tick.Postfix": 20},
                         {m: round(s.total, 3) for (m, _, _), s in mods.items()})
        patched = self.rec.inclusive_methods(self.samples, lambda o, p: p)
        self.assertEqual({"Verse.Pawn.Tick": 70}, {m: round(s.total, 3) for (m, _, _), s in patched.items()})

    def test_no_mod_calls_another_in_the_fixture(self):
        self.assertEqual({}, self.rec.mod_calls(self.samples))
        self.assertIsNone(self.rec.outermost_mod(0))

    def test_counters(self):
        mean, worst, count = self.rec.counter("dotnet.gc.pause.time")
        self.assertAlmostEqual(0.03, mean)
        self.assertAlmostEqual(0.04, worst)
        self.assertEqual(2, count)
        self.assertEqual({"gc.heap.generation=gen0"}, set(self.rec.counters_named("dotnet.gc.collections")))

    def test_a_method_is_matched_by_its_end_or_by_wildcards(self):
        match = sampling.method_matcher("PawnCapacityUtility.CalculateCapacityLevel")
        self.assertTrue(match("Verse.PawnCapacityUtility.CalculateCapacityLevel"))
        self.assertFalse(match("Verse.OtherPawnCapacityUtility.CalculateCapacityLevel"))
        self.assertTrue(sampling.method_matcher("*capacity*")("Verse.PawnCapacityUtility.CalculateCapacityLevel"))
        # Brackets in generic names are plain text, never a character class.
        self.assertTrue(sampling.method_matcher("List`1[System.__Canon].Add")("System.Collections.Generic.List`1[System.__Canon].Add"))
        self.assertFalse(sampling.method_matcher("Tick")("Verse.TickManager.DoSingleTick"))

    def test_callers_of_a_patched_game_method(self):
        found = self.rec.callers(self.samples, sampling.method_matcher("Pawn.Tick"))
        self.assertEqual(70, round(found.total.total, 3))
        self.assertEqual({"Verse.TickManager.DoSingleTick": 70}, {m: round(s.total, 3) for (m, _), s in found.direct.items()})
        self.assertEqual({sampling.NO_MOD: 70}, {o: round(s.total, 3) for o, s in found.inner.items()})
        self.assertEqual({"Verse.PawnCapacityUtility.CalculateCapacityLevel": 40, "System.Collections.Generic.List`1[System.__Canon].Add": 20,
                          "Verse.Pawn.Tick": 10}, {m: round(s.total, 3) for (m, _), s in found.leaf.items()})

    def test_callers_name_the_mods_above(self):
        found = self.rec.callers(self.samples, sampling.method_matcher("CalculateCapacityLevel"))
        self.assertEqual({"Example.Dosing.DoseService.MakeJob": 40}, {m: round(s.total, 3) for (m, _), s in found.owned.items()})
        self.assertEqual({"Example Medical": 40}, {o.name: round(s.total, 3) for o, s in found.inner.items()})
        self.assertEqual({"Example Medical": 40}, {o.name: round(s.total, 3) for o, s in found.outer.items()})

    def test_hot_spots_put_game_time_back_together(self):
        spots = {m: (round(s.total.total, 3), {o.name or "none": round(v.total, 3) for o, v in s.mods.items()})
                 for (m, _), s in self.rec.hot_spots(self.samples).items()}
        # A mod's own work (the postfix calling a .NET list) is not a hot spot: its busiest methods show it.
        self.assertEqual({"Verse.PawnCapacityUtility.CalculateCapacityLevel": (40, {"Example Medical": 40}),
                          "Verse.Pawn.Tick": (10, {"none": 10}), "Waylith.Rendering.Submit": (30, {"none": 30}),
                          "Verse.Root_Play.Update": (10, {"none": 10})}, spots)

    def test_a_file_that_is_not_a_trace(self):
        bad = Path(self.tmp) / "bad.json"
        bad.write_text('{"profiles": []}', encoding="utf-8")
        with self.assertRaises(sampling.SamplingError):
            sampling.index_speedscope(bad, Path(self.tmp) / "bad.sqlite")


class DiagnosticsTests(unittest.TestCase):
    def test_duration(self):
        self.assertEqual("00:00:01:05", dd.duration_text(65))

    def test_find_processes_on_windows(self):
        out = '"RimWorld.exe","4242","Console","1","1,000 K"\r\n'
        run = lambda *a, **k: subprocess.CompletedProcess(a, 0, out, "")
        self.assertEqual([(4242, "RimWorld")], dd.find_processes("RimWorld", run, platform="win32"))

    def test_find_processes_elsewhere(self):
        out = " 77 /opt/game/RimWorld\n 78 bash\n"
        run = lambda *a, **k: subprocess.CompletedProcess(a, 0, out, "")
        self.assertEqual([(77, "RimWorld")], dd.find_processes("RimWorld", run, platform="linux"))


class FakeProcess:
    """Stands in for dotnet-trace or dotnet-counters: writes what the real tool would, from the fixtures."""

    def __init__(self, command, **_):
        out = Path(command[command.index("-o") + 1])
        if "Speedscope" in command:
            shutil.copyfile(TRACE, out.with_name("trace" + dd.SPEEDSCOPE_SUFFIX))
            out.write_bytes(b"nettrace")
        else:
            shutil.copyfile(COUNTERS, out)

    def wait(self, timeout=None):
        return 0

    def kill(self):
        pass


class CommandTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.tools = self.tmp / "tools"
        self.tools.mkdir()
        for name in (dd.TRACE, dd.COUNTERS):
            (self.tools / dd.native.program_name(name)).write_bytes(b"")
        self.environ = {"PHOBOS_MODKIT_CACHE": str(self.tmp / "cache"), dd.TOOLS_ENV: str(self.tools)}
        self.common = ["--game", str(self.tmp / "game"), "--config", str(self.tmp / "config")]
        self.mods = mock.patch.object(perf, "active_mod_assemblies", return_value=(MODS, set()))
        self.mods.start()

    def tearDown(self):
        self.mods.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_cli(self, *argv, now=datetime(2026, 11, 17, 18, 0, 0), run=None):
        out = io.StringIO()
        code = perf_cli.main(list(argv), environ=self.environ, out=out, popen=FakeProcess, now=now,
                             run=run or (lambda *a, **k: subprocess.CompletedProcess(a, 0, '"RimWorld.exe","4242","Console","1","1 K"\n', "")))
        return code, out.getvalue()

    def test_record_then_report(self):
        with mock.patch.object(dd, "find_processes", return_value=[(4242, "RimWorld")]):
            code, text = self.run_cli("record", "--seconds", "5", "--label", "many wounded", *self.common)
        self.assertEqual(perf_cli.EXIT_OK, code, text)
        self.assertIn("rimworld-perf: 20261117-180000-many-wounded", text)
        self.assertIn("| Example Medical | mod | 40 | 57.1% |", text)
        self.assertIn("Time paused for garbage collection | 3.0% of the time", text)
        self.assertIn("300.0 MB a second", text)
        folder = self.tmp / "cache" / perf_cli.CACHE_FOLDER / "20261117-180000-many-wounded"
        self.assertTrue((folder / perf_cli.INDEX_NAME).is_file())
        self.assertFalse((folder / ("trace" + dd.SPEEDSCOPE_SUFFIX)).exists())
        self.assertFalse((folder / dd.TRACE_FILE).exists())                     # packed once indexed (1.149.0)
        self.assertEqual(packed.read_bytes(folder / dd.TRACE_FILE), b"nettrace")
        code, again = self.run_cli("report", "many wounded", *self.common)
        self.assertEqual(perf_cli.EXIT_OK, code, again)
        self.assertIn("| Example.Dosing.DoseService.MakeJob | Example Medical | 40 | 57.1% |", again)

    def test_record_without_the_game(self):
        with mock.patch.object(dd, "find_processes", return_value=[]):
            code, text = self.run_cli("record", *self.common)
        self.assertEqual(perf_cli.EXIT_FAILED, code)
        self.assertIn("RimWorld is not running", text)

    def test_index_mod_compare_and_list(self):
        self.assertEqual(perf_cli.EXIT_OK, self.run_cli("index", str(TRACE), "--counters", str(COUNTERS), "--label", "before", *self.common)[0])
        self.assertEqual(perf_cli.EXIT_OK, self.run_cli("index", str(TRACE), "--label", "after", *self.common,
                                                         now=datetime(2026, 11, 17, 19, 0, 0))[0])
        code, text = self.run_cli("mod", "example*", *self.common)
        self.assertEqual(perf_cli.EXIT_OK, code, text)
        self.assertIn("Caused 40 ms on the main thread (36.4% of it), 40 ms of it while ticking", text)
        code, text = self.run_cli("compare", *self.common)
        self.assertEqual(perf_cli.EXIT_OK, code, text)
        self.assertIn("| Example Medical | mod | 57.1% | 57.1% | +0.0 |", text)
        code, text = self.run_cli("list", *self.common)
        self.assertIn("20261117-190000-after", text)
        self.assertLess(text.index("20261117-190000-after"), text.index("20261117-180000-before"))

    def test_callers_and_hot_spots(self):
        self.assertEqual(perf_cli.EXIT_OK, self.run_cli("index", str(TRACE), "--label", "one", *self.common)[0])
        code, text = self.run_cli("callers", "CalculateCapacityLevel", *self.common)
        self.assertEqual(perf_cli.EXIT_OK, code, text)
        self.assertIn("**40 ms on the main thread (36.4% of it)**", text)
        self.assertIn("| Example Medical | 40 | 100.0% |", text)
        self.assertIn("| ticking (the simulation) | 40 | 100.0% |", text)
        code, text = self.run_cli("callers", "Nothing.Like.It", *self.common)
        self.assertEqual(perf_cli.EXIT_FAILED, code)
        self.assertIn("add --all-threads", text)
        code, text = self.run_cli("callers", "WaitHandle.WaitOne", "--all-threads", *self.common)
        self.assertEqual(perf_cli.EXIT_OK, code, text)
        self.assertIn("| thread 200 | 100 | 100.0% |", text)
        code, text = self.run_cli("report", *self.common)
        self.assertIn("| Verse.PawnCapacityUtility.CalculateCapacityLevel | RimWorld | 40 | 57.1% | "
                      "Verse.PawnCapacityUtility.CalculateCapacityLevel (100.0%) | Example.Dosing.DoseService.MakeJob (100.0%) | "
                      "Example Medical 40 ms |", text)

    def test_pack_and_unpack_what_was_kept_plain(self):
        # The owner's choice by card (28 Nov 2026): recordings and heaps alike, "Compress them too".
        self.assertEqual(perf_cli.EXIT_OK, self.run_cli("index", str(TRACE), "--label", "old", *self.common)[0])
        recording = self.tmp / "cache" / perf_cli.CACHE_FOLDER / "20261117-180000-old"
        (recording / dd.TRACE_FILE).write_bytes(b"trace " * 1000)
        heap = self.tmp / "cache" / snap.HEAPS_FOLDER / "20261117-170000-day-40"
        heap.mkdir(parents=True)
        (heap / snap.META).write_text('{"label": "day 40"}', encoding="utf-8")
        (heap / snap.HEAP_FILE).write_bytes(b"gcdump " * 1000)
        (heap / snap.HEAP_DATA).write_text("{}", encoding="utf-8")
        code, text = self.run_cli("pack", *self.common)
        self.assertEqual(perf_cli.EXIT_OK, code, text)
        self.assertIn("2 files kept plain", text)
        self.assertTrue((recording / dd.TRACE_FILE).is_file())
        code, text = self.run_cli("pack", "--apply", *self.common)
        self.assertEqual(perf_cli.EXIT_OK, code, text)
        self.assertFalse((recording / dd.TRACE_FILE).exists())
        self.assertFalse((heap / snap.HEAP_FILE).exists())
        self.assertTrue((heap / snap.HEAP_DATA).is_file())                       # read by every report: stays plain
        self.assertIn("nothing left to pack", self.run_cli("pack", *self.common)[1])
        code, text = self.run_cli("unpack", "day 40", *self.common)
        self.assertEqual(perf_cli.EXIT_OK, code, text)
        self.assertEqual((heap / snap.HEAP_FILE).read_bytes(), b"gcdump " * 1000)
        self.assertTrue(packed.packed_of(heap / snap.HEAP_FILE).is_file())
        code, text = self.run_cli("unpack", "20261117-1800", *self.common)
        self.assertEqual(perf_cli.EXIT_OK, code, text)
        self.assertEqual((recording / dd.TRACE_FILE).read_bytes(), b"trace " * 1000)
        self.assertEqual(perf_cli.EXIT_FAILED, self.run_cli("unpack", "nothing like it", *self.common)[0])

    def test_an_unknown_recording(self):
        code, text = self.run_cli("report", "nothing", *self.common)
        self.assertEqual(perf_cli.EXIT_FAILED, code)
        self.assertIn("No recordings", text)


if __name__ == "__main__":
    unittest.main()
