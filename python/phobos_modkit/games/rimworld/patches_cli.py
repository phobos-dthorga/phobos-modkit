"""rimworld-patches: which active mods patch which methods with Harmony, read from their assemblies' metadata.

    rimworld-patches                        counts, and the methods the most mods patch
    rimworld-patches who "Pawn.Kill"        every patch on a method (Type.Method, Method, wildcards * and ?)
    rimworld-patches mod "Vehicle Framework"   what one mod patches (name or package ID, wildcards)
    rimworld-patches hotspots               methods several mods patch, with prefixes that may stop the original

Reads only: each DLL is opened as a file and never loaded or run. The first run builds the kit's C# reader (needs the
.NET SDK) and reads every active mod's assemblies; later runs read only the ones that changed.
"""
from __future__ import annotations

import argparse
import json
from contextlib import closing
from pathlib import Path
import sys

from ...report import Report, Table, home_redactor, keep, render_json, render_markdown
from ... import cache as derived
from ...query import like
from . import loading, paths
from .mods import ModIndex, default_roots
from .patches import CACHE_FOLDER, INDEX_NAME, PatchesError, mod_assemblies, refresh

EXIT_OK, EXIT_FAILED, EXIT_USAGE = 0, 1, 2
REPORTS = ("summary", "who", "mod", "hotspots")

JOINED = """SELECT o.position, o.mod, o.package_id, p.source, p.kind, p.target_type, p.target_member, p.method_type,
                   p.patch_class, p.patch_method, p.can_skip, p.priority, p.note
            FROM patches p JOIN owners o ON o.path = p.path"""


def _parser():
    common = argparse.ArgumentParser(add_help=False)
    c = common.add_argument_group("where the game is")
    c.add_argument("--game", help="the RimWorld folder (else RIMWORLD_PATH, the settings file, Steam's default)")
    c.add_argument("--workshop", help="the Workshop content folder (else RIMWORLD_WORKSHOP_PATH, settings, beside the game)")
    c.add_argument("--config", help="the folder holding ModsConfig.xml (else RIMWORLD_CONFIG_PATH, settings, default)")
    c.add_argument("--cache", help="where the index is kept (else PHOBOS_MODKIT_CACHE, settings, the temp folder)")
    c.add_argument("--settings", help="a JSON settings file with rimworldPath, workshopPath, rimworldConfigPath")
    c.add_argument("--rebuild", action="store_true", help="read every assembly again")
    o = common.add_argument_group("output")
    o.add_argument("--top", type=int, default=25, help="rows per table (default 25)")
    o.add_argument("--json", action="store_true", help="print JSON instead of Markdown")
    o.add_argument("--no-redact", action="store_true", help="show the home folder instead of ~")
    p = argparse.ArgumentParser(prog="rimworld-patches", description=__doc__.split("\n\n")[0],
                                formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__.split("\n\n", 1)[1])
    sub = p.add_subparsers(dest="report", metavar="report")
    sub.add_parser("summary", parents=[common], help="counts and the most-patched methods")
    w = sub.add_parser("who", parents=[common], help="every patch on a method")
    w.add_argument("target", help="Type.Method, Namespace.Type.Method or Method; * and ? are wildcards")
    m = sub.add_parser("mod", parents=[common], help="what one mod patches")
    m.add_argument("name", help="a mod's name or package ID; * and ? are wildcards")
    sub.add_parser("hotspots", parents=[common], help="methods several mods patch")
    return p


def _target(row):
    target_type, member, method_type = row[5], row[6], row[7]
    text = f"{target_type}.{member}" if target_type else (member or "(worked out at run time)")
    return text + (f" ({method_type.lower()})" if method_type and method_type != "Normal" else "")


def _flags(row):
    flags = []
    if row[10]:
        flags.append("may skip the original")
    if row[11] is not None and row[11] >= 0:
        flags.append(f"priority {row[11]}")
    if row[12]:
        flags.append(row[12])
    return "; ".join(flags)


def target_filter(text):
    """SQL and parameters matching a target written as Member, Type.Member or Namespace.Type.Member."""
    if "." not in text:
        return "p.target_member LIKE ? ESCAPE '\\'", [like(text)]
    owner, member = text.rsplit(".", 1)
    return ("p.target_member LIKE ? ESCAPE '\\' AND (p.target_type LIKE ? ESCAPE '\\' OR p.target_type LIKE ? ESCAPE '\\')",
            [like(member), like(owner), "%." + like(owner)])


def who_report(conn, args):
    sql, params = target_filter(args.target)
    rows = conn.execute(JOINED + f" WHERE {sql} ORDER BY p.target_type, p.target_member, o.position, p.kind", params).fetchall()
    mods = sorted({r[1] for r in rows})
    report = Report(f"rimworld-patches who {args.target}")
    report.lines.append(f"{len(rows)} patches from {len(mods)} mods." if rows else
                        f"No active mod patches {args.target} through Harmony (as far as the metadata shows).")
    if rows:
        report.section("Patches, in load order", Table(
            ["#", "Mod", "Target", "Kind", "Patch method", "Notes"],
            [[r[0], r[1], _target(r), r[4], f"{r[8]}.{r[9]}" if r[9] else r[8], _flags(r)] for r in rows[:args.top]],
            total=len(rows)))
    return report


