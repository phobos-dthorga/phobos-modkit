"""crash-dump's full-dump side and windows-dumps: a stack kept only in the full memory list, methods named through a stand-in for
dotnet-dump, and Windows' dump settings through a stand-in registry. The dumps are built here from Microsoft's published structures;
the dotnet-dump answers are written in the shape version 10.0.750501 printed on 18 November 2026."""
import io
from pathlib import Path
import struct
import subprocess
import tempfile
import unittest

import support  # noqa: F401  (the package on the import path)
from phobos_modkit import crashdump, dotnet_diagnostics as dd, windows_dumps
from phobos_modkit.crashdump_cli import main

LOOP, MAIN = 0x7FFC08534FF1, 0x7FFC08530010
STACK_START = 0x6DFA004798


def full_dump(levels=120):
    """A dump as .NET's own writer makes it: no exception stream, the thread's stack pointer 0, the stack in Memory64."""
    words = [0x11]
    for level in range(levels):
        words += [LOOP, level, 0x01A900000000, 0, 0, 0]
    words += [MAIN, 0, 0x22]
    stack = struct.pack(f"<{len(words)}Q", *words)
    header_size, directory_size = 32, 3 * 12
    body = bytearray()
    base = header_size + directory_size

    def place(blob):
        at = base + len(body)
        body.extend(blob)
        return at

    name = "C:\\x\\coreclr.dll".encode("utf-16-le")
    name_rva = place(struct.pack("<I", len(name)) + name)
    threads = struct.pack("<I", 1) + struct.pack("<IIIIQQII", 58696, 0, 0, 0, 0, STACK_START, len(stack), 0) + struct.pack("<II", 0, 0)
    threads_rva = place(threads)
    entry = struct.pack("<QIIII", 0x7FFE00000000, 0x1000, 0, 0, name_rva).ljust(crashdump.MODULE_SIZE, b"\0")
    modules_rva = place(struct.pack("<I", 1) + entry)
    padding = 0x40          # memory before the stack in the same range, so the offset into the range matters
    memory_list_size = 16 + 16
    memory_rva = base + len(body)
    data_rva = memory_rva + memory_list_size
    body.extend(struct.pack("<QQ", 1, data_rva) + struct.pack("<QQ", STACK_START - padding, padding + len(stack)))
    body.extend(b"\xAB" * padding + stack)
    header = struct.pack("<IIIIIIQ", crashdump.SIGNATURE, 0xA793, 3, header_size, 0, 1_700_000_000, crashdump.FLAG_FULL_MEMORY)
    directory = struct.pack("<III", crashdump.STREAM_THREADS, len(threads), threads_rva) \
        + struct.pack("<III", crashdump.STREAM_MODULES, 4 + crashdump.MODULE_SIZE, modules_rva) \
        + struct.pack("<III", crashdump.STREAM_MEMORY64, memory_list_size, memory_rva)
    return header + directory + bytes(body)


IP2MD = """Loading core dump: x.dmp ...
MethodDesc:   00007ffc08720da0
Method Name:          Example.Ticker.Recurse(Int32, System.Object)
Class:                00007ffc08720dc0
Module:               00007ffc086fd008
IsJitted:             yes
"""
IP2MD_MAIN = """Loading core dump: x.dmp ...
MethodDesc:   00007ffc08720e00
Method Name:          Example.Program.Main(System.String[])
Module:               00007ffc086fd008
"""
DUMPMODULE = """Loading core dump: x.dmp ...
Name: C:\\Mods\\Example\\1.7\\Assemblies\\Example.dll
Attributes:              PEFile
"""


class FakeDump:
    """Stands in for dotnet-dump: names LOOP and MAIN, fails (and stops, as the real one does) on anything else."""

    def __init__(self):
        self.calls = []

    def __call__(self, command, **_):
        asked = [command[i + 1] for i, part in enumerate(command) if part == "-c"]
        self.calls.append(asked)
        out, code = "Loading core dump: x.dmp ...\n", 0
        for text in asked:
            if text == "exit":
                break
            if text.startswith("ip2md"):
                address = int(text.split()[1], 16)
                if address == LOOP:
                    out += IP2MD.split("\n", 1)[1]
                elif address == MAIN:
                    out += IP2MD_MAIN.split("\n", 1)[1]
                else:
                    out += "Failed to request MethodData, not in JIT code range\n"
                    code = 1
                    break
            elif text.startswith("dumpmodule"):
                out += DUMPMODULE.split("\n", 1)[1]
        return subprocess.CompletedProcess(command, code, out, "")


class FullDumpTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dump = Path(self.tmp.name) / "Example.exe.1.dmp"
        self.dump.write_bytes(full_dump())

    def test_the_stack_is_found_in_the_full_memory_list(self):
        summary = crashdump.read_dump(self.dump)
        self.assertFalse(summary.thread_named)
        self.assertEqual(58696, summary.thread_id)
        self.assertEqual(120, summary.loop.repeats)
        self.assertEqual([(0, LOOP)], summary.loop.return_addresses)
        self.assertEqual([MAIN], [a for a, _ in summary.outer_addresses])

    def test_parse_ip2md_keeps_order_and_notices_a_failure(self):
        named, failed = crashdump.parse_ip2md(IP2MD + "Failed to request MethodData, not in JIT code range\n")
        self.assertEqual([("Example.Ticker.Recurse(Int32, System.Object)", "00007ffc086fd008")], named)
        self.assertTrue(failed)

    def test_naming_carries_on_past_a_failure(self):
        fake = FakeDump()
        names = crashdump.name_addresses(self.dump, [LOOP, 0x7FFC00000001, MAIN], "dotnet-dump", fake)
        self.assertEqual("Example.Program.Main(System.String[])", names[MAIN][0])
        self.assertTrue(names[LOOP][1].endswith("Example.dll"))
        self.assertNotIn(0x7FFC00000001, names)
        self.assertEqual(["ip2md 0x7FFC08530010", "exit"], fake.calls[1])   # asked again without the one that failed

    def test_the_report_names_the_loop_and_how_it_got_there(self):
        tools = Path(self.tmp.name) / "tools"
        tools.mkdir()
        (tools / dd.native.program_name(dd.DUMP)).write_bytes(b"")
        out = io.StringIO()
        code = main([str(self.dump)], environ={dd.TOOLS_ENV: str(tools)}, out=out, run=FakeDump())
        text = out.getvalue()
        self.assertEqual(0, code, text)
        self.assertIn("| 0 | Example.Ticker.Recurse(Int32, System.Object) | Example.dll |", text)
        self.assertIn("| Example.Program.Main(System.String[]) | Example.dll |", text)
        self.assertIn("dotnet-dump named 2 of the 2 code addresses", text)
        self.assertIn("The dump names no failing thread", text)

    def test_no_names_asks_nothing(self):
        out = io.StringIO()
        fake = FakeDump()
        self.assertEqual(0, main([str(self.dump), "--no-names"], environ={}, out=out, run=fake))
        self.assertEqual([], fake.calls)
        self.assertNotIn("named from the dump", out.getvalue())


class FakeRegistry:
    def __init__(self, defaults=None, programs=None, allowed=True):
        self.defaults_ = defaults
        self.programs = dict(programs or {})
        self.allowed = allowed

    def defaults(self):
        return self.defaults_

    def program(self, exe):
        return self.programs.get(exe)

    def write(self, exe, count, folder):
        if not self.allowed:
            raise PermissionError("Access is denied")
        self.programs[exe] = {"DumpType": 2, "DumpCount": count, **({"DumpFolder": folder} if folder else {})}

    def remove(self, exe):
        if not self.allowed:
            raise PermissionError("Access is denied")
        del self.programs[exe]


class WindowsDumpsTests(unittest.TestCase):
    def run_cli(self, *argv, registry):
        out = io.StringIO()
        code = windows_dumps.main(list(argv), environ={"LOCALAPPDATA": tempfile.gettempdir()}, out=out, registry=registry)
        return code, out.getvalue()

    def test_reports_the_default_and_the_lines_to_change_it(self):
        code, text = self.run_cli("--program", "RimWorld", registry=FakeRegistry(defaults={}))
        self.assertEqual(0, code, text)
        self.assertIn("Windows keeps small dumps of every program", text)
        self.assertIn("**RimWorld.exe has no setting of its own**", text)
        self.assertIn("LocalDumps\\RimWorld.exe' -Name DumpType -PropertyType DWord -Value 2", text)

    def test_apply_then_off(self):
        registry = FakeRegistry(defaults={})
        code, text = self.run_cli("--program", "RimWorld", "--apply", "--count", "3", registry=registry)
        self.assertEqual(0, code, text)
        self.assertIn("**Done: Windows will keep full dumps of RimWorld.exe.**", text)
        self.assertIn("own: full dumps, the newest 3", text)
        code, text = self.run_cli("--program", "RimWorld.exe", "--off", registry=registry)
        self.assertEqual(0, code, text)
        self.assertEqual({}, registry.programs)

    def test_without_administrator_rights_it_changes_nothing_and_gives_the_lines(self):
        registry = FakeRegistry(defaults={}, allowed=False)
        code, text = self.run_cli("--program", "RimWorld", "--apply", registry=registry)
        self.assertEqual(1, code)
        self.assertIn("**Not changed: this needs an administrator window.**", text)
        self.assertIn("The lines to run as administrator", text)
        self.assertEqual({}, registry.programs)

    def test_no_local_dumps_key_says_so(self):
        code, text = self.run_cli("--program", "RimWorld", registry=FakeRegistry(defaults=None))
        self.assertIn("**Windows keeps no crash dumps on this PC**", text)


if __name__ == "__main__":
    unittest.main()
