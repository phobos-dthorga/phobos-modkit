"""The terrain report: how high the land stands and how rough it is, across the world, at the player's places and around one.

What the game saves, in our own words (the atlas module says more): each surface tile's elevation in metres plus 8192 (16-bit),
and its hilliness (a byte: undefined, flat, small hills, large hills, mountainous, impassable). Water reads 0 m or below. In
RimWorld 1.7 hilliness and elevation are made from separate noise, so a mountainous tile is no higher than a flat one on
average; a local map has no height of its own, so a map stands at its tile's height.
"""
from __future__ import annotations

from ...report import Report, Table
from . import planet
from . import planet_reports
from . import save as saves
from .atlas import ELEVATION_OFFSET, HILLINESS
from .save_reports import PLAYER_FACTION_PREFIX

LAND_NOTE = ("Land is every tile above the sea with a hilliness; water is left out of every figure. Heights are the game's "
             "own metres above sea level.")
STEP_NOTE = "A step is the height difference between two neighbouring land tiles; the tile's size is not in the save, so it is not a slope."


def heights(conn):
    """(elevation in metres per tile, hilliness per tile), or (None, None) when the save holds no such layers."""
    raw = planet.layer_from_index(conn, "tileElevation", "H")
    hills = planet.layer_from_index(conn, "tileHilliness", "B")
    if raw is None or hills is None or len(raw) != len(hills):
        return None, None
    return [v - ELEVATION_OFFSET for v in raw], hills


def is_land(elevation, hills, tile):
    return elevation[tile] > 0 and 0 < hills[tile] < len(HILLINESS)


def hill_name(value):
    return HILLINESS[value] if 0 <= value < len(HILLINESS) else "unknown"


def percentile(ordered, share):
    """The value a share of the way through a sorted list (nearest rank, a half rounded up)."""
    if not ordered:
        return None
    return ordered[min(len(ordered) - 1, max(0, int(share * (len(ordered) - 1) + 0.5)))]


def _steps(elevation, hills, shape, tiles):
    """Every height difference between neighbouring land tiles among <tiles>, each pair once, sorted."""
    inside = set(tiles)
    steps = []
    for tile in tiles:
        if not is_land(elevation, hills, tile):
            continue
        for other in shape.around(tile):
            if other > tile and other in inside and is_land(elevation, hills, other):
                steps.append(abs(elevation[tile] - elevation[other]))
    steps.sort()
    return steps


def _spread(values):
    ordered = sorted(values)
    return [f"{percentile(ordered, p):,} m" if ordered else "-" for p in (0.1, 0.5, 0.9)] + ([f"{ordered[-1]:,} m"] if ordered else ["-"])


def _player_places(conn):
    return conn.execute(
        "SELECT name, def, tile FROM world_object_view WHERE faction_def LIKE ? AND tile IS NOT NULL ORDER BY def, name",
        (PLAYER_FACTION_PREFIX + "%",)).fetchall()


def report_terrain(conn, cache, near=None, hops=8, top=30):
    """Heights and hilliness of the surface layer in a save index."""
    report = Report("Terrain: how high the land stands, and how rough it is")
    elevation, hills = heights(conn)
    if elevation is None:
        report.lines.append("This save holds no elevation and hilliness layers for its planet's surface.")
        return report
    tiles = len(elevation)
    land = [t for t in range(tiles) if is_land(elevation, hills, t)]
    report.lines.append(f"{len(land):,} of {tiles:,} surface tiles are land. {LAND_NOTE}")
    report.section("Land heights", Table(["Lowest tenth below", "Median", "Highest tenth above", "Highest"], [_spread([elevation[t] for t in land])]))
    by_class = {}
    for t in land:
        by_class.setdefault(hills[t], []).append(elevation[t])
    report.section("By hilliness", Table(["Hilliness", "Tiles", "Share of land", "Median height"],
                                         [(hill_name(h), len(v), f"{len(v) / max(1, len(land)):.0%}", f"{sorted(v)[len(v) // 2]:,} m")
                                          for h, v in sorted(by_class.items())]))
    places = []
    for name, def_, tile in _player_places(conn):
        number, _, layer = str(tile).partition(",")
        if not number.lstrip("-").isdigit() or (layer and layer != planet.SURFACE_LAYER):
            continue
        t = int(number)
        if 0 <= t < tiles:
            places.append((name or def_, def_, str(t), f"{max(0, elevation[t]):,} m" if elevation[t] > 0 else "water",
                           hill_name(hills[t])))
    if places:
        report.section("Your places", Table(["Place", "Kind", "Tile", "Height", "Hilliness"], places[:top], len(places)))
    subdivisions = planet.subdivisions_for(tiles)
    shape = None if subdivisions is None else planet.load_shape(cache, subdivisions)
    if shape is None:
        report.lines.append(planet_reports.SHAPE_REFUSED.format(tiles=tiles))
        return report
    steps = _steps(elevation, hills, shape, land)
    report.section("Steps between neighbouring land tiles", STEP_NOTE,
                   Table(["Pairs", "Median", "One in ten above", "One in a hundred above", "Steepest"],
                         [(f"{len(steps):,}", *(f"{percentile(steps, p):,} m" for p in (0.5, 0.9, 0.99)),
                           f"{steps[-1]:,} m" if steps else "-")]))
    if near is not None:
        tile, name = planet_reports.find_place(conn, near)
        if not 0 <= tile < tiles:
            raise saves.SaveError(f"Tile {tile} is not on this planet.")
        here = f"{elevation[tile]:,} m" if elevation[tile] > 0 else "water"
        report.lines.append(f"Around {name}: tile {tile} stands at {here}, {hill_name(hills[tile])}.")
        rings = shape.rings(tile, hops)
        by_ring = {}
        for t, distance in rings.items():
            by_ring.setdefault(distance, []).append(t)
        rows = []
        for distance in sorted(by_ring):
            ring_land = [elevation[t] for t in by_ring[distance] if is_land(elevation, hills, t)]
            ordered = sorted(ring_land)
            rows.append((distance, len(by_ring[distance]), len(ring_land),
                         f"{ordered[0]:,} m" if ordered else "-", f"{percentile(ordered, 0.5):,} m" if ordered else "-",
                         f"{ordered[-1]:,} m" if ordered else "-"))
        report.section(f"Rings around it, out to {hops} steps", Table(["Steps", "Tiles", "Land", "Lowest", "Median", "Highest"], rows))
        area = _steps(elevation, hills, shape, list(rings))
        if area:
            report.lines.append(f"Within {hops} steps the steepest step between neighbouring land tiles is {area[-1]:,} m; "
                                f"the median is {percentile(area, 0.5):,} m.")
    return report
