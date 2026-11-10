"""One report model for every tool, rendered as Markdown for people and agent sessions, or as JSON for programs.

A report has a title, intro lines (one paragraph, one line each), further opening blocks, and sections. A block is a
paragraph (a plain string), Bullets, a Table, Code, a Chart (text bars in Markdown, a spec a program can draw in
JSON) or a Globe (a planet of tiles a program can draw; a line saying what it holds in Markdown). Redaction, such as hiding the home folder, applies to every
piece of text when the report is rendered, so no tool can forget a field.

    report = Report("Things")
    report.lines.append("1,878 things match.")
    report.section("By def", Table(["Def", "Things"], rows, total=1878))
    print(render_markdown(report, redact=home_redactor()))
"""
from __future__ import annotations

from array import array
import base64
from dataclasses import dataclass, field
import json
import os
import re
from pathlib import Path
import sys

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


# ---- Globes ----
#
# A globe is a planet of tiles for a program to draw: every tile's point on the unit sphere (y up; longitude is
# atan2(x, -z) and latitude asin(y), as RimWorld reckons them), each tile's neighbours in order round it, and layers
# of one value per tile. A tile's outline joins the centres of the triangles it makes with each pair of neighbours
# next to each other, so a program needs no other geometry. Arrays travel as little-endian base64 in JSON.

GLOBE_DTYPES = {"B": "u8", "H": "u16", "i": "i32", "f": "f32"}   # array typecode -> name in JSON
GLOBE_LAYER_KINDS = ("categories", "measure", "names")            # names: a label per tile, never a colour
GLOBE_RAMPS = ("temperature", "rainfall", "elevation", "sequential", "pollution")
GLOBE_LINE_STYLES = ("river", "road")


@dataclass
class GlobeCategory:
    label: str
    colour: str = ""                              # "#rrggbb": the map's own colour for it (a biome's look), not a theme's
    description: str = ""


@dataclass
class GlobeBand:
    """A named range of a measure, in shown units, such as the game's pollution bands."""
    label: str
    low: float
    high: float


@dataclass
class GlobeLayer:
    """One value per tile. A category layer's value is an index into categories; a measure's shown value is
    raw * scale + offset, in unit; a names layer's value is an index into categories, shown only as text."""
    key: str
    label: str
    description: str
    values: object                                # array.array, one per tile
    kind: str = "measure"
    categories: list = field(default_factory=list)   # GlobeCategory
    unit: str = ""
    scale: float = 1.0
    offset: float = 0.0
    precision: int = 0                            # decimals to show
    ramp: str = "sequential"
    missing: int = None                           # a raw value meaning "nothing here"
    missing_label: str = ""                       # what a missing value means, such as water
    overlay: bool = False                         # drawn over the chosen view; a raw 0 or missing value is clear
    bands: list = field(default_factory=list)     # GlobeBand


@dataclass
class GlobePlace:
    tile: int
    label: str
    kind: str                                     # what it is, such as Settlement
    group: str                                    # which list it belongs in, such as Your colonies
    role: str = "neutral"                         # CHART_ROLES: how a program colours it
    detail: str = ""                              # such as the faction's name
    priority: int = 0                             # higher is labelled first when labels crowd


@dataclass
class GlobeLines:
    """Lines from tile centre to tile centre, such as roads, with a width from 1 to 4 for each piece."""
    key: str
    label: str
    description: str
    style: str
    pairs: object                                 # array.array("i"): two tiles per piece
    widths: object                                # array.array("B"): one per piece
    names: list = field(default_factory=list)     # what each piece is, by index in kinds
    kinds: object = None                          # array.array("H"): one per piece, an index into names


@dataclass
class GlobeTags:
    """Short notes on some tiles, several per tile allowed, such as Caves or Coast."""
    key: str
    label: str
    names: list
    tiles: object                                 # array.array("i")
    tags: object                                  # array.array("H"): an index into names, one per entry in tiles


@dataclass
class GlobeLabel:
    """A named region's label where the game draws it: a point on the unit sphere and a size in tiles."""
    label: str
    kind: str
    position: tuple
    size: float = 1.0


