"""Other programs: what the kit's tools use beyond Python, whether each is on this PC, what needs it, and where to get it.

`programs status` answers it in one place (owner, 20 November 2026: D'thorga Companion is to be released for others, and its
release audit's B7 asks that each tool say what it needs). It only looks: it finds programs on the PATH, in the kit's folders and
where settings name them, and runs none of them. A game's own programs come from its adapter (`games/<game>/programs.py`, a
`PROGRAMS` list), so the core names no game.

`programs bundle --out FOLDER` builds the kit's own compiled tools (the Rust XML indexer and the .NET assembly and heap readers) and
copies them into one folder, for an installer to carry beside the kit (the release audit's A4): a PC that installs them needs neither Rust
nor the .NET SDK to read a save, and only the .NET runtime to read assemblies. The kit looks in that folder before building
anything (`native.bundled_dir`).
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import importlib
import json
import os
from pathlib import Path
import pkgutil
import shutil
import subprocess
import sys
from typing import Callable

from . import __version__, assemblies, code_names, heap_reader, native
from .dotnet_tools import ToolBuildError
from .manifest import READS, WRITES
from .report import Report, Table, envelope_text, home_redactor, keep, render_markdown

EXIT_OK, EXIT_FAILED, EXIT_USAGE = 0, 1, 2
STAMP = "bundle.json"
BUNDLE_FORMAT = 1
DOTNET_MAJOR = "10."


@dataclass
class Found:
    """Whether a program is here: where, and how it was found or what happens without it."""
    here: bool
    where: str | None
    how: str


@dataclass
class Program:
    key: str
    name: str
    needed_by: str
    get: str
    find: Callable[[dict], Found]


def _on_path(name, which=shutil.which):
    found = which(name)
    return Path(found) if found else None


def _git(environ):
    found = _on_path("git")
    return Found(True, str(found), "on the PATH") if found else Found(False, None, "not on the PATH")


def _xml_index(environ):
    path = native.tool_path("xml-index", environ=environ)
    if not path.is_file():
        return Found(False, None, "not built: the first save read builds it with Rust's cargo, when Rust is installed")
    bundled = native.bundled_dir(environ) in path.parents
    return Found(True, str(path), "came with the installer" if bundled else "built on this PC")


def _dotnet_tool(tool):
    """How one of the kit's C# tools is found: as an installer brought it, as built here, or not yet built."""
    def find(environ):
        bundled = tool.bundled_path(environ)
        if bundled is not None:
            return Found(True, str(bundled), "came with the installer; runs with the .NET 10 runtime")
        built = tool.built_path(environ)
        if built.is_file():
            return Found(True, str(built), "built on this PC")
        return Found(False, None, "not built: the first use builds it with the .NET SDK, when it is installed")
    return find


_reader = _dotnet_tool(assemblies.TOOL)
# What a bundle carries, each in its own folder; the names reader since 1.111.0.
DOTNET_TOOLS = (assemblies.TOOL, heap_reader.TOOL, code_names.TOOL)


def dotnet_versions(dotnet):
    """(runtimes, sdks): the version folders beside a dotnet program, read from its folders, never by running it."""
    root = Path(dotnet).resolve().parent

    def versions(folder):
        try:
            return sorted(p.name for p in folder.iterdir() if p.is_dir())
        except OSError:
            return []
    return versions(root / "shared" / "Microsoft.NETCore.App"), versions(root / "sdk")


def _dotnet(environ):
    found = _on_path("dotnet")
    if not found:
        return Found(False, None, "not on the PATH")
    runtimes, sdks = dotnet_versions(found)
    ten = [v for v in runtimes if v.startswith(DOTNET_MAJOR)]
    sdk_ten = [v for v in sdks if v.startswith(DOTNET_MAJOR)]
    if not ten:
        return Found(False, str(found), f"here, but without the .NET 10 runtime (has {', '.join(runtimes) or 'none'})")
    return Found(True, str(found), f"runtime {ten[-1]}" + (f", SDK {sdk_ten[-1]}" if sdk_ten else ", no SDK"))


def _diagnostics(environ):
    from . import dotnet_diagnostics as diagnostics
    found = {name: diagnostics.tool_path(name, environ) for name in diagnostics.RECORDING}
    if all(found.values()):
        return Found(True, str(found[diagnostics.TRACE].parent), "installed")
    return Found(False, None, "not installed: the first watch or recording installs them, when the .NET SDK is here")


