"""Microsoft's .NET diagnostics tools: find or install them, find a running program, and record or read it.

`dotnet-trace` samples every managed thread's call stack about once a millisecond and `dotnet-counters` reads the runtime's own
counters (garbage collection, allocation, JIT, locks), both through the diagnostics pipe a .NET program opens (Microsoft,
https://learn.microsoft.com/dotnet/core/diagnostics/). `dotnet-stack` prints every managed thread's stack once, through the same
pipe; `dotnet-gcdump` forces a full garbage collection and writes what the managed heap holds, by type; `dotnet-dump` reads a
dump file. They attach from outside: nothing is installed in the program, and they detach when they finish. The kit installs a
pinned version into its own build folder with `dotnet tool install`, so nothing depends on what else is on the machine. Nothing
here names a game.
"""
from __future__ import annotations

import csv
import io
import os
from pathlib import Path
import shutil
import subprocess
import sys

from . import native

TOOLS_VERSION = "10.0.750501"      # Microsoft's release of 2026; the version the tool was built and checked against
TRACE, COUNTERS = "dotnet-trace", "dotnet-counters"
STACK, GCDUMP, DUMP = "dotnet-stack", "dotnet-gcdump", "dotnet-dump"
RECORDING = (TRACE, COUNTERS)
TOOLS_ENV = "PHOBOS_DOTNET_TOOLS"   # a folder holding both programs, instead of the kit's own copy
SPEEDSCOPE_SUFFIX = ".speedscope.json"
STOP_GRACE_SECONDS = 600           # dotnet-trace converts the trace after recording; its own message warns this can take minutes
STACK_SECONDS = 120                # one snapshot of every thread's stack; half a second on a small program (seen 18 November 2026)
GCDUMP_SECONDS = 1800              # a full garbage collection of a large heap, then walking it
DUMP_SECONDS = 1800                # opening a dump as large as a program's memory, then the commands


class DiagnosticsError(RuntimeError):
    pass


def tools_folder(environ=None):
    environ = os.environ if environ is None else environ
    return Path(environ[TOOLS_ENV]) if environ.get(TOOLS_ENV) else native.build_dir(environ) / "dotnet-tools"


def tool_path(name, environ=None, which=shutil.which):
    """The program for a tool: the tools folder's copy, else one on PATH, else None."""
    own = tools_folder(environ) / native.program_name(name)
    if own.is_file():
        return own
    found = which(name)
    return Path(found) if found else None


def install_tools(environ=None, run=subprocess.run, which=shutil.which, names=RECORDING):
    """Install the named tools at TOOLS_VERSION into the kit's tools folder. Raises DiagnosticsError without the .NET SDK."""
    if run is subprocess.run and which("dotnet") is None:
        raise DiagnosticsError("The .NET SDK is not installed; install .NET 10 or newer from https://dotnet.microsoft.com first.")
    folder = tools_folder(environ)
    for name in names:
        command = ["dotnet", "tool", "update" if (folder / native.program_name(name)).is_file() else "install", name,
                   "--version", TOOLS_VERSION, "--tool-path", str(folder)]
        result = run(command, capture_output=True, text=True, check=False)
        if result.returncode != 0:
            raise DiagnosticsError(f"Installing {name} failed:\n{(result.stdout or '')[-1500:]}{(result.stderr or '')[-1500:]}")
    return folder


def ensure(names, environ=None, run=subprocess.run, which=shutil.which):
    """({name: program} for the tools named, installing the missing ones first; whether it installed any)."""
    found = {name: tool_path(name, environ, which) for name in names}
    missing = [name for name, program in found.items() if program is None]
    if missing:
        install_tools(environ, run, which, missing)
        found = {name: tool_path(name, environ, which) for name in names}
    still = [name for name, program in found.items() if program is None]
    if still:
        raise DiagnosticsError(f"{' and '.join(still)} could not be found after installing them in {tools_folder(environ)}.")
    return found, bool(missing)


def ensure_tools(environ=None, run=subprocess.run, which=shutil.which):
    """(trace program, counters program), installing them first when either is missing. Returns also whether it installed."""
    found, installed = ensure(RECORDING, environ, run, which)
    return found[TRACE], found[COUNTERS], installed


