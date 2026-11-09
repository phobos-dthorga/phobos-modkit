"""rimworld-readiness: which active mods are ready for a game version, and which would be likeliest to break if they are not.

    rimworld-readiness                       against the version the game is on now
    rimworld-readiness --game-version 1.8    against another version
    rimworld-readiness --all                 every mod that does not declare it, uncut
    rimworld-readiness --no-save             do not remember this run for the next comparison

Reads only: About.xml files, assemblies opened as files and never loaded or run, and the Steam tags already in the Workshop cache
(python -m phobos_modkit rimworld-workshop versions refreshes them). Each run says what changed since the last. A mod's
declaration is the author's statement, and its transpilers and bundles only say how closely it depends on the game: neither is a
test of whether it works.
"""
from __future__ import annotations

import argparse
from contextlib import closing
import json
from pathlib import Path
import sys

from ... import cache as derived
from ...report import Report, Table, envelope_text, home_redactor, keep, render_markdown
from ...steam import workshop
from ...steam.workshop_reports import version_tags
from . import loading, paths
from .mods import ModIndex, default_roots
from .patches import CACHE_FOLDER as PATCHES_FOLDER, INDEX_NAME as PATCHES_INDEX, PatchesError, mod_assemblies, refresh
from .readiness import assess, changes, riskiest, snapshot
from ...manifest import READS

EXIT_OK, EXIT_FAILED, EXIT_USAGE = 0, 1, 2
CACHE_FOLDER = "rimworld-readiness"
TRANSPILERS = """SELECT o.package_id, COUNT(*) FROM patches p JOIN owners o ON o.path = p.path
                 WHERE lower(p.kind) = 'transpiler' GROUP BY o.package_id"""
HEADERS = ["Load order", "Mod", "About.xml", "Steam tags", "Transpilers", "Prepatcher", "Asset bundles"]


def _parser():
    p = argparse.ArgumentParser(prog="rimworld-readiness", description=__doc__.split("\n\n")[0],
                                formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__.split("\n\n", 1)[1])
    p.add_argument("--game-version", help="the version to check against, like 1.8 (default: the one the game is on)")
    p.add_argument("--game", help="the RimWorld folder (else RIMWORLD_PATH, the settings file, Steam's default)")
    p.add_argument("--workshop", help="the Workshop content folder (else RIMWORLD_WORKSHOP_PATH, settings, beside the game)")
    p.add_argument("--config", help="the folder holding ModsConfig.xml (else RIMWORLD_CONFIG_PATH, settings, default)")
    p.add_argument("--cache", help="where indexes are kept (else PHOBOS_MODKIT_CACHE, settings, the temp folder)")
    p.add_argument("--settings", help="a JSON settings file with rimworldPath, workshopPath, rimworldConfigPath")
    p.add_argument("--top", type=int, default=25, help="rows per table (default 25)")
    p.add_argument("--all", action="store_true", help="list every mod that does not declare the version")
    p.add_argument("--no-save", action="store_true", help="do not remember this run")
    p.add_argument("--json", action="store_true", help="print JSON instead of Markdown")
    p.add_argument("--no-redact", action="store_true", help="show the home folder instead of ~")
    return p


def _steam_tags(cache, settings_file, environ, ids):
    """Workshop ID -> version tags, for the mods the Workshop cache already knows; it is never fetched here."""
    index = derived.folder(workshop.CACHE_FOLDER, cache, environ, settings_file) / workshop.INDEX_NAME
    if not Path(index).is_file():
        return {}
    with closing(derived.open_read_only(index)) as conn:
        found = {row[0]: row[1] for row in conn.execute("SELECT id, tags FROM item WHERE result = 1")}
    return {i: [t for t in version_tags(found[i]).split(", ") if t] for i in ids if i in found}


def _transpilers(index_file, found, environ):
    refresh(index_file, found, environ)
    with closing(derived.open_read_only(index_file)) as conn:
        return dict(conn.execute(TRANSPILERS).fetchall())


def _row(r):
    return (r["position"], r["name"], ", ".join(r["about"]), ", ".join(r["steam"]), r["transpilers"] or "",
            "yes" if r["prepatcher"] else "", "yes" if r["bundles"] else "")


