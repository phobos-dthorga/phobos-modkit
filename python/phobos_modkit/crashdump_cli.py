"""crash-dump: what a Windows crash dump says failed, and whether a call loop ran away.

    crash-dump                       the newest dump in Windows' CrashDumps folder
    crash-dump --program RimWorld    the newest dump of one program
    crash-dump FILE.dmp              one dump

Reads only the dump. Windows keeps these in %LOCALAPPDATA%\\CrashDumps when a program dies without being able to report it. A small
dump holds the failing thread's stack but not the memory that would name a compiled method, and the report says what it could not tell.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import os
from pathlib import Path
import sys

from .crashdump import STACK_OVERFLOW, DumpError, newest_dump, read_dump
from .manifest import READS
from .report import Bullets, Report, Table, envelope_text, home_redactor, keep, render_markdown

EXIT_OK, EXIT_FAILED, EXIT_USAGE = 0, 1, 2
UNNAMED_CODE = "(compiled at run time)"


def _parser():
    p = argparse.ArgumentParser(prog="crash-dump", description=__doc__.split("\n\n")[0],
                                formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__.split("\n\n", 1)[1])
    p.add_argument("dump", nargs="?", help="the .dmp file (default: the newest in the crash dumps folder)")
    p.add_argument("--program", help="with no file named, only this program's dumps, by the start of the file name")
    p.add_argument("--folder", help="the crash dumps folder (else PHOBOS_CRASH_DUMPS, else %%LOCALAPPDATA%%\\CrashDumps)")
    p.add_argument("--top", type=int, default=15, help="rows per table (default 15)")
    p.add_argument("--json", action="store_true", help="print JSON instead of Markdown")
    p.add_argument("--no-redact", action="store_true", help="show the home folder instead of ~")
    return p


def _folder(args, environ):
    if args.folder:
        return Path(args.folder)
    if environ.get("PHOBOS_CRASH_DUMPS"):
        return Path(environ["PHOBOS_CRASH_DUMPS"])
    if environ.get("LOCALAPPDATA"):
        return Path(environ["LOCALAPPDATA"]) / "CrashDumps"
    raise DumpError("No crash dumps folder: name a file, or use --folder.")


def build_report(summary, top):
    report = Report("Crash dump")
    when = datetime.fromtimestamp(summary.timestamp, timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    code = f"0x{summary.exception_code:08X}" if summary.exception_code is not None else "none"
    report.lines.append(f"{summary.path}, written {when}, {summary.size:,} bytes.")
    report.lines.append(f"**Exception: {summary.exception_name}** ({code}) on thread {summary.thread_id if summary.thread_id is not None else 'unknown'}.")
    report.lines.append(f"{summary.stack_bytes:,} bytes of its stack, {summary.module_count} modules, {'full memory' if summary.full_memory else 'a small dump, without the full memory'}.")
    loop = summary.loop
    if loop:
        report.section("A call loop ran away", Bullets([
            f"**One level of {loop.spacing_words * 8} bytes repeats {loop.repeats:,} times.**",
            f"Each level holds {len(loop.return_addresses)} return address(es), so about that many calls take part.",
            "**Every level holds the same objects**, so nothing changed between calls and it could never stop on its own."
            if loop.same_arguments else f"{loop.values_changing} of the {loop.values_compared} values each level holds change between levels, so it was walking through something.",
        ]), Table(["Offset in the level", "Return address"], [[offset, f"0x{value:X}"] for offset, value in loop.return_addresses]))
    elif summary.exception_code == STACK_OVERFLOW:
        report.section("No single call loop", "The stack overflowed without one repeating pattern: a very deep chain of different calls, or a loop too long to see.")
    report.section("Where the stack's return addresses point",
                   Table(["Module", "Addresses"], [[name or UNNAMED_CODE, count] for name, count in summary.code_modules[:top]],
                         total=len(summary.code_modules)))
    limits = []
    if not summary.full_memory and summary.runtime:
        limits.append("A small dump of a .NET program cannot name the methods: their names live in memory it left out. The addresses above only prove the shape.")
        if summary.exception_code == STACK_OVERFLOW:
            limits.append("**To get the names, run the program again with its error output sent to a file** (`program.exe 2> errors.txt`): .NET writes the repeating methods there on a stack overflow.")
    limits.append("Addresses are good only for this run: compare the shape between crashes, never the numbers.")
    report.section("What this cannot say", Bullets(limits))
    return report


def main(argv=None, environ=None, out=None):
    out = out or sys.stdout
    environ = os.environ if environ is None else environ
    try:
        args = _parser().parse_args(list(sys.argv[1:] if argv is None else argv))
    except SystemExit as stop:
        return EXIT_USAGE if stop.code else EXIT_OK
    redact = keep if args.no_redact else home_redactor()
    try:
        path = Path(args.dump) if args.dump else newest_dump(_folder(args, environ), args.program)
        if path is None:
            raise DumpError("No crash dumps found.")
        report = build_report(read_dump(path), args.top)
    except DumpError as failed:
        print(redact(str(failed)), file=sys.stderr)
        return EXIT_FAILED
    out.write((envelope_text("crash-dump", report, redact) if args.json else render_markdown(report, redact)) + "\n")
    return EXIT_OK


MANIFEST = {"game": None, "parser": _parser, "effect": READS, "question": "Why did this program crash?"}
