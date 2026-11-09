"""manifest: every command, its reports and options, and what each one reads or changes.

    python -m phobos_modkit manifest           a table of the commands
    python -m phobos_modkit manifest --json    the whole description, in the report envelope's data

A program can build its forms from this, and can refuse what a command must not do from it. Each command's module
declares a MANIFEST beside its argument parser: the game it belongs to (None for core), the parser, and its effect.
Options come from the parser itself, so they cannot drift from what the command accepts.
"""
from __future__ import annotations

import argparse
from importlib import import_module
import sys

from .commands import COMMANDS
from .report import Report, Table, envelope_text, home_redactor, keep, render_markdown

# What a report can do. Reading may still keep derived data in the kit's cache.
READS = "reads"
ONLINE = "reads-online"
WRITES = "writes"
RUNS = "runs"
OWNER_ONLY = "owner-only"
EFFECTS = (READS, ONLINE, WRITES, RUNS, OWNER_ONLY)

EXIT_OK = 0
MANIFEST_FORMAT = 1


def _help(action):
    text = action.help or ""
    return text.replace("%(default)s", str(action.default)).replace("%%", "%")


def _kind(action):
    if action.nargs == 0:
        return "flag"
    return {int: "integer", float: "number"}.get(action.type, "text")


def _option(action):
    default = action.default if isinstance(action.default, (str, int, float, bool)) else None
    return {"name": max(action.option_strings, key=len) if action.option_strings else action.dest,
            "positional": not action.option_strings,
            "kind": _kind(action),
            "required": bool(action.required),
            "repeatable": isinstance(action, argparse._AppendAction) or action.nargs in ("*", "+"),
            "choices": sorted(str(c) for c in action.choices) if action.choices else None,
            "default": default,
            "help": _help(action)}


def _shown(action):
    return not isinstance(action, (argparse._HelpAction, argparse._SubParsersAction)) and action.help != argparse.SUPPRESS


def _options(parser):
    """(options, groups of options that exclude each other) of one parser, in the order it declares them."""
    options = [_option(a) for a in parser._actions if _shown(a)]
    exclusive = [[max(a.option_strings, key=len) for a in group._group_actions]
                 for group in parser._mutually_exclusive_groups]
    return options, exclusive


def _report(name, helptext, parser, declared):
    effect = {"effect": declared["effect"], "when": None, "note": declared.get("note"), "question": declared.get("question")}
    effect.update(declared.get("reports", {}).get(name, {}))
    options, exclusive = _options(parser)
    return {"name": name, "help": helptext, **effect, "options": options, "exclusive": exclusive}


def describe(name, module_name, summary):
    """One command as plain data."""
    declared = import_module(module_name, __package__).MANIFEST
    parser = declared["parser"]()
    subcommands = next((a for a in parser._actions if isinstance(a, argparse._SubParsersAction)), None)
    if subcommands is None:
        reports = [_report(None, summary, parser, declared)]
    else:
        helps = {c.dest: c.help or "" for c in subcommands._choices_actions}
        reports = [_report(key, helps.get(key, ""), sub, declared) for key, sub in subcommands.choices.items()]
    return {"name": name, "summary": summary, "game": declared["game"], "reports": reports}


def manifest():
    return {"manifest": MANIFEST_FORMAT,
            "commands": [describe(name, module, summary) for name, (module, summary) in COMMANDS.items()]}


def _parser():
    p = argparse.ArgumentParser(prog="manifest", description=__doc__.split("\n\n")[0])
    p.add_argument("--json", action="store_true", help="print JSON instead of Markdown")
    p.add_argument("--no-redact", action="store_true", help="show the home folder instead of ~")
    return p


def main(argv=None, out=None):
    args = _parser().parse_args(argv)
    out = out or sys.stdout
    redact = keep if args.no_redact else home_redactor()
    data = manifest()
    report = Report("The kit's commands")
    report.lines.append(f"{len(data['commands'])} commands.")
    report.section("Commands", Table(
        ["Command", "Game", "Reports", "What it does"],
        [(c["name"], c["game"] or "any", ", ".join(r["name"] for r in c["reports"] if r["name"]) or "one", c["summary"])
         for c in data["commands"]]))
    out.write((envelope_text("manifest", report, redact, data) if args.json else render_markdown(report, redact)) + "\n")
    return EXIT_OK


MANIFEST = {"game": None, "parser": _parser, "effect": READS}


if __name__ == "__main__":
    sys.exit(main())
