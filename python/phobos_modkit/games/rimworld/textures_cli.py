"""rimworld-textures: whether every active mod's encoded textures (.dds) match its pictures (.png), and encoding those that don't.

    rimworld-textures status                    active mods with stale or missing encoded textures, and left-over ones
    rimworld-textures status --all              every active mod, even those in step
    rimworld-textures encode --mod ID           re-encode one mod's textures with RimSort's own todds preset (repeatable),
                                                then shorten the mip chains Waylith would unpack

A stale .dds makes the game show a mod's old picture: the game loads a .dds instead of the .png beside it without comparing dates
(docs/rimworld-textures.md). Waylith unpacks a compressed texture whose mip heights stop being multiples of four, taking four times
the memory; encode shortens those chains in every .dds of the mod, those already in step included. Only active mods in local Mods and Workshop folders are read; the game's own Data never. encode writes
.dds files into those mod folders, Workshop ones included (owner, 18 Nov 2026), refuses while the game runs, and needs RimSort's todds.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import os
from pathlib import Path
import sys

from ...installs import game_running
from ...manifest import READS, WRITES
from ... import history
from ...progress import Progress
from ...report import Bullets, Report, Table, envelope_text, home_redactor, keep, render_markdown
from . import loading, textures
from .installs import PROCESSES
from .mods import ModIndex, default_roots
from .paths import config_path, game_path, workshop_path

EXIT_OK, EXIT_REFUSED, EXIT_USAGE = 0, 1, 2
OWN_SOURCES = ("Local", "Workshop")
CHECK_THREADS = 8
PROGRESS_EVERY = 10        # mods between progress lines while checking


def _parser():
    p = argparse.ArgumentParser(prog="rimworld-textures", description=__doc__.split("\n\n")[0],
                                formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__.split("\n\n", 1)[1])
    sub = p.add_subparsers(dest="report", required=True)
    for name, helptext in (("status", "active mods whose encoded textures are stale, missing or left over"),
                           ("encode", "re-encode named mods' textures with RimSort's todds preset")):
        s = sub.add_parser(name, help=helptext)
        s.add_argument("--settings", help="a JSON settings file naming the game, Workshop, Config and todds paths")
        s.add_argument("--game", help="the RimWorld folder")
        s.add_argument("--todds", help="RimSort's todds.exe")
        if name == "status":
            s.add_argument("--all", action="store_true", help="list every active mod, not only those needing attention")
            s.add_argument("--top", type=int, default=40, help="mods per table (default 40)")
        else:
            s.add_argument("--mod", action="append", required=True, help="a package ID or folder name (repeatable)")
        s.add_argument("--json", action="store_true", help="print JSON instead of Markdown")
        s.add_argument("--no-redact", action="store_true", help="show the home folder instead of ~")
    return p


def active_mods(settings=None, environ=None, game=None):
    """Active mods in local Mods and Workshop folders, in load order: the game's own Data is never included."""
    game = game_path(game, environ, settings)
    workshop = workshop_path(game, None, environ, settings)
    mods_config = Path(config_path(None, environ, settings)) / "ModsConfig.xml"
    _, _, ids = loading.read_mods_config(mods_config)
    active = loading.resolve_active(ModIndex.scan(default_roots(game, workshop)).mods, ids)
    return [entry.mod for entry in active if entry.mod is not None and entry.mod.source in OWN_SOURCES]


def _mod_data(mod, fresh):
    return {"name": mod.name, "packageId": mod.package_id, "folder": str(mod.folder), "folderName": mod.folder.name,
            "source": mod.source, "pictures": fresh.pictures, "stale": len(fresh.stale), "missing": len(fresh.missing),
            "leftOver": len(fresh.left_over), "stalePaths": fresh.stale[:textures.SAMPLE_PATHS],
            "missingPaths": fresh.missing[:textures.SAMPLE_PATHS], "leftOverPaths": fresh.left_over[:textures.SAMPLE_PATHS]}


