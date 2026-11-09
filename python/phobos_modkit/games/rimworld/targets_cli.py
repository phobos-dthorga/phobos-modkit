"""rimworld-targets: does every member our C# names by string still exist in the game and the mods?

    rimworld-targets --root .                          check src/**/*.cs against the game and the active mods
    rimworld-targets --root . --assemblies "mods/*/1.7/Assemblies/*.dll"   read these first (a fresh build of our own)
    rimworld-targets --root . --all                    list what passed too

Reads only: each DLL is opened as a file and never loaded or run. The compiler checks typeof and nameof; this checks what
it cannot: Harmony patches and reflected lookups named in strings, the overloads they ask for, and the parameters Harmony
fills at run time (__instance, __result, ___field). Exit 1 when something named no longer exists.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

from ...report import Bullets, Report, Table, home_redactor, keep, render_json, render_markdown
from ...targets import Listing, check_targets, scan_tree
from . import loading, paths
from .mods import ModIndex, default_roots
from .patches import PatchesError, ensure_reader, mod_assemblies

EXIT_OK, EXIT_FAILED, EXIT_USAGE = 0, 1, 2


def _parser():
    p = argparse.ArgumentParser(prog="rimworld-targets", description=__doc__.split("\n\n")[0],
                                formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__.split("\n\n", 1)[1])
    p.add_argument("--root", default=".", help="the repository holding the C# source (default: here)")
    p.add_argument("--source", action="append", help="a glob under the root (default src/**/*.cs); may repeat")
    p.add_argument("--assemblies", action="append", default=[], help="a glob under the root to read before the game's; may repeat")
    p.add_argument("--game", help="the RimWorld folder (else RIMWORLD_PATH, the settings file, Steam's default)")
    p.add_argument("--workshop", help="the Workshop content folder (else RIMWORLD_WORKSHOP_PATH, settings, beside the game)")
    p.add_argument("--config", help="the folder holding ModsConfig.xml (else RIMWORLD_CONFIG_PATH, settings, default)")
    p.add_argument("--settings", help="a JSON settings file with rimworldPath, workshopPath, rimworldConfigPath")
    p.add_argument("--if-installed", action="store_true", help="with no game on this machine, say so and pass (for CI)")
    p.add_argument("--all", action="store_true", help="list what passed too")
    p.add_argument("--top", type=int, default=40, help="rows per table (default 40)")
    p.add_argument("--json", action="store_true", help="print JSON instead of Markdown")
    p.add_argument("--no-redact", action="store_true", help="show the home folder instead of ~")
    return p


def game_assemblies(game):
    """The game's own managed assemblies: beside the executable on 1.7, under its Data folder's Managed before that."""
    found = []
    for folder in [Path(game)] + sorted(Path(game).glob("*_Data/Managed")):
        found.extend(sorted(folder.glob("*.dll"), key=lambda path: path.name.lower()))
    return found if any(path.name == "Assembly-CSharp.dll" for path in found) else []


def read_members(tool, wanted, files, run=subprocess.run):
    """The reader's records for the wanted type names across the files."""
    types = tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".txt", prefix="phobos-types-", delete=False)
    listing = tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".txt", prefix="phobos-assemblies-", delete=False)
    try:
        with types:
            types.write("\n".join(wanted))
        with listing:
            listing.write("\n".join(str(path) for path in files))
        result = run([str(tool), "members", "@" + types.name, "@" + listing.name], capture_output=True, check=False)
    finally:
        os.remove(types.name)
        os.remove(listing.name)
    if result.returncode != 0:
        raise PatchesError(f"The assembly reader failed: {(result.stderr or b'').decode('utf-8', 'replace')[-1000:]}")
    return [json.loads(line) for line in result.stdout.decode("utf-8").splitlines() if line.strip()]


