"""The gate: output parsers on hand-written tool output, and the runner on a made-up repository with real subprocesses."""
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

import support  # noqa: F401  (the package on the import path)
from phobos_modkit.gate import parsers
from phobos_modkit.gate.cli import EXIT_FAILED, EXIT_OK, EXIT_USAGE, main
from phobos_modkit.gate.runner import GateError, load, run, select

# Written by hand in the shapes the tools print; never copied from a real build.
MSBUILD_FAILED = r"""  Example -> C:\repo\src\Example\bin\Example.dll
C:\repo\src\Example\Thing.cs(12,5): error CS0103: The name 'missing' does not exist in the current context [C:\repo\src\Example\Example.csproj]
C:\repo\src\Example\Thing.cs(30,9): warning CS0168: The variable 'e' is declared but never used [C:\repo\src\Example\Example.csproj]
C:\repo\src\Example\Thing.cs(12,5): error CS0103: The name 'missing' does not exist in the current context [C:\repo\src\Example\Example.csproj]
MSBUILD : error MSB1009: Project file does not exist.
Build FAILED.
"""
DOTNET_TEST_FAILED = """  Failed Example.Tests.RuleTests.HalvesAtDouble [3 ms]
  Error Message:
   Assert.Equal() Failure: Values differ
  Stack Trace:
     at Example.Tests.RuleTests.HalvesAtDouble()
Failed!  - Failed:     1, Passed:    41, Skipped:     0, Total:    42, Duration: 30 ms - Example.Tests.dll (net10.0)
"""
DOTNET_TEST_PASSED = "Passed!  - Failed:     0, Passed:    56, Skipped:     0, Total:    56, Duration: 26 ms - Example.Tests.dll (net10.0)\n"
UNITTEST_FAILED = """..F.E
======================================================================
ERROR: test_reads (test_tool.ReaderTests.test_reads)
----------------------------------------------------------------------
Traceback (most recent call last):
  File "tests/test_tool.py", line 9, in test_reads
    open('missing')
FileNotFoundError: [Errno 2] No such file or directory: 'missing'

======================================================================
FAIL: test_adds (test_tool.MathTests.test_adds)
----------------------------------------------------------------------
Traceback (most recent call last):
  File "tests/test_tool.py", line 4, in test_adds
    self.assertEqual(1 + 1, 3)
AssertionError: 2 != 3

----------------------------------------------------------------------
Ran 5 tests in 0.010s

FAILED (failures=1, errors=1)
"""
CARGO_FAILED = """error[E0308]: mismatched types
  --> crates/xml-index/src/lib.rs:41:17
   |
41 |     let x: u8 = "no";
   |                 ^^^^ expected `u8`, found `&str`
warning: unused variable: `y`
 --> crates/xml-index/src/lib.rs:50:9
error: could not compile `xml-index` (lib) due to 1 previous error
"""
CARGO_TESTS = """running 3 tests
test reads ... ok
test writes ... FAILED
test result: FAILED. 2 passed; 1 failed; 0 ignored; 0 measured; 0 filtered out; finished in 0.01s
"""


