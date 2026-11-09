"""One report model for every tool, rendered as Markdown for people and agent sessions, or as JSON for programs.

A report has a title, intro lines (one paragraph, one line each), further opening blocks, and sections. A block is a
paragraph (a plain string), Bullets, a Table or Code. Redaction, such as hiding the home folder, applies to every
piece of text when the report is rendered, so no tool can forget a field.

    report = Report("Things")
    report.lines.append("1,878 things match.")
    report.section("By def", Table(["Def", "Things"], rows, total=1878))
    print(render_markdown(report, redact=home_redactor()))
"""
from __future__ import annotations

from dataclasses import dataclass, field
import json
import os
import re
from pathlib import Path

from . import __version__
from .markdown import CELL_LIMIT, cell

JSON_FORMAT = 1
ENVELOPE_FORMAT = 1
NOTHING = "None."


@dataclass
class Table:
    headers: list
    rows: list
    total: int = None                             # rows in all, when more exist than are shown
    widths: dict = field(default_factory=dict)    # column position -> character limit for its cells
    more: str = "raise --top to see more"         # what to do when rows were cut


@dataclass
class Bullets:
    items: list


@dataclass
class Code:
    lines: list
    language: str = "text"


@dataclass
class Section:
    heading: str
    blocks: list = field(default_factory=list)
    level: int = 2

    @property
    def table(self):
        """The section's first table, or None."""
        return next((b for b in self.blocks if isinstance(b, Table)), None)


@dataclass
class Report:
    title: str
    lines: list = field(default_factory=list)     # the opening paragraph, one line each
    blocks: list = field(default_factory=list)    # further opening blocks, before the first section
    sections: list = field(default_factory=list)

    def section(self, heading, *blocks, level=2):
        found = Section(heading, list(blocks), level)
        self.sections.append(found)
        return found


# ---- Redaction ----

def home_redactor(home=None):
    """A function that replaces the user's home folder with ~ in any text, whichever slashes the text uses."""
    home = str(Path.home() if home is None else home).rstrip("\\/")
    if len(home) < 3:
        return keep
    variants = {home, home.replace("\\", "/"), home.replace("/", "\\")}
    pattern = re.compile("|".join(re.escape(v) for v in sorted(variants, key=len, reverse=True)), re.IGNORECASE)
    return lambda text: pattern.sub("~", text)


def keep(text):
    return text


def _scrub(value, redact):
    return redact(value) if isinstance(value, str) else value


# ---- Markdown ----

def _table_lines(table, redact):
    if not table.rows:
        return [NOTHING]
    limit = lambda i: table.widths.get(i, CELL_LIMIT)
    lines = ["| " + " | ".join(cell(redact(str(h)), limit(i)) for i, h in enumerate(table.headers)) + " |",
             "| " + " | ".join("---" for _ in table.headers) + " |"]
    lines += ["| " + " | ".join(cell(_scrub(v, redact), limit(i)) for i, v in enumerate(row)) + " |"
              for row in table.rows]
    if table.total is not None and table.total > len(table.rows):
        lines += ["", f"Showing {len(table.rows):,} of {table.total:,}; {table.more}."]
    return lines


def _block_lines(block, redact):
    if isinstance(block, str):
        return [redact(block)]
    if isinstance(block, Bullets):
        return [f"- {redact(str(item))}" for item in block.items]
    if isinstance(block, Table):
        return _table_lines(block, redact)
    if isinstance(block, Code):
        return [f"```{block.language}", *(redact(str(line)) for line in block.lines), "```"]
    raise TypeError(f"not a report block: {type(block).__name__}")


def render_markdown(report, redact=None):
    redact = redact or keep
    out = [f"# {redact(report.title)}", ""]
    if report.lines:
        out += [*(redact(line) for line in report.lines), ""]
    for block in report.blocks:
        out += [*_block_lines(block, redact), ""]
    for section in report.sections:
        out += [f"{'#' * section.level} {redact(section.heading)}", ""]
        for block in section.blocks or [NOTHING]:
            out += [*_block_lines(block, redact), ""]
    return "\n".join(out)


# ---- JSON ----

def _block_json(block, redact):
    if isinstance(block, str):
        return {"type": "text", "text": redact(block)}
    if isinstance(block, Bullets):
        return {"type": "bullets", "items": [redact(str(i)) for i in block.items]}
    if isinstance(block, Table):
        return {"type": "table", "headers": [redact(str(h)) for h in block.headers],
                "rows": [[_scrub(v, redact) for v in row] for row in block.rows],
                "total": block.total if block.total is not None else len(block.rows)}
    if isinstance(block, Code):
        return {"type": "code", "language": block.language, "lines": [redact(str(l)) for l in block.lines]}
    raise TypeError(f"not a report block: {type(block).__name__}")


def render_json(report, redact=None):
    redact = redact or keep
    return {"format": JSON_FORMAT, "title": redact(report.title), "lines": [redact(l) for l in report.lines],
            "blocks": [_block_json(b, redact) for b in report.blocks],
            "sections": [{"heading": redact(s.heading), "level": s.level,
                          "blocks": [_block_json(b, redact) for b in s.blocks]} for s in report.sections]}


# ---- The envelope: what every command's --json prints ----

def _scrub_tree(value, redact):
    if isinstance(value, os.PathLike):
        value = os.fspath(value)
    if isinstance(value, str):
        return redact(value)
    if isinstance(value, dict):
        return {key: _scrub_tree(item, redact) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_scrub_tree(item, redact) for item in value]
    return value


def envelope(tool, report, redact=None, data=None):
    """One shape for every command: which tool and kit made it, its report, and any data of its own."""
    redact = redact or keep
    return {"envelope": ENVELOPE_FORMAT, "tool": tool, "kit_version": __version__, "report": render_json(report, redact),
            "data": _scrub_tree(data or {}, redact)}


def envelope_text(tool, report, redact=None, data=None):
    return json.dumps(envelope(tool, report, redact, data), indent=1, ensure_ascii=False, default=str)
