"""The heap reader: its answers turned into reports, rimworld-perf's look-serve relay, and (on Windows, with the .NET SDK) a real
snapshot of a small made-up program (fixtures/dotnet/HeapFixture) read end to end.

Snapshots of a running program are a Windows feature, so the reading tests run on Windows only; there, without the .NET SDK, they
are skipped unless PHOBOS_REQUIRE_NATIVE is set, as for the other native tools.
"""
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from support import FIXTURES
from phobos_modkit import file_lock
from phobos_modkit import heap_reader as hr
from phobos_modkit import native
from phobos_modkit.dotnet_snapshots import heap_owners
from phobos_modkit.games.rimworld import look
from phobos_modkit.games.rimworld import perf_cli
from phobos_modkit.games.rimworld import perf_snapshots as snap
from phobos_modkit.report import render_markdown
from phobos_modkit.sampling import MOD, UNKNOWN, Owner

HAVE_DOTNET = shutil.which("dotnet") is not None
REQUIRE = bool(os.environ.get("PHOBOS_REQUIRE_NATIVE"))
WINDOWS = sys.platform == "win32"
FIXTURE_PROJECT = FIXTURES / "dotnet" / "HeapFixture" / "HeapFixture.csproj"

OVERVIEW = {"totalObjects": 30, "totalBytes": 3000, "freeBytes": 500, "untyped": 0, "seconds": 0.2,
            "types": [{"type": "System.String", "module": "System.Private.CoreLib", "count": 20, "bytes": 1000},
                      {"type": "Mine.Thing", "module": "MyMod", "count": 8, "bytes": 1600},
                      {"type": "System.Collections.Generic.List<Mine.Thing>", "module": "System.Private.CoreLib", "count": 2,
                       "bytes": 400}]}
PATH = {"root": "StaticVar", "static": "Mine.Store.All", "pinned": False, "skipped": 1,
        "links": [{"address": "0x10", "type": "System.Collections.Generic.List<Mine.Thing>", "summary": ""},
                  {"address": "0x20", "type": "Mine.Thing[]", "summary": "4 items", "field": "_items"},
                  {"address": "0x30", "type": "Mine.Thing", "summary": "Steel · 75", "field": "[2]"}]}


class FakeSession:
    """Stands in for heap_reader.Session: answers from a table, numbering as the reader does."""

    def __init__(self, pid, folder, describe, limit_seconds):
        self.ready = {"ready": True, "pid": pid, "snapshotMs": 400, "runtime": "10.0.15"}
        self.describe, self.closed = describe, False

    def ask(self, request):
        if request["op"] == "overview":
            return {"ok": True, "id": 1, "data": OVERVIEW}
        if request["op"] == "release":
            return {"ok": True, "id": 2, "released": True, "data": {}}
        return {"ok": False, "id": 3, "error": "There is no object at 0x1 in this snapshot."}

    def close(self):
        self.closed = True


class Answers(unittest.TestCase):
    def test_an_overview_becomes_the_kits_heap_largest_first(self):
        heap = hr.heap_of(OVERVIEW)
        self.assertEqual((heap.total_bytes, heap.total_objects), (3000, 30))
        self.assertEqual([t.type for t in heap.types][:2], ["Mine.Thing", "System.String"])

    def test_a_collection_of_a_mods_type_counts_for_that_mod(self):
        heap = hr.heap_of(OVERVIEW)
        owners = heap_owners(heap, lambda m: Owner(MOD, "My Mod") if m == "MyMod" else Owner(UNKNOWN, m))
        owner, through = owners[("System.Collections.Generic.List<Mine.Thing>", "System.Private.CoreLib")]
        self.assertEqual((owner.name, through), ("My Mod", "Mine.Thing"))

    def test_a_path_reads_from_the_static_field_down(self):
        lines = hr.path_lines(PATH)
        self.assertEqual(lines[0], "Held from the static field Mine.Store.All:")
        self.assertEqual(lines[-1], "through [2]: Mine.Thing (Steel · 75) at 0x30")

    def test_garbage_is_said_to_be_garbage_not_a_leak(self):
        text = render_markdown(hr.why_report("t", {"type": "Mine.Orphan", "count": 20, "totalBytes": 480, "checked": 20,
                                                   "paths": [], "noneReachable": True}))
        self.assertIn("garbage the collector has not reclaimed yet", text)
        self.assertIn("They are not a leak", text)

    def test_values_read_as_a_person_would(self):
        self.assertEqual(hr.value_text({"kind": "struct", "fields": [{"name": "X", "kind": "value", "value": "3"},
                                                                     {"name": "Z", "kind": "value", "value": "4"}]}),
                         "{ X = 3, Z = 4 }")
        self.assertEqual(hr.value_text({"kind": "null"}), "nothing (null)")
        self.assertEqual(hr.value_text({"kind": "link", "valueType": "Verse.ThingDef", "summary": "Steel", "address": "0x9"}),
                         "→ Verse.ThingDef (Steel) at 0x9")

    def test_a_refusal_keeps_the_readers_words(self):
        with self.assertRaises(hr.LookError) as caught:
            hr.answer_data({"ok": False, "error": "There is no object at 0x1 in this snapshot."})
        self.assertIn("0x1", str(caught.exception))

    def test_the_command_names_the_trusted_install_and_each_request(self):
        line = hr.command("reader", "run", 42, "C:/Games/RimWorld", ["defName"], None, [{"op": "overview"}])
        self.assertEqual(line, ["reader", "run", "--pid", "42", "--runtime-folder", "C:/Games/RimWorld", "--describe", "defName",
                                "--request", '{"op": "overview"}'])


