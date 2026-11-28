"""rimworld-perf and the sampling core on a made-up trace of a game loop (fixtures/rimworld/perf). Nothing attaches to a program.

The fixture's main thread, in milliseconds: 0-40 a mod's method calling a game method from inside a patched Pawn.Tick, while
ticking; 40-60 another mod's postfix calling a .NET list; 60-70 the patched Pawn.Tick itself; 70-100 the engine drawing the map,
in native code; 100-110 the frame update itself. A second thread waits for its whole 100 ms.
"""
from contextlib import closing
import io
import json
from datetime import datetime
from pathlib import Path
import shutil
import sqlite3
import subprocess
import tempfile
import unittest
from unittest import mock

from support import FIXTURES
from test_nettrace import made_up_trace
from phobos_modkit import dotnet_diagnostics as dd
from phobos_modkit import packed
from phobos_modkit import sampling
from phobos_modkit.games.rimworld import perf, perf_cli
from phobos_modkit.games.rimworld import perf_snapshots as snap
from phobos_modkit.sampling import ENGINE, GAME, LIBRARY, MOD, RUNTIME, UNKNOWN, Owner  # noqa: F401

TRACE = FIXTURES / "rimworld" / "perf" / "main-loop.speedscope.json"
COUNTERS = FIXTURES / "rimworld" / "perf" / "counters.json"
MODS = {"examplemedical": "Example Medical", "othermod": "Other Mod"}


def indexed(tmp):
    index = Path(tmp) / "index.sqlite"
    sampling.index_speedscope(TRACE, index, {"game_name": "RimWorld"})
    sampling.write_owners(index, perf.classify(sampling.modules(index), {"waylith"}, MODS))
    sampling.write_counters(index, sampling.read_counters(COUNTERS))
    return sampling.Recording(index)


