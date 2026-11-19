"""rimworld-code: another author's code, as a program asks for it (1.49.0, for D'thorga Companion's "their code"): a type's or
member's source from the best copy kept, which assembly declares a type, and a decompile of that assembly on request.

    rimworld-code show Vehicles.VehicleTurret.FireTurret --root REPO   the source, from a public clone or a decompile
    rimworld-code holder Vehicles.VehicleTurret --root REPO            which of the game's and active mods' assemblies declares it
    rimworld-code decompile --assembly PATH --root REPO                 decompile it once into the kit's cache (minutes for the game's)

Where source is looked for, in order: the mods' public source clones (sourceClonesPath), the repository's .local/decompiled,
and the decompiles this command made. Public source comes first: it has the author's own names and comments, while a decompile
is the compiled file read back. Our own src/ is never searched: the Code map shows it. Decompiled code stays on this machine,
in the kit's cache; it is never written into a repository.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

from ... import cache as derived
from ... import paths as kit_paths
from ...code import compare, index
from ...code.scan import DECOMPILER_NOTE
from ...manifest import READS, RUNS
from ...progress import Progress
from ...report import Code, Fact, Report, Table, envelope_text, home_redactor, keep, render_markdown
from . import loading, paths
from .mods import ModIndex, default_roots
from .patches import PatchesError, ensure_reader, mod_assemblies
from .targets_cli import game_assemblies, read_members

EXIT_OK, EXIT_FAILED, EXIT_USAGE = 0, 1, 2
CLONES = ("sourceClonesPath", "PHOBOS_SOURCE_CLONES")
LOCAL_SETTINGS = Path(".local") / "install-settings.json"
DECOMPILED = Path(".local") / "decompiled"
SOURCE, DECOMPILE = "source", "decompiled"
LINES_SHOWN = 400
DECLARATIONS_SHOWN = 6


def _parser():
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--root", default=".", help="the repository whose clones and decompiles are read (default: here)")
    common.add_argument("--clones", help="the source clones' folder (else PHOBOS_SOURCE_CLONES, sourceClonesPath in settings)")
    common.add_argument("--cache", help="the kit's cache folder")
    common.add_argument("--settings", help="a JSON settings file (default: the repository's .local/install-settings.json)")
    common.add_argument("--game", help="the RimWorld folder (else RIMWORLD_PATH, the settings file, Steam's default)")
    common.add_argument("--workshop", help="the Workshop content folder")
    common.add_argument("--config", help="the folder holding ModsConfig.xml")
    common.add_argument("--json", action="store_true", help="print JSON instead of Markdown")
    common.add_argument("--no-redact", action="store_true", help="show the home folder instead of ~")
    p = argparse.ArgumentParser(prog="rimworld-code", description=__doc__.split("\n\n")[0],
                                formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__.split("\n\n", 1)[1])
    sub = p.add_subparsers(dest="report", metavar="report")
    show = sub.add_parser("show", parents=[common], help="a type's or member's source, from the best copy kept")
    show.add_argument("name", help="Type, Type.Member or Namespace.Type.Member (a leading dot or a colon is fine)")
    show.add_argument("--lines", type=int, default=LINES_SHOWN, help=f"lines per declaration (default {LINES_SHOWN})")
    holder = sub.add_parser("holder", parents=[common], help="which of the game's and active mods' assemblies declares a type")
    holder.add_argument("name", help="a type's name or full name, or a member of it")
    dec = sub.add_parser("decompile", parents=[common], help="decompile an assembly into the kit's cache, once per build")
    dec.add_argument("--assembly", required=True, help="the assembly's path, as holder gave it")
    return p


# ---- Names ----

def plain_name(name):
    """A target as Harmony, our graph or a person writes it, as the code index takes it: Namespace.Type.Member."""
    return name.strip().replace(":", ".").replace("+", ".").replace("/", ".").strip(".")


def type_candidates(name):
    """The type a name may mean: the whole name (a type) or all but its last part (a member of one)."""
    parts = plain_name(name).split(".")
    found = [".".join(parts)]
    if len(parts) > 1:
        found.append(".".join(parts[:-1]))
    return found


# ---- Where source is kept ----

def settings_for(root, given):
    if given:
        return given
    local = Path(root) / LOCAL_SETTINGS
    return str(local) if local.is_file() else None


def decompile_folder(cache, environ, settings_file):
    return derived.folder(compare.CACHE_FOLDER, cache, environ, settings_file)


def _children(folder):
    folder = Path(folder)
    if not folder.is_dir():
        return []
    return [c for c in sorted(folder.iterdir(), key=lambda p: p.name.lower()) if c.is_dir() or c.suffix.lower() == ".cs"]


def made_decompiles(folder):
    """The finished decompiles in the kit's cache, each named for the assembly it came from."""
    found = []
    for child in _children(folder):
        marker = child / compare.COMPLETE_MARKER
        if not marker.is_file():
            continue
        try:
            source = json.loads(marker.read_text(encoding="utf-8")).get("source") or child.name
        except (OSError, ValueError):
            source = child.name
        found.append((index.Corpus(f"{Path(source).stem} (decompiled {child.name.rsplit('-', 1)[-1][:8]})", child), DECOMPILE))
    return found