class Relay(unittest.TestCase):
    def test_an_overview_gains_owners_and_is_kept_and_ids_are_the_callers(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = io.StringIO()
            requests = io.StringIO('{"op": "overview", "id": "a"}\n\n{"op": "object", "address": "0x1", "id": 7}\n'
                                   '{"op": "release", "id": "z"}\n{"op": "info"}\n')
            code = look.serve(5, tmp, tmp, lambda names: ({"MyMod": Owner(MOD, "My Mod")}, []), "day 4", 60, top=10,
                              stdin=requests, stdout=out, session_class=FakeSession)
            lines = [json.loads(line) for line in out.getvalue().splitlines()]
            kept = snap.kept(tmp)
            meta, heap = snap.read_heap(kept[0])
        self.assertEqual(code, 0)
        self.assertTrue(lines[0]["ready"])
        overview = lines[1]
        self.assertEqual((overview["id"], overview["ok"]), ("a", True))
        self.assertEqual(overview["data"]["owners"][0], {"name": "My Mod", "kind": MOD, "bytes": 2000, "count": 10})
        self.assertEqual(overview["data"]["kept"], kept[0].name)
        self.assertEqual((lines[2]["id"], lines[2]["ok"]), (7, False))
        self.assertTrue(lines[3]["released"])
        self.assertEqual(len(lines), 4, "nothing is answered after the snapshot is let go")
        self.assertEqual((meta["method"], meta["label"], heap.total_bytes), ("snapshot", "day 4", 3000))

    def test_a_snapshot_heap_report_says_what_a_snapshot_is(self):
        with tempfile.TemporaryDirectory() as tmp:
            kept, heap = look.save_overview(tmp, {"pid": 5, "snapshotMs": 431}, OVERVIEW, "x")
            text = render_markdown(snap.heap_report(kept, snap.meta_of(kept), heap, {}, []))
        self.assertIn("The game paused for 431 ms", text)
        self.assertIn("garbage collector has not reclaimed yet", text)
        self.assertNotIn("forced a full garbage collection", text)
        self.assertNotIn("PerfView", text)

    def test_a_game_not_running_is_one_json_line_too(self):
        out = io.StringIO()
        code = perf_cli.main(["look-serve"], environ={}, out=out,
                             run=lambda *a, **k: subprocess.CompletedProcess(a, 0, "", ""))
        answer = json.loads(out.getvalue())
        self.assertEqual((code, answer["ready"]), (1, False))
        self.assertIn("not running", answer["error"])

    def test_a_refused_snapshot_is_one_line_saying_why(self):
        class Refusing:
            def __init__(self, *args, **kwargs):
                raise hr.LookError("That program's .NET runtime is in D:/Elsewhere, not in the install named.")
        out = io.StringIO()
        code = look.serve(5, "C:/Games", "C:/heaps", lambda names: ({}, []), stdin=io.StringIO(""), stdout=out,
                          session_class=Refusing)
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(out.getvalue())["ready"], False)


