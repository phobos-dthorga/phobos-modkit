"""A RimWorld planet's surface tiles from a save: where they are, which touch, and how polluted each one is.

What the game writes, summarised in our own words from the RimWorld 1.7 code (November 2026):

- The surface layer saves one 16-bit number per tile for pollution (0 to 65535 is none to full), little-endian, as
  base64 of raw deflate when that is smaller; the element is tilePollutionDeflate, or tilePollution when not deflated.
- A planet is an icosahedron refined by repeated sqrt(3) subdivision, and a tile is a vertex of the result. A save
  holds no positions, so they are rebuilt here, following the game's own construction (IcosahedronGenerator and
  PlanetLayer.Subdivide, read from the 1.7 code on 10 November 2026): the same points and triangles, never rotated.
- A tile's neighbours are kept in the game's order, which saves use to name a road's or river's other end: from the
  first triangle touching the tile, by number, round the triangles the way they wind. Checked against a real save
  (10 November 2026): its 17,900 river pieces join into 233 river systems and its 14,901 road pieces into 33 networks;
  in any other order they fall apart into thousands of scraps.
- A world generated with less than full planet coverage drops tiles and renumbers the rest; this model does not cover
  that, and says so.

The shape takes seconds to build and depends only on the number of subdivisions, so it is cached as derived data.
"""
from __future__ import annotations

from array import array
from collections import deque
from contextlib import closing
from dataclasses import dataclass
import base64
import math
import mmap
from pathlib import Path
import sqlite3
import sys
import zlib

from ... import __version__
from ... import cache as derived

POLLUTION_FULL = 65535
ELEMENT = b"tilePollution"
CACHE_FOLDER = "rimworld-planet"
MAX_SUBDIVISIONS = 12
SURFACE_LAYER = "0"
SHAPE_FORMAT = 3              # 2 added each tile's ring; 3 put neighbours in the game's order

# The game's bands for a tile's pollution, as PollutionUtility reads them.
BANDS = (("light", 0.0, 0.25), ("moderate", 0.25, 0.5), ("heavy", 0.5, 0.75), ("extreme", 0.75, 1.01))

_ICO_TRIANGLES = (0, 11, 5, 0, 5, 1, 0, 1, 7, 0, 7, 10, 0, 10, 11, 1, 5, 9, 5, 11, 4, 11, 10, 2, 10, 7, 6, 7, 1, 8,
                  3, 9, 4, 3, 4, 2, 3, 2, 6, 3, 6, 8, 3, 8, 9, 4, 9, 5, 2, 4, 11, 6, 2, 10, 8, 6, 7, 9, 8, 1)
_PHI = (1 + math.sqrt(5)) / 2
_ICO_POINTS = ((-1, _PHI, 0), (1, _PHI, 0), (-1, -_PHI, 0), (1, -_PHI, 0), (0, -1, _PHI), (0, 1, _PHI), (0, -1, -_PHI),
               (0, 1, -_PHI), (_PHI, 0, -1), (_PHI, 0, 1), (-_PHI, 0, -1), (-_PHI, 0, 1))


class PlanetError(ValueError):
    pass


def subdivisions_for(tiles):
    """The number of subdivisions that gives this many tiles (10 * 3^n + 2), or None when no whole number does."""
    for n in range(MAX_SUBDIVISIONS + 1):
        if 10 * 3 ** n + 2 == tiles:
            return n
    return None


@dataclass
class Shape:
    """Tile points on the unit sphere, and each tile's neighbours (neighbours[start[t]:start[t + 1]]) in the game's
    order, which saves use to name a neighbour by its position. ring holds the same neighbours in order round the
    tile, anticlockwise seen from outside, for drawing its outline."""
    xs: array
    ys: array
    zs: array
    start: array
    neighbours: array
    ring: array

    def __len__(self):
        return len(self.xs)

    def around(self, tile):
        return self.neighbours[self.start[tile]:self.start[tile + 1]]

    def corners(self, tile):
        """The tile's outline as the game builds it: the centre of the triangle it makes with each pair of
        neighbours next to each other in the ring, on the unit sphere."""
        ring = self.ring[self.start[tile]:self.start[tile + 1]]
        x0, y0, z0 = self.xs[tile], self.ys[tile], self.zs[tile]
        out = []
        for k, a in enumerate(ring):
            b = ring[(k + 1) % len(ring)]
            x, y, z = x0 + self.xs[a] + self.xs[b], y0 + self.ys[a] + self.ys[b], z0 + self.zs[a] + self.zs[b]
            length = math.sqrt(x * x + y * y + z * z)
            out.append((x / length, y / length, z / length))
        return out

    def long_lat(self, tile):
        """(longitude, latitude) in degrees as the game reckons them (PlanetLayer.LongLatOf): from the mean of the
        tile's corners, which lies just inside the sphere, so a latitude reads a hair nearer the equator."""
        corners = self.corners(tile)
        x = sum(c[0] for c in corners) / len(corners)
        y = sum(c[1] for c in corners) / len(corners)
        z = sum(c[2] for c in corners) / len(corners)
        return math.degrees(math.atan2(x, -z)), math.degrees(math.asin(max(-1.0, min(1.0, y))))

    def rings(self, tile, hops):
        """{tile: distance in steps} for every tile within hops of this one."""
        seen = {tile: 0}
        queue = deque([tile])
        while queue:
            current = queue.popleft()
            distance = seen[current]
            if distance < hops:
                for next_tile in self.around(current):
                    if next_tile not in seen:
                        seen[next_tile] = distance + 1
                        queue.append(next_tile)
        return seen


