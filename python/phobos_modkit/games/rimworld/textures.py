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

from dataclasses import dataclass, field
import os
from pathlib import Path
import subprocess

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

    @property
    def needs_encoding(self):
        return bool(self.stale or self.missing)


def check_folder(folder, slack=SLACK_SECONDS):
    """How a mod folder's encoded textures stand against its pictures. Reads file names and dates only."""
    folder = Path(folder)
    base = len(str(folder)) + 1
    pictures, encoded = {}, {}
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
                        mtime = entry.stat(follow_symlinks=False).st_mtime   # from the listing itself on Windows
                    except OSError:
                        continue
                    relative = entry.path[base:].replace("\\", "/")
                    (pictures if lower.endswith(SOURCE_SUFFIX) else encoded)[entry.path[:-4].lower()] = (mtime, relative)
        except OSError:
            continue
    found = Freshness(pictures=len(pictures))
    for stem, (mtime, relative) in sorted(pictures.items(), key=lambda item: item[1][1]):
        if stem not in encoded:
            found.missing.append(relative)
        elif mtime > encoded[stem][0] + slack:
            found.stale.append(relative)
    found.left_over = sorted(relative for stem, (_, relative) in encoded.items() if stem not in pictures)
    return found


def encode(folder, todds, run=subprocess.run):
    """Runs todds with RimSort's preset on one mod folder. Returns (exit code, its last line of output)."""
    result = run([str(todds), *RIMSORT_OPTIMIZED, str(Path(folder))], capture_output=True, text=True, check=False,
                 timeout=ENCODE_TIMEOUT)
    lines = ((result.stdout or "") + (result.stderr or "")).strip().splitlines()
    return result.returncode, (lines[-1][:300] if lines else "")
