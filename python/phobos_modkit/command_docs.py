"""command-docs: each command's doc lists its reports and options, and the README its commands, generated from the manifest.

    command-docs              check: name each doc whose generated block is missing or out of date (fails when one is)
    command-docs --write      write every block that is missing or out of date

A doc keeps its own words; only the text between `<!-- generated: options COMMAND -->` and `<!-- end generated -->` is
generated, from the command's own parser (`manifest`), so it cannot drift from what the command accepts. The README's command
index sits between `<!-- generated: command index -->` and the same end mark. config/command-docs.json says which doc holds each
command. A doc without a block gains a "Reports and options" section at its end. It writes only those files, and only with --write.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass, field
import json
from pathlib import Path
import re
import sys

from . import generated_blocks as blocks
from . import manifest as kit_manifest
from .generated_blocks import END, append_section, replace_block, start  # noqa: F401  (END and start: callers' names)
from .manifest import READS, WRITES
from .markdown import table
from .report import Bullets, Report, Table, envelope_text, home_redactor, keep, render_markdown

EXIT_OK, EXIT_FAILED, EXIT_USAGE = 0, 1, 2
CONFIG = "config/command-docs.json"
CONFIG_FORMAT = 1
KIT_ROOT = Path(__file__).resolve().parents[2]
INDEX_KEY = "command index"
SECTION = "## Reports and options"
INDEX_SECTION = "## Commands"
CELL = 10_000  # a doc's cells are never cut
NOTE = ("Generated from the command's own parser by `python -m phobos_modkit command-docs --write`: change a help text in the "
        "parser, not here.")
EFFECTS = {kit_manifest.READS: "reads only", kit_manifest.ONLINE: "reads public pages online",
           kit_manifest.WRITES: "writes", kit_manifest.RUNS: "runs other programs",
           kit_manifest.OWNER_PRESS: "only on the owner's own press", kit_manifest.OWNER_ONLY: "only the owner runs it"}
_DEFAULT_IN_HELP = re.compile(r"\(default:? ([^)]+)\)")


def options_key(command):
    return f"options {command}"


# ---- Plain text for a cell ----

def _text(value):
    """Help text safe in a Markdown cell: stars and angle brackets shown as typed, and every --flag as code."""
    return _flags((value or "").replace("*", "\\*").replace("<", "\\<"))


def _sentence(value):
    value = (value or "").strip()
    if not value:
        return ""
    value = value[0].upper() + value[1:]
    return value if value.endswith((".", "?", "!")) else value + "."


def _flags(text):
    """Every --flag in text as code."""
    return re.sub(r"(?<![`\w])(--[\w-]+)", r"`\1`", text)


def effect_text(report):
    said = EFFECTS.get(report["effect"], report["effect"])
    when = report.get("when")
    if not when:
        return said
    return f"{said}, {'with' if when.startswith('--') else 'when'} {_flags(when)}"


# ---- One command's block ----

def _shown_name(option):
    metavar = option.get("metavar")
    if option["positional"]:
        name = metavar or option["name"].upper()
        return f"`{name} ...`" if option["repeatable"] else f"`{name}`"
    if option["kind"] == "flag":
        return f"`{option['name']}`"
    return f"`{option['name']} {metavar or ('N' if option['kind'] in ('integer', 'number') else 'VALUE')}`"


def _help_cell(option):
    text = _text(option["help"])
    extras = []
    if option["positional"] and not option["required"]:
        text = f"(optional) {text}".strip()
    elif option["required"] and not option["positional"]:
        extras.append("Required.")
    choices = option.get("choices") or []
    if choices and not all(c in (option["help"] or "") for c in choices):
        extras.append("One of " + ", ".join(f"`{c}`" for c in choices) + ".")
    if option["repeatable"] and not option["positional"] and "repeat" not in (option["help"] or "").lower():
        extras.append("Repeatable.")
    if not extras:
        return text
    text = text.rstrip()
    return " ".join([text + ("" if not text or text.endswith((".", "?", "!")) else ".")] + extras).strip()


def _default_cell(option):
    value = option.get("default")
    if value is None or value is False or value == "" or option["kind"] == "flag" and value is not True:
        return ""
    return "on" if value is True else f"`{value}`"


def _identity(option):
    return (option["name"], option["help"], option.get("default"), option["kind"], tuple(option.get("choices") or ()),
            option["required"], option["repeatable"], option["positional"])


def _where(names, everyone):
    if len(names) == len(everyone):
        return "all"
    left = [n for n in everyone if n not in names]
    if len(everyone) >= 5 and len(left) <= 2:
        return "all but " + ", ".join(f"`{n}`" for n in left)
    return ", ".join(f"`{n}`" for n in names)


def _brief(command, config):
    """The options every report takes with the same help, named in config's "brief": said once in a sentence."""
    reports = command["reports"]
    said = []
    for name in config.get("brief", []):
        found = [next((o for o in r["options"] if o["name"] == name), None) for r in reports]
        if all(found) and len({_identity(o) for o in found}) == 1:
            said.append(found[0])
    return said


