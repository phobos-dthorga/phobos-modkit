"""crash-dump: what a Windows crash dump says failed, and whether a call loop ran away.

    crash-dump                       the newest dump in Windows' CrashDumps folder
    crash-dump --program RimWorld    the newest dump of one program
    crash-dump FILE.dmp              one dump
    crash-dump --list                every dump kept, newest first, without opening one (quick; 1.138.0)

Reads only the dump. Windows keeps these in %LOCALAPPDATA%\\CrashDumps when a program dies without being able to report it. A small
dump holds the failing thread's stack but not the memory that would name a compiled method, and the report says what it could not tell.
A dump with the full memory of a .NET program is also read by Microsoft's dotnet-dump (installed into the kit's build folder on first
use), which names the methods the stack's return addresses fall in; --no-names skips that. windows-dumps asks Windows for such dumps.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import os
from pathlib import Path
import sys

from . import dotnet_diagnostics as dd
from .crashdump import STACK_OVERFLOW, DumpError, name_addresses, newest_dump, read_dump
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
    p.add_argument("--no-names", action="store_true", help="do not ask dotnet-dump to name methods, even in a full dump")
    p.add_argument("--list", action="store_true", help="list the dumps kept, newest first, without opening any")
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


NAMES_CAVEAT = ("These are the words on the stack that point into code the runtime compiled, named by dotnet-dump: most are "
                "return addresses, so a chain of calls, but a stale value left on the stack can appear among them. Words that "
                "name no method are left out.")


def _assembly(file):
    return Path(file.replace("\\", "/")).name if file else "-"


def _named_rows(addresses, names, top):
    rows = [[names[a][0], _assembly(names[a][1])] for a, _ in addresses if names.get(a, ("", ""))[0]]
    return rows[:top], len(rows)


def _names_section(report, summary, names, top):
    blocks = [NAMES_CAVEAT]
    loop = summary.loop
    if loop:
        blocks.append(Table(["The loop's return addresses", "Method", "Assembly"],
                            [[offset, names.get(value, ("(not named)", ""))[0], _assembly(names.get(value, ("", ""))[1])]
                             for offset, value in loop.return_addresses]))
    outer_title = "Beyond the loop, outermost first: how it got there" if loop else "The stack, outermost first"
    rows, total = _named_rows(summary.outer_addresses, names, top)
    if rows:
        blocks.append(Table([outer_title, "Assembly"], rows, total=total))
    if loop:
        rows, total = _named_rows(summary.inner_addresses, names, top)
        if rows:
            blocks.append(Table(["Inside the first level, innermost first: where the stack ran out", "Assembly"], rows, total=total))
    report.section("The methods, named from the dump's memory", *blocks)


def addresses_to_name(summary):
    """The loop's return addresses, then the stack's outer and inner code words, each once."""
    wanted = [value for _, value in summary.loop.return_addresses] if summary.loop else []
    for address, _ in summary.outer_addresses + summary.inner_addresses:
        if address not in wanted:
            wanted.append(address)
    return wanted


def build_report(summary, top, names=None, notes=()):
    report = Report("Crash dump")
    when = datetime.fromtimestamp(summary.timestamp, timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    code = f"0x{summary.exception_code:08X}" if summary.exception_code is not None else "none"
    report.lines.append(f"{summary.path}, written {when}, {summary.size:,} bytes.")
    report.lines.append(f"**Exception: {summary.exception_name}** ({code}) on thread {summary.thread_id if summary.thread_id is not None else 'unknown'}.")
    if not summary.thread_named:
        report.lines.append("The dump names no failing thread, so this reads its first thread. .NET's own dump writer puts the failing "
                            "thread first (seen once, 18 November 2026); Windows names it.")
    for note in notes:
        report.lines.append(note)
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
    if names:
        _names_section(report, summary, names, top)
    report.section("Where the stack's return addresses point",
                   Table(["Module", "Addresses"], [[name or UNNAMED_CODE, count] for name, count in summary.code_modules[:top]],
                         total=len(summary.code_modules)))
    limits = []
    if not summary.full_memory and summary.runtime:
        limits.append("A small dump of a .NET program cannot name the methods: their names live in memory it left out. The addresses above only prove the shape.")
        limits.append("**To get the names next time, ask Windows for full dumps of the program** (windows-dumps), or run it with its "
                      "error output sent to a file (`program.exe 2> errors.txt`): .NET writes the repeating methods there on a stack overflow.")
    limits.append("Addresses are good only for this run: compare the shape between crashes, never the numbers.")
    report.section("What this cannot say", Bullets(limits))
    return report


def _names(path, summary, environ, run):
    """({address: (method, file)}, notes) from dotnet-dump, for a full dump of a .NET program; empty when it cannot."""
    wanted = addresses_to_name(summary)
    if not (summary.full_memory and summary.runtime and wanted):
        return {}, []
    try:
        found, installed = dd.ensure([dd.DUMP], environ, run)
        names = name_addresses(path, wanted, found[dd.DUMP], run)
    except dd.DiagnosticsError as failed:
        return {}, [f"dotnet-dump could not name the methods: {failed}"]
    notes = [f"Installed dotnet-dump {dd.TOOLS_VERSION} into {dd.tools_folder(environ)} first."] if installed else []
    named = sum(1 for method, _ in names.values() if method)
    notes.append(f"dotnet-dump named {named} of the {len(wanted)} code addresses on the stack.")
    return names, notes


def program_of(name):
    """The program a dump's file name names: Windows writes PROGRAM.exe.PID.dmp, or PROGRAM.exe(N).PID.dmp for a second."""
    head = name.split(".exe", 1)[0] if ".exe" in name.lower() else name.split(".", 1)[0]
    return head.split("(", 1)[0] or name


