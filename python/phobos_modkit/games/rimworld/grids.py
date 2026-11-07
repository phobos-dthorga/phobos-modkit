"""RimWorld map grids, decoded from a save index's map_grid table.

How the game writes them, summarised in our own words from the RimWorld 1.7 code (November 2026):

- Each grid is a byte array saved as base64, deflated (raw deflate, no header) when that makes it smaller, in which
  case the element's name gains "Deflate". Cells run row by row: index = z * width + x.
- Terrain (top, under and foundation layers), roofs and deep resources store each cell's Def as its 16-bit short hash,
  little-endian; 0 is none. Deep resources also store a 16-bit count per cell.
- A Def's short hash is (StableStringHash(defName) mod 65535) as a 16-bit number, where StableStringHash starts at
  23 and takes hash * 31 + each character in 32-bit arithmetic. When two Defs of one type would share a number,
  the game takes them in defName order and moves each later one up to the next free number; 0 is never used.
- Gas is one 32-bit number per cell holding four 8-bit densities (0 to 255): blind smoke in the lowest byte, then
  toxic gas, rot stink and deadlife dust.
- Snow depth is a 16-bit fraction of full depth (0 to 65535). Fog and pollution are one bit per cell, lowest bit
  first.
"""
from __future__ import annotations

import base64
from collections import Counter
from dataclasses import dataclass
import struct
import zlib

GAS_TYPES = (("blind smoke", 0), ("toxic gas", 8), ("rot stink", 16), ("deadlife dust", 24))
GAS_FULL = 255
SNOW_FULL = 65535


@dataclass(frozen=True)
class GridKind:
    key: str          # the name reports use
    layout: str       # def16, count16, gas32, bits, fraction16
    def_type: str = ""


# (owning element, element without "Deflate") -> what the grid holds
GRIDS = {
    ("terrainGrid", "topGrid"): GridKind("terrain", "def16", "TerrainDef"),
    ("terrainGrid", "underGrid"): GridKind("under-terrain", "def16", "TerrainDef"),
    ("terrainGrid", "foundationGrid"): GridKind("foundation", "def16", "TerrainDef"),
    ("roofGrid", "roofs"): GridKind("roof", "def16", "RoofDef"),
    ("gasGrid", "gasDensity"): GridKind("gas", "gas32"),
    ("fogGrid", "fogGrid"): GridKind("fog", "bits"),
    ("snowGrid", "depthGrid"): GridKind("snow", "fraction16"),
    ("grid", "arr"): GridKind("pollution", "bits"),
    ("deepResourceGrid", "defGrid"): GridKind("deep resource", "def16", "ThingDef"),
    ("deepResourceGrid", "countGrid"): GridKind("deep resource count", "count16"),
}
KINDS = {kind.key: kind for kind in GRIDS.values()}


class GridError(ValueError):
    pass


def kind_of(owner, element):
    base = element[:-len("Deflate")] if element.endswith("Deflate") else element
    return GRIDS.get((owner, base)), element.endswith("Deflate")


def raw_bytes(text, deflated):
    data = base64.b64decode("".join(text.split()))
    return zlib.decompress(data, -15) if deflated else data


def cells(kind, data, count):
    """One value per cell: an integer for every layout (gas cells hold all four densities packed)."""
    if kind.layout in ("def16", "count16", "fraction16"):
        if len(data) < count * 2:
            raise GridError(f"{kind.key} grid has {len(data)} bytes for {count} cells")
        return list(struct.unpack(f"<{count}H", data[:count * 2]))
    if kind.layout == "gas32":
        if len(data) < count * 4:
            raise GridError(f"gas grid has {len(data)} bytes for {count} cells")
        return list(struct.unpack(f"<{count}I", data[:count * 4]))
    if kind.layout == "bits":
        if len(data) * 8 < count:
            raise GridError(f"{kind.key} grid has {len(data)} bytes for {count} cells")
        return [(data[i >> 3] >> (i & 7)) & 1 for i in range(count)]
    raise GridError(f"unknown grid layout {kind.layout}")


def gas_density(value, offset):
    return (value >> offset) & 0xFF


# ---- Def short hashes ----

def stable_string_hash(text):
    """The game's StableStringHash: 23, then hash * 31 + each UTF-16 code unit, in signed 32-bit arithmetic."""
    value = 23
    units = text.encode("utf-16-le")
    for i in range(0, len(units), 2):
        value = (value * 31 + int.from_bytes(units[i:i + 2], "little")) & 0xFFFFFFFF
    return value - (1 << 32) if value >= 1 << 31 else value


def base_short_hash(def_name):
    value = stable_string_hash(def_name)
    remainder = abs(value) % 65535 * (-1 if value < 0 else 1)  # C#'s % keeps the dividend's sign
    return remainder & 0xFFFF


