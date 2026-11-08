"""The code tool on made-up C#: the scanner's hard cases, the index's staleness, and the four queries."""
import io
from pathlib import Path
import tempfile
import time
import unittest

import support  # noqa: F401  (the package on the import path)
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


if __name__ == "__main__":
    unittest.main()
