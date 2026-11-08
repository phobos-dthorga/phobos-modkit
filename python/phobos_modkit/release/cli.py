"""release: changelog checks, version constants kept in step, and a screen of history before going public.

    python -m phobos_modkit release changelog mods/*/CHANGELOG.md        structure, dates, renderable entries
    python -m phobos_modkit release changelog CHANGELOG.md --version 1.2.0   and this version has an entry
    python -m phobos_modkit release constants --list | --check
    python -m phobos_modkit release constants --set Framework.version=0.13.0           preview
    python -m phobos_modkit release constants --set Framework.version=0.13.0 --apply   write every copy
    python -m phobos_modkit release history                               screen the history before going public

Run from the repository, or pass --root. Nothing here contacts a network.
"""
from __future__ import annotations

import argparse
import json
from decimal import InvalidOperation
from pathlib import Path
import re
import subprocess
import sys

from ..report import Bullets, Report, Table, home_redactor, keep, render_json, render_markdown
from ..steam import bbcode
from . import changelog, constants, history

EXIT_OK, EXIT_FAILED, EXIT_USAGE = 0, 1, 2


def build_parser():
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--root", help="the repository (default: the current folder)")
    common.add_argument("--json", action="store_true", help="print JSON instead of Markdown")
    common.add_argument("--no-redact", action="store_true", help="show the home folder instead of ~")
    p = argparse.ArgumentParser(prog="release", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="command", metavar="command")
    s = sub.add_parser("changelog", parents=[common], help="check changelogs: structure, dates and entry text")
    s.add_argument("files", nargs="+")
    s.add_argument("--version", help="also require an entry for this version")
    s.add_argument("--plain", action="store_true", help="skip the store-page text check (any Markdown allowed)")
    s = sub.add_parser("constants", parents=[common], help="list, check or change registered constants")
    s.add_argument("--catalogue", default=constants.CATALOGUE)
    mode = s.add_mutually_exclusive_group()
    mode.add_argument("--list", action="store_true", help="every key, value, bounds and target")
    mode.add_argument("--check", action="store_true", help="verify every registered copy; write nothing")
    mode.add_argument("--apply", action="store_true", help="write the changes; default only previews them")
    s.add_argument("--set", action="append", default=[], metavar="KEY=VALUE")
    s.add_argument("--expect", action="append", default=[], metavar="KEY=OLD_VALUE")
    sub.add_parser("history", parents=[common], help="credentials, personal paths and refused file types in history")
    return p


def changelog_report(root, args):
    report, failed = Report("Changelog check"), []
    rows = []
    for name in args.files:
        path = Path(name) if Path(name).is_absolute() else root / name
        try:
            releases = changelog.parse(path.read_text(encoding="utf-8-sig"))
            if not args.plain:
                for release in releases.values():
                    try:
                        bbcode.render(release.body)
                    except bbcode.BBCodeError as error:
                        raise changelog.ChangelogError(f"{release.version}: {error}") from None
            if args.version and args.version not in releases:
                raise changelog.ChangelogError(f"no entry for {args.version}")
            latest = max(releases, key=changelog.version_key) if releases else ""
            rows.append([name, len(releases), latest, releases[latest].status if latest else "", "ok"])
        except (OSError, ValueError) as error:
            failed.append(name)
            rows.append([name, "", "", "", str(error)])
    report.lines.append(f"{len(args.files) - len(failed)} of {len(args.files)} changelogs pass.")
    report.section("Changelogs", Table(["File", "Entries", "Latest", "Status", "Result"], rows, widths={4: 200}))
    return report, EXIT_FAILED if failed else EXIT_OK


def constants_report(root, args):
    updates, expected = constants.assignments(args.set), constants.assignments(args.expect)
    if (args.list or args.check) and (updates or expected):
        raise constants.UpdateError("--list and --check take no assignments")
    if not (args.list or args.check or updates):
        raise constants.UpdateError("Choose --list, --check or one or more --set assignments")
    original, proposed, summary = constants.plan(root, updates, expected, args.catalogue)
    if args.list:
        state = "listed"
    elif args.check:
        state = "valid"
    elif args.apply and proposed:
        constants.apply(root, original, proposed, args.catalogue)
        state = "applied"
    else:
        state = "preview" if proposed else "unchanged"
    report = Report(f"Constants: {state}")
    report.lines.append(f"{summary['checked']} constants verified in every registered copy.")
    if args.list:
        report.section("Constants", Table(["Key", "Value", "Type", "Targets", "Description"], [
            [k, e["value"], e["type"] + (f" {e['min']}..{e['max']}" if "min" in e else ""), len(e["targets"]),
             e.get("description", "")] for k, e in summary["constants"].items()], widths={4: 120}))
    if summary["changes"]:
        report.section("Changes", Table(["Key", "File", "Line", "Before", "After"], [
            [c["key"], c["path"], c["line"], c["before"], c["after"]] for c in summary["changes"]]))
    review = [f"{k}: {item}" for k, items in summary["review"].items() for item in items]
    if review and state in ("preview", "applied"):
        report.section("Review", Bullets(review))
    if state == "preview":
        report.lines.append("Nothing written. Repeat with --apply, then run the affected builds and checks.")
    return report, EXIT_OK


def history_report(root):
    findings, blobs = history.screen(root)
    report = Report("History screen")
    report.lines.append(f"Read {blobs:,} reachable file objects; {len(findings)} findings. A pattern screen, not a "
                        "guarantee: contents are never shown.")
    if findings:
        report.section("Findings", Table(["Category", "Path", "Object"], [list(f) for f in findings], widths={1: 200}))
    return report, EXIT_FAILED if findings else EXIT_OK


def main(argv=None, root=None, out=None):
    out = out or sys.stdout
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.command:
        parser.print_help(out)
        return EXIT_USAGE
    root = Path(args.root or root or Path.cwd()).resolve()
    redact = keep if args.no_redact else home_redactor()
    try:
        if args.command == "changelog":
            report, code = changelog_report(root, args)
        elif args.command == "constants":
            report, code = constants_report(root, args)
        else:
            report, code = history_report(root)
    except (ValueError, OSError, KeyError, TypeError, InvalidOperation, re.error, RuntimeError,
            subprocess.SubprocessError) as error:
        report, code = Report(f"release {args.command}: error", [str(error)]), EXIT_FAILED
    print(json.dumps(render_json(report, redact), indent=2, ensure_ascii=False) if args.json
          else render_markdown(report, redact), file=out)
    return code