def status(mods, running, todds, everything=False, top=40, now=None, progress=None):
    rows = []
    with ThreadPoolExecutor(max_workers=CHECK_THREADS) as pool:     # the disk does the waiting, so folders are read side by side
        for row in pool.map(lambda mod: _mod_data(mod, textures.check_folder(mod.folder)), mods):
            rows.append(row)
            if progress and (len(rows) % PROGRESS_EVERY == 0 or len(rows) == len(mods)):
                progress("Checking each active mod's textures against its pictures", len(rows), len(mods))
    stale = [r for r in rows if r["stale"]]
    missing = [r for r in rows if r["missing"] and not r["stale"]]
    title = ("Textures: in step" if not stale and not missing else
             f"Textures: {len(stale):,} mods would show old pictures, {len(missing):,} more have pictures never encoded")
    report = Report(title)
    report.lines.append(f"{len(rows):,} active mods read, {sum(r['pictures'] for r in rows):,} pictures. The game loads a mod's .dds "
                        "instead of the .png beside it without comparing dates, so a stale .dds shows the old picture.")
    if running:
        report.lines.append(f"**The game is running ({', '.join(running)}): encoding waits until it closes.**")
    if todds is None:
        report.lines.append("**RimSort's todds was not found**: pass --todds, set RIMSORT_TODDS, or install RimSort.")
    columns = ["Mod", "From", "Stale", "Never encoded", "Left over", "Pictures"]
    cells = lambda r: [r["name"], r["source"], f"{r['stale']:,}", f"{r['missing']:,}", f"{r['leftOver']:,}", f"{r['pictures']:,}"]
    if stale:
        report.section("Would show old pictures: encode before the next launch", Table(columns, [cells(r) for r in stale[:top]],
                                                                                      total=len(stale)))
    if missing:
        report.section("Pictures never encoded: slower loading, more memory", Table(columns, [cells(r) for r in missing[:top]],
                                                                                    total=len(missing)))
    if everything:
        report.section("Every active mod", Table(columns, [cells(r) for r in rows[:top]], total=len(rows)))
    left = [r for r in rows if r["leftOver"]]
    if left:
        report.section("Left over", Bullets([f"{len(left):,} mods hold .dds files whose .png is gone ({sum(r['leftOver'] for r in left):,} "
                                             "files). They still load under their names; nothing here removes them."]))
    data = {"checkedAt": (now or datetime.now(timezone.utc)).isoformat(timespec="seconds"), "gameRunning": running,
            "todds": str(todds) if todds else None, "slackSeconds": textures.SLACK_SECONDS,
            "totals": {"mods": len(rows), "pictures": sum(r["pictures"] for r in rows), "staleMods": len(stale),
                       "missingMods": len(missing), "stale": sum(r["stale"] for r in rows), "missing": sum(r["missing"] for r in rows),
                       "leftOver": sum(r["leftOver"] for r in rows)},
            "mods": rows if everything else [r for r in rows if r["stale"] or r["missing"] or r["leftOver"]]}
    return report, data


def _pick(mods, wanted):
    """The active mods named by package ID or folder name; raises ValueError naming any that is not active."""
    by_key = {}
    for mod in mods:
        by_key.setdefault(mod.package_id.lower(), mod)
        by_key.setdefault(mod.folder.name.lower(), mod)
    unknown = [w for w in wanted if w.lower() not in by_key]
    if unknown:
        raise ValueError("not an active mod in local Mods or Workshop folders: " + ", ".join(unknown))
    picked, seen = [], set()
    for w in wanted:
        mod = by_key[w.lower()]
        if mod.folder not in seen:
            seen.add(mod.folder)
            picked.append(mod)
    return picked


