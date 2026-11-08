"""python -m phobos_modkit <command> [options]: run one of the kit's tools."""
from __future__ import annotations

import sys


def _rimworld_log(argv):
    from .games.rimworld.cli import main
    return main(argv)


def _rimworld_save(argv):
    from .games.rimworld.save_cli import main
    return main(argv)


def _rimworld_defs(argv):
    from .games.rimworld.defs_cli import main
    return main(argv)


def _steam_workshop(argv):
    from .steam.workshop_cli import main
    return main(argv)


def _rimworld_workshop(argv):
    from .games.rimworld.workshop_cli import main
    return main(argv)


def _steam_publish(argv):
    from .steam.publish.cli import main
    return main(argv)


def _release(argv):
    from .release.cli import main
    return main(argv)


def _rimworld_settings(argv):
    from .games.rimworld.settings_cli import main
    return main(argv)


def _rimworld_startup(argv):
    from .games.rimworld.startup_cli import main
    return main(argv)


def _rimworld_readiness(argv):
    from .games.rimworld.readiness_cli import main
    return main(argv)


def _rimworld_patches(argv):
    from .games.rimworld.patches_cli import main
    return main(argv)


def _code(argv):
    from .code.cli import main
    return main(argv)


def _gate(argv):
    from .gate.cli import main
    return main(argv)


COMMANDS = {
    "rimworld-log": (_rimworld_log, "summarise a RimWorld Player.log and name the mods involved"),
    "rimworld-save": (_rimworld_save, "answer questions about a RimWorld save from a fast index"),
    "rimworld-defs": (_rimworld_defs, "which active mods define and patch each RimWorld Def"),
    "rimworld-settings": (_rimworld_settings, "the player's RimWorld mod settings, files left behind, changes since a snapshot"),
    "rimworld-patches": (_rimworld_patches, "which active mods patch which methods with Harmony, from their metadata"),
    "rimworld-startup": (_rimworld_startup, "how long RimWorld takes to start, the costliest mods, what changed between launches"),
    "rimworld-readiness": (_rimworld_readiness, "which active mods are ready for a game version, and which are likeliest to break"),
    "rimworld-workshop": (_rimworld_workshop, "what players report about RimWorld mods on the Workshop lately"),
    "steam-workshop": (_steam_workshop, "what players report about Workshop items lately, by ID or URL"),
    "steam-publish": (_steam_publish, "release notes, staging and the owner-run Workshop uploader"),
    "release": (_release, "changelog checks, version constants kept in step, history screen"),
    "code": (_code, "find, outline and show C# declarations, and every line using a name"),
    "gate": (_gate, "run a repository's checks before a commit and report only what failed"),
}


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    if not argv or argv[0] in ("-h", "--help") or argv[0] not in COMMANDS:
        print("usage: python -m phobos_modkit <command> [options]\n\ncommands:")
        for name, (_, summary) in COMMANDS.items():
            print(f"  {name:14} {summary}")
        return 0 if argv and argv[0] in ("-h", "--help") else 2
    run, _ = COMMANDS[argv[0]]
    return run(argv[1:])


if __name__ == "__main__":
    sys.exit(main())
