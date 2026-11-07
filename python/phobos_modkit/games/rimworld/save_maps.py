"""The grid report: what a save's map grids hold (terrain, roofs, gas, fog, snow, pollution, deep resources)."""
from __future__ import annotations

from collections import Counter

from ...report import Code, Report, Table
from . import grids

GRID_NOTE = ("Terrain, roofs and deep resources are named from the Def index of the installed mods (XML Defs and the "
             "stone floors and carpets the game makes in code); a #number is a Def it could not name, such as one made "
             "by another generator or by a mod no longer active, and (?) marks a name whose number depended on how "
             "the game orders tied names.")


def _share(n, total):
    return f"{n / total:.1%}" if total else ""


def _def_counts(grid_map, kind, names, cells, top):
    counts = Counter(grid_map.values[kind.key][i] for i in cells)
    rows = [(names.label(kind.def_type, number), n, _share(n, len(cells))) for number, n in counts.most_common()]
    return Table(["Value", "Cells", "Share"], rows[:top], len(rows))


def _layer_rows(grid_map, cells):
    rows = []
    values = grid_map.values
    if "gas" in values:
        for gas, offset in grids.GAS_TYPES:
            present = [grids.gas_density(values["gas"][i], offset) for i in cells]
            present = [d for d in present if d]
            rows.append((gas, len(present), f"highest {max(present)} of 255, mean {sum(present) / len(present):.0f}"
                         if present else ""))
    if "fog" in values:
        fogged = sum(values["fog"][i] for i in cells)
        rows.append(("fog", fogged, f"{_share(fogged, len(cells))} of the cells"))
    if "snow" in values:
        snowy = [values["snow"][i] for i in cells if values["snow"][i]]
        rows.append(("snow", len(snowy), f"deepest {max(snowy) / grids.SNOW_FULL:.1%}, mean "
                                         f"{sum(snowy) / len(snowy) / grids.SNOW_FULL:.1%} of full depth"
                     if snowy else ""))
    if "pollution" in values:
        rows.append(("pollution", sum(values["pollution"][i] for i in cells), ""))
    return rows


def _deep_rows(grid_map, names, cells):
    if "deep resource" not in grid_map.values:
        return []
    kinds, amounts = grid_map.values["deep resource"], grid_map.values.get("deep resource count")
    totals, cell_counts = Counter(), Counter()
    for i in cells:
        if kinds[i]:
            cell_counts[kinds[i]] += 1
            totals[kinds[i]] += amounts[i] if amounts else 0
    return [(names.label("ThingDef", n), c, totals[n]) for n, c in cell_counts.most_common()]


def _things_at(conn, position, x, z):
    return [tuple(r) for r in conn.execute(
        "SELECT t.thing_id, t.def, t.stack FROM thing t JOIN thing_place pl ON pl.id = t.id "
        "WHERE pl.place = 'map' AND NOT pl.held AND t.map = ? AND t.pos_x = ? AND t.pos_z = ? ORDER BY t.id",
        (position, x, z)).fetchall()]


def grid(conn, map_position=None, kind=None, names=None, render=False, at=None, area=None, gas=None,
         columns=100, top=15):
    """A map's grids: every layer in short, one layer in full (with a text picture), or every layer at one cell."""
    names = names or grids.Names()
    if map_position is None:
        row = conn.execute("SELECT current_map FROM game").fetchone()
        map_position = row[0] if row and row[0] is not None else 0
    grid_map = grids.load_map(conn, map_position)
    report = Report(f"Map {map_position}: grids")
    cells = list(grid_map.area(area))
    where = f"cells ({area[0]}, {area[1]}) to ({area[2]}, {area[3]})" if area else "the whole map"
    report.lines.append(f"Map {map_position} is {grid_map.width} by {grid_map.height} cells; counts are for {where} "
                        f"({len(cells):,} cells). x runs east, z runs north.")
    if not names.available:
        report.lines.append("No Def index was available, so Defs show as #numbers.")
    report.lines.append(GRID_NOTE)

    if at is not None:
        x, z = at
        i = grid_map.index(x, z)
        rows = []
        for key, values in grid_map.values.items():
            k = grids.KINDS[key]
            v = values[i]
            if k.layout == "def16":
                shown = names.label(k.def_type, v)
            elif k.layout == "gas32":
                shown = ", ".join(f"{g} {grids.gas_density(v, o)}" for g, o in grids.GAS_TYPES
                                  if grids.gas_density(v, o)) or "none"
            elif k.layout == "fraction16":
                shown = f"{v / grids.SNOW_FULL:.1%} of full depth"
            elif k.layout == "bits":
                shown = "yes" if v else "no"
            else:
                shown = v
            rows.append((key, shown))
        report.section(f"Cell ({x}, {z})", Table(["Layer", "Value"], rows))
        report.section("Things standing there", Table(["ID", "Def", "Stack"], _things_at(conn, map_position, x, z)))
        return report

    if kind is not None:
        k = grids.KINDS.get(kind)
        if k is None or k.key not in grid_map.values:
            raise grids.GridError(f"No {kind} grid on map {map_position}. Layers: "
                                  + ", ".join(sorted(grid_map.values)) + ".")
        if k.layout in ("def16", "count16"):
            report.section(k.key.capitalize(), _def_counts(grid_map, k, names, cells, top))
        else:
            report.section(k.key.capitalize(), Table(["Layer", "Cells", "Detail"],
                                                     [r for r in _layer_rows(grid_map, cells)
                                                      if k.key == "gas" and r[0] in dict(grids.GAS_TYPES)
                                                      or r[0] == k.key]))
        if render:
            offset = dict(grids.GAS_TYPES).get(gas) if gas else None
            lines, legend, block = grids.render(grid_map, k, names, columns, offset)
            report.section("Picture", f"North is up; each character is {block} by {block} cells.", Code(lines),
                           Table(["Symbol", "Meaning", "Cells"], legend))
        return report

    for key in ("terrain", "foundation", "roof"):
        if key in grid_map.values:
            report.section(key.capitalize(), _def_counts(grid_map, grids.KINDS[key], names, cells, top))
    report.section("Gas, fog, snow and pollution", Table(["Layer", "Cells", "Detail"], _layer_rows(grid_map, cells)))
    report.section("Deep resources", Table(["Resource", "Cells", "Total count"], _deep_rows(grid_map, names, cells)))
    return report
