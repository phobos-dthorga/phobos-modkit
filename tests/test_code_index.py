"""The code tool on made-up C#: the scanner's hard cases, the index's staleness, and the four queries."""
import io
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest import mock

import support  # noqa: F401  (the package on the import path)
from phobos_modkit import cache as derived
from phobos_modkit.code import index
from phobos_modkit.code.cli import EXIT_FAILED, EXIT_OK, main
from phobos_modkit.code.scan import blank, declarations

# Written for these tests in the shapes decompilers and tidy code produce; no real source.
HARD = '''#define TRACE
using System;

namespace Example.Things
{
    [HeaderTitle(Label = "Props", Translate = true)]
    public class Widget : IThing
    {
        public enum Depth { Undefined, External, Internal }

        private float health;
        public bool required;
        public static readonly (string name, int count)[] Pairs = new (string, int)[2];
        public float Health => health;
        public Dictionary<string, int> Map { get; private set; } = new Dictionary<string, int> { { "a", 1 } };
        public event Action Changed;
        public int this[int index] => index;

        public Widget(float health) : base()
        {
            this.health = health;
        }

        public virtual string Label(float value, Sense sense = (Sense)1)
        {
            string text = $"{(value > 0 ? "up" : "down")} by {value:0.0} {{literal}}";
            char brace = '{';
            return text + @"a ""quoted"" } brace";
        }

        public void Apply(DamageInfo dinfo) => Apply(dinfo, IntVec2.Zero);

        private (int a, int b) Pair => (1, 2);

        public static bool operator ==(Widget a, Widget b) => true;
    }
}
'''
PATCHES = '''namespace Example.Patches;

[HarmonyPatch(typeof(Widget), "Apply",
    new[] { typeof(DamageInfo) })]
public static class ApplyPatch
{
    public static void Postfix(Widget __instance) => Note(__instance.Health); // it's a comment with { a brace
}
'''


class Scanner(unittest.TestCase):
    def test_blank_keeps_lines_and_hides_every_literal(self):
        blanked = blank(HARD)
        self.assertEqual(blanked.count("\n"), HARD.count("\n"))
        self.assertNotIn("up", blanked)
        self.assertNotIn("quoted", blanked)
        line = next(l for l in blanked.split("\n") if "char brace" in l)
        self.assertNotIn("{", line)

    def test_hard_declarations_are_found_with_their_lines(self):
        found = {(d.kind, d.full): (d.start, d.end) for d in declarations(HARD)}
        expect = {
            ("class", "Example.Things.Widget"): (6, 36),
            ("enum", "Example.Things.Widget.Depth"): (9, 9),
            ("field", "Example.Things.Widget.health"): (11, 11),
            ("field", "Example.Things.Widget.required"): (12, 12),
            ("field", "Example.Things.Widget.Pairs"): (13, 13),
            ("property", "Example.Things.Widget.Health"): (14, 14),
            ("property", "Example.Things.Widget.Map"): (15, 15),
            ("event", "Example.Things.Widget.Changed"): (16, 16),
            ("indexer", "Example.Things.Widget.this[]"): (17, 17),
            ("constructor", "Example.Things.Widget.Widget"): (19, 22),
            ("method", "Example.Things.Widget.Label"): (24, 29),
            ("method", "Example.Things.Widget.Apply"): (31, 31),
            ("property", "Example.Things.Widget.Pair"): (33, 33),
            ("operator", "Example.Things.Widget.operator =="): (35, 35),
        }
        for key, lines in expect.items():
            with self.subTest(key):
                self.assertEqual(found.get(key), lines)
        self.assertNotIn(("field", "Example.Things.Widget.External"), found)

    def test_attributes_with_braces_and_file_scoped_namespaces(self):
        found = {(d.kind, d.full): (d.start, d.end) for d in declarations(PATCHES)}
        self.assertEqual(found[("class", "Example.Patches.ApplyPatch")], (3, 8))
        self.assertEqual(found[("method", "Example.Patches.ApplyPatch.Postfix")], (7, 7))