def mod_report(conn, args):
    pattern = like(args.name)
    rows = conn.execute(JOINED + " WHERE o.mod LIKE ? ESCAPE '\\' OR o.package_id LIKE ? ESCAPE '\\'"
                        " ORDER BY o.position, p.target_type, p.target_member", (pattern, pattern.lower())).fetchall()
    report = Report(f"rimworld-patches mod {args.name}")
    report.lines.append(f"{len(rows)} patches." if rows else f"No patches from a mod matching {args.name}.")
    if rows:
        report.section("Patches", Table(["Mod", "Target", "Kind", "Patch method", "Notes"],
                                        [[r[1], _target(r), r[4], f"{r[8]}.{r[9]}" if r[9] else r[8], _flags(r)]
                                         for r in rows[:args.top]], total=len(rows)))
    return report


HOTSPOTS = """SELECT p.target_type, p.target_member, p.method_type, COUNT(DISTINCT o.package_id) AS mods, COUNT(*) AS patches,
                     SUM(CASE WHEN p.can_skip = 1 THEN 1 ELSE 0 END) AS skippers, GROUP_CONCAT(DISTINCT o.mod)
              FROM patches p JOIN owners o ON o.path = p.path
              WHERE p.target_type != '' AND p.target_member != ''
              GROUP BY p.target_type, p.target_member, p.method_type
              HAVING mods >= ? ORDER BY mods DESC, skippers DESC, p.target_type, p.target_member"""


def hotspot_rows(conn, minimum, top):
    rows = conn.execute(HOTSPOTS, (minimum,)).fetchall()
    shown = []
    for target_type, member, method_type, mods, patches, skippers, names in rows[:top]:
        names = sorted(set((names or "").split(",")))
        listed = ", ".join(names[:4]) + (f" (+{len(names) - 4})" if len(names) > 4 else "")
        shown.append([f"{target_type}.{member}" + (f" ({method_type.lower()})" if method_type not in ("", "Normal") else ""),
                      mods, patches, skippers, listed])
    return shown, len(rows)


def summary_report(conn, read, kept, built):
    report = Report("rimworld-patches")
    assemblies = conn.execute("SELECT COUNT(*) FROM owners").fetchone()[0]
    mods = conn.execute("SELECT COUNT(DISTINCT package_id) FROM owners").fetchone()[0]
    errors = conn.execute("SELECT COUNT(*) FROM assemblies WHERE error != ''").fetchone()[0]
    total = conn.execute("SELECT COUNT(*) FROM patches p JOIN owners o ON o.path = p.path").fetchone()[0]
    by_source = dict(conn.execute("SELECT p.source, COUNT(*) FROM patches p JOIN owners o ON o.path = p.path GROUP BY p.source"))
    report.lines.append(f"{total} Harmony patches in {assemblies} assemblies of {mods} active mods: "
                        f"{by_source.get('attribute', 0)} declared by attributes, {by_source.get('call', 0)} by harmony.Patch calls.")
    report.lines.append(f"Read now: {read} assemblies; {kept} unchanged since last time"
                        + ("; the reader was built first." if built else ".")
                        + (f" {errors} could not be read (native DLLs or damaged files)." if errors else ""))
    rows, count = hotspot_rows(conn, 3, 15)
    report.section("Methods patched by three or more mods", Table(["Method", "Mods", "Patches", "May skip", "Mods (some)"], rows,
                                                                 total=count, more="run hotspots --top N to see more"),
                   "\"May skip\" counts prefixes returning bool: each may stop the original and every later prefix.")
    return report


def main(argv=None, settings_file=None, environ=None, out=None, run=None):
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
        game = paths.game_path(args.game, environ, settings_file)
        workshop = paths.workshop_path(game, args.workshop, environ, settings_file)
        config = paths.config_path(args.config, environ, settings_file)
        mods_config = Path(config) / "ModsConfig.xml"
        if not mods_config.is_file():
            raise PatchesError(f"No ModsConfig.xml in {config}. Name the folder with --config.")
        version, _, ids = loading.read_mods_config(mods_config)
        index_mods = ModIndex.scan(default_roots(game, workshop))
        active = loading.resolve_active(index_mods.mods, ids)
        found = mod_assemblies(active, version)
        index = derived.folder(CACHE_FOLDER, args.cache, environ, settings_file) / INDEX_NAME
        options = {"run": run} if run is not None else {}
        read, kept, built = refresh(index, found, environ, rebuild=args.rebuild, **options)
        with closing(derived.open_read_only(index)) as conn:
            if args.report == "who":
                report = who_report(conn, args)
            elif args.report == "mod":
                report = mod_report(conn, args)
            elif args.report == "hotspots":
                rows, count = hotspot_rows(conn, 2, args.top)
                report = Report("rimworld-patches hotspots", [f"{count} methods are patched by two or more active mods."])
                report.section("Methods", Table(["Method", "Mods", "Patches", "May skip", "Mods (some)"], rows, total=count))
            else:
                report = summary_report(conn, read, kept, built)
            if args.report != "summary" and read:
                report.lines.append(f"Read {read} changed assemblies first.")
    except PatchesError as error:
        report, code = Report("rimworld-patches: error", [str(error)]), EXIT_FAILED
    print(json.dumps(render_json(report, redact), indent=2, ensure_ascii=False) if args.json
          else render_markdown(report, redact), file=out)
    return code