def build_shape(subdivisions):
    """Rebuild the tile centres and neighbours of a whole planet with this many subdivisions."""
    if subdivisions < 1:
        raise PlanetError("A planet needs at least one subdivision.")
    xs, ys, zs = [], [], []
    for x, y, z in _ICO_POINTS:
        length = math.sqrt(x * x + y * y + z * z)
        xs.append(x / length), ys.append(y / length), zs.append(z / length)
    triangles = list(_ICO_TRIANGLES)
    for _ in range(subdivisions):
        vertices = len(xs)
        count = len(triangles) // 3
        for t in range(count):
            a, b, c = triangles[3 * t], triangles[3 * t + 1], triangles[3 * t + 2]
            x, y, z = xs[a] + xs[b] + xs[c], ys[a] + ys[b] + ys[c], zs[a] + zs[b] + zs[c]
            length = math.sqrt(x * x + y * y + z * z)
            xs.append(x / length), ys.append(y / length), zs.append(z / length)
        touching = _touching(triangles, vertices)
        made = []
        for root in range(vertices):
            around = touching[root]
            for current in around:
                after = _next_round(triangles, current, root)
                for other in around:
                    if other != current and after in triangles[3 * other:3 * other + 3]:
                        made += (root, vertices + other, vertices + current)
                        break
                else:
                    raise PlanetError("The planet's triangles do not close up.")
        triangles = made

    # Every vertex is a tile now. Its neighbours come in the game's order (PlanetLayer.Subdivide's last pass, then
    # CalculateTileNeighbors): from the first triangle touching it, by number, round the triangles the way they wind;
    # neighbour j is the tile the j-th triangle shares with the next. Saves name a road's or river's other end by its
    # place in this list.
    touching = _touching(triangles, len(xs))
    start, joined = array("i", [0]), array("i")
    for root in range(len(xs)):
        around = touching[root]
        position, vertex = 0, _next_round(triangles, around[0], root)
        for _ in range(len(around)):
            joined.append(vertex)
            position = next((i for i, t in enumerate(around)
                             if i != position and vertex in triangles[3 * t:3 * t + 3]), None)
            if position is None:
                raise PlanetError(f"Tile {root}'s triangles do not close round it.")
            vertex = _next_round(triangles, around[position], root)
        start.append(len(joined))
    return Shape(array("f", xs), array("f", ys), array("f", zs), start, joined, _rings(xs, ys, zs, start, joined))


def _touching(triangles, vertices):
    """For each vertex, the triangles touching it, in the order they are numbered."""
    touching = [[] for _ in range(vertices)]
    for t in range(len(triangles) // 3):
        touching[triangles[3 * t]].append(t)
        touching[triangles[3 * t + 1]].append(t)
        touching[triangles[3 * t + 2]].append(t)
    return touching


def _next_round(triangles, triangle, root):
    """The vertex after root in a triangle, the way it winds (TriangleIndices.GetNextOrderedVertex)."""
    a, b, c = triangles[3 * triangle], triangles[3 * triangle + 1], triangles[3 * triangle + 2]
    return b if a == root else (c if b == root else a)


def _rings(xs, ys, zs, start, joined):
    """Each tile's neighbours in order round it: from any neighbour, the next is the one that also touches it and is
    not the one before. Turned anticlockwise seen from outside, so every outline winds the same way."""
    ring = array("i")
    for tile in range(len(start) - 1):
        around = joined[start[tile]:start[tile + 1]]
        members = set(around)
        ordered, previous, current = [around[0]], -1, around[0]
        while len(ordered) < len(around):
            following = next((n for n in joined[start[current]:start[current + 1]]
                              if n in members and n != previous and n not in ordered), None)
            if following is None:
                raise PlanetError(f"Tile {tile}'s neighbours do not close round it.")
            ordered.append(following)
            previous, current = current, following
        a, b = ordered[0], ordered[1]
        ax, ay, az = xs[a] - xs[tile], ys[a] - ys[tile], zs[a] - zs[tile]
        bx, by, bz = xs[b] - xs[tile], ys[b] - ys[tile], zs[b] - zs[tile]
        turn = (ay * bz - az * by) * xs[tile] + (az * bx - ax * bz) * ys[tile] + (ax * by - ay * bx) * zs[tile]
        ring.extend(ordered if turn > 0 else ordered[:1] + ordered[:0:-1])
    return ring


def _shape_path(cache, subdivisions):
    return Path(cache) / f"planet-{subdivisions}.sqlite"


def load_shape(cache, subdivisions):
    """The shape from the kit's cache, building and storing it the first time."""
    path = _shape_path(cache, subdivisions)
    expected = {"subdivisions": subdivisions, "shape_format": SHAPE_FORMAT, "kit_version": __version__}
    if derived.is_current(path, expected):
        with closing(derived.open_read_only(path)) as conn:
            parts = dict(conn.execute("SELECT name, data FROM shape").fetchall())
        return Shape(*(_array(code, parts[name]) for name, code in _PARTS))
    shape = build_shape(subdivisions)
    Path(cache).mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".building")
    derived.remove(temporary)
    with closing(sqlite3.connect(temporary)) as conn:
        conn.execute("CREATE TABLE shape (name TEXT PRIMARY KEY, data BLOB)")
        conn.executemany("INSERT INTO shape VALUES (?, ?)",
                         [(name, getattr(shape, name).tobytes()) for name, _ in _PARTS])
        derived.write_meta(conn, expected)
        conn.commit()
    temporary.replace(path)
    return shape