_relative = blocks.relative


def mismatched_defaults(command):
    """(report, option, the default its help states, the parser's default) wherever the two disagree."""
    found = []
    for report in command["reports"]:
        for option in report["options"]:
            match = _DEFAULT_IN_HELP.search(option["help"] or "")
            value = option.get("default")
            if match and isinstance(value, (int, float)) and not isinstance(value, bool):
                stated = match.group(1).strip().split()[0].rstrip(";,")
                if re.fullmatch(r"-?\d+(\.\d+)?", stated) and float(stated) != float(value):
                    found.append((report["name"], option["name"], stated, value))
    return found


def command_block(command, doc, config):
    """The lines between one command's marks: its reports, its options and what they share."""
    reports = command["reports"]
    named = [r["name"] for r in reports if r["name"]]
    lines = [NOTE, ""]
    if named:
        notes = [r["note"] for r in reports if r.get("note")]
        common = max(set(notes), key=notes.count) if notes else None
        if common and (notes.count(common) < 3 or notes.count(common) * 2 <= len(reports)):
            common = None
        rows = []
        for r in reports:
            said = _sentence(_text(r["help"]))
            if r.get("note") and r["note"] != common:
                said = f"{said} {_sentence(_text(r['note']))}".strip()
            rows.append([f"`{r['name']}`", said, effect_text(r)])
        lines += table(["Report", "What it does", "Effect"], rows, CELL) + [""]
        if common:
            lines += [f"Unless its row says otherwise, each report: {_sentence(_text(common))}", ""]
    else:
        only = reports[0]
        lines += [f"Effect: {effect_text(only)}." + (f" {_sentence(_text(only['note']))}" if only.get("note") else ""), ""]

    brief = _brief(command, config)
    skipped = {o["name"] for o in brief}
    seen, order = {}, []
    for r in reports:
        for option in r["options"]:
            if option["name"] in skipped:
                continue
            key = _identity(option)
            if key not in seen:
                seen[key] = (option, [])
                order.append(key)
            seen[key][1].append(r["name"])
    rows = []
    for key in order:
        option, where = seen[key]
        row = [_shown_name(option), _help_cell(option), _default_cell(option)]
        if named:
            row.insert(1, _where(where, named))
        rows.append(row)
    if rows:
        headers = ["Option", "Reports", "What it does", "Default"] if named else ["Option", "What it does", "Default"]
        lines += table(headers, rows, CELL) + [""]
    elif not brief:
        lines += ["It takes no options.", ""]
    after = []
    if brief:
        who = "Every report also takes" if named else ("It also takes" if rows else "It takes")
        listed = [f"`{o['name']}` ({_text(o['help'])})" for o in brief]
        after.append(f"{who} {', '.join(listed[:-1]) + ' and ' + listed[-1] if len(listed) > 1 else listed[0]}.")
    if any(option["positional"] for option, _ in seen.values()):
        after.append("Names in capitals are given bare, without a flag, in the order shown.")
    if config.get("settingsDoc") and any(option["name"] in config.get("paths", []) and "else " in (option["help"] or "")
                                         for option, _ in seen.values()):
        after.append(f"A path left out is looked for in the order [settings]({_relative(config['settingsDoc'], doc)}) explains: "
                     "an environment variable, the repository's own settings file, the central settings file, then the default.")
    groups = []
    for r in reports:
        for group in r.get("exclusive") or []:
            entry = next((g for g in groups if g[0] == group), None)
            if entry is None:
                groups.append((group, [r["name"]]))
            else:
                entry[1].append(r["name"])
    for group, where in groups:
        place = f" (`{'`, `'.join(where)}`)" if named and len(where) < len(named) else ""
        after.append(f"Only one of {', '.join(f'`{g}`' for g in group)} at a time{place}.")
    if len(after) == 1:
        lines += after + [""]
    elif after:
        lines += [f"- {a}" for a in after] + [""]
    return lines[:-1] if lines and lines[-1] == "" else lines


