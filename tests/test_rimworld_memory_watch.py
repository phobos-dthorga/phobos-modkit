"""The memory watch: Windows' and Linux's memory figures, the memory map's sums, dotnet-counters' file, and rimworld-perf watch.

Everything is written by hand: regions, counters and a log in the shapes seen on 19 November 2026 (dotnet-counters 10.0.750501's
JSON, RimWorld 1.7's Player.log). The one real reading is of this test's own process, on Windows. Nothing here reads a game.
"""
from datetime import datetime
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

import support  # noqa: F401  (the package on the import path)
from phobos_modkit import dotnet_diagnostics as dd
from phobos_modkit import process_memory as pm
from phobos_modkit.games.rimworld import perf, perf_cli
from phobos_modkit.games.rimworld import perf_snapshots as snap
from phobos_modkit.games.rimworld import perf_watch as pw
from phobos_modkit.sampling import MOD, Owner

GB, MB = 10 ** 9, 2 ** 20
START = datetime(2026, 11, 19, 20, 0, 0).timestamp()
HEAP_BLOCK = 0x7F0000000000


def region(base, size, kind=pm.PRIVATE, committed=True, allocation=None, file=""):
    return pm.Region(base, base if allocation is None else allocation, size, committed, kind, file)


def counters_json(points, cut=False):
    """dotnet-counters' JSON for [(seconds after START, name with unit, tags, value)]."""
    events = []
    for offset, name, tags, value in points:
        stamp = datetime.fromtimestamp(START + offset).strftime("%Y-%m-%dT%H:%M:%S") + ".1234567"
        events.append(json.dumps({"timestamp": stamp, "provider": "System.Runtime", "name": name, "tags": tags,
                                  "counterType": "Metric", "meterTags": "", "instrumentTags": "", "value": value}))
    text = '{ "TargetProcess": "RimWorld", "StartTime": "2026-11-19T20:00:00", "Events": [' + ",".join(events) + "] }"
    return text[:-20] if cut else text


LOG = """=== Waylith log ===
Started: 2026-11-19 19:50:00
Version: 1.7.5013
2026-11-19 19:55:00.000  INFO [Verse] Loading game from file PG14 with mods:
  - ludeon.rimworld
2026-11-19 20:00:22.500  INFO [Verse] Loading game from file PG15 with mods:
  - ludeon.rimworld
2026-11-19 20:00:24.000 ERROR [Verse] Exception ticking Example.Thing: NullReferenceException
2026-11-19 20:00:50.000 ERROR [Verse] Another failure
"""


class FiguresTests(unittest.TestCase):
    def test_the_map_sums_by_kind_block_size_and_file(self):
        regions = [region(HEAP_BLOCK, 4 * GB), region(HEAP_BLOCK + 4 * GB, 96 * GB, committed=False, allocation=HEAP_BLOCK),
                   region(0x1000, 2 * MB), region(0x1000 + 2 * MB, 2 * MB, committed=False, allocation=0x1000),
                   region(0x9000000, 20 * MB), region(0x20000000, 3 * MB, pm.IMAGE, file="Example.dll"),
                   region(0x20300000, 1 * MB, pm.IMAGE, allocation=0x20000000, file="Example.dll"),
                   region(0x30000000, 5 * MB, pm.MAPPED), region(0x40000000, 7 * MB, pm.MAPPED, committed=False)]
        found = pm.summarise(regions, keep=2)
        self.assertEqual(4 * GB + 22 * MB, found.committed[pm.PRIVATE])
        self.assertEqual(96 * GB + 2 * MB, found.reserved[pm.PRIVATE])
        self.assertEqual([(HEAP_BLOCK, 4 * GB, 100 * GB), (0x9000000, 20 * MB, 20 * MB)], found.blocks)
        self.assertEqual(2 * MB, found.blocks_rest)
        self.assertEqual([1, 4 * GB], found.sizes["16 GB and over"])
        self.assertEqual([1, 2 * MB], found.sizes["1-16 MB"])
        self.assertEqual([1, 20 * MB], found.sizes["16-64 MB"])
        self.assertEqual({(pm.IMAGE, "Example.dll"): 4 * MB, (pm.MAPPED, pm.NO_FILE): 5 * MB}, found.files)
        self.assertEqual(9, found.regions)

    def test_a_device_path_keeps_only_its_file_name(self):
        self.assertEqual("Example.dll", pm.file_name(r"\Device\HarddiskVolume3\Games\Mods\Example\Example.dll"))
        self.assertEqual("", pm.file_name(""))

    def test_linux_figures(self):
        status = "Name:\tRimWorld\nVmHWM:\t 9000 kB\nVmRSS:\t 8000 kB\nRssAnon:\t 6000 kB\nVmSwap:\t 1000 kB\nThreads:\t40\n"
        meminfo = "MemTotal:       64000 kB\nMemAvailable:   20000 kB\n"
        found = pm.linux_figures(status, meminfo)
        self.assertEqual(pm.Figures(7000 * 1024, 8000 * 1024, 9000 * 1024, 20000 * 1024, 64000 * 1024), found)

    @unittest.skipUnless(sys.platform == "win32", "the memory map is read on Windows only")
    def test_this_process_can_be_read(self):
        with pm.Process(os.getpid()) as process:
            self.assertTrue(process.running())
            self.assertGreater(process.figures().private, 0)
            found = pm.summarise(process.regions())
        self.assertGreater(found.committed[pm.IMAGE], 0)
        self.assertTrue(any(name.lower().startswith("python") for _, name in found.files))


class CounterFileTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def test_events_with_seven_decimals_and_units_dropped(self):
        (self.tmp / "c.json").write_text(counters_json([(5, "dotnet.gc.last_collection.heap.size (By)", "gc.heap.generation=gen2", 3e9)]),
                                         encoding="utf-8")
        found = dd.counter_events(self.tmp / "c.json")
        self.assertEqual(1, len(found))
        t, name, tags, value = found[0]
        self.assertAlmostEqual(START + 5.1234567, t, places=5)
        self.assertEqual((dd.HEAP_SIZE, "gc.heap.generation=gen2", 3e9), (name, tags, value))

    def test_a_file_cut_off_keeps_its_whole_events(self):
        points = [(n, "dotnet.gc.last_collection.memory.committed_size (By)", "", n * 1e9) for n in range(1, 5)]
        (self.tmp / "c.json").write_text(counters_json(points, cut=True), encoding="utf-8")
        found = dd.counter_events(self.tmp / "c.json")
        self.assertEqual([1e9, 2e9, 3e9], [e[3] for e in found])
        self.assertEqual([], dd.counter_events(self.tmp / "missing.json"))

    def test_runtime_figures_add_the_generations(self):
        events = [(1, dd.HEAP_SIZE, "gc.heap.generation=gen2", 1e9), (2, dd.HEAP_SIZE, "gc.heap.generation=gen2", 3e9),
                  (2, dd.HEAP_SIZE, "gc.heap.generation=loh", 2e9), (2, dd.HEAP_COMMITTED, "", 6e9),
                  (2, dd.HEAP_FRAGMENTATION, "gc.heap.generation=gen2", 1e9), (2, dd.HEAP_FRAGMENTATION, "gc.heap.generation=loh", 0.5e9)]
        self.assertEqual({"heap": 5 * 10 ** 9, "gaps": 15 * 10 ** 8, "live": 35 * 10 ** 8, "committed": 6 * 10 ** 9},
                         snap.runtime_figures(events))


class PartialHeapTests(unittest.TestCase):
    def heap(self, total, objects):
        return snap.Heap(total, objects, [])

    def test_less_than_the_runtime_counted_is_partial(self):
        note = snap.partial_note({"runtime": {"heap": 6 * GB}}, self.heap(667 * 10 ** 6, 10_000_003))
        self.assertIn("**This snapshot holds only part of the heap", note)
        self.assertIn("counted on its heap (11%)", note)

    def test_live_objects_are_compared_when_the_gaps_are_known(self):
        note = snap.partial_note({"runtime": {"heap": 8 * GB, "gaps": 3 * GB, "live": 5 * GB}}, self.heap(667 * 10 ** 6, 10_000_003))
        self.assertIn("of the 5.0 GB the runtime itself counted in live objects (13%)", note)

    def test_the_whole_heap_says_so(self):
        note = snap.partial_note({"runtime": {"heap": 100 * 10 ** 6}}, self.heap(98 * 10 ** 6, 5000))
        self.assertTrue(note.startswith("The runtime counted"))

    def test_a_round_count_without_the_runtimes_figure(self):
        self.assertIn("a round number it seems to stop at", snap.partial_note({}, self.heap(667 * 10 ** 6, 10_000_003)))
        self.assertEqual("", snap.partial_note({}, self.heap(21 * 10 ** 6, 44_028)))