_PARTS = (("xs", "f"), ("ys", "f"), ("zs", "f"), ("start", "i"), ("neighbours", "i"), ("ring", "i"))


def _array(code, data):
    values = array(code)
    values.frombytes(data)
    return values


def decode(text, deflated, typecode="H"):
    """The numbers in a layer element's text: 16-bit by default; "B" for bytes and "i" for 32-bit, as the game
    writes them (little-endian, base64, of raw deflate when the element's name ends in Deflate)."""
    if isinstance(text, (bytes, bytearray)):
        text = text.decode("ascii")
    data = base64.b64decode("".join(text.split()))
    if deflated:
        data = zlib.decompress(data, -15)
    size = array(typecode).itemsize
    if len(data) % size:
        raise PlanetError(f"A layer of {len(data)} bytes is not whole {8 * size}-bit numbers.")
    values = _array(typecode, data)
    if sys.byteorder == "big" and size > 1:
        values.byteswap()
    return values


def layer_from_index(conn, name, typecode="H"):
    """One of the surface layer's saved arrays (tileBiome, tileRoadOrigins...) from a save index, or None. The surface
    layer is the first in the save, and the only one that saves these."""
    row = conn.execute("SELECT element, data FROM planet_grid WHERE element IN (?, ?) ORDER BY id",
                       (name + "Deflate", name)).fetchone()
    return decode(row[1], row[0].endswith("Deflate"), typecode) if row else None


def from_index(conn):
    """The surface pollution layer from a save index, or None when the index holds none."""
    return layer_from_index(conn, ELEMENT.decode())


def _element(view, name):
    """The text of the first element with this name, or None; the name is bytes without brackets."""
    opening = b"<" + name + b">"
    start = view.find(opening)
    if start < 0:
        return None
    start += len(opening)
    end = view.find(b"</" + name + b">", start)
    return None if end < 0 else view[start:end]


def read_save(path):
    """(ticks, world seed, pollution layer) straight from a save, without indexing it. Raises PlanetError when the
    save changes while it is read, since the game may be writing it."""
    path = Path(path)
    before = derived.file_stamp(path)
    with open(path, "rb") as stream, mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ) as view:
        ticks = _element(view, b"ticksGame")
        seed = _element(view, b"seedString")
        text = _element(view, ELEMENT + b"Deflate")
        deflated = text is not None
        if text is None:
            text = _element(view, ELEMENT)
    if derived.file_stamp(path) != before:
        raise PlanetError(f"{path.name} changed while it was read.")
    if text is None:
        return int(ticks) if ticks else None, seed.decode("utf-8", "replace") if seed else None, None
    return int(ticks) if ticks else None, seed.decode("utf-8", "replace") if seed else None, decode(text, deflated)


def patches(values, shape):
    """Groups of polluted tiles that touch, biggest load first: lists of tile numbers."""
    seen = set()
    groups = []
    for tile, value in enumerate(values):
        if value and tile not in seen:
            seen.add(tile)
            group, queue = [], deque([tile])
            while queue:
                current = queue.popleft()
                group.append(current)
                for next_tile in shape.around(current):
                    if values[next_tile] and next_tile not in seen:
                        seen.add(next_tile)
                        queue.append(next_tile)
            groups.append(group)
    return sorted(groups, key=lambda g: (-sum(values[t] for t in g), g[0]))


def band_of(value):
    fraction = value / POLLUTION_FULL
    return next(name for name, low, high in BANDS if low <= fraction < high)
