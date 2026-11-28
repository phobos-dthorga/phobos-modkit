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

    def test_a_rate_over_the_refresh_interval_is_given_a_second(self):
        (self.tmp / "c.json").write_text(counters_json([(5, "rimworld.ticks ({tick} / 5 sec)", "", 3000),
                                                        (5, "dotnet.gc.collections ({collection} / 1 sec)", "", 4)]), encoding="utf-8")
        self.assertEqual([("rimworld.ticks", 600.0), ("dotnet.gc.collections", 4.0)],
                         [(name, value) for _, name, _, value in dd.counter_events(self.tmp / "c.json")])

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


def pace_popen(command, **_):
    """dotnet-counters collect asked for the game's meter too: the runtime's figures, with ticks and frames over each 5 s."""
    assert command[command.index("--counters") + 1] == "System.Runtime,DThorga.RimWorld", command
    counters_popen(command)
    points = json.loads(Path(command[command.index("-o") + 1]).read_text(encoding="utf-8"))["Events"]
    extra = []
    for second in range(0, 61, 5):
        slow = 25 <= second < 35
        extra += [(second, "rimworld.ticks ({tick} / 5 sec)", "", 1500 if slow else 3000),
                  (second, "rimworld.frames ({frame} / 5 sec)", "", 250 if slow else 300),
                  (second, "rimworld.frame.worst (ms)", "", 120 if slow else 20), (second, "rimworld.speed ({speed})", "", 3)]
    text = counters_json(extra)
    events = json.loads(text)["Events"]
    Path(command[command.index("-o") + 1]).write_text(json.dumps({"Events": points + events}), encoding="utf-8")
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
                         kw.get("popen", counters_popen), FakeProcess(self.clock), self.tmp / "Player.log")
        return folder, notes

    def test_the_games_pace_beside_its_memory(self):
        folder, _ = self.watch(popen=pace_popen)
        from phobos_modkit.report import render_json, render_markdown
        watched = pw.Watch(folder)
        text = render_markdown(pw.watch_report(watched, {}))
        self.assertIn("## The game's pace over the watch", text)
        self.assertIn("the game ran at superfast.", text)
        self.assertIn("| Ticks a second | 300 | 545 | 600 |", text)        # 3,000 over 5 s is 600 a second
        self.assertIn("| Frames a second | 50 | 58 | 60 |", text)
        self.assertIn("| Longest frame | 20 ms | 38 ms | 120 ms |", text)
        _, data = pw.status(folder.parent, folder.name, now=self.clock())
        self.assertEqual((600.0, 60.0, 20.0, 3.0), tuple(data["latest"][k] for k in ("ticks_a_second", "frames_a_second",
                                                                                    "longest_frame_ms", "speed")))

    def test_without_the_games_meter_the_watch_says_why(self):
        folder, _ = self.watch()
        from phobos_modkit.report import render_markdown
        text = render_markdown(pw.watch_report(pw.Watch(folder), {}))
        self.assertIn("needs D'thorga Framework 0.380.0 or newer running", text)
        self.assertNotIn("The game's pace", text)

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

    def test_a_stop_file_ends_the_watch_and_its_counters(self):
        folder = pw.new_folder(self.tmp / "watches", "stopped", datetime(2026, 11, 19, 20, 0, 0))
        counting = mock.Mock(wait=lambda timeout=None: 0)

        def popen(command, **kw):
            counters_popen(command, **kw)
            return counting

        def sleep(seconds):
            self.clock.sleep(seconds)
            if self.clock() - START >= 12:
                (folder / pw.STOP_FILE).write_text("stop", encoding="utf-8")
        pw.watch(4242, folder, 1, 5, 30, "dotnet-counters", "stopped", None, self.clock, sleep, popen, FakeProcess(self.clock))
        watched = pw.Watch(folder)
        self.assertEqual("it was asked to stop", watched.meta["reason"])
        self.assertEqual(3, len(watched.samples))
        self.assertLess(self.clock() - START, 14)
        counting.terminate.assert_called_once()
        self.assertFalse((folder / pw.STOP_FILE).exists())
        self.assertEqual(pw.ENDED, pw.state(folder, self.clock()))

    def test_marks_sit_beside_the_figures_and_a_reload_the_log_never_showed_is_said(self):
        folder, _ = self.watch()
        pw.add_mark(folder, "  loaded   PG15 ", START + 21, now=START + 70)
        pw.add_mark(folder, "reloading now", START + 40, now=START + 70)
        from phobos_modkit.report import render_markdown
        text = render_markdown(pw.watch_report(pw.Watch(folder), {}))
        self.assertIn('Your marks: "loaded PG15" at 20:00:21; "reloading now" at 20:00:40.', text)
        self.assertIn('you marked "loaded PG15" at 20:00:21', text)
        self.assertIn('**You marked "reloading now" at 20:00:40, but the log shows no save loaded in the 3 minutes after it**', text)
        self.assertNotIn('You marked "loaded PG15"', text)

    def test_marks_are_refused_when_empty_too_long_or_outside_the_watch(self):
        folder, _ = self.watch()
        for text, at in (("   ", None), ("x" * (pw.MAX_MARK + 1), None), ("late", START + 60 * 10)):
            with self.assertRaises(pw.WatchError):
                pw.add_mark(folder, text, at, now=START + 60 * 20)