def index_block(commands, config):
    """The README's command index: one row per command, by name."""
    readme = config.get("readme", "README.md")
    rows = [[f"[`{c['name']}`]({_relative(config['docs'][c['name']], readme)})" if c["name"] in config.get("docs", {})
             else f"`{c['name']}`", c["game"] or "any", _text(c["summary"])]
            for c in sorted(commands, key=lambda c: c["name"])]
    return [f"Generated from the manifest by `python -m phobos_modkit command-docs --write`. Each doc ends with every report and "
            f"option its command takes.", "", *table(["Command", "Game", "What it is for"], rows, CELL)]


# ---- Blocks in a file: the marks, reading and writing are generated_blocks', shared with doc-tables ----

@dataclass
class Doc:
    path: str
    commands: list = field(default_factory=list)
    before: str = None
    after: str = None
    missing: list = field(default_factory=list)   # commands (or the index) whose block was not there
    stale: list = field(default_factory=list)     # whose block was there but out of date
    crlf: bool = False

    @property
    def state(self):
        if self.before is None:
            return "no such file"
        if self.missing:
            return "block missing"
        return "out of date" if self.stale else "current"


def load_config(root):
    path = Path(root) / CONFIG
    config = json.loads(path.read_text(encoding="utf-8"))
    if config.get("schemaVersion") != CONFIG_FORMAT:
        raise ValueError(f"{CONFIG}: schemaVersion {config.get('schemaVersion')} is not {CONFIG_FORMAT}")
    return config


_read = blocks.read


def plan(root, commands=None, config=None):
    """(docs, problems): each file the blocks go in, with its text now and as it should be; and what cannot be generated."""
    root = Path(root)
    commands = kit_manifest.manifest()["commands"] if commands is None else commands
    config = load_config(root) if config is None else config
    mapping = config.get("docs", {})
    names = [c["name"] for c in commands]
    problems = [f"`{n}` has no doc in {CONFIG}" for n in names if n not in mapping]
    problems += [f"{CONFIG} names `{n}`, which is not a command" for n in mapping if n not in names]
    docs = {}
    for command in commands:
        if command["name"] in mapping:
            docs.setdefault(mapping[command["name"]], Doc(mapping[command["name"]])).commands.append(command)
    found = []
    for doc in docs.values():
        path = root / doc.path
        if not path.is_file():
            problems.append(f"{doc.path} does not exist (the doc for {', '.join(c['name'] for c in doc.commands)})")
            found.append(doc)
            continue
        doc.before, doc.crlf = _read(path)
        text, added = doc.before, []
        several = len(doc.commands) > 1
        for command in doc.commands:
            body = command_block(command, doc.path, config)
            text, there = replace_block(text, options_key(command["name"]), body)
            if not there:
                doc.missing.append(command["name"])
                added.append((options_key(command["name"]), f"### `{command['name']}`" if several else None, body))
        if added:
            text = append_section(text, SECTION, added)
        doc.after = text
        doc.stale = [c["name"] for c in doc.commands if c["name"] not in doc.missing] if text != doc.before else []
        found.append(doc)
    readme = config.get("readme")
    if readme:
        doc = Doc(readme, [{"name": INDEX_KEY}])
        path = root / readme
        if not path.is_file():
            problems.append(f"{readme} does not exist (the command index)")
        else:
            doc.before, doc.crlf = _read(path)
            body = index_block(commands, config)
            text, there = replace_block(doc.before, INDEX_KEY, body)
            if not there:
                doc.missing.append(INDEX_KEY)
                text = append_section(text, INDEX_SECTION, [(INDEX_KEY, None, body)])
            doc.after = text
            doc.stale = [INDEX_KEY] if there and text != doc.before else []
        found.append(doc)
    return found, problems


