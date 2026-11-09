"""rimworld-workshop: Workshop research for RimWorld mods, named as you know them.

    python -m phobos_modkit rimworld-workshop report "Useful Marks" smashphil.vehicleframework 2023507013
    python -m phobos_modkit rimworld-workshop details "Vanilla*"
    python -m phobos_modkit rimworld-workshop comments "Field Tents"
    python -m phobos_modkit rimworld-workshop versions        every active Workshop mod's declared versions
    python -m phobos_modkit rimworld-workshop collection 3497770083 --grep "*tank*"   a collection's items

A mod may be named by its Workshop ID or URL, its package ID, or its name (* and ? are wildcards); names and
package IDs are looked up among the installed Workshop mods. Comment problem flags include the game's version from
ModsConfig.xml unless --game-version says otherwise. Everything else is as for steam-workshop.
"""
from __future__ import annotations

from fnmatch import fnmatch
import sys

from ...report import Report, Table
from ...steam import workshop
from ...steam import workshop_cli as core
from ...steam.workshop_reports import date_text, version_tags
from . import paths
from .loading import read_mods_config, resolve_active
from .mods import ModIndex
from ...manifest import ONLINE, READS


def _extra(sub, common):
    v = sub.add_parser("versions", parents=[common], help="the active Workshop mods' declared versions against the "
                                                          "game's (details only, one quick request per 100 mods)")
    for option, text in (("--game", "the RimWorld folder"), ("--workshop", "the Workshop content folder"),
                         ("--config", "the folder holding ModsConfig.xml")):
        v.add_argument(option, help=text)
    for name in ("report", "details", "comments", "collection"):
        s = sub.choices[name]
        s.add_argument("--game", help="the RimWorld folder (for finding the Workshop folder)")
        s.add_argument("--workshop", help="the Workshop content folder, where mods are looked up by name")
        s.add_argument("--config", help="the folder holding ModsConfig.xml (for the game's version)")


def _installed(workshop_folder):
    return [m for m in ModIndex.scan([("Workshop", workshop_folder)]).mods if m.workshop_id]


def resolve(targets, installed):
    """(Workshop IDs, [targets nothing matched]) for IDs, URLs, package IDs or names (wildcards allowed)."""
    ids, unknown = [], []
    for target in targets:
        found = workshop.item_id(target)
        if found:
            ids.append(found)
            continue
        wanted = target.lower()
        matches = [m.workshop_id for m in installed if m.package_id == wanted or fnmatch(m.name.lower(), wanted)]
        if matches:
            ids += matches
        else:
            unknown.append(target)
    return list(dict.fromkeys(ids)), unknown


def _versions_report(conn, game_version, active, top):
    report = Report("Active Workshop mods against the game's version")
    rows = []
    marks = ",".join("?" * len(active))
    found = {r[0]: r[1:] for r in conn.execute(
        f"SELECT id, result, time_updated, tags FROM item WHERE id IN ({marks})", [a[2] for a in active])} if active else {}
    missing_details = []
    for position, name, item_id in active:
        if item_id not in found or found[item_id][0] != 1:
            missing_details.append(name)
            continue
        _, updated, tags = found[item_id]
        versions = version_tags(tags)
        if game_version not in versions.split(", "):
            rows.append((position, name, item_id, date_text(updated), versions))
    declared = len(active) - len(rows) - len(missing_details)
    report.lines.append(f"RimWorld {game_version}: {declared:,} of {len(active):,} active Workshop mods declare it in "
                        f"their Steam tags; {len(rows):,} do not.")
    report.lines.append("A mod without the tag may still work: tags are the author's statement, not a test.")
    report.section(f"Not declaring {game_version}", Table(["Load order", "Mod", "ID", "Updated", "Versions"], rows[:top],
                                                          len(rows)))
    if missing_details:
        report.section("No details from Steam", "Removed, private or not fetched: " + ", ".join(missing_details) + ".")
    return report


def _parser():
    return core.build_parser("rimworld-workshop", __doc__.split("\n\n")[0], __doc__.split("\n\n", 1)[1],
                             "a mod's name, package ID, Workshop ID or URL", _extra)


def main(argv=None, settings_file=None, environ=None, out=None, post=None, pacer=None, clock=None):
    argv = core.normalise(argv)
    parser = _parser()
    if not argv:
        parser.print_help()
        return core.EXIT_USAGE
    args = parser.parse_args(argv)
    settings = args.settings or settings_file
    game = paths.game_path(getattr(args, "game", None), environ, settings)
    workshop_folder = paths.workshop_path(game, getattr(args, "workshop", None), environ, settings)
    config = paths.config_path(getattr(args, "config", None), environ, settings) / "ModsConfig.xml"
    game_version, active_ids = "", []
    if config.is_file():
        game_version, _, active_ids = read_mods_config(config)
    if not args.game_version and game_version:
        args.game_version = game_version

    prepare = None
    if args.report == "versions":
        if not active_ids:
            print(f"No ModsConfig.xml at {config}. Name its folder with --config.", file=sys.stderr)
            return core.EXIT_USAGE
        active = [(a.position, a.mod.name, a.mod.workshop_id) for a in resolve_active(_installed(workshop_folder),
                                                                                   active_ids)
                  if a.mod is not None and a.mod.workshop_id]
        ids = [a[2] for a in active]
        prepare = lambda conn, _: _versions_report(conn, args.game_version, active, args.top)
    elif args.report == "sql":
        ids = []
    elif args.report == "collection":
        ids = [workshop.item_id(t) for t in args.targets]
        if None in ids:
            print("A collection is named by its Workshop ID or URL.", file=sys.stderr)
            return core.EXIT_USAGE
        ids = list(dict.fromkeys(ids))
    else:
        needs_names = any(workshop.item_id(t) is None for t in args.targets)
        ids, unknown = resolve(args.targets, _installed(workshop_folder) if needs_names else [])
        if unknown:
            print(f"No installed Workshop mod matches: {', '.join(unknown)}. Name it by Workshop ID or URL instead.",
                  file=sys.stderr)
            return core.EXIT_USAGE
    return core.run(args, ids, settings_file, environ, out, post, pacer, clock, prepare, "rimworld-workshop")


MANIFEST = {"game": "rimworld", "parser": _parser, "effect": ONLINE,
            "reports": {"sql": {"effect": READS}}}
