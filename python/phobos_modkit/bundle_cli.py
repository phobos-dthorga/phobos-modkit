"""bundle: a script and the kit modules it imports, written as one file that runs with Python alone, for people without the kit.

    bundle SCRIPT --out FILE [--python 3.9]       write the one file
    bundle SCRIPT --check FILE [--python 3.9]     whether FILE is what bundling SCRIPT gives now (exit 1 when not)

The same script and kit always give the same bytes. --python is the oldest Python the file promises: every bundled module's
syntax is checked against it (default 3.10, the kit's own). It reads the script and the kit; only --out writes, and only that file.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import sys

from . import bundle as bundling
from .manifest import READS, WRITES
from .report import Report, Table, envelope_text, home_redactor, keep, render_markdown

EXIT_OK, EXIT_FAILED, EXIT_USAGE = 0, 1, 2


def _parser():
    p = argparse.ArgumentParser(prog="bundle", description=__doc__.split("\n\n")[0],
                                formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__.split("\n\n", 1)[1])
    p.add_argument("script", help="the script to bundle: it imports what it needs from phobos_modkit")
    where = p.add_mutually_exclusive_group(required=True)
    where.add_argument("--out", metavar="FILE", help="write the bundled file here")
    where.add_argument("--check", metavar="FILE", help="only compare FILE with what bundling gives now; exit 1 when it differs")
    p.add_argument("--python", default="3.10", help="the oldest Python the file promises, such as 3.9 (default 3.10)")
    p.add_argument("--json", action="store_true", help="print JSON instead of Markdown")
    p.add_argument("--no-redact", action="store_true", help="show the home folder instead of ~")
    return p


def main(argv=None, out=None):
    out = out or sys.stdout
    try:
        args = _parser().parse_args(list(sys.argv[1:] if argv is None else argv))
    except SystemExit as stop:
        return EXIT_USAGE if stop.code else EXIT_OK
    redact = keep if args.no_redact else home_redactor()
    script = Path(args.script)
    target = Path(args.out or args.check)
    try:
        if not script.is_file():
            raise bundling.BundleError(f"no such script: {script}")
        made = bundling.bundle(script, python=bundling.parse_python(args.python))
    except bundling.BundleError as refused:
        report = Report(f"Bundle: {script.name} cannot be bundled")
        report.lines.append(str(refused))
        out.write((envelope_text("bundle", report, redact, {"script": str(script), "error": str(refused)}) if args.json
                   else render_markdown(report, redact)) + "\n")
        return EXIT_FAILED
    current = target.read_bytes() if target.is_file() else None
    same = current == made.text.encode("utf-8")
    written = False
    if args.out and not same:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(made.text.encode("utf-8"))
        written = True
    if args.out:
        state = "written" if written else "already up to date"
    else:
        state = "up to date" if same else ("missing" if current is None else "out of date: bundle it again")
    report = Report(f"Bundle: {script.name} with {len(made.modules)} kit module{'' if len(made.modules) == 1 else 's'}, {state}")
    report.lines.append(f"{target}: {made.text.count(chr(10)):,} lines, Python {made.python[0]}.{made.python[1]} or newer, "
                        f"sha256 {made.sha256}.")
    report.section("Kit modules, in the order they are set up", Table(["Module", "Lines"], [[name, f"{lines:,}"]
                                                                                          for name, lines in made.modules]))
    data = {"script": str(script), "file": str(target), "state": state, "sha256": made.sha256,
            "python": f"{made.python[0]}.{made.python[1]}", "modules": [{"module": n, "lines": c} for n, c in made.modules]}
    out.write((envelope_text("bundle", report, redact, data) if args.json else render_markdown(report, redact)) + "\n")
    return EXIT_OK if args.out or same else EXIT_FAILED


MANIFEST = {"game": None, "parser": _parser, "effect": READS,
            "reports": {None: {"effect": WRITES, "when": "--out"}},
            "question": "Can I give this script to someone without the kit, as one file?",
            "note": "fails when the script cannot be bundled, or with --check when the file differs; with --out, writes only that file"}