def corpora(root, clones, decompiles):
    """Every place source may be kept, public clones first: (Corpus, kind)."""
    found = [(index.Corpus(c.name, c), SOURCE) for c in _children(clones)] if clones else []
    found += [(index.Corpus(c.name, c), DECOMPILE) for c in _children(Path(root) / DECOMPILED)]
    found += made_decompiles(decompiles)
    return found


def _lines_of(corpus, hit, limit):
    """The declaration's lines and each one's number in its file, without the decompiler's //IL_ notes."""
    root = Path(corpus.root)
    file = root if root.is_file() else root / hit.path
    try:
        text = file.read_text(encoding="utf-8-sig", errors="replace").splitlines()
    except OSError:
        return [], [], False
    kept = [(hit.start + i, line) for i, line in enumerate(text[hit.start - 1:hit.end]) if not DECOMPILER_NOTE.match(line)]
    more = bool(limit) and len(kept) > limit
    kept = kept[:limit] if limit else kept
    return [line for _, line in kept], [n for n, _ in kept], more


def show(name, places, cache, limit, progress=None, rebuild=False):
    """Every declaration the name points at, in the order of the places: public source first."""
    wanted = plain_name(name)
    found = []
    for number, (corpus, kind) in enumerate(places, 1):
        if progress:
            progress("Looking through the source kept", number, len(places), corpus.name)
        try:
            built, _ = index.ensure(corpus, cache, rebuild)
        except (OSError, index.CodeError):
            continue
        for hit in index.resolve(built, corpus.name, wanted):
            lines, numbers, more = _lines_of(corpus, hit, limit)
            found.append({"corpus": corpus.name, "source": kind, "kind": hit.kind, "full": hit.full,
                          "signature": hit.signature, "file": hit.path.replace("\\", "/"), "start": hit.start,
                          "end": hit.end, "language": "cs", "lines": lines, "numbers": numbers, "more": more})
            if len(found) >= DECLARATIONS_SHOWN:
                return found
        if found and kind == SOURCE:
            return found                # the author's own source answers it; a decompile would only repeat it
    return found


# ---- Which assembly declares a type ----

def assemblies(args, environ, settings_file):
    """The game's own assemblies and every active mod's, as files to read."""
    game = paths.game_path(args.game, environ, settings_file)
    managed = game_assemblies(game)
    if not managed:
        raise PatchesError(f"No game assemblies under {game}. Name the folder with --game.")
    workshop = paths.workshop_path(game, args.workshop, environ, settings_file)
    config = paths.config_path(args.config, environ, settings_file)
    mods_config = Path(config) / "ModsConfig.xml"
    if not mods_config.is_file():
        raise PatchesError(f"No ModsConfig.xml in {config}. Name the folder with --config.")
    version, _, ids = loading.read_mods_config(mods_config)
    active = loading.resolve_active(ModIndex.scan(default_roots(game, workshop)).mods, ids)
    owners = {str(dll): mod for mod, dll in mod_assemblies(active, version)}
    return game, managed, owners


def _same(path):
    """A path as compared: one file whichever slashes and case name it."""
    return os.path.normcase(os.path.normpath(str(path)))


def holders(name, records, owners, managed):
    """The assemblies declaring the type a name means: (type, assembly, path, mod), nearest match first."""
    found = []
    managed = {_same(p) for p in managed}
    owners = {_same(p): entry for p, entry in owners.items()}
    for candidate in type_candidates(name):
        for record in records:
            full = record.get("type") or ""
            if full != candidate and not full.endswith("." + candidate):
                continue
            path = record.get("path") or ""
            entry = owners.get(_same(path))
            mod = getattr(getattr(entry, "mod", None), "name", None)
            owner = mod or ("the game" if _same(path) in managed else None)
            row = {"type": full, "assembly": record.get("assembly"), "path": path, "mod": owner}
            if row not in found:
                found.append(row)
        if found:
            return found
    return found