def short_hashes(def_names):
    """({short hash: defName}, names whose number depended on how ties were ordered).

    Ties go in defName order with the game's default string comparison, which this approximates as case-insensitive
    then case-sensitive order; only names that collided can come out differently."""
    taken, by_hash, uncertain = set(), {}, []
    bases = {name: base_short_hash(name) for name in def_names}
    collided = {h for h, n in Counter(bases.values()).items() if n > 1} | {0}
    for name in sorted(def_names, key=lambda n: (n.lower(), n)):
        number = bases[name]
        moved = number in collided or number in taken
        while number == 0 or number in taken:
            number = (number + 1) & 0xFFFF
        taken.add(number)
        by_hash[number] = name
        if moved:
            uncertain.append(name)
    return by_hash, uncertain


# ---- A map's grids ----

@dataclass
class MapGrids:
    position: int
    width: int
    height: int
    values: dict          # kind key -> list of cell values

    def index(self, x, z):
        if not (0 <= x < self.width and 0 <= z < self.height):
            raise GridError(f"({x}, {z}) is outside the map, which is {self.width} by {self.height}")
        return z * self.width + x

    def area(self, rect=None):
        """Cell indexes inside (x1, z1, x2, z2), inclusive; the whole map without one."""
        if rect is None:
            return range(self.width * self.height)
        x1, z1, x2, z2 = rect
        x1, x2 = sorted((max(0, x1), min(self.width - 1, x2)))
        z1, z2 = sorted((max(0, z1), min(self.height - 1, z2)))
        return [z * self.width + x for z in range(z1, z2 + 1) for x in range(x1, x2 + 1)]


class Names:
    """Def names for short hashes, from the Def index's Defs (XML and game-made) of each type; numbers it cannot
    name show as #number, and names whose number depended on tie order are marked with ?."""

    def __init__(self, defs_conn=None):
        self.conn, self._books = defs_conn, {}

    @property
    def available(self):
        return self.conn is not None

    def _book(self, def_type):
        if def_type not in self._books:
            names = [n for (n,) in self.conn.execute("SELECT def_name FROM def WHERE wins AND def_type = ?",
                                                     (def_type,))] if self.conn else []
            table, uncertain = short_hashes(names)
            self._books[def_type] = (table, set(uncertain))
        return self._books[def_type]

    def label(self, def_type, number):
        if number == 0:
            return "(none)"
        table, uncertain = self._book(def_type)
        name = table.get(number)
        if name is None:
            return f"#{number}"
        return name + (" (?)" if name in uncertain else "")


SYMBOLS = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
LEVELS = ".123456789"


def render(grid_map, kind, names, max_columns=100, gas_offset=None):
    """(lines of a text picture, north up, and a legend [(symbol, meaning, cells)]). One character stands for a
    square block of cells: the commonest value for Def and count layers, the highest for gas and snow, and for fog and
    pollution # when at least half the block is set, + when any is."""
    values = grid_map.values[kind.key]
    block = max(1, -(-max(grid_map.width, grid_map.height) // max_columns))
    legend, symbol_of = [], {}
    if kind.layout in ("def16", "count16"):
        for number, cells_with in Counter(v for v in values if v).most_common(len(SYMBOLS)):
            symbol_of[number] = SYMBOLS[len(symbol_of)]
            meaning = names.label(kind.def_type, number) if kind.layout == "def16" else str(number)
            legend.append((symbol_of[number], meaning, cells_with))
    lines = []
    for top in range(grid_map.height - 1, -1, -block):
        row = []
        for left in range(0, grid_map.width, block):
            members = [values[z * grid_map.width + x] for z in range(max(0, top - block + 1), top + 1)
                       for x in range(left, min(grid_map.width, left + block))]
            if kind.layout in ("def16", "count16"):
                common = Counter(members).most_common(1)[0][0]
                row.append("." if common == 0 else symbol_of.get(common, "?"))
            elif kind.layout == "gas32":
                offsets = [gas_offset] if gas_offset is not None else [o for _, o in GAS_TYPES]
                highest = max(gas_density(v, o) for v in members for o in offsets)
                row.append(LEVELS[min(9, -(-highest * 9 // GAS_FULL))])
            elif kind.layout == "fraction16":
                row.append(LEVELS[min(9, -(-max(members) * 9 // SNOW_FULL))])
            else:
                share = sum(members) / len(members)
                row.append("#" if share >= 0.5 else "+" if share > 0 else ".")
        lines.append("".join(row))
    if kind.layout in ("gas32", "fraction16"):
        legend = [(".", "none", None), ("1 to 9", "ninths of full density" if kind.layout == "gas32" else
                                        "ninths of full depth", None)]
    elif kind.layout == "bits":
        legend = [("#", "at least half the block", None), ("+", "some of the block", None), (".", "none", None)]
    return lines, legend, block


def load_map(conn, position):
    """Every grid of the map at this position, decoded; GridError when the map or a grid is missing or broken."""
    row = conn.execute("SELECT id, size_x, size_z FROM map WHERE position = ?", (position,)).fetchone()
    if row is None:
        raise GridError(f"No map {position} in this save.")
    map_id, width, height = row
    values = {}
    for owner, element, data in conn.execute("SELECT owner, element, data FROM map_grid WHERE map = ?", (map_id,)):
        kind, deflated = kind_of(owner, element)
        if kind is None:
            continue
        values[kind.key] = cells(kind, raw_bytes(data, deflated), width * height)
    return MapGrids(position, width, height, values)