class Parsers(unittest.TestCase):
    def test_msbuild_keeps_errors_once_and_shortens_paths(self):
        parsed = parsers.msbuild(MSBUILD_FAILED, ok=False, root=r"C:\repo")
        self.assertEqual(parsed.problems, ["src/Example/Thing.cs:12: CS0103 The name 'missing' does not exist in the current context",
                                           "MSB1009 Project file does not exist."])
        self.assertEqual(parsed.warnings, ["src/Example/Thing.cs:30: CS0168 The variable 'e' is declared but never used"])
        self.assertEqual(parsed.summary, "2 errors, 1 warning")
        self.assertEqual(parsers.msbuild("  Example -> C:\\out.dll\n", ok=True).summary, "built")

    def test_dotnet_test_names_the_failed_test_and_its_message(self):
        parsed = parsers.dotnet_test(DOTNET_TEST_FAILED, ok=False)
        self.assertEqual(parsed.problems, ["Example.Tests.RuleTests.HalvesAtDouble: Assert.Equal() Failure: Values differ"])
        self.assertEqual((parsed.summary, parsed.counts["tests"]), ("1 of 42 failed", 42))
        self.assertEqual(parsers.dotnet_test(DOTNET_TEST_PASSED, ok=True).summary, "56 passed")
        broken = parsers.dotnet_test(MSBUILD_FAILED, ok=False, root=r"C:\repo")
        self.assertTrue(broken.summary.startswith("did not build"))

    def test_unittest_lists_each_failure_with_its_last_line(self):
        parsed = parsers.unittest(UNITTEST_FAILED, ok=False)
        self.assertEqual(parsed.problems, [
            "ERROR ReaderTests.test_reads: FileNotFoundError: [Errno 2] No such file or directory: 'missing'",
            "FAIL MathTests.test_adds: AssertionError: 2 != 3"])
        self.assertEqual(parsed.summary, "2 of 5 failed")
        older = parsers.unittest(UNITTEST_FAILED.replace("(test_tool.MathTests.test_adds)", "(test_tool.MathTests)"), ok=False)
        self.assertEqual(older.problems[1], "FAIL MathTests.test_adds: AssertionError: 2 != 3")
        self.assertEqual(parsers.unittest("....\nRan 4 tests in 0.1s\n\nOK\n", ok=True).summary, "4 passed")

    def test_cargo_errors_tests_and_formatting(self):
        parsed = parsers.cargo(CARGO_FAILED, ok=False)
        self.assertEqual(parsed.problems, ["crates/xml-index/src/lib.rs:41:17: E0308 mismatched types"])
        self.assertEqual(parsed.warnings, ["crates/xml-index/src/lib.rs:50:9: unused variable: `y`"])
        tests = parsers.cargo(CARGO_TESTS, ok=False)
        self.assertEqual((tests.summary, tests.problems), ("1 of 3 failed", ["test writes failed"]))
        fmt = parsers.cargo("Diff in /repo/src/lib.rs at line 3:\n-a\n+b\n", ok=False, root="/repo")
        self.assertEqual(fmt.problems, ["src/lib.rs:3: not formatted (cargo fmt)"])

    def test_text_keeps_the_tail_of_a_failure(self):
        output = "\n".join(f"line {n}" for n in range(40))
        self.assertEqual(parsers.text(output, ok=False).problems[-1], "line 39")
        self.assertEqual(len(parsers.text(output, ok=False).problems), parsers.TAIL)
        self.assertEqual(parsers.text(output, ok=True).problems, [])


def script(code):
    """A run list that executes Python code with this interpreter."""
    return ["{python}", "-c", code]