def _completed(command, run, seconds, what):
    try:
        return run([str(part) for part in command], capture_output=True, text=True, encoding="utf-8", errors="replace",
                   check=False, timeout=seconds, stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired as late:
        raise DiagnosticsError(f"{what} did not finish within {seconds} s.") from late
    except OSError as failed:
        raise DiagnosticsError(f"{what} could not be started: {failed}") from failed


def _output(command, run, seconds, what):
    """A tool's standard output, or DiagnosticsError with the end of what it said when it failed or ran too long."""
    result = _completed(command, run, seconds, what)
    if result.returncode != 0:
        raise DiagnosticsError(f"{what} failed (exit {result.returncode}):\n{(result.stdout or '')[-1500:]}{(result.stderr or '')[-1500:]}")
    return result.stdout or ""


def stack_text(pid, tool, run=subprocess.run):
    """dotnet-stack's report of every managed thread's stack in a running program, as it printed it."""
    return _output([tool, "report", "-p", pid], run, STACK_SECONDS, "dotnet-stack")


def collect_gcdump(pid, file, tool, run=subprocess.run):
    """Write a running program's heap to file with dotnet-gcdump; return the warnings the tool printed.

    The tool forces a full garbage collection first, so the program pauses until it is done.
    """
    file = Path(file)
    file.parent.mkdir(parents=True, exist_ok=True)
    text = _output([tool, "collect", "-p", pid, "-o", file], run, GCDUMP_SECONDS, "dotnet-gcdump")
    if not file.is_file():
        raise DiagnosticsError(f"dotnet-gcdump finished but wrote no file at {file}.\n{text[-1500:]}")
    return [line.strip() for line in text.splitlines() if line.strip().lower().startswith("warning")]


def gcdump_text(file, tool, run=subprocess.run):
    """dotnet-gcdump's table of a heap file: one row per type, with its size and count."""
    return _output([tool, "report", file], run, STACK_SECONDS, "dotnet-gcdump report")


def _analyze(dump, commands, tool):
    command = [tool, "analyze", dump]
    for text in list(commands) + ["exit"]:
        command += ["-c", text]
    return command


def dump_commands(dump, commands, tool, run=subprocess.run):
    """What dotnet-dump's analyser printed for the commands, run in order on one dump file."""
    return _output(_analyze(dump, commands, tool), run, DUMP_SECONDS, "dotnet-dump")


def dump_commands_status(dump, commands, tool, run=subprocess.run):
    """(exit code, what it printed): dotnet-dump stops at the first command that fails and exits 1, keeping what came before."""
    result = _completed(_analyze(dump, commands, tool), run, DUMP_SECONDS, "dotnet-dump")
    return result.returncode, (result.stdout or "") + (result.stderr or "")


def find_processes(name, run=subprocess.run, platform=None):
    """[(pid, name)] of running programs whose name is `name` (without .exe), sorted by pid."""
    platform = platform or sys.platform
    wanted = name.lower()
    found = []
    if platform == "win32":
        result = run(["tasklist", "/FO", "CSV", "/NH", "/FI", f"IMAGENAME eq {name}.exe"], capture_output=True, text=True, check=False)
        for row in csv.reader(io.StringIO(result.stdout or "")):
            if len(row) >= 2 and row[0].lower() == f"{wanted}.exe" and row[1].isdigit():
                found.append((int(row[1]), row[0][:-4]))
    else:
        result = run(["ps", "-A", "-o", "pid=,comm="], capture_output=True, text=True, check=False)
        for line in (result.stdout or "").splitlines():
            pid, _, command = line.strip().partition(" ")
            if pid.isdigit() and Path(command.strip()).name.lower() == wanted:
                found.append((int(pid), Path(command.strip()).name))
    return sorted(found)


def duration_text(seconds):
    """dotnet-trace's dd:hh:mm:ss."""
    seconds = int(seconds)
    return f"{seconds // 86400:02d}:{seconds // 3600 % 24:02d}:{seconds // 60 % 60:02d}:{seconds % 60:02d}"


HEAP_SIZE = "dotnet.gc.last_collection.heap.size"                  # bytes on the heap after the last collection, by generation
HEAP_COMMITTED = "dotnet.gc.last_collection.memory.committed_size"  # bytes the collector holds from the system
HEAP_FRAGMENTATION = "dotnet.gc.last_collection.heap.fragmentation.size"  # free gaps inside the heap, by generation
COUNTERS_SECONDS = 4                # a short reading: dotnet-counters' first report comes after its first interval


def start_counters(pid, file, tool, seconds, interval, log, popen=subprocess.Popen):
    """Start dotnet-counters writing the runtime's counters to file every `interval` seconds for `seconds`; returns the process.

    It stops by itself after `seconds`, when the program closes, or on Ctrl+C in the same console, and closes its file each way.
    """
    return popen([str(tool), "collect", "-p", str(pid), "--format", "json", "-o", str(file), "--refresh-interval", str(interval),
                  "--duration", duration_text(seconds)], stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT)


def counters_once(pid, file, tool, run=subprocess.run, seconds=COUNTERS_SECONDS):
    """Read the runtime's counters for a few seconds into file; returns counter_events of it ([] when it wrote nothing)."""
    file = Path(file)
    file.parent.mkdir(parents=True, exist_ok=True)
    _completed([tool, "collect", "-p", pid, "--format", "json", "-o", file, "--refresh-interval", "1",
                "--duration", duration_text(seconds)], run, seconds + STACK_SECONDS, "dotnet-counters")
    return counter_events(file)


def _epoch(stamp):
    """Seconds since 1970 from dotnet-counters' timestamp, e.g. 2026-11-18T08:14:51.6919974+11:00 (seven decimals)."""
    from datetime import datetime
    head, dot, rest = stamp.partition(".")
    if dot:
        digits = len(rest) - len(rest.lstrip("0123456789"))
        stamp = head + "." + rest[:min(digits, 6)].ljust(6, "0") + rest[digits:]
    return datetime.fromisoformat(stamp.replace("Z", "+00:00")).timestamp()


def counter_events(path):
    """[(seconds since 1970, name without its unit, tags, value)] from dotnet-counters' JSON file, in file order.

    The file is read even when it was cut off mid-write (the tool stopped hard or the program closed): every whole event before
    the cut counts. A missing or empty file gives [].
    """
    import json
    path = Path(path)
    if not path.is_file():
        return []
    text = path.read_text(encoding="utf-8-sig", errors="replace")
    start = text.find("[", text.find('"Events"'))
    if start < 0:
        return []
    decoder, at, found = json.JSONDecoder(), start + 1, []
    while True:
        while at < len(text) and text[at] in " \t\r\n,":
            at += 1
        if at >= len(text) or text[at] != "{":
            break
        try:
            event, at = decoder.raw_decode(text, at)
        except ValueError:
            break
        try:
            found.append((_epoch(event["timestamp"]), str(event["name"]).split(" (", 1)[0], event.get("tags") or "",
                          float(event["value"])))
        except (KeyError, TypeError, ValueError):
            continue
    return found


def record(pid, seconds, folder, trace_tool, counters_tool, popen=subprocess.Popen):
    """Record a program for `seconds`: a sampled trace (converted to speedscope) and its counters, side by side.

    Returns (speedscope file, counters file or None, notes). Raises DiagnosticsError when the trace could not be made.
    """
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    trace_file, counters_file = folder / "trace.nettrace", folder / "counters.json"
    counters_log, trace_log = folder / "counters.log", folder / "trace.log"
    duration = duration_text(seconds)
    notes = []
    with open(counters_log, "w", encoding="utf-8") as counters_out, open(trace_log, "w", encoding="utf-8") as trace_out:
        counting = popen([str(counters_tool), "collect", "-p", str(pid), "--format", "json", "-o", str(counters_file),
                          "--refresh-interval", "1", "--duration", duration],
                         stdin=subprocess.DEVNULL, stdout=counters_out, stderr=subprocess.STDOUT)
        tracing = popen([str(trace_tool), "collect", "-p", str(pid), "--format", "Speedscope", "-o", str(trace_file),
                         "--duration", duration], stdin=subprocess.DEVNULL, stdout=trace_out, stderr=subprocess.STDOUT)
        limit = seconds + STOP_GRACE_SECONDS
        try:
            trace_code = tracing.wait(timeout=limit)
        except subprocess.TimeoutExpired:
            tracing.kill()
            trace_code = None
        try:
            counting.wait(timeout=STOP_GRACE_SECONDS)
        except subprocess.TimeoutExpired:
            counting.kill()
            notes.append("The counters did not stop on time and were cut off.")
    speedscope = folder / ("trace" + SPEEDSCOPE_SUFFIX)
    if trace_code != 0 or not speedscope.is_file():
        tail = trace_log.read_text(encoding="utf-8", errors="replace")[-1500:] if trace_log.is_file() else ""
        raise DiagnosticsError(f"dotnet-trace did not finish the recording (exit {trace_code}).\n{tail}")
    if not counters_file.is_file():
        notes.append("dotnet-counters wrote nothing, so the report has no garbage collection figures.")
        counters_file = None
    return speedscope, counters_file, notes