def _report_show(name, found, places):
    report = Report(f"rimworld-code show {name}")
    if not found:
        report.lines.append(f"No source kept for {name}: {len(places)} places looked in. Decompile the assembly that "
                            "declares it (holder names it) to read it.")
        return report
    first = found[0]
    report.facts += [Fact("From", "their public source" if first["source"] == SOURCE else "a decompile"),
                     Fact("Where", f"{first['corpus']}: {first['file']}")]
    for item in found:
        report.section(f"{item['full']} ({item['corpus']}:{item['file']}:{item['start']})", Code(item["lines"], "cs"))
    return report


def main(argv=None, settings_file=None, environ=None, out=None, run=subprocess.run):
    out = out or sys.stdout
    environ = os.environ if environ is None else environ
    try:
        args = _parser().parse_args(list(sys.argv[1:] if argv is None else argv))
    except SystemExit as stop:
        return EXIT_USAGE if stop.code else EXIT_OK
    if not args.report:
        _parser().print_help(out)
        return EXIT_USAGE
    settings_file = args.settings or settings_for(args.root, settings_file)
    redact = keep if args.no_redact else home_redactor()
    progress = Progress(environ)
    data = {}
    code = EXIT_OK
    try:
        decompiles = decompile_folder(args.cache, environ, settings_file)
        if args.report == "show":
            clones = kit_paths.resolve(*CLONES, None, args.clones, environ, settings_file)
            places = corpora(args.root, clones, decompiles)
            cache = derived.folder(index.CACHE_FOLDER, args.cache, environ, settings_file)
            found = show(args.name, places, cache, args.lines, progress)
            data = {"name": plain_name(args.name), "found": found, "looked_in": len(places)}
            report = _report_show(args.name, found, places)
        elif args.report == "holder":
            progress("Reading the game's and mods' assemblies")
            game, managed, owners = assemblies(args, environ, settings_file)
            tool = ensure_reader(environ, run=run)
            records = read_members(tool, type_candidates(args.name), managed + [Path(p) for p in owners], run=run)
            found = holders(args.name, records, owners, managed)
            data = {"name": plain_name(args.name), "holders": found}
            report = Report(f"rimworld-code holder {args.name}")
            report.section("Declared in", Table(["Type", "Assembly", "Mod", "File"],
                                                [[h["type"], h["assembly"], h["mod"] or "", h["path"]] for h in found]))
        else:
            dll = Path(args.assembly)
            if dll.suffix.lower() != ".dll" or not dll.is_file():
                raise index.CodeError(f"No assembly at {dll}")
            progress("Decompiling " + dll.name, detail="Reading the file, never loading or running it")
            game = paths.game_path(args.game, environ, settings_file)
            references = [Path(game)] if Path(game).is_dir() else []
            folder, built = compare.decompile(dll, decompiles, lambda: compare._find_decompiler(None, environ, settings_file),
                                              references, run=run)
            compare.evict(decompiles)
            data = {"assembly": dll.name, "folder": str(folder), "built": built}
            report = Report(f"rimworld-code decompile {dll.name}")
            report.lines.append(f"{'Decompiled' if built else 'Already decompiled'}: {dll.name}, kept in the kit's cache.")
    except (index.CodeError, PatchesError, OSError) as error:
        report, code = Report(f"rimworld-code {args.report}: error", [str(error)]), EXIT_FAILED
        data = {"ok": False, "reason": str(error)}
    if args.json:
        print(envelope_text("rimworld-code", report, redact, data), file=out)
    else:
        print(render_markdown(report, redact), file=out)
    return code


MANIFEST = {"game": "rimworld", "parser": _parser, "effect": READS,
            "question": "What does another author's code look like?",
            "reports": {"show": {"effect": READS, "surface": "other-code"},
                        "holder": {"effect": READS, "surface": "other-code"},
                        "decompile": {"effect": RUNS, "surface": "other-code",
                                      "note": "runs ilspycmd, which reads an assembly without loading or running it; writes "
                                              "only into the kit's cache"}}}