class Runner(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        for name in ("a", "b"):
            (self.root / "tests" / name).mkdir(parents=True)
            (self.root / "tests" / name / f"{name}.proj").write_text("", encoding="utf-8")
        # Nothing from the real environment but what Windows needs to start a process: without SYSTEMROOT, Python 3.10
        # cannot seed its random numbers and stops before running anything (found by the gate's own first run).
        self.env = {k: v for k, v in os.environ.items() if k.upper() in ("SYSTEMROOT", "WINDIR", "TEMP", "TMP")}
        self.env["PATH"] = ""

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, stages):
        (self.root / "config").mkdir(exist_ok=True)
        (self.root / "config" / "gate.json").write_text(json.dumps({"schemaVersion": 1, "stages": stages}), encoding="utf-8")

    def test_each_expands_over_the_files_a_glob_finds(self):
        self.write([{"name": "Tests", "steps": [{"name": "test {stem}", "each": "tests/*/*.proj", "lane": "x",
                                                 "run": ["tool", "{path}", "{dir}"]}]}])
        (_, steps), = load(self.root, environ=self.env)
        self.assertEqual([(s.name, s.run) for s in steps], [("test a", ["tool", "tests/a/a.proj", "tests/a"]),
                                                            ("test b", ["tool", "tests/b/b.proj", "tests/b"])])
        self.assertEqual({s.lane for s in steps}, {"x"})

    def test_bad_configs_are_refused(self):
        for stages, message in (([{"steps": [{"name": "n"}]}], "name and a run list"),
                                ([{"steps": [{"name": "n", "run": ["x"], "parser": "nope"}]}], "unknown parser"),
                                ([{"steps": [{"name": "n {nope}", "run": ["x"]}]}], "Unknown placeholder")):
            self.write(stages)
            with self.subTest(message), self.assertRaisesRegex(GateError, message):
                load(self.root, environ=self.env)
        with self.assertRaisesRegex(GateError, "No gate"):
            load(self.root / "elsewhere", environ=self.env)

    def test_lanes_keep_order_and_a_failed_stage_stops_the_next(self):
        log = (self.root / "order.txt").as_posix()
        append = "import sys; open(%r, 'a').write(sys.argv[1] + '\\n')" % log
        self.write([
            {"name": "One", "steps": [{"name": f"step {n}", "lane": "same", "run": ["{python}", "-c", append, str(n)]}
                                      for n in range(3)] + [{"name": "fails", "run": script("import sys; print('broke'); sys.exit(3)")}]},
            {"name": "Two", "steps": [{"name": "later", "run": script("pass")}]},
        ])
        results = run(load(self.root, environ=self.env), self.root, self.env, jobs=4)
        self.assertEqual((self.root / "order.txt").read_text().split(), ["0", "1", "2"])
        states = {r.step.name: r.state for r in results}
        self.assertEqual(states, {"step 0": "passed", "step 1": "passed", "step 2": "passed", "fails": "failed", "later": "skipped"})
        self.assertEqual([r.parsed.problems for r in results if r.step.name == "fails"], [["broke"]])
        kept = run(load(self.root, environ=self.env), self.root, self.env, keep_going=True)
        self.assertEqual(kept[-1].state, "passed")

    def test_missing_programs_are_skipped_and_failed_output_is_kept(self):
        self.write([{"name": "One", "steps": [
            {"name": "needs a tool", "requires": "no-such-program-here", "run": ["no-such-program-here"]},
            {"name": "noisy", "run": script("import sys; print('x' * 10); sys.exit(1)")}]}])
        logs = self.root / "logs"
        results = run(load(self.root, environ=self.env), self.root, self.env, logs=logs)
        self.assertEqual(results[0].state, "skipped")
        self.assertIn("not on the PATH", results[0].reason)
        self.assertEqual(Path(results[1].log).read_text(encoding="utf-8").strip(), "x" * 10)

    def test_select_by_wildcard(self):
        self.write([{"name": "One", "steps": [{"name": "build a", "run": ["x"]}, {"name": "build b", "run": ["x"]},
                                              {"name": "docs", "run": ["x"]}]}])
        stages = load(self.root, environ=self.env)
        self.assertEqual([s.name for _, steps in select(stages, only=["build *"], skip=["* b"]) for s in steps], ["build a"])

    def test_command_line_report(self):
        self.write([{"name": "One", "steps": [
            {"name": "unit", "parser": "unittest", "run": script("import sys; sys.stderr.write('Ran 3 tests in 0.1s\\n\\nOK\\n')")},
            {"name": "check", "run": script("import sys; print('docs/a.md: broken link'); sys.exit(1)")}]}])
        env = dict(self.env, PHOBOS_MODKIT_CACHE=str(self.root / "cache"))
        out = io.StringIO()
        code = main(["--root", str(self.root), "--no-redact"], out=out, environ=env)
        text = out.getvalue()
        self.assertEqual(code, EXIT_FAILED)
        self.assertIn("# Gate: failed (1 of 2 steps)", text)
        self.assertIn("tests run: 3 Python", text)
        self.assertIn("## Failed: check (failed)", text)
        self.assertIn("docs/a.md: broken link", text)
        out = io.StringIO()
        self.assertEqual(main(["--root", str(self.root), "--only", "unit"], out=out, environ=env), EXIT_OK)
        self.assertIn("# Gate: passed", out.getvalue())
        out = io.StringIO()
        self.assertEqual(main(["--root", str(self.root), "--list"], out=out, environ=env), EXIT_OK)
        self.assertIn("2 steps in 1 stages", out.getvalue())
        self.assertEqual(main(["--root", str(self.root), "--only", "nothing"], out=io.StringIO(), environ=env), EXIT_USAGE)


if __name__ == "__main__":
    unittest.main()