@dataclass
class Globe:
    """A planet a program can draw and explore. Markdown cannot draw one: it says what the globe holds, and every
    figure a person needs should also be in a table of the report."""
    title: str
    description: str
    positions: object                             # array.array("f"): x, y, z for each tile
    ring_start: object                            # array.array("i"): tiles + 1 offsets into ring
    ring: object                                  # array.array("i"): each tile's neighbours, in order round it
    layers: list = field(default_factory=list)    # GlobeLayer; the first category layer is the default view
    places: list = field(default_factory=list)    # GlobePlace
    lines: list = field(default_factory=list)     # GlobeLines
    tags: list = field(default_factory=list)      # GlobeTags
    labels: list = field(default_factory=list)    # GlobeLabel

    @property
    def tiles(self):
        return len(self.positions) // 3

    def __post_init__(self):
        tiles = self.tiles
        problems = []
        if len(self.positions) != 3 * tiles or len(self.ring_start) != tiles + 1:
            problems.append("positions and ring_start do not agree on the number of tiles")
        for layer in self.layers:
            if layer.kind not in GLOBE_LAYER_KINDS:
                problems.append(f"layer {layer.key!r} has kind {layer.kind!r}")
            if layer.ramp not in GLOBE_RAMPS:
                problems.append(f"layer {layer.key!r} has ramp {layer.ramp!r}")
            if len(layer.values) != tiles:
                problems.append(f"layer {layer.key!r} has {len(layer.values)} values for {tiles} tiles")
        for place in self.places:
            if place.role not in CHART_ROLES:
                problems.append(f"place {place.label!r} has role {place.role!r}")
        for lines in self.lines:
            if lines.style not in GLOBE_LINE_STYLES:
                problems.append(f"lines {lines.key!r} have style {lines.style!r}")
            if len(lines.pairs) != 2 * len(lines.widths):
                problems.append(f"lines {lines.key!r} need two tiles and one width per piece")
        if problems:
            raise ValueError("; ".join(problems))


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


def _globe_lines(globe, redact):
    views = [layer.label for layer in globe.layers if layer.kind != "names" and not layer.overlay]
    overlays = [layer.label for layer in globe.layers if layer.overlay]
    parts = [f"{globe.tiles:,} tiles", f"views: {', '.join(views) or 'none'}"]
    if overlays:
        parts.append(f"overlays: {', '.join(overlays)}")
    parts.append(f"{len(globe.places):,} places")
    parts += [f"{len(lines.widths):,} pieces of {lines.label.lower()}" for lines in globe.lines]
    return [f"**{redact(globe.title)}**: {redact(globe.description)}", "",
            redact(f"A globe for a program to draw ({'; '.join(parts)}). The tables in this report list what it shows.")]


def _block_lines(block, redact):
    if isinstance(block, Chart):
        return _chart_lines(block, redact)
    if isinstance(block, Globe):
        return _globe_lines(block, redact)
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


def _array_json(values):
    """An array.array as {"dtype", "count", "data"}: little-endian bytes in base64."""
    if values is None:
        return None
    if values.typecode not in GLOBE_DTYPES:
        raise TypeError(f"a globe array cannot have typecode {values.typecode!r}")
    if sys.byteorder == "big" and values.itemsize > 1:
        values = array(values.typecode, values)
        values.byteswap()
    return {"dtype": GLOBE_DTYPES[values.typecode], "count": len(values),
            "data": base64.b64encode(values.tobytes()).decode("ascii")}


def _globe_json(globe, redact):
    text = lambda value: redact(str(value))
    return {"type": "globe", "title": text(globe.title), "description": text(globe.description), "tiles": globe.tiles,
            "positions": _array_json(globe.positions), "ring_start": _array_json(globe.ring_start),
            "ring": _array_json(globe.ring),
            "layers": [{"key": layer.key, "label": text(layer.label), "description": text(layer.description),
                        "kind": layer.kind, "values": _array_json(layer.values),
                        "categories": [{"label": text(c.label), "colour": c.colour, "description": text(c.description)}
                                       for c in layer.categories],
                        "unit": layer.unit, "scale": layer.scale, "offset": layer.offset, "precision": layer.precision,
                        "ramp": layer.ramp, "missing": layer.missing,
                        "missing_label": text(layer.missing_label), "overlay": layer.overlay,
                        "bands": [{"label": text(b.label), "low": b.low, "high": b.high} for b in layer.bands]}
                       for layer in globe.layers],
            "places": [{"tile": p.tile, "label": text(p.label), "kind": text(p.kind), "group": text(p.group),
                        "role": p.role, "detail": text(p.detail), "priority": p.priority} for p in globe.places],
            "lines": [{"key": lines.key, "label": text(lines.label), "description": text(lines.description),
                       "style": lines.style, "pairs": _array_json(lines.pairs), "widths": _array_json(lines.widths),
                       "names": [text(n) for n in lines.names], "kinds": _array_json(lines.kinds)}
                      for lines in globe.lines],
            "tags": [{"key": tags.key, "label": text(tags.label), "names": [text(n) for n in tags.names],
                      "tiles": _array_json(tags.tiles), "tags": _array_json(tags.tags)} for tags in globe.tags],
            "labels": [{"label": text(label.label), "kind": text(label.kind),
                        "position": [float(v) for v in label.position], "size": float(label.size)}
                       for label in globe.labels]}


def _block_json(block, redact):
    if isinstance(block, Globe):
        return _globe_json(block, redact)
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
