"""A RimWorld planet's surface tiles from a save: where they are, which touch, and how polluted each one is.

What the game writes, summarised in our own words from the RimWorld 1.7 code (November 2026):

- The surface layer saves one 16-bit number per tile for pollution (0 to 65535 is none to full), little-endian, as
  base64 of raw deflate when that is smaller; the element is tilePollutionDeflate, or tilePollution when not deflated.
- A planet is an icosahedron refined by repeated sqrt(3) subdivision, and a tile is a vertex of the result. A save
  holds no positions, so they are rebuilt here. The model is a reconstruction, checked against saves: decoding every
  road and river link in one gives a destination of higher ID every time, as the format requires. A world generated
  with less than full planet coverage drops tiles and renumbers the rest; this model does not cover that, and says so.

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
    """Tile centres on the unit sphere, and each tile's neighbours (neighbours[start[t]:start[t + 1]])."""
    xs: array
    ys: array
    zs: array
    start: array
    neighbours: array

    def __len__(self):
        return len(self.xs)

    def around(self, tile):
        return self.neighbours[self.start[tile]:self.start[tile + 1]]

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
    touching = []
    for step in range(subdivisions):
        vertices = len(xs)
        count = len(triangles) // 3
        for t in range(count):
            a, b, c = triangles[3 * t], triangles[3 * t + 1], triangles[3 * t + 2]
            x, y, z = xs[a] + xs[b] + xs[c], ys[a] + ys[b] + ys[c], zs[a] + zs[b] + zs[c]
            length = math.sqrt(x * x + y * y + z * z)
            xs.append(x / length), ys.append(y / length), zs.append(z / length)
        touching = [[] for _ in range(vertices)]
        for t in range(count):
            touching[triangles[3 * t]].append(t)
            touching[triangles[3 * t + 1]].append(t)
            touching[triangles[3 * t + 2]].append(t)
        if step == subdivisions - 1:
            break  # the tiles are the vertices now; another pass would only shape their outlines
        made = []
        for root in range(vertices):
            around = touching[root]
            for current in around:
                a, b, c = triangles[3 * current], triangles[3 * current + 1], triangles[3 * current + 2]
                after = b if a == root else (c if b == root else a)
                for other in around:
                    if other != current and after in triangles[3 * other:3 * other + 3]:
                        made += (root, vertices + other, vertices + current)
                        break
                else:
                    raise PlanetError("The planet's triangles do not close up.")
        triangles = made

    # An old vertex touches the new tile at the centre of each of its triangles. A new tile touches its triangle's
    # three corners and the centres of the three triangles beside it.
    vertices, count = len(xs) - len(triangles) // 3, len(triangles) // 3
    start, joined = array("i", [0]), array("i")
    for root in range(vertices):
        joined.extend(vertices + t for t in touching[root])
        start.append(len(joined))
    for t in range(count):
        corners = triangles[3 * t:3 * t + 3]
        joined.extend(corners)
        for k in range(3):
            u, v = corners[k], corners[(k + 1) % 3]
            for other in touching[u]:
                if other != t and v in triangles[3 * other:3 * other + 3]:
                    joined.append(vertices + other)
                    break
        start.append(len(joined))
    return Shape(array("f", xs), array("f", ys), array("f", zs), start, joined)


def _shape_path(cache, subdivisions):
    return Path(cache) / f"planet-{subdivisions}.sqlite"


def load_shape(cache, subdivisions):
    """The shape from the kit's cache, building and storing it the first time."""
    path = _shape_path(cache, subdivisions)
    expected = {"subdivisions": subdivisions, "kit_version": __version__}
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


_PARTS = (("xs", "f"), ("ys", "f"), ("zs", "f"), ("start", "i"), ("neighbours", "i"))


def _array(code, data):
    values = array(code)
    values.frombytes(data)
    return values


def decode(text, deflated):
    """One 16-bit number per tile, from the element's text."""
    if isinstance(text, (bytes, bytearray)):
        text = text.decode("ascii")
    data = base64.b64decode("".join(text.split()))
    if deflated:
        data = zlib.decompress(data, -15)
    if len(data) % 2:
        raise PlanetError(f"A pollution layer of {len(data)} bytes is not whole 16-bit numbers.")
    values = _array("H", data)
    if sys.byteorder == "big":
        values.byteswap()
    return values


def from_index(conn):
    """The surface pollution layer from a save index, or None when the index holds none."""
    row = conn.execute("SELECT element, data FROM planet_grid WHERE element LIKE 'tilePollution%' ORDER BY id").fetchone()
    return decode(row[1], row[0].endswith("Deflate")) if row else None


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
