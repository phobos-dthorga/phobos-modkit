"""Whether every active mod's encoded textures match its pictures, and encoding the ones that don't, as RimSort does.

The game's rule (RimWorld 1.7, Verse.ModContentLoader.ShadowedByDds, read in a decompile on 18 Nov 2026): a texture file with a .dds of
the same name beside it is skipped, and the .dds is loaded instead, without comparing their dates. So:

- **stale**: a .png newer than its .dds (an update changed the picture after it was encoded): the game shows the old picture.
- **missing**: a .png with no .dds: the right picture, loaded more slowly and held in more memory.
- **left over**: a .dds whose .png is gone: still loaded under its name; usually harmless, and never touched here.

Only paths containing "Textures" are read, as RimSort's own todds preset does. Dates are file modification times; a .png counts as
newer only by more than SLACK_SECONDS, so files a download wrote moments apart are not flagged (agent default). Encoding runs RimSort's
todds with RimSort's "optimized" preset on one mod folder at a time, which re-encodes only what is newer than its .dds.
"""
from __future__ import annotations

from contextlib import closing
from dataclasses import dataclass, field
import os
from pathlib import Path
import sqlite3
import subprocess
import threading

from ... import cache
from ...paths import resolve

# RimSort's "optimized" todds preset, as its source has it (RimSort/RimSort, app/utils/todds/wrapper.py, commit c02f2b3, 15 Oct 2026):
# BC1, BC7 where there is alpha, re-encode only what is newer than its DDS (RimSort's "overwrite" off), flipped vertically as the game
# reads DDS, sizes fixed to multiples of 4, only paths containing "Textures". The folder goes last. Moved here from phobos-rimworld's
# deploy.py in kit 1.21.0, so both use one copy.
RIMSORT_OPTIMIZED = ("-f", "BC1", "-af", "BC7", "-on", "-vf", "-fs", "-ss", "Textures", "-t", "-p")
TODDS = ("toddsPath", "RIMSORT_TODDS")
DEFAULT_TODDS = Path(r"C:\Program Files (x86)\RimSort\todds\todds.exe")
PATH_SEGMENT = "Textures"
SOURCE_SUFFIX = ".png"
DDS_SUFFIX = ".dds"
SLACK_SECONDS = 120
SAMPLE_PATHS = 5
ENCODE_TIMEOUT = 60 * 60


def todds_path(explicit=None, environ=None, settings=None):
    """RimSort's todds: argument, RIMSORT_TODDS, a settings file's toddsPath, or RimSort's default install; None if absent."""
    path = resolve(*TODDS, DEFAULT_TODDS, explicit, environ, settings)
    return path if path is not None and Path(path).is_file() else None


@dataclass
class Freshness:
    pictures: int = 0
    stale: list = field(default_factory=list)       # relative paths of .png files newer than their .dds
    missing: list = field(default_factory=list)     # relative paths of .png files with no .dds
    left_over: list = field(default_factory=list)   # relative paths of .dds files with no .png
    unpacked: list = field(default_factory=list)    # relative paths of .dds files Waylith unpacks and encode would shorten

    @property
    def needs_encoding(self):
        return bool(self.stale or self.missing or self.unpacked)


def texture_files(folder):
    """Every picture and encoded texture under a mod folder's Textures paths: (path, relative path, stat), from the listing itself
    on Windows. Shared by the check and by pairs (1.82.0)."""
    folder = Path(folder)
    base = len(str(folder)) + 1
    stack = [str(folder)]
    while stack:
        try:
            with os.scandir(stack.pop()) as entries:
                for entry in entries:
                    try:
                        if entry.is_dir(follow_symlinks=False):
                            stack.append(entry.path)
                            continue
                        lower = entry.name.lower()
                        if not (lower.endswith(SOURCE_SUFFIX) or lower.endswith(DDS_SUFFIX)) or PATH_SEGMENT not in entry.path:
                            continue
                        info = entry.stat(follow_symlinks=False)
                    except OSError:
                        continue
                    yield entry.path, entry.path[base:].replace("\\", "/"), info
        except OSError:
            continue


