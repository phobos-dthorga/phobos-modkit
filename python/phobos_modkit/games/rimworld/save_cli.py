"""rimworld-save: answer questions about a RimWorld save from an index, without reading the 300 MB file.

    python -m phobos_modkit rimworld-save                          summary of the newest save
    python -m phobos_modkit rimworld-save pawns --faction player   the colony's pawns
    python -m phobos_modkit rimworld-save things --def "Chunk*" --list
    python -m phobos_modkit rimworld-save hediffs --pawn Abbeson
    python -m phobos_modkit rimworld-save find ChunkA8061017       one thing and what holds it
    python -m phobos_modkit rimworld-save schema --under savegame/game/maps/li --depth 1
    python -m phobos_modkit rimworld-save grid --map 0                every grid layer of a map, counted
    python -m phobos_modkit rimworld-save grid --kind gas --render    one layer, with a text picture
    python -m phobos_modkit rimworld-save grid --at 120,85            every layer at one cell, and what stands there
    python -m phobos_modkit rimworld-save world --faction "Example*"   one faction's settlements and sites
    python -m phobos_modkit rimworld-save components --class "*Wars*"  a mod's saved state, value by value
    python -m phobos_modkit rimworld-save planet --near "Red Brook"   world-map pollution, patch by patch and around one place
    python -m phobos_modkit rimworld-save planet --near 1234 --history "Autosave-*"   when it arrived, save by save
    python -m phobos_modkit rimworld-save diff Autosave-3             what changed since another save
    python -m phobos_modkit rimworld-save sql "SELECT def, COUNT(*) FROM thing GROUP BY def"

The first question about a save indexes a frozen copy of it (about a second and a half for 300 MB with the
xml-index program built); later questions reuse the index until the save changes. The save is only ever read.
Options go after the report's name.
"""
from __future__ import annotations

import argparse
from contextlib import closing
import fnmatch
from pathlib import Path
import sqlite3
import sys

from ... import cache as derived
from ...native import ToolMissing, build_tools
from ...report import envelope_text, home_redactor, keep, render_markdown
from . import defs as def_index
from . import grids
from . import paths
from . import planet
from . import planet_reports
from . import save as saves
from . import save_diff
from . import save_maps
from . import save_reports as reports
from ...manifest import READS

EXIT_OK, EXIT_FAILED, EXIT_USAGE = 0, 1, 2
REPORTS = ("summary", "index", "schema", "things", "pawns", "hediffs", "find", "world", "components", "grid", "planet",
           "diff", "sql")


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
    o = sub.add_parser("world", parents=[common], help="world objects: settlements, sites, caravans, by faction")
    o.add_argument("--def", dest="def_", help="world object def or class, e.g. Settlement; * and ? are wildcards")
    o.add_argument("--faction", help="a faction's name or def")
    o.add_argument("--name", help="a world object's name")
    o.add_argument("--id", type=int, help="one world object's values in full, by its ID")
    k = sub.add_parser("components", parents=[common], help="the game's, world's and maps' components (mods' saved "
                                                           "state) and the values inside them")
    k.add_argument("--class", dest="cls", help="component class, e.g. *RimPacts*; lists its values")
    k.add_argument("--path", help="path inside the component, e.g. spectate/*")
    k.add_argument("--value", help="a value, e.g. Faction_12")
    k.add_argument("--map", type=int, help="map position, for map components")
    g = sub.add_parser("grid", parents=[common], help="a map's grids: terrain, roofs, gas, fog, snow, pollution, "
                                                     "deep resources")
    g.add_argument("--map", type=int, help="map position (default: the map the save was on)")
    g.add_argument("--kind", choices=sorted(grids.KINDS), help="one layer in full")
    g.add_argument("--render", action="store_true", help="with --kind: a text picture of the layer, north up")
    g.add_argument("--gas", choices=[n for n, _ in grids.GAS_TYPES], help="with --kind gas --render: one gas only")
    g.add_argument("--columns", type=int, default=100, help="width of the picture in characters (default 100)")
    g.add_argument("--at", metavar="X,Z", help="every layer at one cell, and the things standing there")
    g.add_argument("--area", metavar="X1,Z1,X2,Z2", help="count only cells inside this rectangle")
    for option, text in (("--game", "the RimWorld folder, for naming terrain and roofs"),
                         ("--workshop", "the Workshop content folder, for naming"),
                         ("--config", "the folder holding ModsConfig.xml, for naming")):
        g.add_argument(option, help=text)
    g.add_argument("--no-names", action="store_true", help="show Defs as numbers; do not read the installed mods")
    l = sub.add_parser("planet", parents=[common], help="pollution on the world map: patch by patch, around a place, "
                                                        "against another save, or across saves")
    l.add_argument("--near", help="a world object's name, or a tile number: rings of tiles around it")
    l.add_argument("--hops", type=int, default=8, help="with --near or --history: tiles out from the place (default 8)")
    l.add_argument("--compare", metavar="SAVE", help="what changed against another save, usually an earlier one")
    l.add_argument("--history", metavar="PATTERN", nargs="?", const="*", help="with --near: every save of this world "
                   "by in-game day, optionally only saves matching a pattern such as Autosave-*")
    d = sub.add_parser("diff", parents=[common], help="what changed between this save and another")
    d.add_argument("other", help="the save to compare with (a name or path), usually an earlier one")
    d.add_argument("--faction", default="player", help="whose pawns and hediffs to compare: player (default), any, "
                                                       "or a faction's name or def")
    d.add_argument("--component", help="compare only components whose class matches, e.g. *RimPacts*")
    q = sub.add_parser("sql", parents=[common], help="any read-only SQL query over the index")
    q.add_argument("query")
    return p