def listed(folder, program=None, top=None):
    """[{file, program, time, size}] of the dumps in a folder, newest first, one program's when named; never opened."""
    found = []
    for path in Path(folder).glob("*.dmp"):
        try:
            stat = path.stat()
        except OSError:
            continue
        if program and not path.name.lower().startswith(program.lower()):
            continue
        found.append({"file": path.name, "program": program_of(path.name),
                      "time": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(timespec="seconds"),
                      "size": stat.st_size})
    found.sort(key=lambda d: (d["time"], d["file"]), reverse=True)
    return found[:top] if top else found


def main(argv=None, environ=None, out=None, run=None):
    out = out or sys.stdout
    environ = os.environ if environ is None else environ
    try:
        args = _parser().parse_args(list(sys.argv[1:] if argv is None else argv))
    except SystemExit as stop:
        return EXIT_USAGE if stop.code else EXIT_OK
    redact = keep if args.no_redact else home_redactor()
    if args.list:
        try:
            folder = _folder(args, environ)
        except DumpError as failed:
            print(redact(str(failed)), file=sys.stderr)
            return EXIT_FAILED
        dumps = listed(folder, args.program, args.top) if folder.is_dir() else []
        report = Report(f"Crash dumps: {len(dumps)} kept" if dumps else "Crash dumps: none kept")
        if dumps:
            report.section("Newest first", Table(["When", "Program", "File", "Bytes"],
                                                 [[d["time"], d["program"], d["file"], str(d["size"])] for d in dumps]))
        data = {"folder": str(folder), "dumps": dumps}
        out.write((envelope_text("crash-dump", report, redact, data) if args.json else render_markdown(report, redact)) + "\n")
        return EXIT_OK
    try:
        path = Path(args.dump) if args.dump else newest_dump(_folder(args, environ), args.program)
        if path is None:
            raise DumpError("No crash dumps found.")
        summary = read_dump(path)
        names, notes = ({}, []) if args.no_names else _names(path, summary, environ, run or dd.subprocess.run)
        report = build_report(summary, args.top, names, notes)
    except DumpError as failed:
        print(redact(str(failed)), file=sys.stderr)
        return EXIT_FAILED
    out.write((envelope_text("crash-dump", report, redact) if args.json else render_markdown(report, redact)) + "\n")
    return EXIT_OK


MANIFEST = {"game": None, "parser": _parser, "effect": READS, "question": "Why did this program crash?", "scope": "machine"}