def _kept_watch(where, started, last, ended=None, every=5, name=None):
    """A watch folder as a watcher leaves it: its meta, one sample at `last`, and `ended` when it finished."""
    import sqlite3
    from contextlib import closing
    from phobos_modkit import cache as derived
    folder = Path(where) / (name or datetime.fromtimestamp(started).strftime("%Y%m%d-%H%M%S"))
    folder.mkdir(parents=True)
    with closing(sqlite3.connect(folder / pw.DATABASE)) as conn:
        conn.executescript(pw.SCHEMA)
        meta = {"started": started, "every": every, "minutes": 15, "counters": True, "label": ""}
        if ended:
            meta.update({"ended": ended, "reason": "the time asked for ran out"})
        derived.write_meta(conn, meta)
        conn.execute("INSERT INTO sample VALUES (?, ?, ?, ?)", (last, 10 * GB, 5 * GB, 20 * GB))
        conn.commit()
    return folder


class StatusTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def test_running_cut_off_and_ended(self):
        running = _kept_watch(self.tmp, START, START + 100)
        self.assertEqual(pw.RUNNING, pw.state(running, START + 110))
        self.assertEqual(pw.CUT_OFF, pw.state(running, START + 200))
        ended = _kept_watch(self.tmp, START + 1000, START + 1100, ended=START + 1101)
        self.assertEqual(pw.ENDED, pw.state(ended, START + 9999))

    def test_a_running_watch_is_read_with_the_counters_written_so_far(self):
        folder = _kept_watch(self.tmp, START, START + 10)
        (folder / pw.COUNTERS_FILE).write_text(counters_json(
            [(5, "dotnet.gc.last_collection.memory.committed_size (By)", "", 4 * GB)], cut=False)[:-2], encoding="utf-8")
        pw.add_mark(folder, "opened the world map", START + 8, now=START + 12)
        report, data = pw.status(self.tmp, now=START + 12)
        self.assertEqual(pw.RUNNING, data["state"])
        self.assertEqual(4 * 10 ** 9, data["latest"]["collector"])
        self.assertEqual(6 * 10 ** 9, data["latest"]["outside"])
        self.assertEqual(12, data["elapsed"])
        self.assertEqual([{"t": START + 8, "text": "opened the world map"}], data["marks"])
        from phobos_modkit.report import render_markdown
        text = render_markdown(report)
        self.assertIn("**Watching**: 0 of 15 minutes", text)
        self.assertIn("only your marks show", text)
        self.assertEqual(pw.RUNNING, data["kept"][0]["state"])

    def test_the_running_watch_is_preferred_to_a_newer_one(self):
        running = _kept_watch(self.tmp, START, START + 100, name="20261119-200000-a")
        _kept_watch(self.tmp, START + 50, START + 60, ended=START + 61, name="20261119-200050-b")
        self.assertEqual(running, pw.find(self.tmp, None, prefer_running=True, now=START + 105))
        self.assertEqual("20261119-200050-b", pw.find(self.tmp, None).name)

    def test_nothing_kept(self):
        _, data = pw.status(self.tmp / "none", now=START)
        self.assertEqual("none", data["state"])

    def test_only_a_running_watch_can_be_asked_to_stop(self):
        running = _kept_watch(self.tmp, START, START + 100)
        pw.ask_to_stop(running, START + 101)
        self.assertTrue((running / pw.STOP_FILE).exists())
        ended = _kept_watch(self.tmp, START + 1000, START + 1100, ended=START + 1101)
        with self.assertRaises(pw.WatchError):
            pw.ask_to_stop(ended, START + 1200)


class CommandTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        (self.tmp / "logs").mkdir()
        (self.tmp / "logs" / "Player.log").write_text(LOG, encoding="utf-8")
        tools = self.tmp / "tools"
        tools.mkdir()
        (tools / dd.native.program_name(dd.COUNTERS)).write_bytes(b"")
        self.environ = {"PHOBOS_MODKIT_CACHE": str(self.tmp / "cache"), dd.TOOLS_ENV: str(tools),
                        "PHOBOS_HISTORY": str(self.tmp / "history")}
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

    def test_status_mark_and_stop_from_a_program(self):
        where = self.tmp / "cache" / pw.WATCH_FOLDER
        clock_ = FakeClock()
        _kept_watch(where, START, START)
        clock_.t = START + 4

        def run(*argv):
            out = io.StringIO()
            code = perf_cli.main([*argv, "--json", *self.common], environ=self.environ, out=out, clock=clock_)
            return code, json.loads(out.getvalue())
        code, answer = run("watch-mark", "reloading now")
        self.assertEqual((perf_cli.EXIT_OK, True, "reloading now"), (code, answer["data"]["ok"], answer["data"]["text"]))
        code, answer = run("watch-status")
        self.assertEqual(pw.RUNNING, answer["data"]["state"])
        self.assertEqual("reloading now", answer["data"]["marks"][0]["text"])
        code, answer = run("watch-stop")
        self.assertEqual((perf_cli.EXIT_OK, True), (code, answer["data"]["ok"]))
        clock_.t = START + 3600
        code, answer = run("watch-stop")
        self.assertEqual(perf_cli.EXIT_FAILED, code)
        self.assertEqual(False, answer["data"]["ok"])
        self.assertIn("No memory watch is running", answer["data"]["refusal"])

    def test_the_memory_page_finds_every_watch_command_by_its_surface(self):
        reports = perf_cli.MANIFEST["reports"]
        found = sorted(name for name, report in reports.items() if report.get("surface") == perf_cli.MEMORY_SURFACE)
        self.assertEqual(["watch", "watch-mark", "watch-report", "watch-status", "watch-stop"], found)

    def test_watch_without_the_game(self):
        with mock.patch.object(dd, "find_processes", return_value=[]):
            out = io.StringIO()
            code = perf_cli.main(["watch", *self.common], environ=self.environ, out=out, run=lambda *a, **k: subprocess.CompletedProcess(a, 0, "", ""))
        self.assertEqual(perf_cli.EXIT_FAILED, code)
        self.assertIn("RimWorld is not running", out.getvalue())
        out = io.StringIO()
        with mock.patch.object(dd, "find_processes", return_value=[]):
            perf_cli.main(["watch", "--json", *self.common], environ=self.environ, out=out,
                          run=lambda *a, **k: subprocess.CompletedProcess(a, 0, "", ""))
        data = json.loads(out.getvalue())["data"]
        self.assertEqual(False, data["ok"])
        self.assertIn("RimWorld is not running", data["refusal"])


if __name__ == "__main__":
    unittest.main()