def main(argv=None, environ=None, out=None, running=None, run=None, mods=None, now=None):
    out = out or sys.stdout
    environ = os.environ if environ is None else environ
    try:
        args = _parser().parse_args(list(sys.argv[1:] if argv is None else argv))
    except SystemExit as stop:
        return EXIT_USAGE if stop.code else EXIT_OK
    redact = keep if args.no_redact else home_redactor()
    running = (running or game_running)(PROCESSES)
    progress = Progress(environ)
    todds = textures.todds_path(args.todds, environ, args.settings)
    code = EXIT_OK
    try:
        progress("Finding the active mods")
        found = mods if mods is not None else active_mods(args.settings, environ, args.game)
        if args.report == "status":
            report, data = status(found, running, todds, args.all, args.top, now, progress)
        else:
            picked = _pick(found, args.mod)
            if running:
                raise ValueError(f"the game is running ({', '.join(running)}). Close it, then try again. Nothing was changed")
            if todds is None:
                raise ValueError("RimSort's todds was not found. Pass --todds, set RIMSORT_TODDS, or install RimSort. Nothing was changed")
            results = []
            for position, mod in enumerate(picked, 1):
                progress(f"Encoding the textures of {mod.name}", position, len(picked))
                exit_code, line = textures.encode(mod.folder, todds, **({"run": run} if run else {}))
                trim = textures.trim_folder(mod.folder)      # every .dds of the mod, those todds left alone included
                after = textures.check_folder(mod.folder)
                results.append({"name": mod.name, "packageId": mod.package_id, "exitCode": exit_code, "line": line,
                                "staleAfter": len(after.stale), "missingAfter": len(after.missing),
                                "mipsShortened": len(trim.trimmed), "leftWhole": len(trim.left_whole),
                                "trimFailed": len(trim.failed), "leftWholePaths": trim.left_whole[:textures.SAMPLE_PATHS],
                                "trimFailedPaths": trim.failed[:textures.SAMPLE_PATHS]})
            ok = all(r["exitCode"] == 0 and not r["trimFailed"] for r in results)
            history.record("rimworld", "encoded", environ, args.settings, ok=ok, count=len(results),
                           mods=[r["name"] for r in results][:20])
            code = EXIT_OK if ok else EXIT_REFUSED
            report = Report(f"Encoded the textures of {len(results):,} mods" if ok else "Some textures could not be encoded")
            report.section("Mods", Table(["Mod", "Exit", "Stale after", "Never encoded after", "Mip chains shortened",
                                          "Left whole", "Could not shorten"],
                                         [[r["name"], str(r["exitCode"]), f"{r['staleAfter']:,}", f"{r['missingAfter']:,}",
                                           f"{r['mipsShortened']:,}", f"{r['leftWhole']:,}", f"{r['trimFailed']:,}"]
                                          for r in results]))
            report.lines.append("Mip chains are shortened so Waylith keeps those textures compressed; the full-size picture is "
                                f"unchanged. Left whole: fewer than {textures.MIN_KEPT_MIPS} levels would remain, so Waylith still "
                                "unpacks them, as before.")
            data = {"ok": ok, "mods": results}
    except (ValueError, OSError) as error:
        message = str(error)
        message = message[0].upper() + message[1:] + ("" if message.endswith(".") else ".")
        if not args.json:
            print(redact(message), file=sys.stderr)
            return EXIT_REFUSED
        report, data = Report("Refused"), {"ok": False, "refusal": message}
        report.lines.append(message)
        code = EXIT_REFUSED
    out.write((envelope_text("rimworld-textures", report, redact, data) if args.json else render_markdown(report, redact)) + "\n")
    return code


MANIFEST = {"game": "rimworld", "parser": _parser, "effect": READS,
            "reports": {"status": {"question": "Do any mods' textures need encoding before my next launch?", "surface": "textures"},
                        "encode": {"effect": WRITES, "note": "writes .dds files into the named mods' folders, Workshop ones included, "
                                                             "and shortens the mip chains of those Waylith would unpack"}}}
