"""python -m phobos_modkit <command> [options]: run one of the kit's tools."""
from __future__ import annotations

from importlib import import_module
import sys

from .commands import COMMANDS


# The oldest Python the kit runs on (the owner's choice of 28 Nov 2026: 3.14, for its built-in zstd compression).
OLDEST_PYTHON = (3, 14)


def main(argv=None):
    if sys.version_info < OLDEST_PYTHON:
        print(f"Phobos ModKit needs Python {'.'.join(map(str, OLDEST_PYTHON))} or newer; this is Python "
              f"{sys.version_info.major}.{sys.version_info.minor}. Install a newer Python from python.org.", file=sys.stderr)
        return 2
    argv = sys.argv[1:] if argv is None else argv
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    if not argv or argv[0] in ("-h", "--help") or argv[0] not in COMMANDS:
        print("usage: python -m phobos_modkit <command> [options]\n\ncommands:")
        for name, (_, summary) in COMMANDS.items():
            print(f"  {name:14} {summary}")
        return 0 if argv and argv[0] in ("-h", "--help") else 2
    module, _ = COMMANDS[argv[0]]
    return import_module(module, __package__).main(argv[1:])


if __name__ == "__main__":
    sys.exit(main())
