"""Looking inside a running .NET program: the heap reader (dotnet/PhobosModKit.Heap) and its reports. Game-free.

The reader takes a Windows snapshot of the program (a pause of about half a second on a large game), opens it with Microsoft's
ClrMD and the program's own memory-reading library, and answers requests about it: every type by count and bytes, one kind's
objects, one object with every value it holds, what holds it, and why it is still alive (a path from a root). It only reads: the
program runs on while the snapshot is read, and nothing is written to it. A game's adapter names the process and the install whose
memory-reading library it trusts, and how an object of that game is best described.

Two ways to use it: `run_requests` takes a snapshot, answers a few requests and lets it go (for a command line); a `Session` holds
the snapshot and answers one request at a time (for a program's page), until it is closed or its time limit passes. Windows keeps
a held snapshot by copying each page the program changes afterwards, so a session costs more memory the longer it is held.
"""
from __future__ import annotations

import json
from pathlib import Path
import re
import shutil
import subprocess

from .dotnet_snapshots import Heap, HeapType
from .dotnet_tools import DotnetTool, ToolBuildError
from .report import Bullets, Report, Table

LIMIT_SECONDS = 600     # ten minutes held at most: the owner's choice of 20 November 2026 (D'thorga Companion's decisions)
RUN_TIMEOUT = 3600      # a command line's whole run: a snapshot, then requests that may each walk every object
WHY_SAMPLE = 3
CAVEAT = ("Read from a snapshot of the running game: it paused for the moment the snapshot took, then ran on. Nothing was "
          "written to it. It is not an in-game test.")
GARBAGE_NOTE = ("A snapshot does not sweep the heap first, so its counts include objects nothing uses any more that the garbage "
                "collector has not reclaimed yet. Why is it still in memory tells the two apart.")
WINDOWS_ONLY = "Looking inside a running game works on Windows only."


class HeapReaderError(ToolBuildError):
    """The heap reader could not be built."""


class LookError(RuntimeError):
    """The snapshot could not be taken or read; the message says why, in words for a person."""


TOOL = DotnetTool("PhobosModKit.Heap", "heap", "look inside a running game", HeapReaderError)


def command(tool, mode, pid, runtime_folder, describe=(), limit_seconds=None, requests=()):
    line = [str(tool), mode, "--pid", str(int(pid)), "--runtime-folder", str(runtime_folder)]
    if limit_seconds:
        line += ["--limit-seconds", str(int(limit_seconds))]
    for path in describe:
        line += ["--describe", path]
    for request in requests:
        line += ["--request", json.dumps(request)]
    return line


def _lines(text):
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def run_requests(pid, runtime_folder, requests, describe=(), environ=None, run=subprocess.run, ensure=None):
    """(ready, answers): a snapshot of process pid, the requests answered in order, then let go. Progress lines, when wanted,
    pass straight to this program's standard error. Raises LookError when no snapshot could be read."""
    tool = (ensure or TOOL.ensure)(environ)
    result = run(command(tool, "run", pid, runtime_folder, describe, None, requests), stdout=subprocess.PIPE, stderr=None,
                 text=True, encoding="utf-8", errors="replace", check=False, timeout=RUN_TIMEOUT)
    lines = _lines(result.stdout or "")
    if not lines:
        raise LookError(f"The heap reader stopped without an answer (exit {result.returncode}).")
    ready, answers = lines[0], lines[1:]
    if not ready.get("ready"):
        raise LookError(ready.get("error") or "The snapshot could not be read.")
    return ready, answers


