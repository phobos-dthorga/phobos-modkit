"""rimworld-startup: how long RimWorld takes to start, which mods cost the most, and what changed between launches.

    rimworld-startup                         every recorded launch, the costliest mods and the slowest stages
    rimworld-startup compare                 the last two launches: mods added or removed, the largest changes
    rimworld-startup compare A B             two launches, by the start of their IDs (20261108-1159)
    rimworld-startup mod "Combat Extended"   one mod across the launches (name or package ID; * and ?)

Reads only the StartupImpact sessions the Loading Progress mod writes. Start-up time varies a lot between launches with the
same mods (what the disk has cached, what else is running), so a small change between two launches means little.
"""
from __future__ import annotations

import argparse
import fnmatch
import json
from pathlib import Path
from statistics import median
import sys

from ...report import Report, Table, home_redactor, keep, render_json, render_markdown
from . import paths
from .startup import StartupError, cost_changes, list_change, median_costs, median_stages, read_sessions, same_list

EXIT_OK, EXIT_FAILED, EXIT_USAGE = 0, 1, 2
REPORTS = ("summary", "compare", "mod")
SESSIONS_FOLDER = "StartupImpactSessions"
NOISE_NOTE = ("Start-up time varies between launches with the same mods (the disk's cache, what else is running): trust a "
              "difference only when it repeats.")


def _parser():
    common = argparse.ArgumentParser(add_help=False)
    c = common.add_argument_group("where the data is")
    c.add_argument("--sessions", help="the StartupImpactSessions folder (else beside the game's Config folder)")
    c.add_argument("--config", help="the game's Config folder (else RIMWORLD_CONFIG_PATH, the settings file, the default)")
    c.add_argument("--settings", help="a JSON settings file with rimworldConfigPath")
    o = common.add_argument_group("output")
    o.add_argument("--top", type=int, default=15, help="rows per table (default 15)")
    o.add_argument("--json", action="store_true", help="print JSON instead of Markdown")
    o.add_argument("--no-redact", action="store_true", help="show the home folder instead of ~")
    p = argparse.ArgumentParser(prog="rimworld-startup", description=__doc__.split("\n\n")[0],
                                formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__.split("\n\n", 1)[1])
    sub = p.add_subparsers(dest="report", metavar="report")
    sub.add_parser("summary", parents=[common], help="every launch, the costliest mods and the slowest stages")
    k = sub.add_parser("compare", parents=[common], help="what changed between two launches")
    k.add_argument("first", nargs="?", help="the earlier launch, by the start of its ID")
    k.add_argument("second", nargs="?", help="the later launch, by the start of its ID")
    m = sub.add_parser("mod", parents=[common], help="one mod across the launches")
    m.add_argument("name", help="a mod's name or package ID; * and ? are wildcards")
    return p


def seconds(milliseconds):
    return f"{milliseconds / 1000:.1f}"


def _summary(sessions, unreadable, top):
    fair = same_list(sessions)
    report = Report("RimWorld start-up", [f"{len(sessions)} launches recorded, {sessions[0].id} to {sessions[-1].id}."])
    times = [s.to_menu_ms for s in fair]
    report.lines.append(f"With the newest mod list ({len(fair)} launches, {sessions[-1].mods_loaded} mods): to the main menu in "
                        f"{seconds(min(times))} to {seconds(max(times))} s, median {seconds(median(times))} s.")
    report.lines.append(NOISE_NOTE)
    rows = []
    for i in range(len(sessions) - 1, -1, -1):
        session, change = sessions[i], ""
        if i > 0:
            added, removed = list_change(sessions[i - 1], session)
            change = "same" if not added and not removed else f"+{len(added)}, -{len(removed)}"
        rows.append((session.id, seconds(session.to_menu_ms), seconds(session.loading_ms), session.mods_loaded, session.defs,
                     session.patch_operations, change))
    report.section("Launches, newest first", Table(["Launch", "To menu (s)", "Loading (s)", "Mods", "Defs", "Patches", "Mod list"],
                                                   rows[:top], len(rows)))
    costs = median_costs(fair)
    report.section("Costliest mods (median over the launches with this mod list)", Table(
        ["Mod", "Package ID", "Median (s)", "Newest (s)"],
        [(c.name, c.package_id, seconds(m), seconds(c.milliseconds)) for c, m in costs[:top]], len(costs)))
    stages = median_stages(fair)
    report.section("Slowest stages (median)", Table(["Stage", "Median (s)"], [(s, seconds(m)) for s, m in stages[:top]], len(stages)))
    if unreadable:
        report.section("Could not be read", ", ".join(unreadable) + ".")
    return report