def _ilspycmd(environ):
    from . import paths
    from .code import compare
    named = paths.resolve(*compare.DECOMPILER, None, None, environ)
    if named is not None:
        return (Found(True, str(named), "named in the settings") if Path(named).is_file()
                else Found(False, str(named), "named in the settings, but not there"))
    found = _on_path("ilspycmd")
    return Found(True, str(found), "on the PATH") if found else Found(False, None, "not on the PATH or named in the settings")


def _steam(environ):
    from .game_files import steam_root
    root = steam_root(environ)
    return (Found(True, str(root), "installed") if root and (Path(root) / "steamapps").is_dir()
            else Found(False, str(root) if root else None, "not found where it is usually installed"))


CORE = [
    Program("git", "git", "Every repository's history: Home, Changes, the Timeline, the code viewer, What changed",
            "Git for Windows, https://git-scm.com", _git),
    Program("xml-index", "The kit's XML indexer", "Reading large XML files fast, such as a game's saves",
            "Comes with D'thorga Companion's installer; or Rust from https://rustup.rs, and the kit builds it", _xml_index),
    Program("assembly-reader", "The kit's assembly reader",
            "Reading .NET code without running it: the Code map's C# links, Harmony patches, what our code names",
            "Comes with D'thorga Companion's installer and needs the .NET 10 runtime; or the .NET 10 SDK, and the kit builds it",
            _reader),
    Program("heap-reader", "The kit's heap reader",
            "Looking inside a running game: what is in its memory, any object's values, and why something is still there",
            "Comes with D'thorga Companion's installer and needs the .NET 10 runtime; or the .NET 10 SDK, and the kit builds it",
            _dotnet_tool(heap_reader.TOOL)),
    Program("names-reader", "The kit's names reader",
            "Following a name in C# code to where it is declared: what each name is, read from source with Roslyn",
            "Comes with D'thorga Companion's installer and needs the .NET 10 runtime; or the .NET 10 SDK, and the kit builds it",
            _dotnet_tool(code_names.TOOL)),
    Program("dotnet", ".NET 10",
            "Running the assembly, heap and names readers; building them and the diagnostics tools needs the SDK",
            "Microsoft, https://dotnet.microsoft.com/download (the runtime, or the SDK to build)", _dotnet),
    Program("dotnet-diagnostics", "Microsoft's .NET diagnostics tools",
            "Watching a running game's memory, and where it spends its time",
            "The kit installs them itself, with the .NET 10 SDK", _diagnostics),
    Program("ilspycmd", "ILSpy's command line (ilspycmd)",
            "Reading another author's code from a .dll, and comparing two builds",
            "With the .NET SDK: dotnet tool install --global ilspycmd", _ilspycmd),
    Program("steam", "Steam", "Game files, adding a game from Steam, and the Workshop's reports",
            "Valve, https://store.steampowered.com/about", _steam),
]


def game_programs():
    """Every game adapter's own programs, from `games/<game>/programs.py` where one exists; [(game, Program)]."""
    from . import games
    found = []
    for module in sorted(pkgutil.iter_modules(games.__path__), key=lambda m: m.name):
        if not module.ispkg:
            continue
        try:
            adapter = importlib.import_module(f"{games.__name__}.{module.name}.programs")
        except ModuleNotFoundError:
            continue
        found.extend((module.name, program) for program in getattr(adapter, "PROGRAMS", []))
    return found


def status(environ=None):
    """Every program, core first, then each game's: what it is, what needs it, whether it is here and where to get it."""
    environ = os.environ if environ is None else environ
    rows = []
    for game, program in [(None, p) for p in CORE] + game_programs():
        try:
            found = program.find(environ)
        except Exception as problem:  # noqa: BLE001 - a lookup that fails is reported as such, never a crash of the report
            found = Found(False, None, f"could not be looked for: {problem}")
        rows.append({"key": program.key, "name": program.name, "game": game, "neededBy": program.needed_by,
                     "get": program.get, "here": found.here, "where": found.where, "how": found.how})
    return {"python": sys.version.split()[0], "programs": rows,
            "missing": sum(1 for r in rows if not r["here"])}