class Session:
    """A held snapshot: `ask` one request at a time; `close` lets it go. The reader lets it go by itself after its limit."""

    def __init__(self, pid, runtime_folder, describe=(), environ=None, limit_seconds=LIMIT_SECONDS, popen=subprocess.Popen,
                 ensure=None, stdin=None, stdout=None):
        tool = (ensure or TOOL.ensure)(environ)
        self.process = popen(command(tool, "serve", pid, runtime_folder, describe, limit_seconds),
                             stdin=stdin or subprocess.PIPE, stdout=stdout or subprocess.PIPE, stderr=None, text=True,
                             encoding="utf-8", errors="replace")
        self.ready = self._read()
        if not self.ready.get("ready"):
            self.close()
            raise LookError(self.ready.get("error") or "The snapshot could not be read.")
        self._next = 0

    def _read(self):
        line = self.process.stdout.readline()
        if not line:
            raise LookError("The heap reader stopped (its time limit may have passed); take another snapshot.")
        return json.loads(line)

    def ask(self, request):
        self._next += 1
        request = dict(request, id=self._next)
        try:
            self.process.stdin.write(json.dumps(request) + "\n")
            self.process.stdin.flush()
        except OSError as error:
            raise LookError("The heap reader has stopped (its time limit may have passed); take another snapshot.") from error
        while True:
            answer = self._read()
            if answer.get("event") == "released":
                raise LookError(f"The snapshot was let go: {answer.get('reason', 'its time limit passed')}.")
            if answer.get("id") == self._next:
                return answer

    def close(self):
        try:
            if self.process.poll() is None and self.process.stdin:
                self.process.stdin.close()
            self.process.wait(timeout=30)
        except (OSError, subprocess.TimeoutExpired):
            self.process.kill()
            self.process.wait(timeout=30)
        finally:
            if self.process.stdout:
                self.process.stdout.close()


def framework_runtime_folder(major=10, run=subprocess.run, which=shutil.which):
    """The newest installed Microsoft.NETCore.App of a major version: where a program built for that .NET, and not shipping its
    own runtime, finds coreclr.dll. None when there is none. (A game that ships its own runtime names its install instead.)"""
    if which("dotnet") is None:
        return None
    result = run(["dotnet", "--list-runtimes"], capture_output=True, text=True, check=False)
    best = None
    for line in (result.stdout or "").splitlines():
        found = re.match(r"Microsoft\.NETCore\.App (\d+)\.(\d+)\.(\d+)\S* \[(.+)\]\s*$", line.strip())
        if found and int(found.group(1)) == major:
            version = tuple(int(found.group(i)) for i in (1, 2, 3))
            if best is None or version > best[0]:
                best = (version, Path(found.group(4)) / ".".join(found.group(i) for i in (1, 2, 3)))
    return best[1] if best else None


# ---- What the answers mean ----

def answer_data(answer):
    """An answer's data, or LookError with the reader's own words."""
    if not answer.get("ok"):
        raise LookError(answer.get("error") or "The heap reader could not answer.")
    return answer.get("data") or {}


def heap_of(overview):
    """The overview as the kit's Heap, so the heap reports and comparisons of dotnet_snapshots read it as they read a gcdump."""
    types = [HeapType(t["type"], t.get("module") or "", int(t["bytes"]), int(t["count"])) for t in overview.get("types", [])]
    types.sort(key=lambda t: (-t.bytes, t.type, t.module))
    return Heap(int(overview.get("totalBytes", 0)), int(overview.get("totalObjects", 0)), types)


def size(value):
    for unit, scale in (("GB", 1e9), ("MB", 1e6), ("KB", 1e3)):
        if abs(value) >= scale:
            return f"{value / scale:,.1f} {unit}"
    return f"{value:,.0f} bytes"


def _link_text(link):
    summary = f" ({link['summary']})" if link.get("summary") else ""
    return f"{link.get('type', '?')}{summary}"


def path_lines(path):
    """A path from a root as lines a person can follow, root first."""
    if not path:
        return []
    start = (f"the static field {path['static']}" if path.get("static")
             else {"Stack": "a local variable on a thread's stack", "StrongHandle": "a handle the runtime keeps",
                   "PinnedHandle": "a pinned handle", "FinalizerQueue": "the finalizer queue (waiting to be finalised)",
                   "ThreadStaticVar": "a thread's static field"}.get(path.get("root"), f"a root ({path.get('root')})"))
    lines = [f"Held from {start}:"]
    for link in path.get("links", []):
        via = f"through {link['field']}: " if link.get("field") else ""
        lines.append(f"{via}{_link_text(link)} at {link['address']}")
    return lines


