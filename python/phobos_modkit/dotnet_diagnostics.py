"""Microsoft's .NET diagnostics tools: find or install them, find a running program, and record it.

`dotnet-trace` samples every managed thread's call stack about once a millisecond and `dotnet-counters` reads the runtime's own
counters (garbage collection, allocation, JIT, locks), both through the diagnostics pipe a .NET program opens (Microsoft,
https://learn.microsoft.com/dotnet/core/diagnostics/). They attach from outside: nothing is installed in the program, and they
detach when the recording ends. The kit installs a pinned version into its own build folder with `dotnet tool install`, so the
recording does not depend on what else is on the machine. Nothing here names a game.
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
TOOLS_ENV = "PHOBOS_DOTNET_TOOLS"   # a folder holding both programs, instead of the kit's own copy
SPEEDSCOPE_SUFFIX = ".speedscope.json"
STOP_GRACE_SECONDS = 600           # dotnet-trace converts the trace after recording; its own message warns this can take minutes


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


def install_tools(environ=None, run=subprocess.run, which=shutil.which):
    """Install both tools at TOOLS_VERSION into the kit's tools folder. Raises DiagnosticsError without the .NET SDK."""
    if run is subprocess.run and which("dotnet") is None:
        raise DiagnosticsError("The .NET SDK is not installed; install .NET 10 or newer from https://dotnet.microsoft.com first.")
    folder = tools_folder(environ)
    for name in (TRACE, COUNTERS):
        command = ["dotnet", "tool", "update" if (folder / native.program_name(name)).is_file() else "install", name,
                   "--version", TOOLS_VERSION, "--tool-path", str(folder)]
        result = run(command, capture_output=True, text=True, check=False)
        if result.returncode != 0:
            raise DiagnosticsError(f"Installing {name} failed:\n{(result.stdout or '')[-1500:]}{(result.stderr or '')[-1500:]}")
    return folder


def ensure_tools(environ=None, run=subprocess.run, which=shutil.which):
    """(trace program, counters program), installing them first when either is missing. Returns also whether it installed."""
    trace, counters = tool_path(TRACE, environ, which), tool_path(COUNTERS, environ, which)
    installed = False
    if trace is None or counters is None:
        install_tools(environ, run, which)
        installed = True
        trace, counters = tool_path(TRACE, environ, which), tool_path(COUNTERS, environ, which)
    if trace is None or counters is None:
        raise DiagnosticsError(f"{TRACE} and {COUNTERS} could not be found after installing them in {tools_folder(environ)}.")
    return trace, counters, installed


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
