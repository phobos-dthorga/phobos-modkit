"""The gate command: run a repository's checks and print a short report of what failed."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys
import time

from .. import cache
from ..report import Bullets, Code, Report, Table, envelope_text, home_redactor, render_markdown
from .runner import CONFIG, GateError, load, run, select
from ..manifest import RUNS

EXIT_OK, EXIT_FAILED, EXIT_USAGE = 0, 1, 2
PROBLEMS_PER_STEP = 12
WARNINGS_SHOWN = 15


def build_parser():
    parser = argparse.ArgumentParser(prog="gate", description="gate: run a repository's checks and report what failed.")
    parser.add_argument("--root", help="the repository (default: the current folder)")
    parser.add_argument("--config", default=CONFIG, help=f"the step list, relative to the root (default {CONFIG})")
    parser.add_argument("--only", action="append", default=[], metavar="PATTERN",
                        help="run only steps whose name matches (wildcards * and ?); repeatable")
    parser.add_argument("--skip", action="append", default=[], metavar="PATTERN", help="leave out matching steps; repeatable")
    parser.add_argument("--jobs", type=int, default=min(4, os.cpu_count() or 1), help="lanes run at once (default up to 4)")
    parser.add_argument("--keep-going", action="store_true", help="run later stages even when a stage failed")
    parser.add_argument("--list", action="store_true", help="show the steps, expanded, without running them")
    parser.add_argument("--verbose", action="store_true", help="list every step, not only the failed ones")
    parser.add_argument("--json", action="store_true", help="print JSON instead of Markdown")
    parser.add_argument("--no-redact", action="store_true", help="show the home folder instead of ~")
    return parser


def list_report(stages):
    report = Report("Gate: steps")
    count = sum(len(steps) for _, steps in stages)
    report.lines.append(f"{count} steps in {len(stages)} stages; steps sharing a lane run one after another.")
    for name, steps in stages:
        report.section(name, Table(["Step", "Lane", "Parser", "Command"],
                                   [[s.name, s.lane, s.parser, " ".join(s.run)] for s in steps], widths={3: 140}))
    return report


def totals_line(results):
    counts = {}
    for r in results:
        if r.state == "skipped":
            continue
        tests = r.parsed.counts.get("tests", 0)
        if tests:
            kind = {"dotnet-test": ".NET", "unittest": "Python", "cargo": "Rust"}.get(r.step.parser, r.step.parser)
            counts[kind] = counts.get(kind, 0) + tests
    return ", ".join(f"{n} {kind}" for kind, n in counts.items())


def result_report(results, seconds, verbose=False):
    failed = [r for r in results if r.state == "failed"]
    skipped = [r for r in results if r.state == "skipped"]
    passed = [r for r in results if r.state == "passed"]
    title = "Gate: passed" if not failed else f"Gate: failed ({len(failed)} of {len(results)} steps)"
    report = Report(title)
    line = f"{len(passed)} of {len(results)} steps passed in {seconds:.0f} s"
    tests = totals_line(results)
    report.lines.append(line + (f"; tests run: {tests}." if tests else "."))
    for r in failed:
        problems = r.parsed.problems
        shown = problems[:PROBLEMS_PER_STEP]
        more = len(problems) - len(shown)
        blocks = [Code(shown + ([f"... and {more} more"] if more > 0 else []))]
        if r.log:
            blocks.append(f"Full output: {r.log}")
        report.section(f"Failed: {r.step.name} ({r.parsed.summary})", *blocks, level=2)
    warnings = [(r.step.name, w) for r in results for w in r.parsed.warnings]
    if warnings:
        unique = list(dict.fromkeys(w for _, w in warnings))
        report.section(f"Warnings ({len(unique)})", Bullets(unique[:WARNINGS_SHOWN] + (
            [f"... and {len(unique) - WARNINGS_SHOWN} more"] if len(unique) > WARNINGS_SHOWN else [])))
    if skipped:
        reasons = {}
        for r in skipped:
            reasons.setdefault(r.reason, []).append(r.step.name)
        report.section("Skipped", Bullets([f"{len(names)} because {reason}: {', '.join(names[:6])}"
                                           + (" ..." if len(names) > 6 else "") for reason, names in reasons.items()]))
    if verbose:
        report.section("Steps", Table(["Step", "Result", "Seconds", "Summary"],
                                      [[r.step.name, r.state, f"{r.seconds:.1f}", r.parsed.summary or r.reason] for r in results]))
    return report


def main(argv=None, out=None, environ=None, runner=None, which=None):
    out = out or sys.stdout
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as stop:
        return EXIT_USAGE if stop.code else EXIT_OK
    root = Path(args.root or ".").resolve()
    environ = os.environ if environ is None else environ
    redact = None if args.no_redact else home_redactor()
    options = {}
    if runner is not None:
        options["runner"] = runner
    if which is not None:
        options["which"] = which
    try:
        stages = select(load(root, args.config, environ), args.only, args.skip)
        if not any(steps for _, steps in stages):
            raise GateError("No steps match")
        if args.list:
            report, code = list_report(stages), EXIT_OK
        else:
            started = time.monotonic()
            logs = cache.folder("gate-logs", environ=environ) / root.name
            results = run(stages, root, environ, args.jobs, args.keep_going, logs, **options)
            report = result_report(results, time.monotonic() - started, args.verbose)
            code = EXIT_FAILED if any(r.state == "failed" for r in results) else EXIT_OK
    except GateError as error:
        report, code = Report("Gate: error", [str(error)]), EXIT_USAGE
    print(envelope_text("gate", report, redact) if args.json
          else render_markdown(report, redact), file=out)
    return code


MANIFEST = {"game": None, "parser": build_parser, "effect": RUNS,
            "note": "builds the repository and runs its tests"}
