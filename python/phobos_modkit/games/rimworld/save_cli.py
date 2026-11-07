"""rimworld-save: answer questions about a RimWorld save from an index, without reading the 300 MB file.

    python -m phobos_modkit rimworld-save                          summary of the newest save
    python -m phobos_modkit rimworld-save pawns --faction player   the colony's pawns
    python -m phobos_modkit rimworld-save things --def "Chunk*" --list
    python -m phobos_modkit rimworld-save hediffs --pawn Abbeson
    python -m phobos_modkit rimworld-save find ChunkA8061017       one thing and what holds it
    python -m phobos_modkit rimworld-save schema --under savegame/game/maps/li --depth 1
    python -m phobos_modkit rimworld-save sql "SELECT def, COUNT(*) FROM thing GROUP BY def"

The first question about a save indexes a frozen copy of it (about a second and a half for 300 MB with the
xml-index program built); later questions reuse the index until the save changes. The save is only ever read.
Options go after the report's name.
"""
from __future__ import annotations

import argparse
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import sys

from ... import cache as derived
from ...native import ToolMissing, build_tools
from ...report import home_redactor, keep, render_json, render_markdown
from . import paths
from . import save as saves
from . import save_reports as reports

EXIT_OK, EXIT_FAILED, EXIT_USAGE = 0, 1, 2
REPORTS = ("summary", "index", "schema", "things", "pawns", "hediffs", "find", "sql")


def _parser():
    common = argparse.ArgumentParser(add_help=False)
    c = common.add_argument_group("which save and where")
    c.add_argument("--save", help="a save's name (PG2) or path (default: the newest save)")
    c.add_argument("--saves", help="the Saves folder (else RIMWORLD_SAVES_PATH, the settings file, the default)")
    c.add_argument("--index", help="read this index file directly; no save needed")
    c.add_argument("--cache", help="where indexes are kept (else PHOBOS_MODKIT_CACHE, settings, the temp folder)")
    c.add_argument("--indexer", help="the xml-index program (else PHOBOS_XML_INDEX, this kit's release build)")
    c.add_argument("--build-indexer", action="store_true", help="build xml-index with cargo first")
    c.add_argument("--rebuild", action="store_true", help="index the save again even if the index is current")
    c.add_argument("--settings", help="a JSON settings file with rimworldSavesPath and modkitCachePath")
    o = common.add_argument_group("output")
    o.add_argument("--top", type=int, default=30, help="rows per table (default 30)")
    o.add_argument("--json", action="store_true", help="print JSON instead of Markdown")
    o.add_argument("--no-redact", action="store_true", help="show the home folder instead of ~")

    p = argparse.ArgumentParser(prog="rimworld-save", description=__doc__.split("\n\n")[0],
                                formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__.split("\n\n", 1)[1])
    sub = p.add_subparsers(dest="report", metavar="report")
    sub.add_parser("summary", parents=[common], help="game, maps, where things are, the colony, commonest things")
    sub.add_parser("index", parents=[common], help="index the save again now and say what the index holds")
    s = sub.add_parser("schema", parents=[common], help="element paths in the save, with counts")
    s.add_argument("--under", default="", help="only paths below this one, e.g. savegame/game/maps/li")
    s.add_argument("--depth", type=int, help="levels to show (default 3 from the root, 2 below --under)")
    t = sub.add_parser("things", parents=[common], help="things by def, or a list of them")
    t.add_argument("--def", dest="def_", help="def name; * and ? are wildcards")
    t.add_argument("--class", dest="cls", help="thing class, e.g. Pawn or *Building*")
    t.add_argument("--map", type=int, help="map position (0 is the first map)")
    t.add_argument("--place", help="map, world pawn, dead world pawn, mothballed world pawn, world object, elsewhere")
    held = t.add_mutually_exclusive_group()
    held.add_argument("--held", dest="held", action="store_const", const=True, help="only things another holds")
    held.add_argument("--loose", dest="held", action="store_const", const=False, help="only things nothing holds")
    t.add_argument("--list", action="store_true", help="one row per thing instead of counts by def")
    w = sub.add_parser("pawns", parents=[common], help="pawns with their faction, place and health")
    w.add_argument("--faction", help="player, or a faction's name or def")
    w.add_argument("--name", help="a pawn's name or ID")
    w.add_argument("--kind", help="pawn kind or race def")
    w.add_argument("--place", help="as for things")
    h = sub.add_parser("hediffs", parents=[common], help="hediffs by def, or one pawn's")
    h.add_argument("--pawn", help="a pawn's name or ID")
    h.add_argument("--def", dest="def_", help="hediff def; * and ? are wildcards")
    f = sub.add_parser("find", parents=[common], help="a thing by its ID, with what holds it")
    f.add_argument("thing_id", help="e.g. ChunkA8061017; * and ? are wildcards")
    q = sub.add_parser("sql", parents=[common], help="any read-only SQL query over the index")
    q.add_argument("query")
    return p


def _report(conn, args):
    top = args.top
    if args.report in ("summary", "index"):
        return reports.summary(conn, top=min(top, 10) if args.report == "summary" else 10)
    if args.report == "schema":
        return reports.schema(conn, args.under, args.depth, top)
    if args.report == "things":
        return reports.things(conn, args.def_, args.cls, args.map, args.place, args.held, args.list, top)
    if args.report == "pawns":
        return reports.pawns(conn, args.faction, args.name, args.kind, args.place, top)
    if args.report == "hediffs":
        return reports.hediffs(conn, args.pawn, args.def_, top)
    if args.report == "find":
        return reports.find(conn, args.thing_id, top)
    return reports.sql(conn, args.query, top)


def main(argv=None, settings_file=None, environ=None, out=None):
    out = out or sys.stdout
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or (argv[0].startswith("-") and argv[0] not in ("-h", "--help")):
        argv.insert(0, "summary")
    args = _parser().parse_args(argv)
    settings_file = args.settings or settings_file
    redact = keep if args.no_redact else home_redactor()

    try:
        if args.build_indexer:
            build_tools()
        built = None
        if args.index:
            index = Path(args.index)
            if not index.is_file():
                raise saves.SaveError(f"No index at {index}.")
            source = saves.read_meta(index).get("source", index.name)
        else:
            folder = paths.saves_path(args.saves, environ, settings_file)
            save = saves.find_save(folder, args.save)
            cache = derived.folder(saves.CACHE_FOLDER, args.cache, environ, settings_file)
            index, built = saves.ensure(save, cache, args.indexer, environ, args.rebuild or args.report == "index")
            source = save.name
        with closing(saves.open_read_only(index)) as conn:
            report = _report(conn, args)
    except (saves.SaveError, ToolMissing) as problem:
        print(redact(str(problem)), file=sys.stderr)
        return EXIT_USAGE
    except sqlite3.Error as problem:
        print(f"The query failed: {problem}", file=sys.stderr)
        return EXIT_FAILED

    if built is not None:
        rows = ", ".join(f"{n:,} {t}" for t, n in built.rows.items() if n and not t.startswith("mod_"))
        provenance = (f"Index of {source}, built now from a frozen copy in {built.seconds:.1f} s "
                      f"({built.elements:,} elements; {rows}).")
    else:
        provenance = f"Index of {source}, reused: the save and the schema have not changed since it was built."
    report.lines.insert(0, provenance)

    if args.json:
        data = {"save": source, "index": redact(str(index)), "built": built is not None,
                "report": render_json(report, redact)}
        out.write(json.dumps(data, indent=1, ensure_ascii=False, default=str) + "\n")
    else:
        out.write(render_markdown(report, redact) + "\n")
    return EXIT_OK
