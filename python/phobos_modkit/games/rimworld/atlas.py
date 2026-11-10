"""The atlas: a save's whole planet surface for a program to draw, with tables of what it shows.

What the game saves for each surface tile, summarised in our own words from the RimWorld 1.7 code (SurfaceLayer and
PlanetLayer, November 2026):

- biome: the BiomeDef's short hash (16-bit). A short hash is GenText.StableStringHash(defName) % 65535, moved up past 0
  and past hashes already given to Defs of the same type earlier in defName order (ShortHashGiver).
- elevation: metres + 8192 (16-bit); hilliness: the Hilliness enum (byte); temperature: (degrees C + 300) x 10
  (16-bit); rainfall: mm a year (16-bit); swampiness: 0 to 1 as 0 to 255 (byte); feature: the WorldFeature's
  uniqueID, 65535 for none (16-bit); pollution: 0 to 1 as 0 to 65535 (16-bit).
- roads and rivers: one entry per piece, from the lower tile: the tile (32-bit), the other tile's position in its
  neighbour list (byte) and the Def's short hash (16-bit).
- mutators: one entry per tile and mutator: the tile (32-bit) and the TileMutatorDef's short hash (16-bit).

The planet's shape is rebuilt by phobos_modkit.games.rimworld.planet, which follows the game's own construction: the
same twelve points and twenty triangles, never rotated, so longitude and latitude come out as the game shows them.
"""
from __future__ import annotations

from array import array
from collections import Counter, defaultdict
import json
import math
from pathlib import Path
import re

from ...report import (Globe, GlobeBand, GlobeCategory, GlobeLabel, GlobeLayer, GlobeLines, GlobePlace, GlobeTags,
                       Report, Table)
from . import planet
from . import planet_reports
from .save_reports import PLAYER_FACTION_PREFIX

PALETTE_FILE = Path(__file__).with_name("atlas-palette.json")
ELEVATION_OFFSET = 8192
TEMPERATURE_OFFSET, TEMPERATURE_SCALE = 300.0, 10.0
NO_FEATURE = 65535
MISSING_U16 = 65535
MISSING_U8 = 255
HILLINESS = ("undefined", "flat", "small hills", "large hills", "mountainous", "impassable")
HILLINESS_KEYS = ("Undefined", "Flat", "SmallHills", "LargeHills", "Mountainous", "Impassable")
SURFACE_LAYER_NAME = "PlanetLayer_0"
WATER = "water"
RAW_LAYERS = (("tileElevation", "H"), ("tileTemperature", "H"), ("tileRainfall", "H"), ("tileHilliness", "B"),
              ("tileSwampiness", "B"))

# Who stands where with the player, as places are grouped and coloured: (group, role, priority).
STANDING = {"player": ("Your colonies and camps", "accent", 30), "Ally": ("Allies", "success", 20),
            "Neutral": ("Neutral", "neutral", 10), "Hostile": ("Hostile", "risk", 10),
            None: ("No faction", "comparison", 0)}

MODEL_NOTE = ("Tile positions are rebuilt from a model of the planet that follows the game's own construction; "
              "the save holds none.")


# ---- Short hashes ----

def short_hash(name):
    """The game's first choice of short hash for a Def name, before collisions move it."""
    value = 23
    for character in name:
        value = (value * 31 + ord(character)) & 0xFFFFFFFF
    if value >= 1 << 31:
        value -= 1 << 32
    return int(math.fmod(value, 65535)) & 0xFFFF   # C#'s % keeps the sign; the cast to ushort wraps


def short_hashes(names):
    """{hash: name} for every Def of one type, given every loaded Def name of that type. The game sorts by its own
    string comparison; ordinal order here differs only for names that collide, which is rare."""
    taken = {}
    for name in sorted(set(names)):
        value = short_hash(name)
        while value == 0 or value in taken:
            value = (value + 1) & 0xFFFF
        taken[value] = name
    return taken


# ---- Names from Defs ----

def pretty(def_name):
    """A Def name as words, for when no label is known: TemperateForest -> temperate forest."""
    words = re.sub(r"(?<=[a-z0-9])(?=[A-Z])|_", " ", def_name).split()
    return " ".join(w if w.isupper() and len(w) > 1 else w.lower() for w in words)