def without_timeline(index):
    """Makes an index look as 1.150.0 built it: format 1, no timeline."""
    with closing(sqlite3.connect(index)) as conn:
        conn.execute("DROP TABLE span")
        conn.execute("UPDATE meta SET value = '1' WHERE key = 'index_format'")
        conn.commit()


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

    def test_the_mods_seen_running_inside_a_patched_method(self):
        self.assertEqual({"Verse.Pawn.Tick": {"Example Medical": 40, "Other Mod": 20}},
                         {m: {o.name: round(s.total, 3) for o, s in owners.items()} for m, owners in self.rec.patch_runners(self.samples).items()})

    def test_threads_are_named_by_what_their_stacks_hold(self):
        self.assertEqual("the game's main loop", self.rec.thread_role(self.main, perf.thread_roles()))
        waiting = next(t for t in self.rec.threads if t != self.main)
        self.assertIsNone(self.rec.thread_role(waiting, perf.thread_roles()))
        self.assertEqual("waiting", self.rec.thread_role(waiting, [("waiting", ["System.Threading.WaitHandle.*"])]))
        # A name needs 30% of the thread's time: drawing holds 30 of the main thread's 110 ms, ticking 70.
        self.assertIsNone(self.rec.thread_role(self.main, [("drawing", ["Verse.Map.MapUpdate"])]))
        self.assertEqual("ticking", self.rec.thread_role(self.main, [("drawing", ["Verse.Map.MapUpdate"]),
                                                                     ("ticking", ["Verse.TickManager.DoSingleTick"])]))

    def test_the_timeline_keeps_each_stretch_of_one_stack(self):
        self.assertTrue(self.rec.has_timeline)
        self.assertEqual([(0, 40, "cpu"), (40, 60, "cpu"), (60, 70, "cpu"), (70, 100, "native"), (100, 110, "cpu")],
                         [(a, b, k) for a, b, _, k in self.rec.spans(self.main)])
        phases, _ = perf.phases()
        windows = self.rec.windows(self.main, 50, lambda node: self.rec.phase_of(node, phases, {}))
        self.assertEqual([(0, {"ticking (the simulation)": 50}), (50, {"ticking (the simulation)": 20, "map and world drawing": 30}),
                          (100, {None: 10})], [(start, {k: round(v.total, 3) for k, v in shares.items()}) for start, shares in windows])

    def test_unbroken_stretches_and_their_stalls(self):
        found = self.rec.stretches(self.main, lambda m, o: o.kind in (MOD, GAME, ENGINE), loop_share=0.5)
        # Root_Play.Update, DoSingleTick and Pawn.Tick hold half the time or more: the loop itself. The .NET list is not kept.
        self.assertEqual({"Example.Dosing.DoseService.MakeJob": (40, 0, 1, 4), "Verse.PawnCapacityUtility.CalculateCapacityLevel": (40, 0, 1, 5),
                          "Other.Patches.Pawn_Tick.Postfix": (20, 40, 1, 4), "Verse.Map.MapUpdate": (30, 70, 1, 2),
                          "Waylith.Rendering.Submit": (30, 70, 1, 3)}, {m: v for (m, _), v in found.items()})
        stalls = [(m, above) for (m, _), _, above in sampling.Recording.innermost_stretches(found, 25)]
        self.assertEqual([("Verse.PawnCapacityUtility.CalculateCapacityLevel", 1), ("Waylith.Rendering.Submit", 1)], stalls)
        node = next(n for n in self.rec.nodes_up(self.rec.spans(self.main)[0][2]) if self.rec.method_at(n)[0].endswith("MakeJob"))
        self.assertEqual({"Example Medical": 40}, {o.name: v for o, v in self.rec.stall_owners(self.main, node, 0, 40).items()})

    def test_an_index_from_before_the_timeline_still_reads(self):
        without_timeline(self.rec.index)
        old = sampling.Recording(self.rec.index)
        self.assertFalse(old.has_timeline)
        self.assertEqual([], old.spans(self.main))
        self.assertEqual({}, old.stretches(self.main, lambda m, o: True))

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

    commands = []

    def __init__(self, command, **_):
        FakeProcess.commands.append(command)
        out = Path(command[command.index("-o") + 1])
        if "Speedscope" in command:
            shutil.copyfile(TRACE, out.with_name("trace" + dd.SPEEDSCOPE_SUFFIX))
            out.write_bytes(made_up_trace())
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
        self.environ = {"PHOBOS_MODKIT_CACHE": str(self.tmp / "cache"), dd.TOOLS_ENV: str(self.tools),
                        "PHOBOS_HISTORY": str(self.tmp / "history")}
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
        self.assertIn("the main thread is thread 100 (the game's main loop)", text)
        self.assertIn("Time paused for garbage collection | 3.0% of the time", text)
        self.assertIn("300.0 MB a second", text)
        folder = self.tmp / "cache" / perf_cli.CACHE_FOLDER / "20261117-180000-many-wounded"
        self.assertTrue((folder / perf_cli.INDEX_NAME).is_file())
        self.assertFalse((folder / ("trace" + dd.SPEEDSCOPE_SUFFIX)).exists())
        self.assertFalse((folder / dd.TRACE_FILE).exists())                     # packed once indexed (1.149.0)
        self.assertEqual(packed.read_bytes(folder / dd.TRACE_FILE), made_up_trace())
        counters_command = next(c for c in FakeProcess.commands if "Speedscope" not in c)
        self.assertEqual(["--counters", "System.Runtime,DThorga.RimWorld"], counters_command[-2:])
        trace_command = next(c for c in FakeProcess.commands if "Speedscope" in c)
        self.assertEqual(["--profile", "dotnet-common,dotnet-sampled-thread-time", "--providers",
                          "Microsoft-Windows-DotNETRuntime:0x100003C01D:4"], trace_command[-4:])
        # The runtime's own events: one lock wait on the main thread, held by thread 200; two allocations.
        self.assertIn("**1 waits on locks, 5 ms in all; the main thread waited 1 times, 5 ms (4.5% of it)**", text)
        self.assertIn("| Verse.PawnCapacityUtility.CalculateCapacityLevel | RimWorld | 1 | 5 | 5.0 | thread 200 (100% of its waits) | "
                      "Example Medical 5 ms |", text)
        self.assertIn("| System.String | 0.2 | 66.7% | Waylith.Rendering.Submit |", text)
        self.assertIn("| Other Mod | 0.1 | 33.3% |", text)
        code, again = self.run_cli("report", "many wounded", *self.common)
        self.assertEqual(perf_cli.EXIT_OK, code, again)
        self.assertIn("| Example.Dosing.DoseService.MakeJob | Example Medical | 40 | 57.1% |", again)
        # The Timeline hears of it (1.153.0).
        facts = [json.loads(line) for line in (self.tmp / "history" / "rimworld.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertEqual([("perf-recorded", "20261117-180000-many-wounded", "many wounded")],
                         [(f["kind"], f["recording"], f["label"]) for f in facts])

    def test_the_game_counts_itself(self):
        self.assertEqual(perf_cli.EXIT_OK, self.run_cli("index", str(TRACE), "--counters", str(COUNTERS), "--label", "one", *self.common)[0])
        code, text = self.run_cli("report", *self.common)
        self.assertIn("| Ticks a second | 570 | slowest second 540 |", text)
        self.assertIn("| Frames a second | 55 | slowest second 50 |", text)
        self.assertIn("| Each second's longest frame | 32.5 ms on average | longest 40.0 ms |", text)
        self.assertIn("| Game speed | superfast | fastest superfast |", text)
        self.assertIn("| The main thread's ticking, a tick | 1.12 ms | - |", text)      # 70 ms over 570 a second for 0.11 s
        code, text = self.run_cli("index", str(TRACE), "--label", "no meter", *self.common, now=datetime(2026, 11, 17, 19, 0, 0))
        self.assertIn("need D'thorga Framework 0.380.0 or newer running", text)

    def test_compare_says_what_each_recording_was_of(self):
        for label, hour, save in (("before", 18, "Colony1"), ("after", 19, "Colony2")):
            self.assertEqual(perf_cli.EXIT_OK, self.run_cli("index", str(TRACE), "--counters", str(COUNTERS), "--label", label,
                                                             *self.common, now=datetime(2026, 11, 17, hour, 0, 0))[0])
            folder = next((self.tmp / "cache" / perf_cli.CACHE_FOLDER).glob(f"*-{label}"))
            with closing(sqlite3.connect(folder / perf_cli.INDEX_NAME)) as conn:
                conn.executemany("INSERT INTO meta VALUES (?, ?)", [("save", save), ("mods_active", "300")])
                conn.commit()
        code, text = self.run_cli("compare", *self.common)
        self.assertEqual(perf_cli.EXIT_OK, code, text)
        self.assertIn("**Not like for like: save Colony1 against Colony2.**", text)
        self.assertIn("| Game speed | superfast | superfast |", text)
        self.assertIn("**The main thread's ticking took 1.12 ms a tick, then 1.12 ms** (+0.0%)", text)
        self.assertIn("| Example Medical | mod | 0.638 | 0.638 | +0.000 |", text)        # 57.1% of 1.117 ms

    def test_a_recording_notes_its_context(self):
        config = self.tmp / "config"
        config.mkdir()
        (config / "ModsConfig.xml").write_text("<ModsConfigData><version>1.7.5011 rev24</version><activeMods><li>ludeon.rimworld</li>"
                                               "<li>example.medical</li></activeMods></ModsConfigData>", encoding="utf-8")
        found = perf.context(FIXTURES / "rimworld" / "player-1.7.log", config / "ModsConfig.xml", "2026-01-02 10:10:00")
        self.assertEqual({"game_version": "1.7.9999.1", "save": "Colony1", "mods_loaded": "5", "mods_active": "2"}, found)
        self.assertNotIn("save", perf.context(FIXTURES / "rimworld" / "player-1.7.log", None, "2026-01-02 10:00:00"))
        self.assertEqual('Context: RimWorld 1.7.9999.1, save "Colony1" (loaded with 5 mods), 2 mods active.', perf_cli.context_text(found))

    def test_trend_follows_some_mods_across_recordings(self):
        for label, hour in (("before", 18), ("after", 19)):
            self.run_cli("index", str(TRACE), "--counters", str(COUNTERS), "--label", label, *self.common, now=datetime(2026, 11, 17, hour, 0, 0))
        code, text = self.run_cli("trend", "example*", *self.common)
        self.assertEqual(perf_cli.EXIT_OK, code, text)
        found = json.loads(self.run_cli("trend", "example*", "--json", *self.common)[1])["report"]["sections"][0]["blocks"]
        self.assertEqual(["before", "after"], found[0]["categories"])
        self.assertEqual({"kind": "recording", "id": "20261117-180000-before", "column": 0}, found[1]["refs"][0][0])
        self.assertIn("| 20261117-180000-before | before | 63.6% | 57.1% | 0.638 | Example Medical |  |", text)
        self.assertIn("| Example Medical | 57.1% | 57.1% | +0.0 |", text)
        code, text = self.run_cli("trend", *self.common)                  # our own by default: none in the fixture
        self.assertIn("| 0.0% |", text)
        self.assertEqual("**up 3.0 points** on the earlier middle (2.0%)", perf_cli.trend_note(5.0, [1.0, 2.0, 9.0]))
        self.assertEqual("down 2.5 points on the earlier middle (4.5%)", perf_cli.trend_note(2.0, [4.0, 5.0]))
        self.assertEqual("", perf_cli.trend_note(5.0, []))
        self.assertEqual("", perf_cli.trend_note(5.0, [4.0]))

    def test_a_report_leads_with_findings_and_facts_and_links_its_rows(self):
        with mock.patch.object(perf, "mod_packages", return_value={"Example Medical": "example.medical", "Unused": "x.y"}):
            self.assertEqual(perf_cli.EXIT_OK, self.run_cli("index", str(TRACE), "--counters", str(COUNTERS), "--label", "one",
                                                             *self.common)[0])
        code, text = self.run_cli("report", "--json", *self.common)
        self.assertEqual(perf_cli.EXIT_OK, code, text)
        found = json.loads(text)
        facts = {f["label"]: f["value"] for f in found["report"]["facts"]}
        self.assertEqual({"Recorded": "2026-11-17 18:00:00", "Length": "0.1 s", "Label": "one", "Ticks a second": "570",
                          "Frames a second": "55", "Ticking, a tick": "1.12 ms", "Longest frame": "40 ms", "Speed": "superfast",
                          "Pawns": "120", "Maps": "2"}, facts)
        findings = found["report"]["blocks"][0]
        self.assertEqual("findings", findings["type"])
        self.assertEqual("Example Medical caused 57% of ticking, the most of any mod.", findings["items"][0]["text"])
        self.assertEqual([{"kind": "mod", "id": "Example Medical", "package": "example.medical"}], findings["items"][0]["refs"])
        self.assertEqual({"kind": "method", "id": "Verse.PawnCapacityUtility.CalculateCapacityLevel", "of": "RimWorld",
                          "of_kind": "game"}, findings["items"][1]["refs"][0])
        self.assertIn("Garbage collection paused the game 3.0% of the time", findings["items"][2]["text"])
        tables = {s["heading"]: [b for b in s["blocks"] if b["type"] == "table"][0] for s in found["report"]["sections"]
                  if any(b["type"] == "table" for b in s["blocks"])}
        spots = tables["Ticking: hot spots in the game's and the engine's code, and the mods that lead to them"]
        self.assertEqual([{"kind": "method", "id": "Verse.PawnCapacityUtility.CalculateCapacityLevel", "column": 0, "of": "RimWorld",
                           "of_kind": "game"},
                          {"kind": "mod", "id": "Example Medical", "column": 6, "package": "example.medical"}], spots["refs"][0])
        self.assertEqual(len(spots["rows"]), len(spots["refs"]))
        charts = [b for s in found["report"]["sections"] for b in s["blocks"] if b["type"] == "chart"]
        self.assertEqual(["Example Medical", "Other Mod", "RimWorld"], charts[0]["categories"])
        # The summary file: what a list, a mod's cost and a home panel read without the index.
        summary = found["data"]["summary"]
        self.assertEqual({"Example Medical": 0.57143, "Other Mod": 0.28571}, summary["mods"])
        self.assertEqual({"Example Medical": "example.medical"}, summary["packages"])
        self.assertEqual(570.0, summary["game"]["ticks_a_second"])
        self.assertEqual(findings["items"], summary["findings"])
        folder = next((self.tmp / "cache" / perf_cli.CACHE_FOLDER).glob("*-one"))
        self.assertEqual(summary, perf_cli.read_summary(folder))
        code, text = self.run_cli("list", "--json", *self.common)
        listed = json.loads(text)["data"]["recordings"]
        self.assertEqual(["20261117-180000-one"], [r["recording"] for r in listed])
        self.assertEqual(summary["findings"], listed[0]["findings"])
        code, text = self.run_cli("list", *self.common)
        self.assertIn("| 20261117-180000-one | 2026-11-17 18:00:00 | 0.11 | one | 570 | Example Medical caused 57% of ticking, "
                      "the most of any mod. |", text)

    def test_costs_say_what_each_mod_costs_against_the_earlier_recordings(self):
        for label, hour in (("before", 18), ("after", 19)):
            self.run_cli("index", str(TRACE), "--counters", str(COUNTERS), "--label", label, *self.common,
                         now=datetime(2026, 11, 17, hour, 0, 0))
        code, text = self.run_cli("costs", "example*", "--json", *self.common)
        self.assertEqual(perf_cli.EXIT_OK, code, text)
        data = json.loads(text)["data"]
        self.assertEqual(("20261117-190000-after", 2), (data["newest"], data["recordings"]))
        medical = next(m for m in data["mods"] if m["name"] == "Example Medical")
        self.assertEqual((57.14, 57.14, 0.0, True, False), (medical["share"], medical["earlier_middle"], medical["change"],
                                                            medical["ours"], medical["flagged"]))
        self.assertEqual({"pattern": "example*", "share": 57.14, "earlier_middle": 57.14, "note": ""}, data["own"])
        self.assertIn("Example.Dosing.DoseService.MakeJob", [m["name"] for m in data["methods"]])
        self.assertEqual("Example Medical caused 57% of ticking, the most of any mod.", data["first_finding"]["text"])
        code, text = self.run_cli("costs", *self.common)
        self.assertIn("| Example Medical | 57.1% | 57.1% | +0.0 |", text)

    def test_what_the_game_logged_while_recording_is_kept_and_linked(self):
        start, end = "2026-01-02 10:00:00", "2026-01-02 10:10:00"
        found = perf.log_during(FIXTURES / "rimworld" / "player-1.7.log", start, end)
        self.assertTrue(found)
        self.assertEqual({"id", "level", "signature", "count"}, set(found[0]))
        self.assertEqual([], perf.log_during(FIXTURES / "rimworld" / "player-1.7.log", "2030-01-01 00:00:00", "2030-01-01 00:01:00"))
        self.assertEqual([], perf.log_during(self.tmp / "missing.log", start, end))
        self.assertEqual(perf_cli.EXIT_OK, self.run_cli("index", str(TRACE), "--label", "one", *self.common)[0])
        folder = next((self.tmp / "cache" / perf_cli.CACHE_FOLDER).glob("*-one"))
        storm = [{"id": "ab12cd34", "level": "ERROR", "signature": "Exception ticking Example.Thing", "count": 25},
                 {"id": "ef56ab78", "level": "WARN", "signature": "A warning", "count": 2}]
        with closing(sqlite3.connect(folder / perf_cli.INDEX_NAME)) as conn:
            conn.executemany("INSERT INTO meta VALUES (?, ?)", [("log_during", json.dumps(storm)),
                                                                ("settings_prints", json.dumps({"Mod_A": "1", "Mod_B": "2"}))])
            conn.commit()
        found = json.loads(self.run_cli("report", "--json", *self.common)[1])
        section = next(s for s in found["report"]["sections"] if s["heading"] == "The log while recording")
        table = next(b for b in section["blocks"] if b["type"] == "table")
        self.assertEqual([{"kind": "signature", "id": "ab12cd34", "column": 1}], table["refs"][0])
        texts = [f["text"] for f in found["report"]["blocks"][0]["items"]]
        self.assertIn("The game logged 25 errors while recording, the most often: Exception ticking Example.Thing", texts)
        self.assertEqual(25, found["data"]["summary"]["log_errors"])
        # A second recording made with one mod's settings changed is not like for like.
        self.assertEqual(perf_cli.EXIT_OK, self.run_cli("index", str(TRACE), "--label", "two", *self.common,
                                                         now=datetime(2026, 11, 17, 19, 0, 0))[0])
        second = next((self.tmp / "cache" / perf_cli.CACHE_FOLDER).glob("*-two"))
        with closing(sqlite3.connect(second / perf_cli.INDEX_NAME)) as conn:
            conn.executemany("INSERT INTO meta VALUES (?, ?)", [("settings_prints", json.dumps({"Mod_A": "1", "Mod_B": "3"})),
                                                                ("mod_versions", json.dumps({"D'thorga Medical": "0.36.0"}))])
            conn.commit()
        code, text = self.run_cli("compare", *self.common)
        self.assertIn("**Not like for like: 1 mods' settings changed.**", text)
        self.assertIn("| Mods' settings files changed | - | 1 (Mod_B) |", text)
        self.assertIn("| D'thorga Medical | - | 0.36.0 |", text)

    def test_settings_prints_and_versions_are_read_from_the_game_and_its_mods(self):
        config = self.tmp / "prints"
        config.mkdir()
        (config / "Mod_Example_Settings.xml").write_text("<a/>", encoding="utf-8")
        (config / "Prefs.xml").write_text("<b/>", encoding="utf-8")
        prints = perf.settings_prints(config)
        self.assertEqual(["Mod_Example_Settings"], list(prints))
        self.assertEqual(12, len(prints["Mod_Example_Settings"]))
        about = self.tmp / "About.xml"
        about.write_text("<ModMetaData><name>X</name><modVersion> 0.36.0 </modVersion></ModMetaData>", encoding="utf-8")
        self.assertEqual("0.36.0", perf._about_version(about))
        self.assertEqual("", perf._about_version(self.tmp / "none.xml"))

    def test_what_the_review_of_1_153_0_found_stays_fixed(self):
        # A hand-recorded counters file at 5 s is read a second, as a recording's are.
        counters = self.tmp / "slow.json"
        counters.write_text(json.dumps({"Events": [
            {"timestamp": "2026-11-18T08:00:00.0000000", "name": "rimworld.ticks ({tick} / 5 sec)", "tags": "", "value": 3000},
            {"timestamp": "2026-11-18T08:00:01.0000000", "name": "dotnet.gc.collections ({collection} / 1 sec)", "tags": "",
             "value": 4}]}), encoding="utf-8")
        found = sampling.read_counters(counters)
        self.assertEqual([600.0], found[("rimworld.ticks ({tick} / 5 sec)", "")])
        self.assertEqual([4.0], found[("dotnet.gc.collections ({collection} / 1 sec)", "")])
        # Events that cannot be read: the index no longer says they were recorded, so no table says "no waits".
        self.assertEqual(perf_cli.EXIT_OK, self.run_cli("index", str(TRACE), "--label", "one", *self.common)[0])
        folder = next((self.tmp / "cache" / perf_cli.CACHE_FOLDER).glob("*-one"))
        index = folder / perf_cli.INDEX_NAME
        with closing(sqlite3.connect(index)) as conn:
            conn.execute("INSERT OR REPLACE INTO meta VALUES ('lock_events', 'yes')")
            conn.commit()
        broken = self.tmp / "broken.nettrace"
        broken.write_bytes(b"not a trace")
        notes = perf_cli.add_events(index, broken)
        self.assertIn("could not be read", notes[0])
        self.assertEqual("", sampling.Recording(index).meta.get("lock_events"))
        # A summary another kit made is made again.
        summary = perf_cli.summary_of(folder)
        self.assertEqual(summary, perf_cli.read_summary(folder))
        (folder / perf_cli.SUMMARY_NAME).write_text(json.dumps(dict(summary, kit_version="0.0.1")), encoding="utf-8")
        self.assertIsNone(perf_cli.read_summary(folder))

    def test_costs_and_trend_leave_out_a_recording_in_which_the_game_hardly_ran(self):
        for label, hour in (("paused", 17), ("before", 18), ("after", 19)):
            self.run_cli("index", str(TRACE), "--counters", str(COUNTERS), "--label", label, *self.common,
                         now=datetime(2026, 11, 17, hour, 0, 0))
        paused = next((self.tmp / "cache" / perf_cli.CACHE_FOLDER).glob("*-paused"))
        summary = perf_cli.summary_of(paused)
        (paused / perf_cli.SUMMARY_NAME).unlink()
        perf_cli.write_summary(paused, dict(summary, ticking_share=0.0, mods={"Example Medical": 0.0}))
        data = json.loads(self.run_cli("costs", "example*", "--json", *self.common)[1])["data"]
        medical = next(m for m in data["mods"] if m["name"] == "Example Medical")
        self.assertEqual(57.14, medical["earlier_middle"])               # the paused one's 0% is left out
        # costs names the newest it could not read, rather than an older one.
        newest = next((self.tmp / "cache" / perf_cli.CACHE_FOLDER).glob("*-after"))
        (newest / perf_cli.SUMMARY_NAME).unlink()
        with closing(sqlite3.connect(newest / perf_cli.INDEX_NAME)) as conn:
            conn.execute("DROP TABLE sample")
            conn.commit()
        code, text = self.run_cli("costs", *self.common)
        self.assertEqual(perf_cli.EXIT_FAILED, code)
        self.assertIn("The newest recording, 20261117-190000-after, could not be read", text)

    def test_a_listed_recording_without_a_summary_gets_one(self):
        self.assertEqual(perf_cli.EXIT_OK, self.run_cli("index", str(TRACE), "--label", "one", *self.common)[0])
        folder = next((self.tmp / "cache" / perf_cli.CACHE_FOLDER).glob("*-one"))
        (folder / perf_cli.SUMMARY_NAME).unlink()
        code, text = self.run_cli("list", "--json", *self.common)
        self.assertEqual(perf_cli.EXIT_OK, code, text)
        self.assertEqual("20261117-180000-one", json.loads(text)["data"]["recordings"][0]["recording"])
        self.assertIsNotNone(perf_cli.read_summary(folder))

    def test_the_performance_page_finds_its_reports(self):
        surfaced = {name for name, report in perf_cli.MANIFEST["reports"].items() if report.get("surface") == perf_cli.PERFORMANCE_SURFACE}
        self.assertEqual({"report", "record", "list", "callers", "mod", "compare", "trend", "costs", "reindex"}, surfaced)

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

    def test_reindex_rebuilds_an_old_recording_with_its_timeline(self):
        self.assertEqual(perf_cli.EXIT_OK, self.run_cli("index", str(TRACE), "--counters", str(COUNTERS), "--label", "old", *self.common)[0])
        folder = self.tmp / "cache" / perf_cli.CACHE_FOLDER / "20261117-180000-old"
        without_timeline(folder / perf_cli.INDEX_NAME)
        code, text = self.run_cli("report", "old", *self.common)
        self.assertIn("rimworld-perf reindex 20261117-180000-old", text)
        self.assertNotIn("## Over time", text)
        (folder / dd.TRACE_FILE).write_bytes(b"nettrace")
        packed.pack(folder / dd.TRACE_FILE)

        def run(command, **_):
            command = [str(c) for c in command]
            if "convert" in command:
                shutil.copyfile(TRACE, command[command.index("-o") + 1] + dd.SPEEDSCOPE_SUFFIX)
            return subprocess.CompletedProcess(command, 0, "", "")
        with mock.patch.object(perf, "active_mod_assemblies", return_value=({}, set())):   # owners come from the old index
            code, text = self.run_cli("reindex", "--all", *self.common, run=run)
        self.assertEqual(perf_cli.EXIT_OK, code, text)
        self.assertIn("| 20261117-180000-old | rebuilt: 2 threads, with its timeline |", text)
        self.assertEqual(["index.sqlite", "summary.json", "trace.nettrace.zst"], sorted(p.name for p in folder.iterdir()))
        self.assertIsNone(perf_cli.read_summary(folder))     # made from the index before it was rebuilt, so made again when read
        code, text = self.run_cli("report", "old", *self.common)
        self.assertIn("## Over time: the main thread, window by window", text)
        self.assertIn("| Example Medical | mod | 40 | 57.1% |", text)                 # the day's owners, kept
        self.assertIn("Time paused for garbage collection | 3.0% of the time", text)   # and its counters
        self.assertIn('("old")', text)

    def test_the_patch_list_names_transpilers(self):
        from phobos_modkit.games.rimworld import patches
        index = self.tmp / "cache" / patches.CACHE_FOLDER / patches.INDEX_NAME
        index.parent.mkdir(parents=True)
        with closing(sqlite3.connect(index)) as conn:
            conn.executescript(patches.SCHEMA)
            conn.executemany("INSERT INTO owners VALUES (?, ?, ?, ?)", [("a.dll", 1, "example.medical", "Example Medical"),
                                                                       ("b.dll", 2, "example.rewriter", "Example Rewriter")])
            conn.executemany("INSERT INTO patches (path, kind, target_type, target_member) VALUES (?, ?, ?, ?)",
                             [("b.dll", "transpiler", "Verse.Pawn", "Tick"), ("a.dll", "postfix", "Verse.Pawn", "Tick")])
            conn.commit()
        self.assertEqual(perf_cli.EXIT_OK, self.run_cli("index", str(TRACE), "--label", "one", *self.common)[0])
        code, text = self.run_cli("report", *self.common)
        self.assertIn("| Verse.Pawn.Tick (patched) | 70 | 100.0% | Example Medical, Other Mod | Example Rewriter; 1 other patch listed |", text)

    def test_without_the_patch_list(self):
        self.assertEqual(perf_cli.EXIT_OK, self.run_cli("index", str(TRACE), "--label", "one", *self.common)[0])
        code, text = self.run_cli("report", *self.common)
        self.assertIn("run `rimworld-patches` once to name transpilers here", text)
        self.assertIn("| Verse.Pawn.Tick (patched) | 70 | 100.0% | Example Medical, Other Mod | - |", text)

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