def check_folder(folder, slack=SLACK_SECONDS, headers=None):
    """How a mod folder's encoded textures stand against its pictures. Reads file names and dates only, and with headers (a
    HeaderCache) each .dds file's first 148 bytes, once per size and date, for the textures Waylith would unpack."""
    pictures, encoded, unpacked = {}, {}, []
    for path, relative, info in texture_files(folder):
        lower = path.lower()
        (pictures if lower.endswith(SOURCE_SUFFIX) else encoded)[path[:-4].lower()] = (info.st_mtime, relative)
        if headers is not None and lower.endswith(DDS_SUFFIX) and \
                headers.verdict(path, info.st_size, info.st_mtime_ns) == FIXABLE:
            unpacked.append(relative)
    found = Freshness(pictures=len(pictures), unpacked=sorted(unpacked))
    for stem, (mtime, relative) in sorted(pictures.items(), key=lambda item: item[1][1]):
        if stem not in encoded:
            found.missing.append(relative)
        elif mtime > encoded[stem][0] + slack:
            found.stale.append(relative)
    found.left_over = sorted(relative for stem, (_, relative) in encoded.items() if stem not in pictures)
    return found


def pairs(folder, slack=SLACK_SECONDS):
    """Each picture of a mod beside the encoded texture the game loads in its place (1.82.0), for a program to compare them: the
    relative paths, sizes and a state, "fresh", "stale" (the picture is newer: the game shows the old one), "missing" (no encoded
    texture: the picture itself is loaded) or "left-over" (an encoded texture with no picture). Sorted by the picture's path.
    RimSort's preset stores the encoded texture upside down, as the game reads DDS, so a program turns it over to compare."""
    pictures, encoded = {}, {}
    for path, relative, info in texture_files(folder):
        (pictures if path.lower().endswith(SOURCE_SUFFIX) else encoded)[path[:-4].lower()] = (relative, info.st_size, info.st_mtime)
    found = []
    for stem in sorted(set(pictures) | set(encoded), key=lambda s: (pictures.get(s) or encoded.get(s))[0].lower()):
        picture, texture = pictures.get(stem), encoded.get(stem)
        if picture and texture:
            state = "stale" if picture[2] > texture[2] + slack else "fresh"
        else:
            state = "missing" if picture else "left-over"
        found.append({"picture": picture[0] if picture else None, "encoded": texture[0] if texture else None, "state": state,
                      "pictureSize": picture[1] if picture else None, "encodedSize": texture[1] if texture else None})
    return found


def encode(folder, todds, run=subprocess.run):
    """Runs todds with RimSort's preset on one mod folder. Returns (exit code, its last line of output)."""
    result = run([str(todds), *RIMSORT_OPTIMIZED, str(Path(folder))], capture_output=True, text=True, check=False,
                 timeout=ENCODE_TIMEOUT)
    lines = ((result.stdout or "") + (result.stderr or "")).strip().splitlines()
    return result.returncode, (lines[-1][:300] if lines else "")


# Shortened mip chains (kit 1.54.0, owner's choice of 20 Nov 2026). Waylith, a replacement engine some players run RimWorld 1.7 on,
# turns a block-compressed texture back into plain 4-byte pixels when any of its mip levels four or more pixels tall has a height that
# is not a multiple of four (UnityStubs' AssetBundleTextures.NeedsDecode, read in a decompile on 20 Nov 2026; width is not checked).
# todds writes the full chain, so nearly every texture whose height is not a power of two took four times the memory: 255 of D'thorga
# Vehicles' 459 (1.9 of its 2.0 GiB). Dropping the levels from the first such height onward keeps them compressed. The picture itself is
# untouched; only the smallest copies, used when zoomed far out, go. Unity's own loader reads the shorter chain as it reads any other.
DDS_MAGIC = b"DDS "
DDS_HEADER_BYTES = 128                   # "DDS " and the 124-byte header
DX10_HEADER_BYTES = 148                  # and the 20-byte DX10 extension
MIPMAP_COUNT_FLAG = 0x20000              # DDSD_MIPMAPCOUNT: without it the file holds one level
FOURCC_FLAG = 0x4                        # DDPF_FOURCC
CUBEMAP_FLAG = 0x200                     # DDSCAPS2_CUBEMAP: six faces, never touched here
BLOCK_PIXELS = 4
# Fewer levels than this and a picture would shimmer when zoomed out, so it is left whole for Waylith to unpack, as before (agent default,
# 20 Nov 2026: it caught only D'thorga Vehicles' Osprey nacelle frames, 24 narrow pictures, about 33 MB unpacked between them). Four
# levels reach an eighth of the full size. Such a picture is better fixed in its art, at a height with more factors of two.
MIN_KEPT_MIPS = 4
FOURCC_BLOCK_BYTES = {b"DXT1": 8, b"DXT3": 16, b"DXT5": 16, b"ATI1": 8, b"BC4U": 8, b"ATI2": 16, b"BC5U": 16}
DXGI_BLOCK_BYTES = {**dict.fromkeys((70, 71, 72, 79, 80, 81), 8),                                  # BC1, BC4
                    **dict.fromkeys((73, 74, 75, 76, 77, 78, 82, 83, 84, 94, 95, 96, 97, 98, 99), 16)}  # BC2, BC3, BC5, BC6H, BC7


