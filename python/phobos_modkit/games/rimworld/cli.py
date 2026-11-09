"""rimworld-log: summarise a RimWorld Player.log, compare it with the run before, and name the mods involved.

    python -m phobos_modkit rimworld-log                  Player.log against Player-prev.log, as Markdown
    python -m phobos_modkit rimworld-log --show 1a2b3c4d  one signature in full
    python -m phobos_modkit rimworld-log some.log --no-previous --json report.json

Reads the log while the game runs. Writes nothing unless --json names a file. The user's home folder is shown as
~ unless --no-redact is given, so the output can be pasted into a bug report.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import sys

from ...logs import render
from ...logs.triage import build_report
from ...report import envelope_text
from ...textfile import read_text_shared
from . import log as rimworld_log
from . import paths
from .mods import ModIndex, default_roots
from ...manifest import READS

EXIT_OK, EXIT_NOT_FOUND, EXIT_USAGE = 0, 1, 2


def _parser():
    p = argparse.ArgumentParser(prog="rimworld-log", description=__doc__.split("\n\n")[0],
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("log", nargs="?", help=f"the log to read (default: {paths.LOG_NAME} in the logs folder)")
    p.add_argument("--previous", help=f"the log to compare with (default: {paths.PREVIOUS_LOG_NAME} beside a "
                                      f"{paths.LOG_NAME})")
    p.add_argument("--no-previous", action="store_true", help="do not compare with another log")
    p.add_argument("--show", metavar="ID", help="print one signature in full (an ID, or the start of one)")
    p.add_argument("--top", type=int, default=20, help="signatures to list (default 20)")
    p.add_argument("--levels", default=",".join(render.DEFAULT_LEVELS),
                   help="levels to list, comma-separated (default %(default)s; add INFO for everything)")
    p.add_argument("--json", metavar="FILE", help="also write the full report as JSON to FILE; - prints only JSON")
    p.add_argument("--logs", help="the logs folder (else RIMWORLD_LOGS_PATH, the settings file, the default)")
    p.add_argument("--game", help="the RimWorld folder, for naming mods (else RIMWORLD_PATH, settings, default)")
    p.add_argument("--workshop", help="the Workshop content folder (else RIMWORLD_WORKSHOP_PATH, settings, beside "
                                      "the game)")
    p.add_argument("--no-mods", action="store_true", help="do not read installed mods; clues stay unnamed")
    p.add_argument("--settings", help="a JSON settings file with rimworldLogsPath, rimworldPath and workshopPath")
    p.add_argument("--no-redact", action="store_true", help="show the home folder instead of ~")
    return p


def _load(path, index):
    log = rimworld_log.parse(read_text_shared(path), Path(path).name)
    if index is not None:
        index.annotate(log.entries)
    return log


def main(argv=None, settings_file=None, environ=None, out=None):
    out = out or sys.stdout
    args = _parser().parse_args(argv)
    settings_file = args.settings or settings_file

    log_path = Path(args.log) if args.log else paths.logs_path(args.logs, environ, settings_file) / paths.LOG_NAME
    if not log_path.is_file():
        print(f"No log at {log_path}. Name one, or set the logs folder with --logs.", file=sys.stderr)
        return EXIT_USAGE
    previous_path = None
    if args.previous:
        previous_path = Path(args.previous)
        if not previous_path.is_file():
            print(f"No log at {previous_path} to compare with.", file=sys.stderr)
            return EXIT_USAGE
    elif not args.no_previous and log_path.name.lower() == paths.LOG_NAME.lower():
        candidate = log_path.with_name(paths.PREVIOUS_LOG_NAME)
        previous_path = candidate if candidate.is_file() else None

    index, mod_note = None, ""
    if not args.no_mods:
        game = paths.game_path(args.game, environ, settings_file)
        workshop = paths.workshop_path(game, args.workshop, environ, settings_file)
        index = ModIndex.scan(default_roots(game, workshop))
        if not index.mods:
            mod_note = f"No installed mods were found under {game} or {workshop}, so clues are not named."
    else:
        mod_note = "Installed mods were not read (--no-mods), so clues are not named."

    log = _load(log_path, index)
    if mod_note:
        log.limits.append(mod_note)
    previous = _load(previous_path, index) if previous_path else None
    if previous is not None:
        log.notices += rimworld_log.comparison_notices(log, previous)
    report = build_report(log, previous)
    redact = None if args.no_redact else render.home_redactor()
    levels = tuple(level.strip().upper() for level in args.levels.split(",") if level.strip())

    if args.show:
        found = report.find(args.show)
        if found is None:
            matches = [g.id for g in report.groups if g.id.startswith(args.show)]
            reason = f"several signatures start with {args.show}: {', '.join(matches[:10])}" if matches else \
                f"no signature starts with {args.show}"
            print(f"Nothing shown: {reason}.", file=sys.stderr)
            return EXIT_NOT_FOUND
        out.write(render.group_detail(report, found, redact=redact) + "\n")
        return EXIT_OK

    if args.json:
        data = envelope_text("rimworld-log", render.summary_report(report, args.top, levels), redact,
                             render.to_json(report, redact=redact))
        if args.json == "-":
            out.write(data + "\n")
            return EXIT_OK
        Path(args.json).write_text(data + "\n", encoding="utf-8")
    out.write(render.to_markdown(report, top=args.top, levels=levels, redact=redact) + "\n")
    return EXIT_OK


MANIFEST = {"game": "rimworld", "parser": _parser, "effect": READS,
            "question": "Why did the game log errors?"}