def _report(rows, target, tags_known, workshop_mods, compared, top):
    missing = riskiest([r for r in rows if not r["declares"]])
    declaring = [r for r in rows if r["declares"]]
    report = Report(f"Mods against RimWorld {target}", [
        f"{len(declaring):,} of {len(rows):,} active mods declare {target}; {len(missing):,} do not.",
        f"With transpilers: {sum(1 for r in rows if r['transpilers']):,}. Mentioning Prepatcher: "
        f"{sum(1 for r in rows if r['prepatcher']):,}. With asset bundles: {sum(1 for r in rows if r['bundles']):,}.",
        "A declaration is the author's statement and these counts only say how closely a mod depends on the game: neither is a "
        "test of whether it works."])
    if tags_known < workshop_mods:
        report.lines.append(f"Steam tags are known for only {tags_known:,} of {workshop_mods:,} Workshop mods, so a mod declaring "
                            f"{target} only on Steam may be counted as not declaring it: run rimworld-workshop versions first.")
    report.section(f"Not declaring {target}, riskiest first", Table(HEADERS, [_row(r) for r in missing[:top]], len(missing)))
    risky = riskiest([r for r in declaring if r["transpilers"] or r["prepatcher"] or r["bundles"]])
    report.section(f"Declaring {target}, but closest to the game's insides",
                   Table(HEADERS, [_row(r) for r in risky[:top]], len(risky)))
    if compared is None:
        report.section("Since the last run", "This is the first run for this version, so there is nothing to compare.")
    elif compared:
        report.section("Since the last run", Table(["Mod", "What changed"], compared[:top], len(compared)))
    else:
        report.section("Since the last run", "Nothing changed.")
    return report


def main(argv=None, settings_file=None, environ=None, out=None, read_transpilers=None):
    out = out or sys.stdout
    try:
        args = _parser().parse_args(list(sys.argv[1:] if argv is None else argv))
    except SystemExit as stop:
        return EXIT_USAGE if stop.code else EXIT_OK
    settings_file = args.settings or settings_file
    redact = keep if args.no_redact else home_redactor()
    code = EXIT_OK
    try:
        game = paths.game_path(args.game, environ, settings_file)
        workshop_folder = paths.workshop_path(game, args.workshop, environ, settings_file)
        mods_config = Path(paths.config_path(args.config, environ, settings_file)) / "ModsConfig.xml"
        if not mods_config.is_file():
            raise PatchesError(f"No ModsConfig.xml at {mods_config}. Name its folder with --config.")
        version, _, ids = loading.read_mods_config(mods_config)
        target = args.game_version or version
        active = loading.resolve_active(ModIndex.scan(default_roots(game, workshop_folder)).mods, ids)
        found = mod_assemblies(active, version)
        assemblies = {}
        for entry, dll in found:
            assemblies.setdefault(entry.mod.package_id, []).append(dll)
        if read_transpilers is not None:
            transpilers = read_transpilers(found)
        else:
            transpilers = _transpilers(derived.folder(PATCHES_FOLDER, args.cache, environ, settings_file) / PATCHES_INDEX, found, environ)
        workshop_ids = [a.mod.workshop_id for a in active if a.mod is not None and a.mod.workshop_id]
        steam_tags = _steam_tags(args.cache, settings_file, environ, workshop_ids)
        rows = assess(active, assemblies, transpilers, steam_tags, target)
        now = snapshot(rows, target)
        last_file = Path(derived.folder(CACHE_FOLDER, args.cache, environ, settings_file)) / f"last-{target}.json"
        compared = None
        if last_file.is_file():
            compared = changes(json.loads(last_file.read_text(encoding="utf-8")), now)
        report = _report(rows, target, len(steam_tags), len(workshop_ids), compared, len(rows) if args.all else args.top)
        if not args.no_save:
            last_file.parent.mkdir(parents=True, exist_ok=True)
            last_file.write_text(json.dumps(now, indent=1, sort_keys=True), encoding="utf-8")
    except PatchesError as error:
        report, code = Report("rimworld-readiness: error", [str(error)]), EXIT_FAILED
    print(envelope_text("rimworld-readiness", report, redact) if args.json
          else render_markdown(report, redact), file=out)
    return code


MANIFEST = {"game": "rimworld", "parser": _parser, "effect": READS,
            "question": "Which of my mods are ready for this game version?"}