def build_report(scan, findings, read_count, errors, top, show_all):
    failing = [f for f in findings if f.fails]
    unread = [f for f in findings if f.status == "type-missing"]
    notes = [f for f in findings if f.status in ("note", "ambiguous")]
    passed = [f for f in findings if f.status in ("ok", "inherited")]
    title = "rimworld-targets: " + (f"{len(failing)} no longer match" if failing else "every target found")
    report = Report(title, [
        f"{scan.files} source files, {len(findings)} named members and injected parameters, {read_count} assemblies read as metadata, none run.",
        f"Found: {len(passed)}. No longer match: {len(failing)}. Notes: {len(notes)}. Type not among the assemblies read, so not checked: {len(unread)}.",
        f"{len(scan.unresolved)} lookups are worked out at run time and cannot be checked.",
        "A pass says the names and signatures still exist, not that the code still behaves; it is not a test in game.",
    ])
    columns = ["Where", "Named by", "Target", "Problem"]

    def rows(items):
        return [[f"{f.file}:{f.line}", f.source, f.label, (f.status + (": " + f.detail if f.detail else ""))] for f in items]

    if failing:
        report.section("No longer match", Table(columns, rows(failing)[:top], total=len(failing)))
    if notes:
        report.section("Notes", Table(columns, rows(notes)[:top], total=len(notes)))
    if unread:
        report.section("Not checked: type not read (an optional mod that is not active, or the .NET library)", Table(columns, rows(unread)[:top], total=len(unread)))
    if scan.unresolved:
        report.section("Worked out at run time", Table(["Where", "Named by", "Member", "Why"],
                       [[f"{u.file}:{u.line}", u.source, u.member, u.reason] for u in scan.unresolved][:top], total=len(scan.unresolved)))
    if errors:
        report.section("Assemblies that could not be read", Bullets([f"{e.get('path')}: {e.get('error')}" for e in errors][:top]))
    if show_all and passed:
        report.section("Found", Table(columns, rows(passed), total=len(passed)))
    return report, bool(failing)


def main(argv=None, settings_file=None, environ=None, out=None, run=None):
    out = out or sys.stdout
    try:
        args = _parser().parse_args(list(sys.argv[1:] if argv is None else argv))
    except SystemExit as stop:
        return EXIT_USAGE if stop.code else EXIT_OK
    settings_file = args.settings or settings_file
    redact = keep if args.no_redact else home_redactor()
    root = Path(args.root)
    code = EXIT_OK
    try:
        game = paths.game_path(args.game, environ, settings_file)
        managed = game_assemblies(game)
        if not managed:
            if args.if_installed:
                print("rimworld-targets: skipped, no RimWorld install on this machine.", file=out)
                return EXIT_OK
            raise PatchesError(f"No game assemblies under {game}. Name the folder with --game.")
        workshop = paths.workshop_path(game, args.workshop, environ, settings_file)
        config = paths.config_path(args.config, environ, settings_file)
        mods_config = Path(config) / "ModsConfig.xml"
        if not mods_config.is_file():
            raise PatchesError(f"No ModsConfig.xml in {config}. Name the folder with --config.")
        version, _, ids = loading.read_mods_config(mods_config)
        index_mods = ModIndex.scan(default_roots(game, workshop))
        active = loading.resolve_active(index_mods.mods, ids)
        # Our own fresh build first, so a stale installed copy never answers for it.
        files = [path for pattern in args.assemblies for path in sorted(root.glob(pattern))]
        files += managed + [dll for _, dll in mod_assemblies(active, version)]
        scan = scan_tree(root, tuple(args.source or ["src/**/*.cs"]))
        options = {"run": run} if run is not None else {}
        tool = ensure_reader(environ, **options)
        records = read_members(tool, scan.type_names(), files, **options)
        listing = Listing(records)
        # The game's folder holds native libraries as well; they have no metadata and no members to name.
        errors = [r for r in records if "error" in r and "type" not in r and "no .NET metadata" not in r["error"]]
        report, failed = build_report(scan, check_targets(scan, listing), len(files), errors, args.top, args.all)
        code = EXIT_FAILED if failed else EXIT_OK
    except PatchesError as error:
        report, code = Report("rimworld-targets: error", [str(error)]), EXIT_FAILED
    print(json.dumps(render_json(report, redact), indent=2, ensure_ascii=False) if args.json
          else render_markdown(report, redact), file=out)
    return code
