"""Readers for the output of the tools a gate runs: what failed, what warned, and how many tests ran.

Each parser takes the step's combined output and whether it exited cleanly, and returns a Parsed: a one-line summary,
the problems (errors, failed tests) and the warnings, each a short line, in the order first seen and without repeats
(MSBuild prints every error twice). Counts feed the report's totals. The formats are the tools' documented or plainly
visible console output; anything a parser does not recognise is left to the text parser's tail of the output.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import re

TAIL = 15


@dataclass
class Parsed:
    summary: str = ""
    problems: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    counts: dict = field(default_factory=dict)    # "tests", "failed", "warnings" and the like


def _unique(items):
    seen, out = set(), []
    for item in items:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out


def _short(path, root):
    """A path relative to the repository when it lies inside it, with forward slashes."""
    path = path.strip().replace("\\", "/")
    base = str(root).replace("\\", "/").rstrip("/") + "/" if root else None
    if base and path.lower().startswith(base.lower()):
        return path[len(base):]
    return path


def _plural(count, word):
    return f"{count} {word}" + ("" if count == 1 else "s")


def tail(output, lines=TAIL):
    """The last non-empty lines of an output."""
    kept = [line.rstrip() for line in output.splitlines() if line.strip()]
    return kept[-lines:]


# ---- MSBuild and the C# compiler ----

MSBUILD = re.compile(r"^\s*(?P<file>[^\s(][^(]*?)\((?P<line>\d+)(?:,(?P<col>\d+))?(?:,\d+,\d+)?\)\s*:\s*"
                     r"(?P<level>error|warning)\s+(?P<code>[A-Za-z]+\d+)\s*:\s*(?P<msg>.*?)(?:\s+\[(?P<proj>[^\]]+)\])?\s*$")
MSBUILD_GENERAL = re.compile(r"^\s*(?P<origin>[^:\[]+?)\s*:\s*(?P<level>error|warning)\s+(?P<code>[A-Za-z]+\d+)\s*:\s*"
                             r"(?P<msg>.*?)(?:\s+\[(?P<proj>[^\]]+)\])?\s*$")


def msbuild_lines(output, root=None):
    """(errors, warnings) from MSBuild output, as 'file:line: CODE message'."""
    errors, warnings = [], []
    for line in output.splitlines():
        found = MSBUILD.match(line)
        if found:
            text = f"{_short(found['file'], root)}:{found['line']}: {found['code']} {found['msg']}"
        else:
            found = MSBUILD_GENERAL.match(line)
            if not found:
                continue
            text = f"{found['code']} {found['msg']}"
        (errors if found["level"] == "error" else warnings).append(text)
    return _unique(errors), _unique(warnings)


def msbuild(output, ok, root=None):
    errors, warnings = msbuild_lines(output, root)
    parsed = Parsed(problems=errors, warnings=warnings, counts={"errors": len(errors), "warnings": len(warnings)})
    if errors:
        parsed.summary = _plural(len(errors), "error") + (f", {_plural(len(warnings), 'warning')}" if warnings else "")
    elif not ok:
        parsed.summary, parsed.problems = "failed", tail(output)
    else:
        parsed.summary = "built" + (f", {_plural(len(warnings), 'warning')}" if warnings else "")
    return parsed


# ---- dotnet test (VSTest's console logger) ----

DOTNET_TOTALS = re.compile(r"(?P<state>Passed|Failed)!\s*-\s*Failed:\s*(?P<failed>\d+),\s*Passed:\s*(?P<passed>\d+),"
                           r"\s*Skipped:\s*(?P<skipped>\d+),\s*Total:\s*(?P<total>\d+)")
DOTNET_FAILED = re.compile(r"^\s*Failed\s+(?P<name>\S+)\s+\[")


def dotnet_test(output, ok, root=None):
    errors, warnings = msbuild_lines(output, root)
    lines = output.splitlines()
    failed = []
    for index, line in enumerate(lines):
        found = DOTNET_FAILED.match(line)
        if not found:
            continue
        message = ""
        for follow in lines[index + 1:index + 12]:
            if follow.strip() == "Error Message:":
                continue
            if follow.strip().startswith(("Stack Trace:", "Failed ", "Passed ")):
                break
            if follow.strip():
                message = follow.strip()
                break
        failed.append(f"{found['name']}: {message}" if message else found["name"])
    totals = [m for m in DOTNET_TOTALS.finditer(output)]
    total = sum(int(m["total"]) for m in totals)
    failures = sum(int(m["failed"]) for m in totals)
    parsed = Parsed(problems=errors + _unique(failed), warnings=warnings,
                    counts={"tests": total, "failed": failures, "warnings": len(warnings)})
    if errors:
        parsed.summary = "did not build: " + _plural(len(errors), "error")
    elif failures:
        parsed.summary = f"{failures} of {total} failed"
    elif totals:
        parsed.summary = f"{total} passed"
    elif not ok:
        parsed.summary, parsed.problems = "failed", tail(output)
    else:
        parsed.summary = "no tests found"
    return parsed


# ---- Python's unittest ----

UNITTEST_RAN = re.compile(r"^Ran (?P<count>\d+) tests? in", re.MULTILINE)
UNITTEST_FAILED = re.compile(r"^FAILED \((?P<detail>[^)]*)\)", re.MULTILINE)
UNITTEST_BLOCK = re.compile(r"^(?P<kind>FAIL|ERROR): (?P<test>\S+) \((?P<where>[^)]+)\)", re.MULTILINE)
SEPARATOR = re.compile(r"^(?:-{20,}|={20,})\s*$")


def unittest(output, ok, root=None):
    lines = output.splitlines()
    problems = []
    for found in UNITTEST_BLOCK.finditer(output):
        start = output.count("\n", 0, found.start())
        last = ""
        for line in lines[start + 1:]:
            if UNITTEST_BLOCK.match(line) or (line.startswith("Ran ") and " test" in line):
                break
            if line.strip() and not SEPARATOR.match(line) and not line.startswith(("Traceback", "  ")):
                last = line.strip()
        # Python 3.11 and later print (module.Class.test), 3.10 prints (module.Class): keep the class either way.
        parts = found["where"].split(".")
        if len(parts) > 1 and parts[-1] == found["test"]:
            parts = parts[:-1]
        problems.append(f"{found['kind']} {parts[-1]}.{found['test']}: {last}".rstrip(": "))
    ran = UNITTEST_RAN.search(output)
    count = int(ran["count"]) if ran else 0
    failed = UNITTEST_FAILED.search(output)
    failures = sum(int(n) for n in re.findall(r"(?:failures|errors)=(\d+)", failed["detail"])) if failed else 0
    parsed = Parsed(problems=_unique(problems), counts={"tests": count, "failed": failures})
    if failed:
        parsed.summary = f"{failures} of {count} failed"
    elif ran and ok:
        parsed.summary = f"{count} passed"
    elif not ok:
        parsed.summary = "failed"
        parsed.problems = parsed.problems or tail(output)
    else:
        parsed.summary = "no tests found"
    return parsed


# ---- cargo: build, clippy, test and fmt --check ----

CARGO_DIAGNOSTIC = re.compile(r"^(?P<level>error|warning)(?:\[(?P<code>[^\]]+)\])?: (?P<msg>.+)$")
CARGO_LOCATION = re.compile(r"^\s*--> (?P<where>.+)$")
CARGO_TEST_FAILED = re.compile(r"^test (?P<name>\S+) \.\.\. FAILED", re.MULTILINE)
CARGO_TOTALS = re.compile(r"^test result: (?:ok|FAILED)\. (?P<passed>\d+) passed; (?P<failed>\d+) failed", re.MULTILINE)
CARGO_FMT = re.compile(r"^Diff in (?P<file>.+?) at line (?P<line>\d+):", re.MULTILINE)
CARGO_NOISE = ("could not compile", "aborting due to", "generated ", "build failed")


def cargo(output, ok, root=None):
    lines = output.splitlines()
    errors, warnings = [], []
    for index, line in enumerate(lines):
        found = CARGO_DIAGNOSTIC.match(line)
        if not found or any(noise in found["msg"] for noise in CARGO_NOISE):
            continue
        where = ""
        for follow in lines[index + 1:index + 4]:
            located = CARGO_LOCATION.match(follow)
            if located:
                where = _short(located["where"], root) + ": "
                break
        code = f"{found['code']} " if found["code"] else ""
        (errors if found["level"] == "error" else warnings).append(f"{where}{code}{found['msg']}")
    failed_tests = [f"test {m['name']} failed" for m in CARGO_TEST_FAILED.finditer(output)]
    formatting = [f"{_short(m['file'], root)}:{m['line']}: not formatted (cargo fmt)" for m in CARGO_FMT.finditer(output)]
    totals = list(CARGO_TOTALS.finditer(output))
    tests = sum(int(m["passed"]) + int(m["failed"]) for m in totals)
    failures = sum(int(m["failed"]) for m in totals)
    problems = _unique(errors + failed_tests + formatting)
    parsed = Parsed(problems=problems, warnings=_unique(warnings), counts={"tests": tests, "failed": failures,
                                                                        "warnings": len(_unique(warnings))})
    if problems:
        parsed.summary = (f"{failures} of {tests} failed" if failures else
                          f"{len(formatting)} files not formatted" if formatting and not errors else
                          _plural(len(_unique(errors)), "error"))
    elif not ok:
        parsed.summary, parsed.problems = "failed", tail(output)
    else:
        parsed.summary = f"{tests} passed" if totals else "ok"
    return parsed


# ---- Anything else ----

def text(output, ok, root=None):
    """Exit code only: on failure, the tail of the output."""
    if ok:
        return Parsed(summary="ok")
    return Parsed(summary="failed", problems=tail(output))


PARSERS = {"msbuild": msbuild, "dotnet-test": dotnet_test, "unittest": unittest, "cargo": cargo, "text": text}
