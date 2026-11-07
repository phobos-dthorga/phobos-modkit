"""Reading RimWorld's Player.log: entries, clues about mods, exception fingerprints and notices."""
import unittest

from support import fixture_text
from phobos_modkit.games.rimworld import log as rimworld_log
from phobos_modkit.logs.model import LogFile, Notice


def parse_fixture(name):
    return rimworld_log.parse(fixture_text(f"rimworld/{name}"), name)


def kinds(entry):
    return [(e.kind, e.value) for e in entry.evidence]


class Layout17(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.log = parse_fixture("player-1.7.log")
        cls.by_line = {e.line: e for e in cls.log.entries}

    def find(self, text):
        return next(e for e in self.log.entries if text in e.headline)

    def test_layout_header_and_message_count(self):
        self.assertEqual(self.log.layout, rimworld_log.LAYOUT_17)
        self.assertEqual(self.log.header["version"], "1.7.9999.1")
        self.assertEqual(len(self.log.entries), 18)

    def test_header_keeps_no_paths_or_command_line(self):
        self.assertNotIn("log file", {k.lower() for k in self.log.header})
        self.assertFalse(any("Users" in v for v in self.log.header.values()))

    def test_levels_categories_and_padded_levels(self):
        first = self.log.entries[0]
        self.assertEqual((first.level, first.category, first.headline), ("INFO", "VulkanStartup", "Engine starting."))
        self.assertEqual({e.level for e in self.log.entries}, {"INFO", "WARN", "ERROR"})

    def test_later_lines_belong_to_their_message(self):
        loading = self.find("Loading game from file")
        self.assertIn("  - example.tools (incompatible version)", loading.body)

    def test_xml_extensions_headers_keep_the_message_line(self):
        first, second = [e for e in self.log.entries if "Start of stack trace" in e.headline]
        self.assertIn("Example_First", first.headline)
        self.assertIn("Example_Second", second.headline)

    def test_clues_from_files_sources_and_the_logging_stack(self):
        patch_error = self.find("Example_First")
        self.assertEqual(kinds(patch_error), [("source", "Example Patches"), ("file", "workshop:1111111111"),
                                              ("caller", "XmlExtensions")])
        def_error = self.find("Exception loading def")
        self.assertIn(("source", "Example Local"), kinds(def_error))
        self.assertIn(("file", "mods:Example Local"), kinds(def_error))

    def test_clues_from_an_exception_trace(self):
        overlay = self.find("for Alice")
        self.assertEqual(kinds(overlay), [("assembly", "ExampleWidgets.dll"), ("namespace", "ExampleWidgets"),
                                          ("patch", "example.widgets"), ("finalizer", "example.rescue")])

    def test_game_assemblies_and_namespaces_are_never_clues(self):
        values = {e.value for entry in self.log.entries for e in entry.evidence}
        self.assertFalse(values & {"Assembly-CSharp.dll", "Verse", "RimWorld", "Brutal", "RimWorldWaylith"})

    def test_a_trace_makes_the_logging_stack_irrelevant(self):
        overlay = self.find("for Alice")
        self.assertNotIn("caller", [e.kind for e in overlay.evidence])

    def test_info_messages_name_their_caller(self):
        self.assertEqual(kinds(self.find("[Example Tools] Ready.")), [("caller", "ExampleTools")])

    def test_one_exception_worded_twice_shares_a_fingerprint(self):
        alice, bob = self.find("for Alice"), self.find("for Bob")
        self.assertEqual(alice.fingerprint, bob.fingerprint)
        self.assertEqual(alice.fingerprint, "System.NullReferenceException at RimWorld.Pawn_GuestTracker."
                                            "get_SlaveIsSecure < ExampleWidgets.Marks.Solve < "
                                            "Verse.PawnUIOverlay.DrawPawnGUIOverlay")
        self.assertEqual(self.find("Parsed 5.5").fingerprint, "")

    def test_notices(self):
        notices = {n.kind: n for n in self.log.notices}
        self.assertEqual(set(notices), {"save-loaded", "logging-stopped", "engine-allocations-held",
                                        "engine-allocations-at-shutdown", "finalizers"})
        saved = notices["save-loaded"]
        self.assertEqual((saved.data["save"], saved.data["mods"]), ("Colony1", 5))
        self.assertIn('2 marked "incompatible version": example.tools, example.patches.', saved.text)
        self.assertEqual(notices["logging-stopped"].data["after"], {"NativeAllocationRuntime": 3})
        self.assertEqual(notices["engine-allocations-held"].data["count"], 2)
        self.assertEqual(notices["engine-allocations-at-shutdown"].data["count"], 1)
        self.assertEqual(notices["finalizers"].data["harmonyIds"], ["example.rescue"])


class Layout16(unittest.TestCase):
    def test_unity_layout_reads_without_levels(self):
        log = parse_fixture("player-1.6.log")
        self.assertEqual(log.layout, rimworld_log.LAYOUT_16)
        self.assertEqual(len(log.entries), 4)
        self.assertEqual({e.level for e in log.entries}, {"UNKNOWN"})
        self.assertTrue(any("1.6 layout" in limit for limit in log.limits))

    def test_unity_traces_give_clues_and_fingerprints(self):
        log = parse_fixture("player-1.6.log")
        first, second = [e for e in log.entries if e.headline.startswith("Exception ticking")]
        self.assertIn(("namespace", "ExampleWidgets"), kinds(first))
        self.assertTrue(first.fingerprint)
        self.assertEqual(first.fingerprint, second.fingerprint)


class Frames(unittest.TestCase):
    def test_namespace_roots(self):
        cases = {
            "Verse.Root+<>c.<Start>b__10_1()": "Verse",
            ".Verse.Log.Error_Patch3(String text)": "Verse",
            "UsefulMarks.MarkerSettings.Solve(Pawn pawn)": "UsefulMarks",
            "DMD<Verse.Thing.Tick>(Thing this)": "",
            "(wrapper dynamic-method) Verse.Thing.Tick()": "",
        }
        for frame, root in cases.items():
            self.assertEqual(rimworld_log.namespace_root(frame), root, frame)


class Comparisons(unittest.TestCase):
    def log(self, name, loaded):
        notices = [Notice("save-loaded", "x")] if loaded else []
        return LogFile(name, rimworld_log.LAYOUT_17, [], notices=notices)

    def test_a_run_without_a_save_is_named(self):
        (notice,) = rimworld_log.comparison_notices(self.log("Player.log", True), self.log("Player-prev.log", False))
        self.assertIn("Player-prev.log loaded no save", notice.text)
        self.assertIn("as new", notice.text)

    def test_even_runs_need_no_notice(self):
        self.assertEqual(rimworld_log.comparison_notices(self.log("a", True), self.log("b", True)), [])


if __name__ == "__main__":
    unittest.main()
