"""code compare: two builds, declaration by declaration."""
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

import support  # noqa: F401  (the package on the import path)
from phobos_modkit.code import compare, index
from phobos_modkit.code.cli import EXIT_FAILED, EXIT_OK, main

OLD = """using System;
namespace Example
{
    public enum Sense { Low, High }

    public class Widget
    {
        public int count;
        public const string Tag = "old";

        public float Rate() => 1.5f;

        public int Same(int a)
        {
            //IL_0001: note the decompiler left
            return a;
        }

        public int Twice(int a) { return a * 2; }
        public int Twice(string a) { return a.Length; }

        public void Goes() { }

        public void Grows(int a)
        {
            Console.WriteLine(a);
        }

        public string Say() { return "hello"; }
    }

    public class Plain { }
}
"""

NEW = """namespace Example
{
    public enum Sense { Low, High, Extreme }

    public sealed class Widget
    {
        public long count;
        public const string Tag = "new";

        // A comment that must not count.
        public float Rate() => 2.5f;

        public int Same(int a)
        {
            //IL_0009: the decompiler's note moved
            return a;
        }

        public int Twice(string a) { return a.Length + 1; }
        public int Twice(int a) { return a * 2; }

        public void Comes() { }

        public void Grows(int a, int b)
        {
            Console.WriteLine(a);
            Console.WriteLine(b);
        }

        public string Say() { return "goodbye"; }
    }

    public class Plain { }

    public class Brand
    {
        public int One() { return 1; }
        public class Inside { public int Two() { return 2; } }
    }
}
"""


