"""python -m phobos_modkit <command> [options]: run one of the kit's tools."""
from __future__ import annotations

import sys


def _rimworld_log(argv):
    from .games.rimworld.cli import main
    return main(argv)


COMMANDS = {
    "rimworld-log": (_rimworld_log, "summarise a RimWorld Player.log and name the mods involved"),
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
