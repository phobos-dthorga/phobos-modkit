"""The planet report: pollution on the world map, patch by patch, around one place, and across saves."""
from __future__ import annotations

from ...query import like
from ...report import Report, Table
from . import planet
from . import save as saves
from .save_reports import TICKS_PER_DAY

MODEL_NOTE = ("Tile positions are rebuilt from a model of the planet's shape, not read from the save. A tile's "
              "pollution is the game's own figure; 100% of one tile is a load of 1.")
SHAPE_REFUSED = ("This world has {tiles:,} surface tiles, which no whole-planet shape gives: it was generated with "
                 "less than full coverage, so tiles cannot be placed or grouped. Totals still hold.")
NEAREST_HOPS = 25


def percent(value):
    """A tile's pollution as a percentage; a trace still shows, rather than rounding to nothing."""
    fraction = value / planet.POLLUTION_FULL
    return f"{fraction:.3%}" if 0 < fraction < 0.001 else f"{fraction:.1%}"


def load(values):
    return sum(values) / planet.POLLUTION_FULL


def world_objects(conn):
    """{tile: [(name, faction, def)]} for the surface layer, settlements first."""
    found = {}
    for tile, name, faction, def_ in conn.execute(
            "SELECT tile, name, faction_name, def FROM world_object_view WHERE tile IS NOT NULL ORDER BY object_id"):
        number, _, layer = str(tile).partition(",")
        if number.lstrip("-").isdigit() and (not layer or layer == planet.SURFACE_LAYER):
            found.setdefault(int(number), []).append((name or def_, faction or "no faction", def_))
    for entries in found.values():
        entries.sort(key=lambda e: e[2] != "Settlement")
    return found


def find_place(conn, text):
    """(tile, how it was named) for a tile number or a world object's name."""
    if text.isdigit():
        return int(text), f"tile {text}"
    row = conn.execute(
        "SELECT tile, name, faction_name FROM world_object_view WHERE name LIKE ? ESCAPE '\\' "
        "ORDER BY def <> 'Settlement', object_id", (like(text),)).fetchone()
    if row is None:
        raise saves.SaveError(f"No world object is named {text}; world --name lists them, or give a tile number.")
    return int(str(row[0]).partition(",")[0]), f"{row[1]} ({row[2] or 'no faction'}, tile {str(row[0]).partition(',')[0]})"


def _label(entries):
    return "; ".join(f"{name} ({faction})" for name, faction, _ in entries)


def _on_patch(group, objects, shape):
    """What stands on a patch of tiles, or the nearest thing that does."""
    here = [e for t in group for e in objects.get(t, ())]
    if here:
        here.sort(key=lambda e: e[2] != "Settlement")
        shown = _label(here[:4])
        return shown + (f" and {len(here) - 4} more" if len(here) > 4 else "")
    if shape is None:
        return ""
    nearest = None
    for tile in group[:40]:
        for other, hops in shape.rings(tile, NEAREST_HOPS).items():
            if other in objects and (nearest is None or hops < nearest[0]):
                nearest = (hops, _label(objects[other][:1]))
    return f"nothing; nearest is {nearest[1]}, {nearest[0]} tiles away" if nearest else "nothing near"


def _bands(values):
    rows = []
    for name, low, high in planet.BANDS:
        chosen = [v for v in values if v and low <= v / planet.POLLUTION_FULL < high]
        rows.append((name, f"{low:.0%} to {min(high, 1):.0%}", len(chosen), f"{load(chosen):.2f}"))
    return Table(["Band", "Pollution", "Tiles", "Load"], rows)


def _changes(values, before, before_name, objects, top):
    changed = [(t, before[t], v) for t, v in enumerate(values) if before[t] != v]
    changed.sort(key=lambda c: (-abs(c[2] - c[1]), c[0]))
    appeared = sum(1 for _, b, a in changed if not b and a)
    cleared = sum(1 for _, b, a in changed if b and not a)
    rose = sum(1 for _, b, a in changed if b and a > b)
    fell = sum(1 for _, b, a in changed if a and a < b)
    rows = [(t, percent(b), percent(a), f"{(a - b) / planet.POLLUTION_FULL:+.1%}", _label(objects.get(t, ())[:2]))
            for t, b, a in changed[:top]]
    return (f"Against {before_name}: {len(changed):,} tiles changed. {appeared:,} became polluted, {cleared:,} became "
            f"clean, {rose:,} rose and {fell:,} fell; the planet's load went from {load(before):.2f} to "
            f"{load(values):.2f}."), Table(["Tile", "Before", "Now", "Change", "On it"], rows, len(changed))


