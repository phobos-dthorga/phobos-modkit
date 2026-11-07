"""rimworld-defs: which active mods define and patch each RimWorld Def, from an index of the installed game.

    python -m phobos_modkit rimworld-defs                         summary: types, names several mods define, problems
    python -m phobos_modkit rimworld-defs who Gun_Revolver        every definition and every patch naming it
    python -m phobos_modkit rimworld-defs show Gun_Revolver       its XML as written, with each parent up the chain
    python -m phobos_modkit rimworld-defs list --type ThingDef --mod "Vanilla*"
    python -m phobos_modkit rimworld-defs patches --target "Gun_*"
    python -m phobos_modkit rimworld-defs mods                    the active mods in load order
    python -m phobos_modkit rimworld-defs sql "SELECT def_type, COUNT(*) FROM def WHERE wins GROUP BY 1"

The first question indexes the active mods (about 8 s for 340 mods); later questions reuse the index until the mod
list, a Workshop item, the game or a local mod changes. Reads the game's files only. Options go after the report.
"""
from __future__ import annotations

import argparse
from contextlib import closing
import json
import sqlite3
import sys

from ... import cache as derived
from ...report import home_redactor, keep, render_json, render_markdown
from . import defs
from . import defs_reports as reports
from . import paths

EXIT_OK, EXIT_FAILED, EXIT_USAGE = 0, 1, 2


def _parser():
    common = argparse.ArgumentParser(add_help=False)
    c = common.add_argument_group("where the game is")
    c.add_argument("--game", help="the RimWorld folder (else RIMWORLD_PATH, the settings file, Steam's default)")
    c.add_argument("--workshop", help="the Workshop content folder (else RIMWORLD_WORKSHOP_PATH, settings, beside "
                                      "the game)")
    c.add_argument("--config", help="the folder holding ModsConfig.xml (else RIMWORLD_CONFIG_PATH, settings, default)")
    c.add_argument("--cache", help="where the index is kept (else PHOBOS_MODKIT_CACHE, settings, the temp folder)")
    c.add_argument("--settings", help="a JSON settings file with rimworldPath, workshopPath, rimworldConfigPath")
    c.add_argument("--rebuild", action="store_true", help="index the mods again even if the index is current")
    o = common.add_argument_group("output")
    o.add_argument("--top", type=int, default=30, help="rows per table (default 30)")
    o.add_argument("--json", action="store_true", help="print JSON instead of Markdown")
    o.add_argument("--no-redact", action="store_true", help="show the home folder instead of ~")

    p = argparse.ArgumentParser(prog="rimworld-defs", description=__doc__.split("\n\n")[0],
                                formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__.split("\n\n", 1)[1])
    sub = p.add_subparsers(dest="report", metavar="report")
    sub.add_parser("summary", parents=[common], help="Def types, names several mods define, mods, problems")
    sub.add_parser("index", parents=[common], help="index the mods again now, then the summary")
    m = sub.add_parser("mods", parents=[common], help="the active mods in load order, with their Defs and patches")
    m.add_argument("--name", help="a mod's name or package ID")
    w = sub.add_parser("who", parents=[common], help="every definition of a Def and every patch naming it")
    w.add_argument("name", help="a defName or abstract Name; * and ? are wildcards")
    s = sub.add_parser("show", parents=[common], help="a Def's XML as written, then each parent up the chain")
    s.add_argument("name", help="a defName or abstract Name")
    s.add_argument("--type", help="the Def type, when several types use the name")
    lst = sub.add_parser("list", parents=[common], help="Defs by type, mod, name or parent")
    lst.add_argument("--type", help="Def type, e.g. ThingDef or *Def")
    lst.add_argument("--mod", help="mod name or package ID")
    lst.add_argument("--name", help="defName or abstract Name")
    lst.add_argument("--parent", help="ParentName")
    lst.add_argument("--all", action="store_true", help="also replaced, abstract and unloaded definitions")
    pt = sub.add_parser("patches", parents=[common], help="patch operations by target, mod, type or operation")
    pt.add_argument("--target", help="a defName the xpath names")
    pt.add_argument("--mod", help="mod name or package ID")
    pt.add_argument("--type", help="the Def type the xpath selects")
    pt.add_argument("--operation", help="operation class, e.g. *Replace*")
    q = sub.add_parser("sql", parents=[common], help="any read-only SQL query over the index")
    q.add_argument("query")
    return p


def _report(conn, args):
    top = args.top
    if args.report in ("summary", "index"):
        return reports.summary(conn, top=min(top, 10))
    if args.report == "mods":
        return reports.mods(conn, args.name, top)
    if args.report == "who":
        return reports.who(conn, args.name, top)
    if args.report == "show":
        return reports.show(conn, args.name, args.type)
    if args.report == "list":
        return reports.list_defs(conn, args.type, args.mod, args.name, args.parent, args.all, top)
    if args.report == "patches":
        return reports.patches(conn, args.target, args.mod, args.type, args.operation, top)
    return reports.sql(conn, args.query, top)


def main(argv=None, settings_file=None, environ=None, out=None):
    out = out or sys.stdout
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or (argv[0].startswith("-") and argv[0] not in ("-h", "--help")):
        argv.insert(0, "summary")
    args = _parser().parse_args(argv)
    settings_file = args.settings or settings_file
    redact = keep if args.no_redact else home_redactor()
    game = paths.game_path(args.game, environ, settings_file)
    install = defs.Install(game, paths.workshop_path(game, args.workshop, environ, settings_file),
                           paths.config_path(args.config, environ, settings_file))
    cache = derived.folder(defs.CACHE_FOLDER, args.cache, environ, settings_file)
    try:
        index, built = defs.ensure(install, cache, args.rebuild or args.report == "index")
        with closing(derived.open_read_only(index)) as conn:
            report = _report(conn, args)
    except defs.DefsError as problem:
        print(redact(str(problem)), file=sys.stderr)
        return EXIT_USAGE
    except sqlite3.Error as problem:
        print(f"The query failed: {problem}", file=sys.stderr)
        return EXIT_FAILED

    if built is not None:
        provenance = (f"Index of the active mods, built now in {built.seconds:.1f} s ({built.mods:,} mods, "
                      f"{built.defs:,} Defs, {built.patches:,} patch operations, {built.problems:,} problems).")
    else:
        provenance = "Index of the active mods, reused: the mod list, the Workshop, the game and local mods are unchanged."
    report.lines.insert(0, provenance)
    if args.json:
        out.write(json.dumps({"index": redact(str(index)), "built": built is not None,
                              "report": render_json(report, redact)}, indent=1, ensure_ascii=False, default=str) + "\n")
    else:
        out.write(render_markdown(report, redact) + "\n")
    return EXIT_OK