def fixture_program():
    """Build the made-up program (once per run) and return its path."""
    out = native.build_dir() / "dotnet" / "fixtures" / "HeapFixture"
    program = out / native.program_name("HeapFixture")
    if not getattr(fixture_program, "built", False):
        # The gate's two Python lanes build it into the same folder: one at a time, as the kit's own tools are built.
        with file_lock.held(out.with_name(out.name + ".lock"), 10 * 60, 30 * 60):
            result = subprocess.run(["dotnet", "build", str(FIXTURE_PROJECT), "-c", "Release", "-o", str(out), "--nologo", "-v",
                                     "q"], capture_output=True, text=True, check=False)
        if result.returncode != 0:
            raise AssertionError("the fixture did not build:\n" + result.stdout[-2000:])
        fixture_program.built = True
    return program


@unittest.skipUnless(WINDOWS, hr.WINDOWS_ONLY)
@unittest.skipUnless(HAVE_DOTNET or REQUIRE, "needs the .NET SDK")
class Reading(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.folder = hr.framework_runtime_folder(10)
        if cls.folder is None:
            raise AssertionError("no .NET 10 runtime found by dotnet --list-runtimes")
        cls.program = subprocess.Popen([str(fixture_program())], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True,
                                       encoding="utf-8")
        cls.pid = int(cls.program.stdout.readline().split()[1])

    @classmethod
    def tearDownClass(cls):
        cls.program.stdin.close()
        cls.program.wait(timeout=30)
        cls.program.stdout.close()

    def test_one_run_reads_types_kinds_and_why(self):
        requests = [{"op": "overview"}, {"op": "kind", "type": "HeapFixture.Colonist", "take": 3, "open": True},
                    {"op": "why", "type": "HeapFixture.Orphan"}, {"op": "why", "type": "HeapFixture.Colonist", "sample": 1}]
        ready, answers = hr.run_requests(self.pid, self.folder, requests, ["Name", "def.defName"])
        self.assertEqual(ready["pid"], self.pid)
        overview, kind, orphans, colonists = (hr.answer_data(a) for a in answers)
        types = {t["type"]: t for t in overview["types"]}
        self.assertEqual((types["HeapFixture.Colonist"]["count"], types["HeapFixture.Colonist"]["module"]), (12, "HeapFixture"))
        self.assertEqual(kind["count"], 12)
        self.assertEqual(kind["items"][0]["summary"], "Colonist 0 · Human")
        fields = {f["name"]: f for f in kind["opened"]["fields"]}
        self.assertEqual(fields["Name"]["value"], "Colonist 0")
        self.assertEqual(fields["Mood"]["value"], "Content (0)")
        self.assertEqual([f["value"] for f in fields["Position"]["fields"]], ["0", "100"])
        self.assertEqual(fields["Bonded"]["summary"], "Colonist 1 · Human")
        if orphans["count"]:    # a collection would have reclaimed them; none should have run
            self.assertTrue(orphans["noneReachable"])
        self.assertEqual(colonists["paths"][0]["static"], "HeapFixture.Colony.Colonists")

    def test_a_session_opens_holds_and_lets_go(self):
        session = hr.Session(self.pid, self.folder, ["Name"])
        try:
            kind = hr.answer_data(session.ask({"op": "kind", "type": "System.Collections.Generic.Dictionary<System.String, System.Int32>"}))
            stocks = [hr.answer_data(session.ask({"op": "object", "address": i["address"]})) for i in kind["items"]]
            stock = next(s for s in stocks if s.get("items", {}).get("count") == 2)
            pairs = [[f["value"] for f in item["fields"]] for item in stock["items"]["items"]]
            self.assertEqual(pairs, [["Steel", "75"], ["Silver", "1200"]])
            colonist = hr.answer_data(session.ask({"op": "kind", "type": "HeapFixture.Colonist", "take": 1}))["items"][0]
            holders = hr.answer_data(session.ask({"op": "holders", "address": colonist["address"]}))
            self.assertEqual(holders["holders"][0]["field"], "[0]")
            refused = session.ask({"op": "object", "address": "0x10"})
            self.assertFalse(refused["ok"])
            self.assertTrue(session.ask({"op": "release"})["released"])
        finally:
            session.close()

    def test_a_runtime_outside_the_named_install_is_refused_before_reading(self):
        with tempfile.TemporaryDirectory() as tmp, self.assertRaises(hr.LookError) as caught:
            hr.run_requests(self.pid, tmp, [{"op": "overview"}])
        self.assertIn("not in the install named", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
