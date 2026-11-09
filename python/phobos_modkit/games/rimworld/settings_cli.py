"""rimworld-settings: the player's mod settings as RimWorld saved them, for debugging a report.

    rimworld-settings                          which mods keep settings, and files left by mods no longer active
    rimworld-settings --mod "PhobosDthorga.*"  the values of matching mods (name, package ID or folder; * and ?)
    rimworld-settings --mod X --defaults F     ... with each value beside its default, and the keys left at default
    rimworld-settings snapshot FILE            every value now, as JSON, to compare later
    rimworld-settings compare FILE [FILE2]     what changed since a snapshot (or between two)

Reads only. RimWorld writes a value only when it differs from the mod's default, so a mod's file shows what the player
changed; a consumer that knows its own mods' defaults (from their source) passes them with --defaults.
"""
from __future__ import annotations

import argparse
import fnmatch
import json
from pathlib import Path
import sys

from ...report import Bullets, Report, Section, Table, envelope_text, home_redactor, keep, render_markdown
from . import loading, paths
from .mods import ModIndex, default_roots
from .settings import LIST_SHOWN, SettingsError, compare, read_defaults, read_snapshot, same_value, scan, snapshot
from ...manifest import READS, WRITES

EXIT_OK, EXIT_FAILED, EXIT_USAGE = 0, 1, 2
VALUE_WIDTH = 100


def _parser():
    common = argparse.ArgumentParser(add_help=False)
    c = common.add_argument_group("where the game is")
    c.add_argument("--config", help="the Config folder (else RIMWORLD_CONFIG_PATH, the settings file, the default)")
    c.add_argument("--game", help="the RimWorld folder, to name the mods (else RIMWORLD_PATH, settings, Steam's default)")
    c.add_argument("--workshop", help="the Workshop content folder (else RIMWORLD_WORKSHOP_PATH, settings, beside the game)")
    c.add_argument("--settings", help="a JSON settings file with rimworldConfigPath, rimworldPath, workshopPath")
    o = common.add_argument_group("what to show")
    o.add_argument("--mod", action="append", default=[], metavar="PATTERN",
                   help="show the values of mods whose name, package ID or folder matches; repeatable")
    o.add_argument("--all", action="store_true", help="show the values of every mod with a settings file")
    o.add_argument("--list", action="store_true", help="list every mod with settings and every file left behind, uncut")
    o.add_argument("--top", type=int, default=15, help="rows per table (default 15)")
    o.add_argument("--defaults", help="a defaults file (schemaVersion 1) naming each settings class's keys and defaults")
    o.add_argument("--json", action="store_true", help="print JSON instead of Markdown")
    o.add_argument("--no-redact", action="store_true", help="show the home folder instead of ~")
    p = argparse.ArgumentParser(prog="rimworld-settings", description=__doc__.split("\n\n")[0],
                                formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__.split("\n\n", 1)[1])
    sub = p.add_subparsers(dest="report", metavar="report")
    sub.add_parser("summary", parents=[common], help="mods with settings, values of chosen mods, files left behind")
    s = sub.add_parser("snapshot", parents=[common], help="write every value now to a JSON file")
    s.add_argument("file")
    k = sub.add_parser("compare", parents=[common], help="what changed since a snapshot, or between two")
    k.add_argument("before")
    k.add_argument("after", nargs="?")
    return p


def _matches(found, patterns):
    texts = [found.folder.lower(), found.path.name.lower()]
    if found.mod is not None:
        texts += [found.mod.name.lower(), found.mod.package_id]
    return any(fnmatch.fnmatchcase(t, p.lower()) for p in patterns for t in texts)


def _short(value):
    if value.startswith("[") and "] " in value:
        count, items = value[1:].split("] ", 1)
        parts = items.split("; ")
        if len(parts) > LIST_SHOWN:
            return f"[{count}] " + "; ".join(parts[:LIST_SHOWN]) + f"; ... ({len(parts) - LIST_SHOWN} more)"
    return value


def summary_report(files, others, args, defaults):
    report = Report("RimWorld mod settings")
    active = sorted((f for f in files if f.active), key=lambda f: f.position)
    inactive = [f for f in files if not f.active and f.mod is not None]
    gone = [f for f in files if f.mod is None]
    report.lines.append(f"{len(files)} mod settings files: {len(active)} for active mods, {len(inactive)} for installed "
                        f"mods that are not active, {len(gone)} for mods not installed.")
    report.lines.append("RimWorld writes a value only when it differs from the mod's default: a file lists what the "
                        "player changed, and a value left at its default does not appear.")
    # With mods chosen, the lists are only counted (the point is those mods' values); --list shows them uncut.
    focused = (args.mod or args.all) and not args.list
    top = None if args.list else max(1, args.top)
    if not focused:
        rows = [[f.position, f.label, f.mod.package_id, len(f.values) if not f.problem else f.problem, f.saved, f.path.name]
                for f in sorted(active, key=lambda f: (-len(f.values), f.position))]
        report.section("Active mods with settings, most values first",
                       Table(["#", "Mod", "Package ID", "Values set", "Saved", "File"], rows[:top], total=len(rows),
                             more="add --list to see every one"))
        left = [[f.path.name, "installed, not active" if f.mod else "no installed mod has this folder", f.saved]
                for f in sorted(inactive + gone, key=lambda f: f.saved, reverse=True)]
        if left:
            report.section("Files left by mods not active, newest first",
                           Table(["File", "Why", "Saved"], left[:top], total=len(left), more="add --list to see every one"),
                           "The game never deletes these; they do no harm. A mod merged into another or renamed leaves one.")
    chosen = files if args.all else [f for f in files if args.mod and _matches(f, args.mod)]
    if args.mod and not chosen:
        report.lines.append(f"No settings file matches {', '.join(args.mod)}: those mods' settings are all at default, "
                            "or the pattern names no mod.")
    for found in sorted(chosen, key=lambda f: (not f.active, f.position, f.path.name.lower())):
        report.sections.append(mod_section(found, defaults))
    if others:
        report.lines.append(f"{len(others)} other files in Config are not mod settings in this format "
                            f"({', '.join(others[:6])}{', ...' if len(others) > 6 else ''}).")
    return report