def capital(text):
    return text[:1].upper() + text[1:]


class Names:
    """Def names and labels by type, from the installed mods' Def index when there is one, else from the palette."""

    def __init__(self, written=None, palette=None):
        self.written = written
        self.palette = palette or {}
        self._labels = {}

    def names(self, def_type, known=()):
        if self.written is None:
            return list(known)
        rows = self.written.execute("SELECT DISTINCT def_name, label FROM def WHERE def_type = ? AND loads AND wins "
                                    "AND NOT abstract AND def_name IS NOT NULL", (def_type,)).fetchall()
        for name, label in rows:
            if label:
                self._labels[(def_type, name)] = label
        return [name for name, _ in rows] or list(known)

    def label(self, def_type, name):
        return self._labels.get((def_type, name)) or pretty(name)


def load_palette(path=PALETTE_FILE):
    return json.loads(Path(path).read_text(encoding="utf-8"))


# ---- Colours ----

def climate_colour(temperature, rainfall):
    """A colour for a biome the palette does not know, from its tiles' mean climate: icy, dry, grassy or green."""
    if temperature < -10:
        return "#dfe6ea"
    if rainfall < 400:
        return "#d1b585" if temperature > 15 else "#b8ab8c"
    if rainfall < 1200:
        return "#8c9d58"
    return "#3f6f3a"


# ---- Reading the save ----

def _layer(conn, name, typecode, tiles):
    values = planet.layer_from_index(conn, name, typecode)
    if values is not None and len(values) != tiles:
        raise planet.PlanetError(f"{name} holds {len(values):,} values for {tiles:,} tiles.")
    return values


def _faction_standing(conn):
    """{'Faction_N': standing with the player} where standing is 'player', 'Ally', 'Neutral' or 'Hostile'."""
    players = [row[0] for row in conn.execute("SELECT load_id FROM faction WHERE def LIKE ?",
                                              (PLAYER_FACTION_PREFIX + "%",))]
    standing = {f"Faction_{p}": "player" for p in players}
    targets = {f"Faction_{p}" for p in players}
    for load_id, other, kind in conn.execute(
            "SELECT f.load_id, r.other, r.kind FROM faction_relation r JOIN faction f ON f.id = r.faction"):
        key = f"Faction_{load_id}"
        if other in targets and key not in standing:
            standing[key] = kind or "Neutral"
    return standing


def _vector(text):
    numbers = [float(n) for n in re.findall(r"-?\d+(?:\.\d+)?(?:[eE]-?\d+)?", text or "")]
    if len(numbers) != 3:
        return None
    length = math.sqrt(sum(n * n for n in numbers))
    return tuple(n / length for n in numbers) if length else None


def where(shape, tile):
    """A tile's place as the game writes it: 12.34°N 56.78°E."""
    longitude, latitude = shape.long_lat(tile)
    return (f"{abs(latitude):.2f}°{'S' if latitude < 0 else 'N'} "
            f"{abs(longitude):.2f}°{'W' if longitude < 0 else 'E'}")


# ---- Building the globe ----