class Compare(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        for name, text in (("old", OLD), ("new", NEW)):
            (self.root / name).mkdir()
            (self.root / name / "Widget.cs").write_text(text, encoding="utf-8")
        self.cache = self.root / "cache"

    def tearDown(self):
        self.tmp.cleanup()

    def run_main(self, *args, left="old", right="new"):
        out = io.StringIO()
        code = main(["compare", str(self.root / left), str(self.root / right), *args, "--cache", str(self.cache),
                     "--no-redact"], environ={}, out=out)
        return code, out.getvalue()

    def data(self, *args):
        out = io.StringIO()
        code = main(["compare", str(self.root / "old"), str(self.root / "new"), *args, "--cache", str(self.cache), "--json"],
                    environ={}, out=out)
        self.assertEqual(code, EXIT_OK)
        return json.loads(out.getvalue())["report"]

    def section(self, text, heading):
        self.assertIn(heading, text)
        return text.split(heading, 1)[1].split("\n## ", 1)[0]

    def test_what_is_listed_as_added_and_removed(self):
        code, text = self.run_main()
        self.assertEqual(code, EXIT_OK)
        added = self.section(text, "## Declarations added")
        self.assertIn("Example.Widget.Comes", added)
        self.assertIn("Example.Brand", added)
        self.assertNotIn("Example.Brand.One", added, "a new type is one row")
        self.assertNotIn("Example.Brand.Inside", added, "a nested type of a new type is inside it")
        self.assertIn("Example.Widget.Goes", self.section(text, "## Declarations removed"))

    def test_a_type_and_a_member_can_change_their_signature(self):
        signatures = self.section(self.run_main()[1], "## New signatures")
        self.assertIn("public sealed class Widget", signatures)
        self.assertIn("public long count", signatures)
        self.assertIn("public void Grows(int a, int b)", signatures, "one left over each side of a name is a new signature")

    def test_values_only_and_code(self):
        bodies = self.section(self.run_main()[1], "## New bodies")
        for name in ("Rate", "Say", "Tag"):
            self.assertRegex(bodies, rf"Example\.Widget\.{name} \| values only")
        self.assertRegex(bodies, r"Example\.Widget\.Twice \| code")
        self.assertRegex(bodies, r"Example\.Sense \| code", "an enum's members are its body")

    def test_comments_notes_layout_and_order_do_not_count(self):
        text = self.run_main()[1]
        self.assertNotIn("Example.Widget.Same", text)
        self.assertNotIn("Example.Plain", text)
        self.assertEqual(text.count("Example.Widget.Twice"), 1, "overloads pair by parameters, whatever their order")

    def test_identical_sides_say_so(self):
        code, text = self.run_main(right="old")
        self.assertEqual(code, EXIT_OK)
        self.assertIn("Nothing differs.", text)

    def test_only_narrows_every_count(self):
        text = self.run_main("--only", "*.Rate")[1]
        self.assertIn("0 added, 0 removed, 0 with a new signature, 1 with a new body (1 of them values only), 0 the same.", text)

    def test_show_prints_a_diff_and_says_when_nothing_changed(self):
        code, text = self.run_main("--show", "Widget.Say")
        self.assertEqual(code, EXIT_OK)
        self.assertIn('-        public string Say() { return "hello"; }', text)
        self.assertIn('+        public string Say() { return "goodbye"; }', text)
        code, text = self.run_main("--show", "Widget.Comes")
        self.assertIn("(added)", text)
        self.assertIn("+         public void Comes() { }", text)
        code, text = self.run_main("--show", "Widget.Same")
        self.assertEqual(code, EXIT_FAILED)
        self.assertIn("did not change", text)

    def test_an_empty_side_is_an_error_not_a_list_of_removals(self):
        (self.root / "empty").mkdir()
        (self.root / "empty" / "Nothing.cs").write_text("// nothing here\n", encoding="utf-8")
        code, text = self.run_main(right="empty")
        self.assertEqual(code, EXIT_FAILED)
        self.assertIn("holds no C# declarations", text)
        self.assertNotIn("removed", text)

    def test_sides_with_nothing_in_common_are_called_out(self):
        (self.root / "other").mkdir()
        (self.root / "other" / "Other.cs").write_text("namespace Elsewhere { class Thing { } }\n", encoding="utf-8")
        code, text = self.run_main(right="other")
        self.assertEqual(code, EXIT_OK)
        self.assertIn("share no declarations", text)
        self.assertNotIn("share no declarations", self.run_main()[1])

    def test_a_side_that_does_not_exist_is_named(self):
        code, text = self.run_main(right="missing")
        self.assertEqual(code, EXIT_FAILED)
        self.assertIn("is not a .dll, a corpus or a folder", text)

    def test_a_side_can_be_a_corpus_by_name(self):
        out = io.StringIO()
        code = main(["compare", "OLDER", str(self.root / "new"), "--corpus", f"older={self.root / 'old'}", "--cache",
                     str(self.cache), "--no-redact"], environ={}, out=out)
        self.assertEqual(code, EXIT_OK)
        self.assertIn("older has", out.getvalue())

    def test_the_output_is_stable(self):
        self.assertEqual(self.data(), self.data())

    def test_parameters_ignore_a_tuple_return_and_read_indexers(self):
        def item(kind, name, signature):
            return compare.Item(kind, name, f"T.{name}", signature, "a.cs", 1, 1)
        self.assertEqual(compare.parameters(item("method", "Pair", "public (int, int) Pair(string a)")), "string a")
        self.assertEqual(compare.parameters(item("method", "Get", "public T Get<T>(Func<int, T> f) where T : class")),
                         "Func<int, T> f")
        self.assertEqual(compare.parameters(item("indexer", "this", "public int this[int a, int b]")), "int a, int b")
        self.assertEqual(compare.parameters(item("field", "x", "public int x")), "")


class Decompile(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.dll = self.root / "Thing.dll"
        self.dll.write_bytes(b"not really an assembly")
        self.cache = self.root / "cache"
        self.commands = []

    def tearDown(self):
        self.tmp.cleanup()

    def fake(self, command, **_):
        self.commands.append(command)
        out = Path(command[command.index("-o") + 1])
        (out / "Thing.cs").write_text("namespace N { public class Thing { } }\n", encoding="utf-8")
        return subprocess.CompletedProcess(command, 0, "", "")

    def tool(self):
        return "ilspycmd"

    def test_decompiles_once_for_the_same_bytes_and_references(self):
        first, built = compare.decompile(self.dll, self.cache, self.tool, ["refs"], run=self.fake)
        self.assertTrue(built)
        self.assertEqual(self.commands[0][:2], ["ilspycmd", "-p"])
        self.assertIn("refs", self.commands[0])
        self.assertEqual(compare.decompile(self.dll, self.cache, self.tool, ["refs"], run=self.fake), (first, False))
        self.assertEqual(len(self.commands), 1)
        self.assertTrue(compare.decompile(self.dll, self.cache, self.tool, [], run=self.fake)[1], "other references, other source")
        self.dll.write_bytes(b"a newer build")
        self.assertTrue(compare.decompile(self.dll, self.cache, self.tool, ["refs"], run=self.fake)[1], "other bytes, other source")

    def test_a_cached_decompile_needs_no_tool(self):
        compare.decompile(self.dll, self.cache, self.tool, run=self.fake)

        def no_tool():
            raise AssertionError("the tool was looked for")
        self.assertFalse(compare.decompile(self.dll, self.cache, no_tool, run=self.fake)[1])

    def test_a_failed_decompile_leaves_nothing_and_says_why(self):
        def fail(command, **_):
            return subprocess.CompletedProcess(command, 3, "", "bad image")
        with self.assertRaisesRegex(index.CodeError, "bad image"):
            compare.decompile(self.dll, self.cache, self.tool, run=fail)
        self.assertEqual(list(self.cache.iterdir()), [])

    def test_exit_zero_with_no_source_is_a_failure(self):
        def empty(command, **_):
            return subprocess.CompletedProcess(command, 0, "", "")
        with self.assertRaisesRegex(index.CodeError, "no source"):
            compare.decompile(self.dll, self.cache, self.tool, run=empty)

    def test_evict_keeps_the_most_recent(self):
        for number in range(4):
            self.dll.write_bytes(bytes([number]))
            folder, _ = compare.decompile(self.dll, self.cache, self.tool, run=self.fake)
            os.utime(folder / compare.COMPLETE_MARKER, (1000 + number, 1000 + number))
        compare.evict(self.cache, keep=2)
        kept = sorted((p / compare.COMPLETE_MARKER).stat().st_mtime for p in self.cache.iterdir())
        self.assertEqual(kept, [1002, 1003])

    def test_a_named_decompiler_must_exist(self):
        with self.assertRaisesRegex(index.CodeError, "No decompiler at"):
            compare._find_decompiler(str(self.root / "absent.exe"), {}, None)


if __name__ == "__main__":
    unittest.main()