def _around(report, values, shape, tile, name, hops, objects, top):
    """Adds what surrounds a tile to the report: its rings of tiles and the polluted ones among them."""
    rings = shape.rings(tile, hops)
    report.lines.append(f"Around {name}: tile {tile} is {percent(values[tile])} polluted.")
    by_ring = {}
    for t, distance in rings.items():
        by_ring.setdefault(distance, []).append(t)
    rows = []
    for distance in sorted(by_ring):
        tiles = by_ring[distance]
        rows.append((distance, len(tiles), sum(1 for t in tiles if values[t]), f"{load([values[t] for t in tiles]):.3f}",
                     percent(max(values[t] for t in tiles))))
    report.section(f"Rings around it, out to {hops} steps", Table(["Steps", "Tiles", "Polluted", "Load", "Highest"], rows))
    polluted = sorted(((rings[t], t) for t in rings if values[t]), key=lambda p: (-values[p[1]], p[0], p[1]))
    report.section("Polluted tiles there", Table(["Tile", "Steps", "Pollution", "On it"],
                                                 [(t, d, percent(values[t]), _label(objects.get(t, ())[:2]))
                                                  for d, t in polluted[:top]], len(polluted)))


def report_planet(conn, cache, near=None, hops=8, compare=None, top=30):
    """Pollution on the surface layer of the world map in a save index."""
    values = planet.from_index(conn)
    report = Report("Planet: pollution on the world map")
    if values is None:
        report.lines.append("This save holds no planet pollution layer (it needs the Biotech expansion).")
        return report
    objects = world_objects(conn)
    subdivisions = planet.subdivisions_for(len(values))
    shape = None if subdivisions is None else planet.load_shape(cache, subdivisions)
    if shape is None:
        report.lines.append(SHAPE_REFUSED.format(tiles=len(values)))
    else:
        report.lines.append(MODEL_NOTE)
    polluted = [v for v in values if v]
    report.lines.append(f"{len(polluted):,} of {len(values):,} surface tiles are polluted; their load is "
                        f"{load(polluted):.2f} tiles' worth and the highest is {percent(max(values) if polluted else 0)}.")
    report.section("By band", _bands(values))
    if compare is not None:
        before, before_name = compare
        if len(before) != len(values):
            raise saves.SaveError(f"{before_name} is a different world: {len(before):,} tiles against {len(values):,}.")
        line, table = _changes(values, before, before_name, objects, top)
        report.section("What changed", line, table)
    if near is not None and shape is not None:
        tile, name = find_place(conn, near)
        if not 0 <= tile < len(values):
            raise saves.SaveError(f"Tile {tile} is not on this planet.")
        _around(report, values, shape, tile, name, hops, objects, top)
    if shape is not None:
        groups = planet.patches(values, shape)
        rows = [(len(g), f"{load([values[t] for t in g]):.3f}", percent(max(values[t] for t in g)),
                 max(g, key=lambda t: values[t]), _on_patch(g, objects, shape)) for g in groups[:top]]
        report.section("Patches of touching polluted tiles, heaviest first",
                       Table(["Tiles", "Load", "Highest", "Worst tile", "Standing on it"], rows, len(groups)))
    return report


def report_history(save_paths, tile, name, hops, cache, seed_of_this_world, top=60):
    """How pollution moved across saves, read straight from each save without indexing it, oldest game day first."""
    report = Report("Planet: pollution across saves")
    report.lines.append(f"Each save is read directly, not indexed. Around means within {hops} steps of {name}.")
    rows, skipped = [], []
    shape, rings = None, None
    for path in save_paths:
        try:
            ticks, seed, values = planet.read_save(path)
        except (planet.PlanetError, OSError, ValueError) as problem:
            skipped.append((path.name, str(problem)))
            continue
        if values is None:
            skipped.append((path.name, "no planet pollution layer"))
            continue
        if seed != seed_of_this_world:
            skipped.append((path.name, f"another world (seed {seed})"))
            continue
        if shape is None:
            subdivisions = planet.subdivisions_for(len(values))
            if subdivisions is None:
                raise saves.SaveError(SHAPE_REFUSED.format(tiles=len(values)))
            shape = planet.load_shape(cache, subdivisions)
            rings = shape.rings(tile, hops)
        here = [values[t] for t in rings]
        rows.append((ticks if ticks is not None else -1, path.name, "" if ticks is None else f"{ticks / TICKS_PER_DAY:,.1f}",
                     sum(1 for v in values if v), f"{load(values):.2f}", sum(1 for v in here if v), f"{load(here):.3f}",
                     percent(max(here)), percent(values[tile])))
    rows.sort(key=lambda r: (r[0], r[1]))
    report.section("Saves, oldest in-game day first",
                   Table(["Save", "Game day", "Polluted tiles", "Planet load", "Tiles around", "Load around",
                          "Highest around", "At the tile"], [r[1:] for r in rows[:top]], len(rows)))
    if skipped:
        report.section("Skipped", Table(["Save", "Why"], skipped[:top], len(skipped)))
    return report