class FakeClock:
    def __init__(self):
        self.t = START

    def __call__(self):
        return self.t

    def sleep(self, seconds):
        self.t += max(seconds, 0.001)


class FakeProcess:
    """Stands in for the game: memory climbs 2 GB at 25 s, half of it in .NET's heap block, half in new small blocks."""

    def __init__(self, clock_):
        self.clock = clock_

    def __call__(self, pid):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *_):
        pass

    def running(self):
        return True

    def late(self):
        return self.clock() - START >= 25

    def figures(self):
        private = 12 * GB if self.late() else 10 * GB
        return pm.Figures(private, private // 2, private, 20 * GB, 64 * GB)

    def regions(self):
        found = [region(HEAP_BLOCK, (5 if self.late() else 4) * GB, allocation=HEAP_BLOCK),
                 region(0x20000000, 3 * MB, pm.IMAGE, file="Example.dll")]
        found += [region(0x100000000 + n * 16 * MB, 8 * MB) for n in range(200 if self.late() else 80)]
        return found


def counters_popen(command, **_):
    """Stands in for dotnet-counters collect: writes the whole watch's counters at once."""
    points = []
    for second in range(0, 61, 5):
        late = second >= 25
        points += [(second, "dotnet.gc.last_collection.heap.size (By)", "gc.heap.generation=gen2", (3.5 if late else 3) * GB),
                   (second, "dotnet.gc.last_collection.heap.size (By)", "gc.heap.generation=loh", 0.5 * GB),
                   (second, "dotnet.gc.last_collection.memory.committed_size (By)", "", (5 if late else 4) * GB),
                   (second, "dotnet.gc.last_collection.heap.fragmentation.size (By)", "gc.heap.generation=gen2", 0.2 * GB)]
    Path(command[command.index("-o") + 1]).write_text(counters_json(points), encoding="utf-8")
    return mock.Mock(wait=lambda timeout=None: 0)


class WatchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        (self.tmp / "Player.log").write_text(LOG, encoding="utf-8")
        self.clock = FakeClock()

    def watch(self, **kw):
        folder = pw.new_folder(self.tmp / "watches", "reload", datetime(2026, 11, 19, 20, 0, 0))
        notes = pw.watch(4242, folder, 1, 5, 30, kw.get("tool", "dotnet-counters"), "reload", None, self.clock, self.clock.sleep,
                         counters_popen, FakeProcess(self.clock), self.tmp / "Player.log")
        return folder, notes

    def test_a_jump_its_cause_and_dotnets_share(self):
        folder, notes = self.watch()
        self.assertEqual([], notes)
        watched = pw.Watch(folder)
        self.assertEqual(12, len(watched.samples))
        self.assertEqual("the time asked for ran out", watched.meta["reason"])
        from phobos_modkit.report import render_markdown
        text = render_markdown(pw.watch_report(watched, {"Example": Owner(MOD, "Example Mod")}))
        self.assertIn("**It climbed 2.00 GB in all, mostly in jumps**: 1 jump", text)
        self.assertIn("it ended 2.00 GB higher than it began", text)
        self.assertIn("At the end, .NET's collector held **5.00 GB** of the 12.00 GB", text)
        self.assertIn("Of .NET's share, 3.80 GB was live objects and 200.0 MB gaps between them.", text)
        self.assertIn("| .NET heap after the last collection, gaps included | 3.50 GB | 4.00 GB |", text)
        self.assertIn("| Of it, live objects | 3.30 GB | 3.80 GB |", text)
        self.assertIn('| 20:00:20 to 20:00:25 | +2.00 GB | 0 | +2.00 GB | save "PG15" loaded at 20:00:22; 2 errors logged |', text)
        self.assertNotIn("PG14", text)
        self.assertIn("| 0x7f0000000000 | 5.00 GB | 4.00 GB | 5.00 GB | +1.00 GB | .NET's heap (its size matches the collector's figure) |", text)
        self.assertIn("| 1-16 MB | 80 | 200 |", text)
        self.assertIn("| Example.dll | code | Example Mod |", text)
        self.assertIn('Saves loaded during the watch: save "PG15" loaded at 20:00:22.', text)

    def test_without_counters_nothing_is_split(self):
        folder, _ = self.watch(tool=None)
        from phobos_modkit.report import render_markdown
        text = render_markdown(pw.watch_report(pw.Watch(folder), {}))
        self.assertIn("nothing attached to the game", text)
        self.assertIn("No .NET figures were recorded", text)
        self.assertNotIn("Outside .NET (claimed", text)

    def test_a_steady_game(self):
        samples = [(START + 5 * n, 10 * GB + n * 10 * MB, 0, 0) for n in range(10)]
        self.assertIn("**It held steady**", pw._verdict([s[1] for s in samples], pw._jumps(samples)))

    def test_jumps_do_not_overlap(self):
        samples = [(START + 10 * n, v, 0, 0) for n, v in enumerate([10, 10, 13, 13, 13, 13, 13, 13, 15, 15])]
        samples = [(t, v * GB, 0, 0) for t, v, *_ in samples]
        self.assertEqual([(1, 2, 3 * GB), (7, 8, 2 * GB)], pw._jumps(samples))

    def test_limits_are_refused(self):
        with self.assertRaises(pw.WatchError):
            pw.watch(1, self.tmp, 0, 5, 30, None)
        with self.assertRaises(pw.WatchError):
            pw.watch(1, self.tmp, 10, 5, 5, None)


class CommandTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        (self.tmp / "logs").mkdir()
        (self.tmp / "logs" / "Player.log").write_text(LOG, encoding="utf-8")
        tools = self.tmp / "tools"
        tools.mkdir()
        (tools / dd.native.program_name(dd.COUNTERS)).write_bytes(b"")
        self.environ = {"PHOBOS_MODKIT_CACHE": str(self.tmp / "cache"), dd.TOOLS_ENV: str(tools)}
        self.common = ["--game", str(self.tmp / "game"), "--config", str(self.tmp / "config")]
        owners = mock.patch.object(perf, "module_owners", side_effect=lambda names, *a, **k: ({}, []))
        owners.start()
        self.addCleanup(owners.stop)

    def test_watch_then_report_and_list(self):
        clock_ = FakeClock()
        with mock.patch.object(dd, "find_processes", return_value=[(4242, "RimWorld")]), \
                mock.patch.object(pm, "Process", FakeProcess(clock_)), mock.patch("sys.stderr", io.StringIO()):
            out = io.StringIO()
            code = perf_cli.main(["watch", "--minutes", "1", "--label", "reload", "--logs", str(self.tmp / "logs"), *self.common],
                                 environ=self.environ, out=out, popen=counters_popen, now=datetime(2026, 11, 19, 20, 0, 0),
                                 sleep=clock_.sleep, clock=clock_)
        self.assertEqual(perf_cli.EXIT_OK, code, out.getvalue())
        self.assertIn("memory watch 20261119-200000-reload", out.getvalue())
        out = io.StringIO()
        self.assertEqual(perf_cli.EXIT_OK, perf_cli.main(["watch-report", "reload", *self.common], environ=self.environ, out=out))
        self.assertIn("mostly in jumps", out.getvalue())
        out = io.StringIO()
        perf_cli.main(["list", *self.common], environ=self.environ, out=out)
        self.assertIn("Memory watches, newest first", out.getvalue())

    def test_watch_without_the_game(self):
        with mock.patch.object(dd, "find_processes", return_value=[]):
            out = io.StringIO()
            code = perf_cli.main(["watch", *self.common], environ=self.environ, out=out, run=lambda *a, **k: subprocess.CompletedProcess(a, 0, "", ""))
        self.assertEqual(perf_cli.EXIT_FAILED, code)
        self.assertIn("RimWorld is not running", out.getvalue())


if __name__ == "__main__":
    unittest.main()