def kind_report(title, data, caveat=CAVEAT):
    report = Report(title)
    report.lines.append(f"**{data.get('count', 0):,} objects of {data.get('type')}, {size(data.get('totalBytes', 0))} in all.**")
    if data.get("match"):
        report.lines.append(f"Only those whose description holds \"{data['match']}\".")
    report.lines.append(caveat)
    rows = [(item["address"], size(item["size"]), item.get("summary", "")) for item in data.get("items", [])]
    report.section("Its objects" + (", largest first" if data.get("sorted") else ""),
                   Table(["Address", "Size", "Which one"], rows, data.get("count") if data.get("more") else None))
    return report


def object_report(title, data, caveat=CAVEAT):
    report = Report(title)
    report.lines.append(f"**{data.get('type')}** at {data.get('address')}, {size(data.get('size', 0))}"
                        + (f": {data['summary']}" if data.get("summary") else "") + ".")
    if data.get("static"):
        report.lines.append(f"The static field {data['static']} holds it.")
    report.lines.append(caveat)
    if data.get("kind") == "text":
        report.section("Its text", Bullets([data.get("text", "")]))
    rows = [(f["name"], f.get("type", ""), value_text(f)) for f in data.get("fields", []) + data.get("elements", [])]
    if rows:
        report.section("Its values", Table(["Name", "Type", "Value"], rows))
    items = data.get("items")
    if items:
        rows = [(i["name"], value_text(i)) for i in items.get("items", [])]
        report.section(f"Its {items.get('count', 0):,} items", Table(["Item", "Value"], rows))
    return report


def value_text(field, depth=0):
    kind = field.get("kind")
    if kind == "struct" and field.get("fields"):
        return "{ " + ", ".join(f"{f['name']} = {value_text(f, depth + 1)}" for f in field["fields"]) + " }"
    if kind == "link":
        return f"→ {_link_text({'type': field.get('valueType'), 'summary': field.get('summary')})} at {field.get('address')}"
    if kind == "text":
        return f"\"{field.get('value', '')}\""
    if kind == "null":
        return "nothing (null)"
    return str(field.get("value", ""))


def why_report(title, data, caveat=CAVEAT):
    report = Report(title)
    count = data.get("count", 0)
    report.lines.append(f"**{count:,} objects of {data.get('type')}, {size(data.get('totalBytes', 0))} in all.**")
    if count == 0:
        report.lines.append("There are none in this snapshot.")
    elif data.get("noneReachable"):
        report.lines.append(f"**Nothing holds any of the {data.get('checked', 0):,} largest of them: they are garbage the collector "
                            "has not reclaimed yet**, and will go at a full collection. They are not a leak.")
    elif data.get("timedOut") and not data.get("paths"):
        report.lines.append("No path was found within the time allowed; the heap may be too large to follow in one go.")
    report.lines.append(caveat)
    for n, path in enumerate(data.get("paths", []), 1):
        report.section(f"Path {n}", Bullets(path_lines(path)))
    return report


def holders_report(title, data, caveat=CAVEAT):
    report = Report(title)
    holders = data.get("holders", [])
    report.lines.append(f"**{len(holders):,} objects hold {data.get('address')}**" + (" (and more)" if data.get("more") else "") + ".")
    if data.get("static"):
        report.lines.append(f"The static field {data['static']} holds it too.")
    if data.get("roots"):
        report.lines.append("It is also a root itself: " + ", ".join(data["roots"]) + ".")
    report.lines.append(caveat)
    rows = [(h["address"], _link_text(h), h.get("field") or "") for h in holders]
    report.section("What holds it", Table(["Address", "Holder", "Through"], rows))
    return report
