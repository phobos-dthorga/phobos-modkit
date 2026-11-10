"""One report model for every tool, rendered as Markdown for people and agent sessions, or as JSON for programs.

A report has a title, intro lines (one paragraph, one line each), further opening blocks, and sections. A block is a
paragraph (a plain string), Bullets, a Table, Code or a Chart (text bars in Markdown, a spec a program can draw in
JSON). Redaction, such as hiding the home folder, applies to every
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
# A cell a program can sort as a number: 1,234 or -5.5, with an optional unit.
_NUMBER = re.compile(r"^([+-]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?)\s?(%|ms|s|KB|MB|GB)?$")


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


# What a chart's series or line means, so a program can colour it from its own theme. Never a colour itself.
CHART_ROLES = ("accent", "observed", "comparison", "risk", "success", "neutral")
CHART_KINDS = ("bar", "line")
BAR_WIDTH = 30                                    # characters in the longest text bar


@dataclass
class ChartSeries:
    label: str
    values: list                                  # one number, or None, per category
    role: str = "accent"


@dataclass
class ChartLine:
    """A reference line across the value axis, such as a threshold."""
    label: str
    value: float
    role: str = "neutral"


@dataclass
class Chart:
    """A picture of numbers a report already states: a program draws it, and Markdown shows text bars.

    Every figure in a chart should also be in a table or a line of the report, so nothing depends on seeing it.
    Bars run sideways, one per category; a line chart runs along the categories in order.
    """
    title: str
    description: str                              # one sentence saying what it shows, read in place of the picture
    categories: list
    series: list
    kind: str = "bar"
    unit: str = ""                                # shown after each value, such as % or ms
    value_label: str = ""                         # what the value axis measures
    lines: list = field(default_factory=list)     # ChartLine
    stacked: bool = False

    def __post_init__(self):
        if self.kind not in CHART_KINDS:
            raise ValueError(f"chart kind must be one of {', '.join(CHART_KINDS)}, not {self.kind!r}")
        for part in [*self.series, *self.lines]:
            if part.role not in CHART_ROLES:
                raise ValueError(f"chart role must be one of {', '.join(CHART_ROLES)}, not {part.role!r}")
        for series in self.series:
            if len(series.values) != len(self.categories):
                raise ValueError(f"series {series.label!r} has {len(series.values)} values for "
                                 f"{len(self.categories)} categories")


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


def _chart_value(value, unit):
    if value is None:
        return ""
    text = f"{value:,.0f}" if float(value).is_integer() or abs(value) >= 100 else f"{value:,.1f}"
    return f"{text}{unit}" if unit == "%" else f"{text} {unit}".rstrip()


def _chart_lines(chart, redact):
    """Text bars when each category has one value; otherwise a table of every series."""
    title = f"**{redact(chart.title)}**: {redact(chart.description)}"
    if not chart.categories:
        return [title, "", NOTHING]
    single = all(sum(s.values[i] is not None for s in chart.series) <= 1 for i in range(len(chart.categories)))
    if not single or chart.kind == "line":
        headers = [chart.value_label or "Category", *(s.label for s in chart.series)]
        rows = [(c, *(_chart_value(s.values[i], chart.unit) for s in chart.series))
                for i, c in enumerate(chart.categories)]
        return [title, "", *_table_lines(Table(headers, rows), redact)]
    picked = [next(((s.values[i], s) for s in chart.series if s.values[i] is not None), (None, None))
              for i in range(len(chart.categories))]
    scale = max([abs(v) for v, _ in picked if v is not None] + [abs(line.value) for line in chart.lines] + [0])
    names = [redact(str(c)) for c in chart.categories]
    width = min(max(len(n) for n in names), 32)
    several = len(chart.series) > 1
    out = []
    for name, (value, series) in zip(names, picked):
        bar = "" if value is None or not scale else "█" * max(1, round(abs(value) / scale * BAR_WIDTH))
        note = f"  ({redact(series.label)})" if several and series is not None else ""
        out.append(f"{name[:width]:<{width}} {bar:<{BAR_WIDTH}} {_chart_value(value, chart.unit)}{note}".rstrip())
    marks = "; ".join(f"{redact(line.label)} {_chart_value(line.value, chart.unit)}" for line in chart.lines)
    return [title, "", "```text", *out, "```", *([f"Lines: {marks}."] if marks else [])]


def _block_lines(block, redact):
    if isinstance(block, Chart):
        return _chart_lines(block, redact)
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

def _number(value):
    """(the number, its unit) in a cell, or None when it holds no number."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return value, ""
    match = _NUMBER.match(value.strip()) if isinstance(value, str) else None
    return (float(match.group(1).replace(",", "")), match.group(2) or "") if match else None


def _empty(value):
    return value is None or value == ""


def _column_values(cells):
    """Each cell's number, or all None unless every filled cell is a number in the same unit: a column to sort as text."""
    numbers = [None if _empty(cell) else _number(cell) for cell in cells]
    filled = [number for cell, number in zip(cells, numbers) if not _empty(cell)]
    if not filled or None in filled or len({unit for _, unit in filled}) > 1:
        return [None] * len(cells)
    return [number[0] if number else None for number in numbers]


def _table_values(table):
    """For each row, the number each cell sorts by, or None."""
    columns = [_column_values(list(column)) for column in zip(*table.rows)]
    return [list(row) for row in zip(*columns)]


def _block_json(block, redact):
    if isinstance(block, str):
        return {"type": "text", "text": redact(block)}
    if isinstance(block, Bullets):
        return {"type": "bullets", "items": [redact(str(i)) for i in block.items]}
    if isinstance(block, Table):
        return {"type": "table", "headers": [redact(str(h)) for h in block.headers],
                "rows": [[_scrub(v, redact) for v in row] for row in block.rows],
                "values": _table_values(block),
                "total": block.total if block.total is not None else len(block.rows)}
    if isinstance(block, Code):
        return {"type": "code", "language": block.language, "lines": [redact(str(l)) for l in block.lines]}
    if isinstance(block, Chart):
        return {"type": "chart", "kind": block.kind, "title": redact(block.title),
                "description": redact(block.description), "unit": block.unit, "value_label": redact(block.value_label),
                "stacked": block.stacked, "categories": [redact(str(c)) for c in block.categories],
                "series": [{"label": redact(s.label), "role": s.role,
                            "values": [None if v is None else float(v) for v in s.values]} for s in block.series],
                "lines": [{"label": redact(l.label), "value": float(l.value), "role": l.role} for l in block.lines]}
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
