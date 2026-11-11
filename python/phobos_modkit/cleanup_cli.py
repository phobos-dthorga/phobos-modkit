"""cleanup: what the kit's tools and a repository's builds and tests leave behind. Lists by default; --apply deletes.

    cleanup --root REPO               list what would go, with sizes and why
    cleanup --root REPO --apply       delete it, and stop git's file-watcher daemons

It clears the kit's cache (derived data its tools rebuild: indexes whose source has changed, and anything unchanged for
--older-than days), the kit's development build (never the programs the tools run), and what the repository's
config/cleanup.json names. It never touches saves, game or mod folders, settings, or anything a rule does not match.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys

from .cleanup import CleanupError, apply, survey
from .manifest import WRITES
from .report import Bullets, Report, Table, envelope_text, home_redactor, keep, render_markdown

EXIT_OK, EXIT_FAILED, EXIT_USAGE = 0, 1, 2


def _parser():
    p = argparse.ArgumentParser(prog="cleanup", description=__doc__.split("\n\n")[0],
                                formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__.split("\n\n", 1)[1])
    p.add_argument("--root", help="the repository whose config/cleanup.json to follow (default: the current folder)")
    p.add_argument("--config", help="a rules file other than ROOT/config/cleanup.json")
    p.add_argument("--settings", help="a JSON settings file with modkitCachePath and the games' paths")
    p.add_argument("--older-than", type=float, default=14, help="days a cache entry may sit unchanged (default 14)")
    p.add_argument("--keep-build", action="store_true", help="leave the kit's development build alone")
    p.add_argument("--apply", action="store_true", help="delete; without it, only list what would go")
    p.add_argument("--top", type=int, default=15, help="rows per detail table (default 15)")
    p.add_argument("--json", action="store_true", help="print JSON instead of Markdown")
    p.add_argument("--no-redact", action="store_true", help="show the home folder instead of ~")
    return p


def megabytes(count):
    return f"{count / 1024 / 1024:,.1f} MB"


def _groups(items):
    groups = {}
    for item in items:
        group = groups.setdefault(item.group, [0, 0, item.why])
        group[0] += 1
        group[1] += item.size
        if group[2] != item.why:
            group[2] = "several reasons; the largest are listed below"
    return groups


def build_report(found, applied=None, top=15):
    deleted, failed, stopped = applied or ([], [], 0)
    if applied is None:
        title = f"Cleanup: {len(found.items):,} to delete, {megabytes(found.size)} (preview)"
    else:
        title = f"Cleanup: deleted {len(deleted):,}, {megabytes(sum(i.size for i in deleted))}"
    report = Report(title)
    groups = _groups(found.items)
    if groups:
        report.section("What would go" if applied is None else "What went", Table(
            ["Group", "Items", "Size", "Why"],
            [[name, count, megabytes(size), why] for name, (count, size, why) in
             sorted(groups.items(), key=lambda g: -g[1][1])]))
        largest = sorted(found.items, key=lambda i: -i.size)
        report.section("Largest", Table(["Path", "Size", "Why"], [[str(i.path), megabytes(i.size), i.why] for i in largest[:top]],
                                        total=len(largest)))
    else:
        report.lines.append("Nothing to delete.")
    daemons = (f"Git file-watcher daemons: {len(found.daemons)} running"
               + (", stopped with --apply; git starts one again when a repository needs it." if applied is None and found.daemons else ".")
               if applied is None else f"Git file-watcher daemons stopped: {stopped} of {len(found.daemons)}.")
    report.lines.append(daemons)
    if found.notes:
        report.section("Left alone", Bullets(found.notes))
    if failed:
        report.section("Could not delete", Bullets([f"{line}: something holds it open; run again later." for line in failed]))
    if applied is None and found.items:
        report.lines.append("**Preview only. Add --apply to delete.**")
    return report


def main(argv=None, environ=None, out=None):
    out = out or sys.stdout
    environ = os.environ if environ is None else environ
    try:
        args = _parser().parse_args(list(sys.argv[1:] if argv is None else argv))
    except SystemExit as stop:
        return EXIT_USAGE if stop.code else EXIT_OK
    redact = keep if args.no_redact else home_redactor()
    root = Path(args.root or ".").resolve()
    try:
        found = survey(root, args.older_than, args.config, environ, args.settings, include_build=not args.keep_build)
    except CleanupError as error:
        print(redact(str(error)), file=sys.stderr)
        return EXIT_USAGE
    applied = apply(found) if args.apply else None
    report = build_report(found, applied, args.top)
    data = {"items": [{"group": i.group, "path": str(i.path), "bytes": i.size, "why": i.why} for i in found.items],
            "applied": bool(args.apply)}
    out.write((envelope_text("cleanup", report, redact, data) if args.json else render_markdown(report, redact)) + "\n")
    return EXIT_FAILED if applied and applied[1] else EXIT_OK


MANIFEST = {"game": None, "parser": _parser, "effect": WRITES, "reports": {None: {"when": "--apply"}},
            "question": "What have the tools and tests left behind, and how much room would clearing it give back?"}