def _find(sessions, text):
    matches = [s for s in sessions if s.id.startswith(text)]
    if len(matches) != 1:
        raise StartupError(f'"{text}" matches {len(matches)} launches; give more of its ID. Launches: '
                           + ", ".join(s.id for s in sessions) + ".")
    return matches[0]


def _compare(sessions, args):
    if bool(args.first) != bool(args.second):
        raise StartupError("Name two launches, or none for the last two.")
    if len(sessions) < 2 and not args.first:
        raise StartupError("Only one launch is recorded, so there is nothing to compare.")
    before = _find(sessions, args.first) if args.first else sessions[-2]
    after = _find(sessions, args.second) if args.second else sessions[-1]
    report = Report(f"RimWorld start-up: {before.id} against {after.id}", [
        f"To the main menu: {seconds(before.to_menu_ms)} s, then {seconds(after.to_menu_ms)} s "
        f"({(after.to_menu_ms - before.to_menu_ms) / 1000:+.1f} s).",
        f"Defs {before.defs:,} to {after.defs:,}; patch operations {before.patch_operations:,} to {after.patch_operations:,}.",
        NOISE_NOTE])
    added, removed = list_change(before, after)
    if added or removed:
        report.section("Mod list", Table(["Change", "Mod"], [("added", n) for n in added] + [("removed", n) for n in removed]))
    else:
        report.lines.append("The mod list did not change.")
    changes = cost_changes(before, after)
    report.section("Largest changes in a mod's cost", Table(["Mod", "Before (s)", "After (s)", "Change (s)"], [
        (name, seconds(was), seconds(now), f"{change / 1000:+.1f}") for name, was, now, change in changes[:args.top]], len(changes)))
    return report


def _mod(sessions, args):
    pattern = args.name.lower()
    wanted = [c for c in sessions[-1].mods.values()
              if fnmatch.fnmatchcase(c.name.lower(), pattern) or fnmatch.fnmatchcase(c.package_id, pattern)]
    if not wanted:
        raise StartupError(f'No mod in the newest launch matches "{args.name}".')
    report = Report(f"RimWorld start-up: {args.name}", [NOISE_NOTE])
    for cost in sorted(wanted, key=lambda c: (-c.milliseconds, c.package_id))[:args.top]:
        rows = [(s.id, seconds(s.mods[cost.package_id].milliseconds)) for s in reversed(sessions) if cost.package_id in s.mods]
        report.section(f"{cost.name} ({cost.package_id})", Table(["Launch", "Cost (s)"], rows[:args.top], len(rows)),
                       Table(["Where the newest launch spent it", "Seconds"],
                             [(m, seconds(v)) for m, v in cost.metrics[:args.top]], len(cost.metrics)))
    return report


def main(argv=None, settings_file=None, environ=None, out=None):
    out = out or sys.stdout
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or (argv[0] not in REPORTS and argv[0] not in ("-h", "--help")):
        argv.insert(0, "summary")
    try:
        args = _parser().parse_args(argv)
    except SystemExit as stop:
        return EXIT_USAGE if stop.code else EXIT_OK
    settings_file = args.settings or settings_file
    redact = keep if args.no_redact else home_redactor()
    code = EXIT_OK
    try:
        folder = Path(args.sessions) if args.sessions else paths.config_path(args.config, environ, settings_file).parent / SESSIONS_FOLDER
        sessions, unreadable = read_sessions(folder)
        if not sessions:
            raise StartupError(f"No sessions could be read in {folder}.")
        if args.report == "compare":
            report = _compare(sessions, args)
        elif args.report == "mod":
            report = _mod(sessions, args)
        else:
            report = _summary(sessions, unreadable, args.top)
    except StartupError as error:
        report, code = Report("rimworld-startup: error", [str(error)]), EXIT_FAILED
    print(json.dumps(render_json(report, redact), indent=2, ensure_ascii=False) if args.json
          else render_markdown(report, redact), file=out)
    return code