def _biomes(raw, names, palette, temperature, rainfall, notes):
    """(the biome layer, {category index: def name}, per-biome rows for the table)."""
    hashes = short_hashes(names.names("BiomeDef", palette.get("biomes", {})))
    counts = Counter(raw)
    order = [h for h, _ in counts.most_common()]
    index = {h: i for i, h in enumerate(order)}
    sums = defaultdict(lambda: [0.0, 0.0, 0])
    if temperature is not None and rainfall is not None:
        for tile, value in enumerate(raw):
            entry = sums[value]
            entry[0] += temperature[tile] / TEMPERATURE_SCALE - TEMPERATURE_OFFSET
            entry[1] += rainfall[tile]
            entry[2] += 1
    categories, def_names, rows, guessed, unknown = [], {}, [], [], []
    for h in order:
        name = hashes.get(h)
        mean_t = sums[h][0] / sums[h][2] if sums[h][2] else None
        mean_r = sums[h][1] / sums[h][2] if sums[h][2] else None
        if name is None:
            unknown.append(h)
            label, colour, description = f"unknown biome ({h})", "#808080", "No loaded BiomeDef has this short hash."
        else:
            label = names.label("BiomeDef", name)
            colour = palette.get("biomes", {}).get(name)
            description = name
            if colour is None:
                colour = climate_colour(mean_t or 0, mean_r or 0)
                guessed.append(label)
                description = f"{name}; colour chosen from its climate"
        def_names[index[h]] = name
        categories.append(GlobeCategory(capital(label), colour, description))
        share = counts[h] / len(raw)
        rows.append((capital(label), f"{counts[h]:,}", f"{share:.1%}",
                     "" if mean_t is None else f"{mean_t:.1f} °C", "" if mean_r is None else f"{mean_r:,.0f} mm"))
    if guessed:
        notes.append(f"No colour is set for {', '.join(guessed)}; each is coloured from its tiles' climate.")
    if unknown:
        notes.append(f"{len(unknown)} biome short hashes match no loaded BiomeDef: the save may come from another mod "
                     f"list, or the Defs were not read.")
    values = array("H", (index[v] for v in raw))
    layer = GlobeLayer("biome", "Biome", "Each tile's biome, as the game's world map shows it.", values,
                       kind="categories", categories=categories)
    return layer, def_names, rows


def _water_tiles(biome_layer, def_names, palette):
    water = {i for i, name in def_names.items() if name in set(palette.get("water_biomes", ()))}
    return [v in water for v in biome_layer.values]


def _measures(raw, water, palette):
    layers = []
    elevation, temperature, rainfall = raw["tileElevation"], raw["tileTemperature"], raw["tileRainfall"]
    hilliness, swampiness = raw["tileHilliness"], raw["tileSwampiness"]
    if elevation is not None:
        layers.append(GlobeLayer("elevation", "Elevation", "Height above sea level; seas and lakes show their depth.",
                                 elevation, unit="m", offset=-ELEVATION_OFFSET, ramp="elevation"))
    if temperature is not None:
        layers.append(GlobeLayer("temperature", "Temperature", "The tile's average temperature over a year.",
                                 temperature, unit="°C", scale=1 / TEMPERATURE_SCALE, offset=-TEMPERATURE_OFFSET,
                                 precision=1, ramp="temperature"))
    if rainfall is not None:
        values = array("H", (MISSING_U16 if wet else r for r, wet in zip(rainfall, water)))
        layers.append(GlobeLayer("rainfall", "Rainfall", "Rain and snow in a year, in millimetres.", values,
                                 unit="mm", ramp="rainfall", missing=MISSING_U16, missing_label=WATER))
    if hilliness is not None:
        colours = palette.get("hilliness", {})
        categories = [GlobeCategory(capital(label), colours.get(key, "#808080"))
                      for key, label in zip(HILLINESS_KEYS, HILLINESS)]
        values = array("B", (0 if wet or h >= len(HILLINESS) else h for h, wet in zip(hilliness, water)))
        layers.append(GlobeLayer("hilliness", "Hills", "How hilly the land is, from flat to impassable mountains.",
                                 values, kind="categories", categories=categories, missing=0, missing_label=WATER))
    if swampiness is not None:
        values = array("B", (MISSING_U8 if wet else round(s * 100 / 255) for s, wet in zip(swampiness, water)))
        layers.append(GlobeLayer("swampiness", "Swampiness", "How much of the land is marsh and bog.", values,
                                 unit="%", ramp="sequential", missing=MISSING_U8, missing_label=WATER))
    return layers


def _pollution(conn, tiles):
    values = _layer(conn, "tilePollution", "H", tiles)
    if values is None:
        return None
    bands = [GlobeBand(capital(name), low * 100, min(high, 1.0) * 100) for name, low, high in planet.BANDS]
    return GlobeLayer("pollution", "Pollution", "Pollution on the world map, in the game's bands.", values,
                      unit="%", scale=100 / planet.POLLUTION_FULL, precision=1, ramp="pollution", overlay=True,
                      bands=bands)