def bundle(out, environ=None, run=subprocess.run, which=shutil.which):
    """Builds the kit's compiled tools and copies them into `out`: `xml-index[.exe]`, `assemblies/` and `heap/`. Needs cargo and the .NET
    SDK on the PC that builds. Writes `bundle.json` (the kit's version, and each file) last, so a half-made folder has none."""
    environ = os.environ if environ is None else environ
    out = Path(out)
    if not out.is_absolute():
        raise native.ToolMissing("the bundle folder must be a full path")
    (out / STAMP).unlink(missing_ok=True)
    native.build_tools(environ=environ, run=run)
    indexer = native.build_dir(environ) / "release" / native.program_name("xml-index")
    if run is subprocess.run and not indexer.is_file():
        raise native.ToolMissing(f"cargo finished, but {indexer} is not there")
    out.mkdir(parents=True, exist_ok=True)
    if indexer.is_file():
        shutil.copy2(indexer, out / indexer.name)
    for tool in DOTNET_TOOLS:
        folder = out / tool.folder
        shutil.rmtree(folder, ignore_errors=True)
        tool.publish(folder, environ, run, which)
    files = sorted(str(p.relative_to(out)).replace("\\", "/") for p in out.rglob("*") if p.is_file() and p.name != STAMP)
    (out / STAMP).write_text(json.dumps({"format": BUNDLE_FORMAT, "kit": __version__, "files": files}, indent=2) + "\n",
                             encoding="utf-8", newline="\n")
    return {"folder": str(out), "kit": __version__, "files": files}


def _parser():
    p = argparse.ArgumentParser(prog="programs", description=__doc__.split("\n\n")[0],
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="report", required=True)
    s = sub.add_parser("status", help="every other program the tools use: here or not, what needs it, where to get it")
    s.add_argument("--json", action="store_true", help="print JSON instead of Markdown")
    s.add_argument("--no-redact", action="store_true", help="show the home folder instead of ~")
    b = sub.add_parser("bundle", help="build the kit's compiled tools and copy them into one folder, for an installer")
    b.add_argument("--out", required=True, help="the folder to fill (a full path)")
    b.add_argument("--json", action="store_true", help="print JSON instead of Markdown")
    b.add_argument("--no-redact", action="store_true", help="show the home folder instead of ~")
    return p


def main(argv=None, out=None, environ=None):
    out = out or sys.stdout
    try:
        args = _parser().parse_args(list(sys.argv[1:] if argv is None else argv))
    except SystemExit as stop:
        return EXIT_USAGE if stop.code else EXIT_OK
    redact = keep if args.no_redact else home_redactor()
    if args.report == "bundle":
        try:
            made = bundle(args.out, environ)
        except (native.ToolMissing, ToolBuildError) as failed:
            out.write((envelope_text("programs", Report("Not bundled"), redact, {"ok": False, "refusal": str(failed)})
                       if args.json else f"Not bundled: {failed}") + "\n")
            return EXIT_FAILED
        report = Report(f"Bundled the kit's compiled tools ({len(made['files'])} files)")
        report.section("Files", Table(["File"], [[f] for f in made["files"]]))
        out.write((envelope_text("programs", report, redact, made) if args.json else render_markdown(report, redact)) + "\n")
        return EXIT_OK
    found = status(environ)
    title = ("Programs: everything the tools use is here" if not found["missing"]
             else f"Programs: {found['missing']} of {len(found['programs'])} not here")
    report = Report(title)
    report.lines.append(f"The tools run on Python {found['python']}. Each program below is needed only by what it names; "
                        "nothing else stops working without it.")
    rows = [[p["name"] + (f" ({p['game']})" if p["game"] else ""), "here" if p["here"] else "not here", p["how"],
             p["neededBy"], p["get"]] for p in found["programs"]]
    report.section("Programs", Table(["Program", "Here?", "How", "Needed by", "Where to get it"], rows))
    out.write((envelope_text("programs", report, redact, found) if args.json else render_markdown(report, redact)) + "\n")
    return EXIT_OK


MANIFEST = {"game": None, "parser": _parser, "effect": READS,
            "reports": {"status": {"question": "Which other programs do the tools use, and are they on this PC?",
                                   "note": "looks only: runs none of them"},
                        "bundle": {"effect": WRITES,
                                   "note": "builds the kit's compiled tools with cargo and the .NET SDK, and copies them into "
                                           "the folder named, for an installer"}}}
