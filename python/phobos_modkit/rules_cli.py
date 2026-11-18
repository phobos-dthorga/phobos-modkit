"""rules: the rules every Phobos and D'thorga repository shares, and whether a repository reads them.

    rules list                    the shared rule files: when each is read, what it covers, how many rules it holds
    rules check --root REPO       whether REPO reads them: the import in its CLAUDE.md and the pointer in its AGENTS.md

The rules live in this repository's rules/ folder (rules/README.md says how a rule is changed and how a repository takes them up).
check fails when a line is missing, so a repository's gate can hold it to reading them. It only reads.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys

from . import rules
from .manifest import READS
from .report import Bullets, Report, Table, envelope_text, home_redactor, keep, render_markdown

EXIT_OK, EXIT_FAILED, EXIT_USAGE = 0, 1, 2


def _parser():
    p = argparse.ArgumentParser(prog="rules", description=__doc__.split("\n\n")[0],
                                formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__.split("\n\n", 1)[1])
    sub = p.add_subparsers(dest="report", required=True)
    for name, helptext in (("list", "the shared rule files, when each is read and what it covers"),
                           ("check", "whether a repository reads the shared rules")):
        s = sub.add_parser(name, help=helptext)
        if name == "check":
            s.add_argument("--root", help="the repository (default: the current folder)")
        s.add_argument("--json", action="store_true", help="print JSON instead of Markdown")
        s.add_argument("--no-redact", action="store_true", help="show the home folder instead of ~")
    return p


def list_report(folder=rules.FOLDER):
    files = rules.rule_files(folder)
    faults = rules.problems(folder)
    report = Report(f"Shared rules: {len(files):,} file{'' if len(files) == 1 else 's'}, "
                    f"{sum(f.rules for f in files):,} rules")
    report.lines.append("What the owner has decided for every repository. A repository reads the copy its pin of the kit holds.")
    report.section("Files", Table(["File", "Read", "Covers", "Rules"],
                                  [[f.name, f.read, f.covers, "a design to edit" if f.design else f"{f.rules:,}"] for f in files]))
    if faults:
        report.section("To put right", Bullets(faults))
    data = {"folder": str(folder), "problems": faults,
            "files": [{"name": f.name, "title": f.title, "read": f.read, "covers": f.covers, "sections": f.sections, "rules": f.rules,
                       "design": f.design}
                      for f in files]}
    return report, data, bool(faults)


def check_report(root):
    found = rules.uptake(root)
    name = Path(root).resolve().name
    if found.ok:
        report = Report(f"Shared rules: {name} reads them")
        report.lines.append(f"Its CLAUDE.md imports {found.path} and its AGENTS.md names it.")
    else:
        report = Report(f"Shared rules: {name} does not read them yet")
        report.section("Missing", Bullets(found.missing))
        report.lines.append("rules/README.md in phobos-modkit says how a repository takes the rules up.")
    data = {"repository": name, "ok": found.ok, "kind": found.kind, "path": found.path, "present": found.present,
            "imports": found.imports, "points": found.points, "missing": found.missing}
    return report, data, not found.ok


def main(argv=None, environ=None, out=None, folder=None):
    out = out or sys.stdout
    environ = os.environ if environ is None else environ
    try:
        args = _parser().parse_args(list(sys.argv[1:] if argv is None else argv))
    except SystemExit as stop:
        return EXIT_USAGE if stop.code else EXIT_OK
    redact = keep if args.no_redact else home_redactor()
    if args.report == "list":
        report, data, failed = list_report(folder or rules.FOLDER)
    else:
        report, data, failed = check_report(Path(args.root or ".").resolve())
    out.write((envelope_text("rules", report, redact, data) if args.json else render_markdown(report, redact)) + "\n")
    return EXIT_FAILED if failed else EXIT_OK


MANIFEST = {"game": None, "parser": _parser, "effect": READS,
            "reports": {"list": {"question": "Which rules do all my repositories share?"},
                        "check": {"note": "fails when the repository's CLAUDE.md or AGENTS.md does not read the shared rules"}}}