def _features(conn, tiles):
    """(the region-name layer or None, labels, {uniqueID: (name, kind)})."""
    found = {}
    labels = []
    for def_, unique_id, name, centre, size, layer in conn.execute(
            "SELECT def, unique_id, name, draw_center, max_draw_size, layer FROM world_feature ORDER BY id"):
        if layer not in (None, "", SURFACE_LAYER_NAME):
            continue
        kind = capital(pretty(def_ or "region"))
        found[unique_id] = (name, kind)
        position = _vector(centre)
        if position is not None:
            labels.append(GlobeLabel(name, kind, position, size or 1.0))
    raw = _layer(conn, "tileFeature", "H", tiles)
    if raw is None:
        return None, labels, found
    order = sorted(found)
    index = {unique_id: i for i, unique_id in enumerate(order)}
    values = array("H", (index.get(v, MISSING_U16) for v in raw))
    categories = [GlobeCategory(found[u][0], "", found[u][1]) for u in order]
    layer = GlobeLayer("region", "Region", "The named island, ocean, range or other region a tile lies in.", values,
                       kind="names", categories=categories, missing=MISSING_U16)
    return layer, labels, found


def _lines(conn, shape, names, palette, key, label, description, style, def_type, widths_by_name, notes):
    origins = planet.layer_from_index(conn, f"tile{key}Origins", "i")
    adjacency = planet.layer_from_index(conn, f"tile{key}Adjacency", "B")
    defs = planet.layer_from_index(conn, f"tile{key}Def", "H")
    if origins is None or adjacency is None or defs is None:
        return None, Counter()
    if not len(origins) == len(adjacency) == len(defs):
        notes.append(f"The save's {label.lower()} lists disagree in length; they are left out.")
        return None, Counter()
    hashes = short_hashes(names.names(def_type, widths_by_name))
    pairs, widths, kinds, kind_names, kind_index, counts, lost = array("i"), array("B"), array("H"), [], {}, Counter(), 0
    for origin, position, value in zip(origins, adjacency, defs):
        around = shape.around(origin) if 0 <= origin < len(shape) else ()
        name = hashes.get(value)
        if position >= len(around) or name is None:
            lost += 1
            continue
        if name not in kind_index:
            kind_index[name] = len(kind_names)
            kind_names.append(capital(names.label(def_type, name)))
        pairs.extend((origin, around[position]))
        widths.append(max(1, min(4, int(widths_by_name.get(name, palette.get("default_width", 2))))))
        kinds.append(kind_index[name])
        counts[kind_names[kind_index[name]]] += 1
    if lost:
        notes.append(f"{lost:,} pieces of {label.lower()} could not be placed (an unknown Def or neighbour).")
    return GlobeLines(key.lower() + "s", label, description, style, pairs, widths, kind_names, kinds), counts


def _mutators(conn, names, tiles):
    tile_list = planet.layer_from_index(conn, "tileMutatorTiles", "i")
    defs = planet.layer_from_index(conn, "tileMutatorDefs", "H")
    if tile_list is None or defs is None or len(tile_list) != len(defs):
        return None
    hashes = short_hashes(names.names("TileMutatorDef"))
    names_out, index, kept_tiles, kept_tags = [], {}, array("i"), array("H")
    for tile, value in zip(tile_list, defs):
        name = hashes.get(value)
        if name is None or not 0 <= tile < tiles:
            continue
        if name not in index:
            index[name] = len(names_out)
            names_out.append(capital(names.label("TileMutatorDef", name)))
        kept_tiles.append(tile)
        kept_tags.append(index[name])
    return GlobeTags("features", "Landscape features", names_out, kept_tiles, kept_tags) if names_out else None


def _places(conn, shape, names, tiles):
    standing = _faction_standing(conn)
    places, rows = [], []
    for tile, name, def_, faction, faction_name in conn.execute(
            "SELECT tile, name, def, faction, faction_name FROM world_object_view WHERE tile IS NOT NULL "
            "ORDER BY object_id"):
        number, _, layer = str(tile).partition(",")
        if not number.lstrip("-").isdigit() or (layer and layer != planet.SURFACE_LAYER):
            continue
        tile = int(number)
        if not 0 <= tile < tiles:
            continue
        kind = capital(names.label("WorldObjectDef", def_)) if def_ else "Place"
        group, role, priority = STANDING[standing.get(faction, "Neutral") if faction else None]
        label = name or kind
        places.append(GlobePlace(tile, label, kind, group, role, faction_name or "", priority))
        rows.append((priority, label, kind, faction_name or "", group, tile, where(shape, tile)))
    rows.sort(key=lambda r: (-r[0], r[4], r[1].lower()))
    return places, [r[1:] for r in rows]


