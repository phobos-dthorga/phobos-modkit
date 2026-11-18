"""settings: the settings the tools read, where each value comes from, and the central settings file.

    settings list                         every setting: its value, and whether it comes from the environment, a repository's own
                                          file, the central file or the default
    settings list --root REPO [...]       also the settings a repository declares, and each repository's own values
    settings set --key historyPath --value K:\\phobos-modkit\\history
                                          set a setting in the central file, for every repository and game
    settings set --key historyPath --clear
                                          take it out of the central file again

The central file is settings.json in D'thorga Companion's folder (PHOBOS_SETTINGS names another). A repository's own file still
wins over it, and the environment over both (docs/settings.md). set writes only the central file.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys

from . import kit_settings, paths
from .manifest import READS, WRITES
from .report import Report, Table, envelope_text, home_redactor, keep, render_markdown

EXIT_OK, EXIT_REFUSED, EXIT_USAGE = 0, 1, 2
LAYER_WORDS = {"environment": "environment variable", "repository": "repository's own file", "central": "central file",
               "default": "default"}


def _parser():
    p = argparse.ArgumentParser(prog="settings", description=__doc__.split("\n\n")[0],
                                formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__.split("\n\n", 1)[1])
    sub = p.add_subparsers(dest="report", required=True)
    for name, helptext in (("list", "every setting, its value and where it comes from"),
                           ("set", "set or clear a setting in the central file")):
        s = sub.add_parser(name, help=helptext)
        s.add_argument("--root", action="append", default=[], help="a repository whose own settings to read (repeatable)")
        if name == "set":
            s.add_argument("--key", required=True, help="the setting's name, as list gives it")
            group = s.add_mutually_exclusive_group(required=True)
            group.add_argument("--value", help="its new value: a full path")
            group.add_argument("--clear", action="store_true", help="take it out of the central file")
        s.add_argument("--json", action="store_true", help="print JSON instead of Markdown")
        s.add_argument("--no-redact", action="store_true", help="show the home folder instead of ~")
    return p


def _data(reading):
    s = reading.setting
    return {"key": s.key, "env": s.env or None, "description": s.description, "kind": s.kind, "game": s.game,
            "declaredBy": s.declared_by, "value": reading.value, "layer": reading.layer, "repository": reading.repository,
            "central": reading.central, "default": reading.default, "exists": reading.exists, "overridden": reading.overridden}


def list_report(roots, environ):
    readings = kit_settings.read(roots, environ)
    central = paths.central_settings_file(environ)
    report = Report(f"Settings: {len(readings):,} the tools read")
    report.lines.append(f"The central file is {central}" + ("." if central.is_file() else " (not written yet)."))
    report.section("Settings", Table(["Setting", "Value", "From", "What it is for"],
                                     [[r.setting.key, r.value or "-", LAYER_WORDS[r.layer], r.setting.description] for r in readings]))
    data = {"centralFile": str(central), "centralExists": central.is_file(), "settings": [_data(r) for r in readings]}
    return report, data


def main(argv=None, environ=None, out=None):
    out = out or sys.stdout
    environ = os.environ if environ is None else environ
    try:
        args = _parser().parse_args(list(sys.argv[1:] if argv is None else argv))
    except SystemExit as stop:
        return EXIT_USAGE if stop.code else EXIT_OK
    redact = keep if args.no_redact else home_redactor()
    roots = [Path(r).resolve() for r in args.root]
    code = EXIT_OK
    try:
        if args.report == "list":
            report, data = list_report(roots, environ)
        else:
            path = kit_settings.set_central(args.key, None if args.clear else args.value, roots, environ)
            report = Report(f"Settings: {args.key} {'cleared from' if args.clear else 'set in'} the central file")
            report.lines.append(f"{path}")
            data = {"ok": True, "key": args.key, "value": None if args.clear else args.value, "centralFile": str(path)}
    except (kit_settings.SettingsError, OSError) as error:
        if not args.json:
            print(redact(str(error)), file=sys.stderr)
            return EXIT_REFUSED
        report, data = Report("Refused"), {"ok": False, "refusal": str(error)}
        report.lines.append(str(error))
        code = EXIT_REFUSED
    out.write((envelope_text("settings", report, redact, data) if args.json else render_markdown(report, redact)) + "\n")
    return code


MANIFEST = {"game": None, "parser": _parser, "effect": READS,
            "reports": {"list": {"question": "Which settings do the tools read, and where does each value come from?",
                                 "surface": "settings"},
                        "set": {"effect": WRITES, "note": "writes one setting into the central settings file"}}}
