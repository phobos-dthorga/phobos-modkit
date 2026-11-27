"""RimWorld's side of rimworld-perf: the process, who owns each module in a trace, and the named parts of the main loop.

RimWorld 1.7 runs on Microsoft's CoreCLR runtime (its install holds coreclr.dll and hostfxr.dll, seen November 2026) and opens the
standard .NET diagnostics pipe, which is what lets dotnet-trace record it. Owners are worked out from what is installed: the game's
own assemblies (Assembly-CSharp and RimWorld), the engine and libraries Ludeon ships beside them, .NET's, Harmony's, and each active
mod's assemblies for the game's version, in load order.
"""
from __future__ import annotations

import fnmatch
import json
from pathlib import Path

from ...sampling import DOTNET_THREADS, ENGINE, GAME, LIBRARY, MOD, RUNTIME, UNKNOWN, Owner
from . import loading, paths
from .mods import ModIndex, default_roots
from .patches import mod_assemblies

PROCESS_NAME = "RimWorld"
GAME_NAME = "RimWorld"
GAME_ASSEMBLIES = frozenset({"assembly-csharp", "rimworld"})
RUNTIME_NAMES = frozenset({"mscorlib", "netstandard", "windowsbase", "system"})
RUNTIME_PREFIXES = ("system.", "microsoft.")
LIBRARIES = {"0harmony": "Harmony", "harmony": "Harmony", "prepatcher": "Prepatcher"}
LIBRARY_PREFIXES = {"monomod": "Harmony"}
ENGINE_NAME = "the engine and Ludeon's libraries"
PHASES_FILE = Path(__file__).with_name("perf-phases.json")
THREADS_FILE = Path(__file__).with_name("perf-threads.json")


def phases():
    """([(label, [patterns])], the ticking phase's label) from the data file."""
    data = json.loads(PHASES_FILE.read_text(encoding="utf-8"))
    return [(label, list(patterns)) for label, patterns in data["phases"]], data["ticking"]


def thread_roles():
    """[(name, [patterns])]: RimWorld's and its engine's threads from the data file, then .NET's own (sampling.DOTNET_THREADS)."""
    data = json.loads(THREADS_FILE.read_text(encoding="utf-8"))
    return [(name, list(patterns)) for name, patterns in data["threads"]] + DOTNET_THREADS


def install_assemblies(game):
    """Lower-case stems of the DLLs in the game's install folder (not its Mods folder)."""
    game = Path(game) if game else None
    if game is None or not game.is_dir():
        return set()
    return {p.stem.lower() for p in game.glob("*.dll")}


def active_mod_assemblies(game, workshop, config):
    """{lower-case assembly stem: mod name} for the active mods, the first in load order winning; and the stems more than one ships."""
    mods_config = Path(config) / "ModsConfig.xml"
    if not mods_config.is_file():
        return {}, set()
    version, _, ids = loading.read_mods_config(mods_config)
    index = ModIndex.scan(default_roots(game, workshop))
    active = loading.resolve_active(index.mods, ids)
    owners, shared = {}, set()
    for entry, dll in mod_assemblies(active, version):
        stem = dll.stem.lower()
        if stem in owners and owners[stem] != entry.mod.name:
            shared.add(stem)
            continue
        owners.setdefault(stem, entry.mod.name)
    return owners, shared


def classify(modules, install, mod_owners):
    """{module: Owner} for every module in a trace."""
    result = {}
    for module in modules:
        key = module.lower()
        if key in mod_owners:
            result[module] = Owner(MOD, mod_owners[key])
        elif key in GAME_ASSEMBLIES:
            result[module] = Owner(GAME, GAME_NAME)
        elif key in LIBRARIES:
            result[module] = Owner(LIBRARY, LIBRARIES[key])
        elif any(key.startswith(p) for p in LIBRARY_PREFIXES):
            result[module] = Owner(LIBRARY, next(v for p, v in LIBRARY_PREFIXES.items() if key.startswith(p)))
        elif key in RUNTIME_NAMES or key.startswith(RUNTIME_PREFIXES):
            result[module] = Owner(RUNTIME, ".NET")
        elif key in install:
            result[module] = Owner(ENGINE, ENGINE_NAME)
        else:
            result[module] = Owner(UNKNOWN, module or "?")
    return result


def module_owners(modules, game=None, workshop=None, config=None, environ=None, settings_file=None):
    """({module: Owner}, notes): who owns each module, against the game's install and the mod list as they are now.

    Best effort: when the mod list cannot be read, no module is put down to a mod and a note says why.
    """
    notes, install, mod_owners = [], set(), {}
    try:
        game_folder = paths.game_path(game, environ, settings_file)
        install = install_assemblies(game_folder)
        workshop_folder = paths.workshop_path(game_folder, workshop, environ, settings_file)
        config_folder = paths.config_path(config, environ, settings_file)
        mod_owners, shared = active_mod_assemblies(game_folder, workshop_folder, config_folder)
        if shared:
            notes.append(f"{len(shared)} assembly names are shipped by more than one active mod; each counts for the first in load order.")
    except Exception as error:  # noqa: BLE001 - a report without mod names beats no report
        notes.append(f"The mod list could not be read ({error}), so nothing is put down to a mod.")
    return classify(modules, install, mod_owners), notes


# The game's own loop, for finding the main thread in a snapshot: the named parts, and the root that calls them each frame.
MAIN_LOOP_ROOTS = ("Verse.Root*",)


def loop_patterns():
    return [p for _, patterns in phases()[0] for p in patterns] + list(MAIN_LOOP_ROOTS)


def is_main_loop(stack):
    """True when a thread's stack runs the game's loop: one of its frames matches a named part or the loop's root."""
    patterns = loop_patterns()
    return any(fnmatch.fnmatchcase(f.method, p) for f in stack.frames for p in patterns)


def phase_of_frames(frames):
    """The named part of the loop a stack (innermost first) is in: the first whose pattern matches, from the root; None if none."""
    named, _ = phases()
    for item in reversed(frames):
        for label, patterns in named:
            if any(fnmatch.fnmatchcase(item.method, p) for p in patterns):
                return label
    return None
