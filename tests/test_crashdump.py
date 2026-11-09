"""crash-dump on made-up minidumps, built here from Microsoft's published structures."""
import io
import json
from pathlib import Path
import struct
import tempfile
import unittest

import support  # noqa: F401  (the package on the import path)
from phobos_modkit import crashdump
from phobos_modkit.crashdump_cli import EXIT_FAILED, EXIT_OK, main

CODE_A, CODE_B, CODE_C = 0x7FFC00001000, 0x7FFC00002000, 0x7FFE00000123
OBJECT = 0x01D400000000


def minidump(words, code=crashdump.STACK_OVERFLOW, module=("C:\\x\\coreclr.dll", 0x7FFE00000000, 0x1000), thread=7, full=False):
    """A dump with an exception, one thread whose stack is these words, and one module."""
    name = module[0].encode("utf-16-le")
    header_size, directory_size = 32, 3 * 12
    body = bytearray()
    base = header_size + directory_size

    def place(blob):
        at = base + len(body)
        body.extend(blob)
        return at

    name_rva = place(struct.pack("<I", len(name)) + name)
    stack_rva = place(struct.pack(f"<{len(words)}Q", *words))
    threads = struct.pack("<I", 1) + struct.pack("<IIIIQQII", thread, 0, 0, 0, 0, 0x4700000000, len(words) * 8, stack_rva) + struct.pack("<II", 0, 0)
    threads_rva = place(threads)
    entry = struct.pack("<QIIII", module[1], module[2], 0, 0, name_rva).ljust(crashdump.MODULE_SIZE, b"\0")
    modules_rva = place(struct.pack("<I", 1) + entry)
    exception = struct.pack("<IIIIQQ", thread, 0, code, 0, 0, 0x7FFC00003000).ljust(168, b"\0")
    exception_rva = place(exception)
    flags = crashdump.FLAG_FULL_MEMORY if full else 0x121
    header = struct.pack("<IIIIIIQ", crashdump.SIGNATURE, 0xA793, 3, header_size, 0, 1_700_000_000, flags)
    directory = struct.pack("<III", crashdump.STREAM_THREADS, len(threads), threads_rva) \
        + struct.pack("<III", crashdump.STREAM_MODULES, 4 + crashdump.MODULE_SIZE, modules_rva) \
        + struct.pack("<III", crashdump.STREAM_EXCEPTION, len(exception), exception_rva)
    return header + directory + bytes(body)


def looping(levels=200, object_at=lambda level: OBJECT, frame_base=0x4700001000):
    words = [0x11, 0x22]
    for level in range(levels):
        words += [CODE_A, 0, object_at(level), frame_base + level * 48, CODE_B, CODE_C]
    return words


class FindLoopTests(unittest.TestCase):
    def test_a_loop_is_found_with_its_size_and_repeats(self):
        loop = crashdump.find_loop(looping())
        self.assertEqual((loop.repeats, loop.spacing_words), (200, 6))
        self.assertEqual({value for _, value in loop.return_addresses}, {CODE_A, CODE_B, CODE_C})

    def test_the_same_objects_at_every_level_means_nothing_changed(self):
        self.assertTrue(crashdump.find_loop(looping()).same_arguments)

    def test_objects_that_change_mean_it_was_walking_something(self):
        loop = crashdump.find_loop(looping(object_at=lambda level: OBJECT + level * 7 * level))
        self.assertFalse(loop.same_arguments)
        self.assertEqual(loop.values_changing, 1)

    def test_saved_stack_pointers_do_not_count_as_changing_arguments(self):
        self.assertEqual(crashdump.find_loop(looping()).values_changing, 0)

    def test_a_short_repeat_is_not_a_loop(self):
        self.assertIsNone(crashdump.find_loop(looping(levels=crashdump.LOOP_MIN_REPEATS - 1)))

    def test_scattered_repeats_are_not_a_loop(self):
        words = []
        for i in range(300):
            words += [CODE_A] + [0] * (i % 17 + 1)
        self.assertIsNone(crashdump.find_loop(words))

    def test_an_empty_stack_has_no_loop(self):
        self.assertIsNone(crashdump.find_loop(()))


class ReadDumpTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.folder = Path(folder.name)

    def write(self, name, blob):
        path = self.folder / name
        path.write_bytes(blob)
        return path

    def test_reads_the_exception_thread_and_modules(self):
        summary = crashdump.read_dump(self.write("a.dmp", minidump(looping())))
        self.assertEqual((summary.exception_name, summary.thread_id, summary.runtime), ("stack overflow", 7, "coreclr.dll"))
        self.assertFalse(summary.full_memory)
        self.assertIn(("coreclr.dll", 200), summary.code_modules)
        self.assertIn((None, 400), summary.code_modules)

    def test_an_unknown_exception_says_so(self):
        self.assertEqual(crashdump.read_dump(self.write("a.dmp", minidump([], code=0x12345678))).exception_name, "unknown")

    def test_not_a_dump_is_an_error(self):
        with self.assertRaises(crashdump.DumpError):
            crashdump.read_dump(self.write("a.dmp", b"not a minidump, no signature here at all...."))

    def test_a_cut_short_dump_is_an_error(self):
        with self.assertRaises(crashdump.DumpError):
            crashdump.read_dump(self.write("a.dmp", minidump(looping())[:60]))

    def test_newest_dump_picks_by_program(self):
        self.write("Other.exe.1.dmp", minidump([]))
        wanted = self.write("Game.exe.2.dmp", minidump([]))
        self.assertEqual(crashdump.newest_dump(self.folder, "Game"), wanted)
        self.assertIsNone(crashdump.newest_dump(self.folder, "Nothing"))


class CommandTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.folder = Path(folder.name)
        self.dump = self.folder / "Game.exe.9.dmp"
        self.dump.write_bytes(minidump(looping()))

    def run_it(self, *args):
        out = io.StringIO()
        return main(list(args) + ["--no-redact"], environ={"PHOBOS_CRASH_DUMPS": str(self.folder)}, out=out), out.getvalue()

    def test_markdown_names_the_loop_and_how_to_get_names(self):
        code, text = self.run_it()
        self.assertEqual(code, EXIT_OK)
        self.assertIn("stack overflow", text)
        self.assertIn("repeats 200 times", text)
        self.assertIn("Every level holds the same objects", text)
        self.assertIn("2> errors.txt", text)

    def test_a_full_dump_does_not_ask_for_the_error_output(self):
        self.dump.write_bytes(minidump(looping(), full=True))
        self.assertNotIn("2> errors.txt", self.run_it()[1])

    def test_json_is_the_envelope(self):
        code, text = self.run_it("--json")
        self.assertEqual(code, EXIT_OK)
        self.assertEqual(json.loads(text)["tool"], "crash-dump")

    def test_nothing_found_is_a_failure(self):
        self.assertEqual(self.run_it("--program", "Nothing")[0], EXIT_FAILED)

    def test_output_is_the_same_every_time(self):
        self.assertEqual(self.run_it()[1], self.run_it()[1])


if __name__ == "__main__":
    unittest.main()