def atlas(conn, cache, written=None, top=30, palette=None):
    """The atlas of the save in this index: a Globe block and tables of what it shows."""
    palette = palette or load_palette()
    report = Report("Atlas: the world map")
    names = Names(written, palette)
    biome_raw = planet.layer_from_index(conn, "tileBiome", "H")
    if biome_raw is None:
        report.lines.append("This save holds no world map tiles.")
        return report
    tiles = len(biome_raw)
    subdivisions = planet.subdivisions_for(tiles)
    if subdivisions is None:
        report.lines.append(planet_reports.SHAPE_REFUSED.format(tiles=tiles))
        return report
    shape = planet.load_shape(cache, subdivisions)
    seed = conn.execute("SELECT world_seed FROM game").fetchone()
    report.lines.append(f"World seed {seed[0] if seed and seed[0] else 'unknown'}: {tiles:,} surface tiles "
                        f"({subdivisions} subdivisions). {MODEL_NOTE}")
    if written is None:
        report.lines.append("The installed mods' Defs were not read, so only the game's own biomes, roads and rivers "
                            "are named.")
    notes = []
    raw = {name: _layer(conn, name, typecode, tiles) for name, typecode in RAW_LAYERS}
    biome_layer, def_names, biome_rows = _biomes(biome_raw, names, palette, raw["tileTemperature"],
                                                 raw["tileRainfall"], notes)
    layers = [biome_layer, *_measures(raw, _water_tiles(biome_layer, def_names, palette), palette)]
    pollution = _pollution(conn, tiles)
    if pollution is not None:
        layers.append(pollution)
    region_layer, labels, regions = _features(conn, tiles)
    if region_layer is not None:
        layers.append(region_layer)
    roads, road_counts = _lines(conn, shape, names, palette, "Road", "Roads", "Roads and paths between settlements.",
                                "road", "RoadDef", palette.get("roads", {}), notes)
    rivers, river_counts = _lines(conn, shape, names, palette, "River", "Rivers", "Rivers and creeks.", "river",
                                  "RiverDef", palette.get("rivers", {}), notes)
    tags = _mutators(conn, names, tiles)
    places, place_rows = _places(conn, shape, names, tiles)
    globe = Globe("The world map", "Every tile of the planet's surface: its biome, climate, terrain and pollution, "
                  "with settlements, roads and rivers.", _positions(shape), shape.start, shape.ring, layers, places,
                  [lines for lines in (rivers, roads) if lines is not None], [tags] if tags else [], labels)
    report.blocks.append(globe)
    report.section("Biomes", Table(["Biome", "Tiles", "Share", "Mean temperature", "Mean rainfall"], biome_rows[:top],
                                   len(biome_rows)))
    report.section("Places", Table(["Place", "Kind", "Faction", "Standing", "Tile", "Where"], place_rows[:top],
                                   len(place_rows)))
    if region_layer is not None:
        sizes = Counter(v for v in region_layer.values if v != MISSING_U16)
        order = sorted(regions)
        region_rows = sorted(((regions[order[i]][0], regions[order[i]][1], n) for i, n in sizes.items()),
                             key=lambda r: (-r[2], r[0]))
        report.section("Named regions", Table(["Region", "Kind", "Tiles"],
                                              [(n, k, f"{c:,}") for n, k, c in region_rows[:top]], len(region_rows)))
    line_rows = [("River", kind, f"{n:,}") for kind, n in river_counts.most_common()]
    line_rows += [("Road", kind, f"{n:,}") for kind, n in road_counts.most_common()]
    report.section("Roads and rivers", Table(["What", "Kind", "Pieces"], line_rows))
    if notes:
        report.section("What the atlas could not show", *notes)
    return report


def _positions(shape):
    """x, y, z for each tile, interleaved."""
    positions = array("f", bytes(12 * len(shape)))
    positions[0::3] = shape.xs
    positions[1::3] = shape.ys
    positions[2::3] = shape.zs
    return positions
