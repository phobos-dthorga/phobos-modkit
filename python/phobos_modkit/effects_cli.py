"""effects: what a repository's data says a thing does, and whether anything reads it.

    effects check --root REPO    every declared effect nothing reads, or whose name is defined nowhere; fails when one is new
    effects list --root REPO     the same, with the accepted ones and how much was read

The table is the repository's own config/effects.json (docs/effects.md): which data elements declare effects, along which paths, and
what counts as reading them. A finding the repository knows of goes under its "accepted", with why, so check passes while listing it.
check fails on a finding not accepted, and on an accepted one that no longer finds anything, so a repository's gate can hold it. It
only reads.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys

from . import effects
from .manifest import READS
from .report import Bullets, Report, Table, envelope_text, home_redactor, keep, render_markdown

EXIT_OK, EXIT_FAILED, EXIT_USAGE = 0, 1, 2


def _parser():
    p = argparse.ArgumentParser(prog="effects", description=__doc__.split("\n\n")[0],
                                formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__.split("\n\n", 1)[1])
    sub = p.add_subparsers(dest="report", required=True)
    for name, helptext in (("check", "every declared effect nothing reads; fails on one not accepted"),
                           ("list", "the same, with the accepted ones and what was read")):
        s = sub.add_parser(name, help=helptext)
        s.add_argument("--root", help="the repository (default: the current folder)")
        s.add_argument("--config", help="the table (default: config/effects.json in the repository)")
        s.add_argument("--json", action="store_true", help="print JSON instead of Markdown")
        s.add_argument("--no-redact", action="store_true", help="show the home folder instead of ~")
    return p


def _rows(findings):
    return [[f.kind, f.entry, f.what, f.value, f.problem, f.file] for f in findings]


def build(root: Path, config_path=None, everything=False):
    config = effects.load_config(root, Path(config_path) if config_path else None)
    result = effects.audit(root, config)
    failed = bool(result.findings or result.stale)
    name = root.resolve().name
    if failed:
        report = Report(f"Declared effects: {len(result.findings):,} in {name} read by nothing")
    else:
        report = Report(f"Declared effects: everything {name} declares is read")
    report.lines.append(f"{result.effects:,} declared effects on {result.entries:,} entries of {result.kinds:,} kinds; "
                        f"{len(result.accepted):,} accepted.")
    if config.get("description"):
        report.lines.append(config["description"])
    columns = ["Kind", "Entry", "Effect", "Name", "Problem", "File"]
    if result.findings:
        report.section("Read by nothing", Table(columns, _rows(result.findings)))
    if result.stale:
        report.section("Accepted, but no longer found", Bullets(
            [f"{a.get('entry')}: {a.get('value')} (take it out of the table's \"accepted\")" for a in result.stale]))
    if everything and result.accepted:
        report.section("Accepted", Table(["Kind", "Entry", "Effect", "Name", "Why"],
                                         [[f.kind, f.entry, f.what, f.value, f.why or ""] for f in result.accepted]))
    if result.unreadable:
        report.section("Not read", Bullets([f"{p} would not parse as XML" for p in result.unreadable]))
    report.lines.append("A declared name counts as read when another data file names it where the table says it reads, or the code "
                        "names it as a string; it never shows that the reading does what the description promises.")
    as_dict = lambda f: {"kind": f.kind, "entry": f.entry, "what": f.what, "value": f.value, "problem": f.problem, "file": f.file,
                         "why": f.why}
    data = {"repository": name, "kinds": result.kinds, "entries": result.entries, "effects": result.effects,
            "unread": [as_dict(f) for f in result.findings], "accepted": [as_dict(f) for f in result.accepted],
            "stale": result.stale, "unreadable": result.unreadable, "waiting": len(result.findings) + len(result.stale)}
    return report, data, failed


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
        report, data, failed = build(root, args.config, everything=args.report == "list")
    except effects.EffectsError as fault:
        report = Report("Declared effects: the table cannot be used")
        report.lines.append(str(fault))
        data, failed = {"error": str(fault)}, True
    out.write((envelope_text("effects", report, redact, data) if args.json else render_markdown(report, redact)) + "\n")
    return EXIT_FAILED if failed else EXIT_OK


MANIFEST = {"game": None, "parser": _parser, "effect": READS,
            "reports": {"check": {"note": "fails on a declared effect nothing reads that the repository's table has not accepted",
                                  "waits": "waiting"},
                        "list": {"question": "Which of my mods' fittings and upgrades promise something nothing models?",
                                 "waits": "waiting"}}}
