"""rimworld-archive: keep every version of the game's assembly and of the mods a project ties into, to compare later.

    rimworld-archive snapshot --root .            keep what changed since the last snapshot (the game and every tied mod)
    rimworld-archive list                         what the archive holds, newest version of each file first
    rimworld-archive list --file Vehicles.dll     every version kept of one file
    rimworld-archive compare Vehicles.dll         what changed between the last two versions, member by member
    rimworld-archive compare Assembly-CSharp.dll --back 2   the newest against two versions before it
    rimworld-archive get Vehicles.dll --back 1    unpack an older version and print where it is, for any other tool

Steam replaces a mod's or the game's files in place, so once an update lands the older build is gone. A snapshot copies
each watched file whose content changed into the archive (compressed, one copy per distinct content). Which mods: every
active mod a project's own mods name in About.xml (modDependencies, loadAfter) or in LoadFolders.xml (IfModActive), plus
any named with --mod; the project's own mods are left out, since their history is in git. Which game files:
Assembly-CSharp.dll, plus any named with --game-file.

Reads the game and Workshop folders as files and never writes to them. compare decompiles both sides with ilspycmd,
which reads a file without loading or running it, through the code tool's compare.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path
import sys
import xml.etree.ElementTree as ET

from ...assembly_archive import Archive, ArchiveError, Source, archive_root, history, pick
from ...cache import CacheError
from ...manifest import READS, RUNS, WRITES
from ...report import Report, Table, envelope_text, home_redactor, keep, render_markdown
from . import loading, paths
from .mods import ModIndex, _about_root, _text, default_roots
from .patches import mod_assemblies

EXIT_OK, EXIT_FAILED, EXIT_USAGE = 0, 1, 2
GAME_OWNER = "ludeon.rimworld"
DEFAULT_GAME_FILES = ("Assembly-CSharp.dll",)
REPORTS = ("snapshot", "list", "compare", "get")


def _parser():
    p = argparse.ArgumentParser(prog="rimworld-archive", description=__doc__.split("\n\n")[0],
                                formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__.split("\n\n", 1)[1])
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--archive", help="the archive folder (else PHOBOS_ASSEMBLY_ARCHIVE, assemblyArchivePath in settings, "
                                          "%%LOCALAPPDATA%%\\phobos-modkit\\assembly-archive)")
    common.add_argument("--settings", help="a JSON settings file with rimworldPath, workshopPath, rimworldConfigPath, assemblyArchivePath")
    common.add_argument("--top", type=int, default=60, help="rows per table (default %(default)s)")
    common.add_argument("--json", action="store_true", help="print JSON instead of Markdown")
    common.add_argument("--no-redact", action="store_true", help="show the home folder instead of ~")
    sub = p.add_subparsers(dest="report")
    s = sub.add_parser("snapshot", parents=[common], help="keep each watched file whose content changed since the last snapshot")
    s.add_argument("--root", default=".", help="the project whose mods' tie-ins decide what to watch (default: here)")
    s.add_argument("--mod", action="append", default=[], metavar="PACKAGE_ID", help="watch this active mod too; may repeat")
    s.add_argument("--game-file", action="append", default=[], metavar="NAME",
                   help="a game assembly to watch beside Assembly-CSharp.dll; may repeat")
    s.add_argument("--game", help="the RimWorld folder (else RIMWORLD_PATH, the settings file, Steam's default)")
    s.add_argument("--workshop", help="the Workshop content folder (else RIMWORLD_WORKSHOP_PATH, settings, beside the game)")
    s.add_argument("--config", help="the folder holding ModsConfig.xml (else RIMWORLD_CONFIG_PATH, settings, default)")
    s.add_argument("--if-installed", action="store_true", help="with no game on this machine, say so and pass (for CI)")
    lst = sub.add_parser("list", parents=[common], help="what the archive holds")
    lst.add_argument("--file", help="every version of one file (its name, any case)")
    for name, verb in (("compare", "what changed between two kept versions, member by member"),
                       ("get", "unpack a kept version and print where it is")):
        c = sub.add_parser(name, parents=[common], help=verb)
        c.add_argument("file", help="the file's name, as the mod or game ships it")
        c.add_argument("--owner", help="the package ID that ships it, when several do")
        c.add_argument("--back", type=int, default=1, help="how many versions before the newest (default %(default)s)")
    cmp = sub.choices["compare"]
    cmp.add_argument("--to", type=int, default=0, metavar="BACK", help="the newer side, versions before the newest (default 0)")
    cmp.add_argument("--only", action="append", default=[], metavar="PATTERN", help="only declarations whose full name matches; repeatable")
    cmp.add_argument("--show", metavar="NAME", help="the changes in one declaration, as a diff")
    cmp.add_argument("--decompiler", help="ilspycmd (else PHOBOS_MODKIT_ILSPYCMD, settings, the PATH)")
    return p


# ---- What to watch ----

def _ids(text):
    return {loading.bare_id(part) for part in (text or "").split(",") if part.strip()}


def tied_mods(root):
    """(the project's own package IDs, every other package ID its mods name in About.xml or LoadFolders.xml)."""
    own, named = set(), set()
    for folder in sorted(Path(root).glob("mods/*")):
        about = _about_root(folder) if folder.is_dir() else None
        if about is None:
            continue
        own.add(loading.bare_id(_text(about, "packageId")))
        for tag in ("modDependencies", "loadAfter", "forceLoadAfter"):
            for element in about.iter():
                if isinstance(element.tag, str) and element.tag.lower() == tag.lower():
                    for li in element:
                        package = _text(li, "packageId") if len(li) else (li.text or "")
                        named |= _ids(package)
        for load_folders in folder.glob("[Ll]oad[Ff]olders.xml"):
            try:
                tree = ET.parse(load_folders).getroot()
            except ET.ParseError:
                continue
            for element in tree.iter():
                for attribute in ("IfModActive", "IfModActiveAll"):
                    named |= _ids(element.get(attribute))
    named.discard("")
    return own, named - own


def _mod_version(folder):
    about = _about_root(folder)
    return _text(about, "modVersion") if about is not None else ""


def sources(root, game, workshop, mods_config, extra_mods=(), game_files=()):
    """The files to keep: the game's chosen assemblies, then every DLL each watched active mod loads."""
    found = []
    version_file = Path(game) / "Version.txt"
    game_version = version_file.read_text(encoding="utf-8", errors="replace").strip() if version_file.is_file() else ""
    for name in DEFAULT_GAME_FILES + tuple(game_files):
        path = Path(game) / name
        if path.is_file():
            found.append(Source(GAME_OWNER, "RimWorld", game_version, path))
    _, watched = tied_mods(root)
    watched |= {loading.bare_id(m) for m in extra_mods}
    version, _, ids = loading.read_mods_config(mods_config)
    active = loading.resolve_active(ModIndex.scan(default_roots(game, workshop)).mods, ids)
    for entry, dll in mod_assemblies(active, version):
        if loading.bare_id(entry.mod.package_id) in watched:
            found.append(Source(entry.mod.package_id, entry.mod.name, _mod_version(entry.mod.folder), dll))
    return found, watched


# ---- Reports ----

def _size(n):
    return f"{n / 1_048_576:.1f} MB" if n >= 1_048_576 else f"{n / 1024:.0f} KB"


def snapshot_report(archive, found, watched, results, top):
    kept = [(s, status) for s, status in results if status != "same"]
    report = Report("rimworld-archive snapshot")
    report.lines.append(f"{len(found)} files watched: the game's and those of {len({s.owner for s in found} - {GAME_OWNER})} "
                        f"active mods of the {len(watched)} this project ties into. {len(kept)} kept now, "
                        f"{len(results) - len(kept)} unchanged since the last snapshot.")
    report.lines.append(f"The archive holds {_size(archive.stored_bytes())} at {archive.root}.")
    if kept:
        rows = [[s.owner_name, Path(s.path).name, s.version or "-", "first copy" if status == "first" else "changed"]
                for s, status in kept]
        report.section("Kept now", Table(["Owner", "File", "Version", "Why"], rows[:top], total=len(rows)))
    return report


def list_report(archive, file, top):
    versions = archive.versions()
    report = Report("rimworld-archive list")
    if not versions:
        report.lines.append(f"The archive at {archive.root} is empty. Run the snapshot report first.")
        return report
    report.lines.append(f"{len(versions)} versions of {len({(v.owner, v.file) for v in versions})} files, "
                        f"{_size(archive.stored_bytes())} stored at {archive.root}.")
    if file:
        chain = history(versions, file)
        rows = [[len(chain) - 1 - i, v.version or "-", v.seen_at, _size(v.size), v.sha256[:12]] for i, v in enumerate(chain)]
        report.section(f"{chain[-1].file} from {chain[-1].owner_name}, newest last",
                       Table(["Back", "Version", "First seen", "Size", "SHA-256"], rows[-top:], total=len(rows)))
        return report
    groups = {}
    for v in versions:
        groups.setdefault((v.owner, v.file), []).append(v)
    rows = sorted(([chain[-1].owner_name, chain[-1].file, len(chain), chain[-1].version or "-", chain[-1].seen_at]
                   for chain in groups.values()), key=lambda r: (-r[2], r[0].lower(), r[1].lower()))
    report.section("Files, most versions first", Table(["Owner", "File", "Versions", "Newest version", "Newest seen"],
                                                       rows[:top], total=len(rows)))
    return report


def main(argv=None, settings_file=None, environ=None, out=None, now=None):
    out = out or sys.stdout
    argv = list(sys.argv[1:] if argv is None else argv) or ["list"]
    try:
        args = _parser().parse_args(argv)
    except SystemExit as stop:
        return EXIT_USAGE if stop.code else EXIT_OK
    settings_file = args.settings or settings_file
    redact = keep if args.no_redact else home_redactor()
    archive = Archive(archive_root(args.archive, environ, settings_file))
    code = EXIT_OK
    try:
        if args.report == "snapshot":
            game = paths.game_path(args.game, environ, settings_file)
            if not (Path(game) / "Assembly-CSharp.dll").is_file() and not any(Path(game).glob("*_Data/Managed/Assembly-CSharp.dll")):
                if args.if_installed:
                    print("rimworld-archive: skipped, no RimWorld install on this machine.", file=out)
                    return EXIT_OK
                raise ArchiveError(f"No Assembly-CSharp.dll in {game}. Name the folder with --game.")
            workshop = paths.workshop_path(game, args.workshop, environ, settings_file)
            mods_config = Path(paths.config_path(args.config, environ, settings_file)) / "ModsConfig.xml"
            if not mods_config.is_file():
                raise ArchiveError(f"No ModsConfig.xml at {mods_config}. Name the folder with --config.")
            found, watched = sources(args.root, game, workshop, mods_config, args.mod, args.game_file)
            stamp = now or datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
            report = snapshot_report(archive, found, watched, archive.add(found, stamp), args.top)
        elif args.report in ("compare", "get"):
            chain = history(archive.versions(), args.file, args.owner)
            older = archive.extract(pick(chain, args.back))
            if args.report == "get":
                print(str(older), file=out)
                return EXIT_OK
            newer = archive.extract(pick(chain, args.to))
            from ...code.cli import main as code_main
            forwarded = ["compare", str(older), str(newer), "--top", str(args.top)]
            for pattern in args.only:
                forwarded += ["--only", pattern]
            for flag, value in (("--show", args.show), ("--decompiler", args.decompiler), ("--settings", args.settings)):
                if value:
                    forwarded += [flag, value]
            if args.json:
                forwarded.append("--json")
            if args.no_redact:
                forwarded.append("--no-redact")
            return code_main(forwarded, settings_file=settings_file, environ=environ, out=out)
        else:
            report = list_report(archive, getattr(args, "file", None), args.top)
    except (ArchiveError, CacheError, OSError, ET.ParseError) as error:
        report, code = Report("rimworld-archive: error", [str(error)]), EXIT_FAILED
    print(envelope_text("rimworld-archive", report, redact) if args.json else render_markdown(report, redact), file=out)
    return code


MANIFEST = {"game": "rimworld", "parser": _parser, "effect": READS,
            "reports": {"snapshot": {"effect": WRITES, "note": "writes only to the archive folder, never to the game or Workshop"},
                        "get": {"effect": WRITES, "note": "unpacks a kept file inside the archive folder"},
                        "compare": {"effect": RUNS, "note": "unpacks both sides inside the archive folder and runs ilspycmd, "
                                                            "which reads a file without loading or running it"}}}