class Command(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.src = root / "src"
        (self.src / "Things").mkdir(parents=True)
        (self.src / "Things" / "Widget.cs").write_text(HARD, encoding="utf-8")
        (self.src / "Patches.cs").write_text(PATCHES, encoding="utf-8")
        (self.src / "obj").mkdir()
        (self.src / "obj" / "Generated.cs").write_text("class Ignored { }", encoding="utf-8")
        self.cache = root / "cache"

    def tearDown(self):
        self.tmp.cleanup()

    def run_main(self, *args):
        out = io.StringIO()
        code = main(list(args) + ["--corpus", f"example={self.src}", "--cache", str(self.cache), "--no-redact"],
                    environ={}, out=out)
        return code, out.getvalue()

    def test_summary_builds_once_and_again_when_a_file_changes(self):
        code, text = self.run_main("summary")
        self.assertEqual(code, EXIT_OK)
        self.assertIn("| example | 2 |", text)
        self.assertIn("built now", text)
        self.assertIn("current", self.run_main("summary")[1])
        time.sleep(0.01)
        (self.src / "Patches.cs").write_text(PATCHES + "\nnamespace More { class Extra { } }\n", encoding="utf-8")
        self.assertIn("built now", self.run_main("summary")[1])

    def test_find_outline_show_and_refs(self):
        code, text = self.run_main("find", "*Apply*")
        self.assertIn("Example.Patches.ApplyPatch", text)
        self.assertIn("| method | Example.Things.Widget.Apply |", text)
        code, text = self.run_main("outline", "Widget")
        self.assertEqual(code, EXIT_OK)
        self.assertIn("| 24 | method | public virtual string Label(float value, Sense sense = (Sense)1) |", text)
        big = HARD.replace("namespace Example.Things", "\n" * 2000 + "namespace Example.Things")
        (self.src / "Things" / "Widget.cs").write_text(big, encoding="utf-8")
        self.assertIn("| 2024 | method |", self.run_main("outline", "Widget")[1], "line numbers without separators")
        (self.src / "Things" / "Widget.cs").write_text(HARD, encoding="utf-8")
        code, text = self.run_main("show", "Widget.Label")
        self.assertIn("24|         public virtual string Label(", text)
        self.assertIn("29|         }", text)
        code, text = self.run_main("refs", "Health")
        self.assertIn("2 lines use Health: 2 in example", text)
        self.assertIn("| Example.Patches.ApplyPatch.Postfix | example:Patches.cs:7 |", text)
        self.assertNotIn("Ignored", self.run_main("find", "*")[1])

    def test_misses_say_what_to_try(self):
        code, text = self.run_main("show", "Nothing.Here")
        self.assertEqual(code, EXIT_FAILED)
        self.assertIn('Try: code find "*Here*"', text)
        code, text = self.run_main("summary", "--in", "nope*")
        self.assertIn("No corpus matches nope*", text)


class TwoRunsAtOnce(unittest.TestCase):
    """Two runs wanting one index at once (27 Nov 2026: a second run died deleting the first's half-built file)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        (root / "src").mkdir()
        (root / "src" / "Widget.cs").write_text(HARD, encoding="utf-8")
        self.corpus = index.Corpus("example", root / "src")
        self.cache = root / "cache"
        self.target = index.index_path(self.cache, self.corpus)
        self.cache.mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def test_a_second_run_waits_and_uses_what_the_first_built(self):
        waited = []
        with derived.one_builder(self.target):
            second = threading.Thread(target=lambda: waited.append(index.ensure(self.corpus, self.cache,
                                                                                waiting=lambda c: waited.append(c.name))))
            second.start()
            time.sleep(0.2)
            self.assertTrue(second.is_alive(), "the second run waits while the first holds the build")
            index.build(self.corpus, self.target)
        second.join(10)
        self.assertEqual(waited, ["example", (self.target, False)])

    def test_another_runs_half_built_file_is_left_alone(self):
        theirs = self.target.with_name(self.target.stem + ".999-1.building")
        with open(theirs, "wb") as held:            # held open, as a live build holds it
            held.write(b"half")
            path, built = index.ensure(self.corpus, self.cache)
        self.assertTrue(built)
        self.assertTrue(theirs.exists())
        self.assertEqual(index.counts(path)[0], 1)

    def test_a_stopped_runs_leftovers_are_cleared_and_never_block(self):
        stale = [self.target.with_name(self.target.stem + ".building"),     # named as before 1.141.1
                 self.target.with_name(self.target.stem + ".123-4.building-journal")]
        fresh = self.target.with_name(self.target.stem + ".456-7.building")
        old = time.time() - index.BUILD_STALE_S - 60
        for path in stale + [fresh]:
            path.write_bytes(b"half")
        for path in stale:
            os.utime(path, (old, old))
        path, built = index.ensure(self.corpus, self.cache)
        self.assertTrue(built)
        self.assertEqual([p.exists() for p in stale], [False, False])
        self.assertTrue(fresh.exists(), "a recent one may be a live build's")
        self.assertEqual(sorted(p.name for p in self.cache.glob("*.lock")), [])

    def test_a_half_built_file_that_will_not_delete_is_no_error(self):
        real = derived.remove

        def stubborn(path):
            if str(path).endswith(".building"):
                raise PermissionError(32, "being used by another process", str(path))
            real(path)

        with mock.patch.object(index.derived, "remove", stubborn):
            path, built = index.ensure(self.corpus, self.cache, rebuild=True)
        self.assertTrue(built)
        self.assertEqual(index.counts(path)[0], 1)


class OnlyTheIndexesRead(unittest.TestCase):
    """A narrowed query builds only the indexes it reads (27 Nov 2026: one corpus's question built about ninety)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.trees = root / "trees"
        for name in ("Alpha", "Beta"):
            (self.trees / name).mkdir(parents=True)
            (self.trees / name / f"{name}.cs").write_text(f"namespace {name} {{ public class {name}Thing {{ }} }}\n",
                                                           encoding="utf-8")
        self.own = root / "own"
        self.own.mkdir()
        (self.own / "Own.cs").write_text("namespace Own { public class OwnThing { } }\n", encoding="utf-8")
        self.cache = root / "cache"

    def tearDown(self):
        self.tmp.cleanup()

    def run_main(self, *args):
        out = io.StringIO()
        code = main(list(args) + ["--cache", str(self.cache), "--no-redact"], environ={}, out=out)
        return code, out.getvalue()

    def indexes(self):
        return sorted(p.name.split("-")[0] for p in (self.cache / index.CACHE_FOLDER).glob("*.sqlite"))

    def test_defaults_are_read_when_nothing_is_named(self):
        code, text = self.run_main("find", "*Thing", "--default-each-in", str(self.trees), "--default-corpus", f"own={self.own}")
        self.assertEqual(code, EXIT_OK)
        self.assertIn("Indexed now: own, Alpha, Beta.", text)
        self.assertEqual(self.indexes(), ["Alpha", "Beta", "own"])

    def test_a_corpus_named_on_the_command_line_is_read_alone(self):
        code, text = self.run_main("find", "*Thing", "--corpus", f"mine={self.own}", "--default-each-in", str(self.trees))
        self.assertEqual(code, EXIT_OK)
        self.assertIn("Own.OwnThing", text)
        self.assertNotIn("AlphaThing", text)
        self.assertEqual(self.indexes(), ["mine"])

    def test_in_builds_only_the_matching_indexes(self):
        code, text = self.run_main("refs", "BetaThing", "--in", "beta", "--default-each-in", str(self.trees),
                                   "--default-corpus", f"own={self.own}")
        self.assertEqual(code, EXIT_OK)
        self.assertIn("1 lines use BetaThing: 1 in Beta", text)
        self.assertEqual(self.indexes(), ["Beta"])


if __name__ == "__main__":
    unittest.main()