write = blocks.write_changed


# ---- The command ----

def _parser():
    p = argparse.ArgumentParser(prog="command-docs", description=__doc__.split("\n\n")[0],
                                formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__.split("\n\n", 1)[1])
    p.add_argument("--root", help="the kit's repository (default: the one this copy of the kit is in)")
    p.add_argument("--write", action="store_true", help="write the blocks that are missing or out of date; without it, only check")
    p.add_argument("--json", action="store_true", help="print JSON instead of Markdown")
    p.add_argument("--no-redact", action="store_true", help="show the home folder instead of ~")
    return p


def report_of(docs, problems, written, wrote):
    out_of_date = [d for d in docs if d.before is not None and d.after != d.before]
    options = sum(len({_identity(o) for r in c["reports"] for o in r["options"]})
                  for d in docs for c in d.commands if c["name"] != INDEX_KEY)
    if wrote:
        title = f"Command docs: wrote {len(written)} file{'' if len(written) == 1 else 's'}" if written else "Command docs: all current"
    else:
        title = ("Command docs: all current" if not out_of_date
                 else f"Command docs: {len(out_of_date)} file{'' if len(out_of_date) == 1 else 's'} out of date")
    report = Report(title)
    report.lines.append(f"{sum(len(d.commands) for d in docs if d.commands[0]['name'] != INDEX_KEY)} commands in "
                        f"{sum(1 for d in docs if d.commands[0]['name'] != INDEX_KEY)} docs, {options:,} distinct options, "
                        "and the README's command index.")
    if out_of_date and not wrote:
        report.lines.append("Run `python -m phobos_modkit command-docs --write` to bring them up to date.")
    rows = [[d.path, ", ".join(c["name"] for c in d.commands),
             ("written" if d.path in written else d.state) if wrote else d.state] for d in docs if d.state != "current"
            or d.path in written]
    if rows:
        report.section("Files", Table(["Doc", "Commands", "State"], rows))
    if problems:
        report.section("Cannot generate", Bullets(problems))
    mismatches = [f"`{c['name']}{' ' + r if r else ''}` {o}: its help says {stated}, its default is {value}"
                  for d in docs for c in d.commands if c["name"] != INDEX_KEY for r, o, stated, value in mismatched_defaults(c)]
    if mismatches:
        report.section("Help that states another default", Bullets(mismatches))
    data = {"written": written, "problems": problems, "mismatchedDefaults": mismatches,
            "docs": [{"path": d.path, "commands": [c["name"] for c in d.commands], "state": d.state,
                      "missing": d.missing, "stale": d.stale} for d in docs]}
    failed = bool(problems) or (bool(out_of_date) and not wrote)
    return report, data, failed


def main(argv=None, out=None, commands=None):
    out = out or sys.stdout
    try:
        args = _parser().parse_args(list(sys.argv[1:] if argv is None else argv))
    except SystemExit as stop:
        return EXIT_USAGE if stop.code else EXIT_OK
    redact = keep if args.no_redact else home_redactor()
    root = Path(args.root).resolve() if args.root else KIT_ROOT
    try:
        docs, problems = plan(root, commands)
    except (OSError, ValueError) as failed:
        out.write((envelope_text("command-docs", Report("Command docs: cannot read the config"), redact,
                                 {"problems": [str(failed)]}) if args.json else f"Command docs: cannot read the config: {failed}")
                  + "\n")
        return EXIT_FAILED
    written = write(root, docs) if args.write else []
    report, data, failed = report_of(docs, problems, written, args.write)
    out.write((envelope_text("command-docs", report, redact, data) if args.json else render_markdown(report, redact)) + "\n")
    return EXIT_FAILED if failed else EXIT_OK


MANIFEST = {"game": None, "parser": _parser, "effect": READS,
            "reports": {None: {"effect": WRITES, "when": "--write"}},
            "question": "Does every command's doc list all its options?",
            "note": "fails when a block is missing or out of date; with --write, writes only the generated blocks in the kit's docs"}


if __name__ == "__main__":
    sys.exit(main())