@dataclass(frozen=True)
class DdsLayout:
    width: int
    height: int
    mips: int
    block_bytes: int
    header_bytes: int

    def level_bytes(self, level):
        width, height = max(1, self.width >> level), max(1, self.height >> level)
        return -(-width // BLOCK_PIXELS) * -(-height // BLOCK_PIXELS) * self.block_bytes

    def data_bytes(self, levels=None):
        return sum(self.level_bytes(level) for level in range(self.mips if levels is None else levels))


def read_layout(head, file_size):
    """A block-compressed 2D DDS file's layout from its first 148 bytes, or None for anything else (plain pixels, cube maps, arrays,
    a size that does not add up), which is then left alone."""
    if len(head) < DDS_HEADER_BYTES or head[:4] != DDS_MAGIC or int.from_bytes(head[4:8], "little") != 124:
        return None
    flags, height, width = (int.from_bytes(head[at:at + 4], "little") for at in (8, 12, 16))
    mips = int.from_bytes(head[28:32], "little") if flags & MIPMAP_COUNT_FLAG else 1
    pixel_flags, fourcc = int.from_bytes(head[80:84], "little"), head[84:88]
    if not pixel_flags & FOURCC_FLAG or int.from_bytes(head[112:116], "little") & CUBEMAP_FLAG or not (width and height):
        return None
    if fourcc == b"DX10":
        if len(head) < DX10_HEADER_BYTES or int.from_bytes(head[140:144], "little") > 1:
            return None
        block, header = DXGI_BLOCK_BYTES.get(int.from_bytes(head[128:132], "little")), DX10_HEADER_BYTES
    else:
        block, header = FOURCC_BLOCK_BYTES.get(fourcc), DDS_HEADER_BYTES
    if block is None:
        return None
    layout = DdsLayout(width, height, max(1, mips), block, header)
    return layout if header + layout.data_bytes() == file_size else None


def kept_mips(height, mips):
    """How many mip levels stay compressed under Waylith's rule: up to the first level four or more pixels tall whose height is not a
    multiple of four. 0 when the full-size picture itself fails (todds' -fs prevents it)."""
    for level in range(mips):
        level_height = max(1, height >> level)
        if level_height >= BLOCK_PIXELS and level_height % BLOCK_PIXELS:
            return level
    return mips


TRIMMED, IN_STEP, LEFT_WHOLE, NOT_COMPRESSED = "trimmed", "in step", "left whole", "not compressed"
FIXABLE = "fixable"      # Waylith unpacks it, and shortening its chain would keep it compressed


def classify(head, file_size, min_kept=MIN_KEPT_MIPS):
    """(verdict, layout, levels to keep) for a DDS file from its first 148 bytes and its size: FIXABLE, IN_STEP, LEFT_WHOLE (Waylith
    unpacks it, but fewer than min_kept levels would remain) or NOT_COMPRESSED."""
    layout = read_layout(head, file_size)
    if layout is None:
        return NOT_COMPRESSED, None, 0
    keep = kept_mips(layout.height, layout.mips)
    if keep == layout.mips:
        return IN_STEP, layout, keep
    return (LEFT_WHOLE if keep < min_kept else FIXABLE), layout, keep


def trim_mips(path, min_kept=MIN_KEPT_MIPS):
    """Shortens one DDS file's mip chain where Waylith would otherwise unpack it, writing a new file beside it and moving it into place.
    Returns TRIMMED, IN_STEP, LEFT_WHOLE (fewer than min_kept levels would remain) or NOT_COMPRESSED; only TRIMMED changes the file."""
    path = Path(path)
    with path.open("rb") as handle:
        head = handle.read(DX10_HEADER_BYTES)
    verdict, layout, keep = classify(head, path.stat().st_size, min_kept)
    if verdict != FIXABLE:
        return verdict
    data = path.read_bytes()
    header = bytearray(data[:layout.header_bytes])
    header[28:32] = keep.to_bytes(4, "little")
    temporary = path.with_name(path.name + ".trimming")
    temporary.write_bytes(bytes(header) + data[layout.header_bytes:layout.header_bytes + layout.data_bytes(keep)])
    os.replace(temporary, path)
    return TRIMMED


@dataclass
class MipTrim:
    checked: int = 0
    trimmed: list = field(default_factory=list)      # relative paths shortened now
    left_whole: list = field(default_factory=list)   # relative paths Waylith still unpacks: too few levels would remain
    failed: list = field(default_factory=list)       # relative paths that could not be read or written


def trim_folder(folder, min_kept=MIN_KEPT_MIPS):
    """Shortens the mip chain of every encoded texture in a mod folder that Waylith would unpack; only paths containing "Textures",
    as todds' preset encodes them. Files already in step are only read (their first 148 bytes), so a second run changes nothing."""
    folder = Path(folder)
    found = MipTrim()
    for path in sorted(folder.rglob("*")):
        if not path.name.lower().endswith(DDS_SUFFIX) or PATH_SEGMENT not in str(path) or not path.is_file():
            continue
        relative = path.relative_to(folder).as_posix()
        found.checked += 1
        try:
            outcome = trim_mips(path, min_kept)
        except OSError:
            found.failed.append(relative)
            continue
        if outcome == TRIMMED:
            found.trimmed.append(relative)
        elif outcome == LEFT_WHOLE:
            found.left_whole.append(relative)
    return found


# What status remembers of each .dds (kit 1.57.0): its verdict, keyed by path, size and modification time, so a check of every active
# mod reads only the headers of files that changed. A cold read of the owner's 36,447 encoded textures took 35 seconds on 20 Nov 2026;
# names and dates alone take about three. A file whose size or date changed (an update, encode's own shortening) is read again.
HEADER_CACHE_NAMESPACE = "rimworld-textures"
HEADER_CACHE_FILE = "dds-headers.sqlite"
HEADER_RULES = f"waylith-height-4/min-kept-{MIN_KEPT_MIPS}"     # a change to the rule or its threshold reads every file again


class HeaderCache:
    """Verdicts on .dds files (FIXABLE, IN_STEP, LEFT_WHOLE, NOT_COMPRESSED), read from disk only when a file is new or changed. Safe
    to share between the threads status checks mods in: lookups read a dictionary loaded at the start, new verdicts go in under a
    lock, and save() writes them once, dropping files not seen in this run. Without a path it remembers nothing between runs."""

    def __init__(self, path=None):
        self.path = Path(path) if path else None
        self._known, self._seen, self._lock = {}, {}, threading.Lock()
        self.read_now = 0
        if self.path is not None and cache.is_current(self.path, {"rules": HEADER_RULES}):
            try:
                with closing(cache.open_read_only(self.path)) as conn:
                    self._known = {row[0]: tuple(row[1:]) for row in conn.execute("SELECT path, size, mtime_ns, verdict FROM headers")}
            except sqlite3.Error:
                self._known = {}

    @classmethod
    def default(cls, environ=None, settings=None):
        return cls(cache.folder(HEADER_CACHE_NAMESPACE, None, environ, settings) / HEADER_CACHE_FILE)

    def verdict(self, path, size, mtime_ns):
        key = str(path).lower()
        known = self._known.get(key)
        if known is not None and known[0] == size and known[1] == mtime_ns:
            found = known[2]
        else:
            try:
                with open(path, "rb") as handle:
                    found = classify(handle.read(DX10_HEADER_BYTES), size)[0]
            except OSError:
                return NOT_COMPRESSED          # unreadable now: neither counted nor remembered
            with self._lock:
                self.read_now += 1
        with self._lock:
            self._seen[key] = (size, mtime_ns, found)
        return found

    def save(self):
        """Writes what this run saw; a cache folder that cannot be written only costs the next run its reading time."""
        if self.path is None:
            return False
        if self.read_now == 0 and self._seen.keys() == self._known.keys():
            return True                        # nothing new and nothing gone: the file already says it
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_name(self.path.name + ".writing")
            cache.remove(temporary)
            with closing(sqlite3.connect(temporary)) as conn:
                conn.execute("CREATE TABLE headers (path TEXT PRIMARY KEY, size INTEGER, mtime_ns INTEGER, verdict TEXT)")
                conn.executemany("INSERT INTO headers VALUES (?, ?, ?, ?)",
                                 sorted((key, *values) for key, values in self._seen.items()))
                cache.write_meta(conn, {"rules": HEADER_RULES, "files": len(self._seen)})
                conn.commit()
            os.replace(temporary, self.path)
            return True
        except (OSError, sqlite3.Error):
            return False