def _numbers(text, count, option):
    try:
        values = tuple(int(v) for v in text.split(","))
    except ValueError:
        values = ()
    if len(values) != count:
        raise saves.SaveError(f"{option} takes {count} whole numbers separated by commas, such as "
                              + ",".join(str(10 * (i + 1)) for i in range(count)) + ".")
    return values


def _names(args, environ, settings_file):
    """Def names for grids from the Def index of the installed game, or none (with the reason)."""
    if args.no_names:
        return grids.Names(), None
    try:
        game = paths.game_path(args.game, environ, settings_file)
        install = def_index.Install(game, paths.workshop_path(game, args.workshop, environ, settings_file),
                                    paths.config_path(args.config, environ, settings_file))
        index, _ = def_index.ensure(install, derived.folder(def_index.CACHE_FOLDER, args.cache, environ, settings_file))
    except (def_index.DefsError, OSError) as problem:
        return grids.Names(), f"Defs are shown as numbers: the installed mods could not be read ({problem})."
    return grids.Names(derived.open_read_only(index)), None


def _planet(conn, args, environ, settings_file, cache, top):
    folder = paths.saves_path(args.saves, environ, settings_file)
    try:
        if args.history is not None:
            if not args.near:
                raise saves.SaveError("--history needs --near, the place to follow.")
            tile, name = planet_reports.find_place(conn, args.near)
            source = saves.find_save(folder, args.save)
            _, seed, _ = planet.read_save(source)
            chosen = [p for p in saves.saves_in(folder) if fnmatch.fnmatch(p.stem.lower(), args.history.lower())]
            return planet_reports.report_history(chosen, tile, name, args.hops, cache, seed, top)
        compare = None
        if args.compare:
            other = saves.find_save(folder, args.compare)
            values = planet.read_save(other)[2]
            if values is None:
                raise saves.SaveError(f"{other.name} holds no planet pollution layer.")
            compare = (values, other.name)
        return planet_reports.report_planet(conn, cache, args.near, args.hops, compare, top)
    except planet.PlanetError as problem:
        raise saves.SaveError(str(problem)) from None


def _report(conn, args, environ=None, settings_file=None, other=None):
    top = args.top
    if args.report == "grid":
        names, note = _names(args, environ, settings_file)
        try:
            report = save_maps.grid(conn, args.map, args.kind, names, args.render,
                                    _numbers(args.at, 2, "--at") if args.at else None,
                                    _numbers(args.area, 4, "--area") if args.area else None,
                                    args.gas, args.columns, top)
        except grids.GridError as problem:
            raise saves.SaveError(str(problem)) from None
        finally:
            if names.conn is not None:
                names.conn.close()
        if note:
            report.lines.append(note)
        return report
    if args.report == "planet":
        cache = derived.folder(planet.CACHE_FOLDER, args.cache, environ, settings_file)
        return _planet(conn, args, environ, settings_file, cache, top)
    if args.report == "diff":
        other_index, other_name, this_name = other
        return save_diff.diff(conn, Path(other_index).resolve().as_uri() + "?mode=ro", other_name, this_name,
                              args.faction, top, args.component)
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
    if args.report == "world":
        return reports.world(conn, args.def_, args.faction, args.name, top, args.id)
    if args.report == "components":
        return reports.components(conn, args.cls, args.path, args.value, args.map, top)
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
        other = None
        if args.report == "diff":
            folder = paths.saves_path(args.saves, environ, settings_file)
            other_save = saves.find_save(folder, args.other)
            cache = derived.folder(saves.CACHE_FOLDER, args.cache, environ, settings_file)
            other_index, _ = saves.ensure(other_save, cache, args.indexer, environ, args.rebuild)
            other = (other_index, other_save.name, source)
        with closing(saves.open_read_only(index)) as conn:
            report = _report(conn, args, environ, settings_file, other)
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
        out.write(envelope_text("rimworld-save", report, redact,
                                {"save": source, "index": str(index), "built": built is not None}) + "\n")
    else:
        out.write(render_markdown(report, redact) + "\n")
    return EXIT_OK


MANIFEST = {"game": "rimworld", "parser": _parser, "effect": READS}