def mod_section(found, defaults):
    known = defaults.get(found.settings_class, {}) if defaults else {}
    state = "active" if found.active else "not active" if found.mod else "not installed"
    heading = f"{found.label} ({state}; {found.path.name})"
    blocks = []
    if found.problem:
        return Section(heading, [found.problem])
    if found.settings_class:
        blocks.append(f"Settings class {found.settings_class}.")
    rows = []
    for key, value in found.values.items():
        row = [key, _short(value)]
        if known:
            entry = known.get(key)
            if entry is None:
                row.append("not read by this version")
            elif same_value(value, entry.get("default", "")):
                row.append("= default (written anyway)")
            else:
                row.append(str(entry.get("default", "")))
        rows.append(row)
    headers = ["Key", "Value"] + (["Default"] if known else [])
    blocks.append(Table(headers, rows, widths={1: VALUE_WIDTH}) if rows else "Every value is at its default.")
    if known:
        at_default = [f"{k} = {e.get('default', '')}" for k, e in known.items() if k not in found.values]
        if at_default:
            blocks.append(Bullets([f"At default, so not in the file: {'; '.join(at_default)}"]))
        disagree = [f"{k}: field starts at {e['initial']}, but a missing key loads as {e.get('default', '')}"
                    for k, e in known.items() if "initial" in e and not same_value(str(e["initial"]), e.get("default", ""))]
        if disagree:
            blocks.append(Bullets(["Defaults that disagree (a new player and one upgrading get different values): "
                                   + "; ".join(disagree)]))
    return Section(heading, blocks)


def compare_report(rows, before, after):
    report = Report("RimWorld mod settings: changes")
    report.lines.append(f"{len(rows)} differences between {before} and {after}." if rows else
                        f"No differences between {before} and {after}.")
    if rows:
        report.section("Changes", Table(["File", "Mod", "Key", "Before", "After"],
                                        [[f, m, k, _short(str(a)), _short(str(b))] for f, m, k, a, b in rows],
                                        widths={3: 60, 4: 60}))
    return report


def main(argv=None, settings_file=None, environ=None, out=None):
    out = out or sys.stdout
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or (argv[0].startswith("-") and argv[0] not in ("-h", "--help")):
        argv.insert(0, "summary")
    try:
        args = _parser().parse_args(argv)
    except SystemExit as stop:
        return EXIT_USAGE if stop.code else EXIT_OK
    settings_file = args.settings or settings_file
    redact = keep if args.no_redact else home_redactor()
    try:
        config = paths.config_path(args.config, environ, settings_file)
        game = paths.game_path(args.game, environ, settings_file)
        workshop = paths.workshop_path(game, args.workshop, environ, settings_file) if game else None
        index = ModIndex.scan(default_roots(game, workshop))
        mods_config = Path(config) / "ModsConfig.xml"
        active = loading.resolve_active(index.mods, loading.read_mods_config(mods_config)[2]) if mods_config.is_file() else []
        files, others = scan(config, index.mods, active)
        defaults = read_defaults(args.defaults) if args.defaults else {}
        if args.report == "snapshot":
            Path(args.file).write_text(json.dumps(snapshot(files), indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
            report = Report("RimWorld mod settings: snapshot", [f"Wrote {len(files)} files' values to {args.file}."])
        elif args.report == "compare":
            before = read_snapshot(args.before)
            after = read_snapshot(args.after) if args.after else snapshot(files)
            report = compare_report(compare(before, after), args.before, args.after or "now")
        else:
            report = summary_report(files, others, args, defaults)
        code = EXIT_OK
    except SettingsError as error:
        report, code = Report("rimworld-settings: error", [str(error)]), EXIT_FAILED
    print(envelope_text("rimworld-settings", report, redact) if args.json
          else render_markdown(report, redact), file=out)
    return code


MANIFEST = {"game": "rimworld", "parser": _parser, "effect": READS,
            "reports": {"snapshot": {"effect": WRITES, "note": "writes the snapshot file you name"}}}
