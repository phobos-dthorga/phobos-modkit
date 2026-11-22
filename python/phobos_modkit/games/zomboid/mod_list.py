"""Project Zomboid's side of the mod-list check (1.72.0): its lists of active mods and its mods' mod.info files.

Seen on the owner's PC on 22 Nov 2026 (Build 42.16, the game itself not installed at the time), in our own words:

- **The lists**: `<data>/mods/default.txt` (the mods the game starts with) and each save's `Saves/<mode>/<save>/mods.txt`, in one
  format: `VERSION = 1,`, then a `mods { ... }` block of `    mod = <id>,` lines, then a `maps { ... }` block. An id is everything
  between "mod = " and the last comma: it may hold spaces, dots, apostrophes and other letters. `mods/reset-mods-42_00.txt` must be
  left alone (without it the game empties default.txt).
- **A mod** is a folder holding `mod.info` (`key=value` lines), in `<data>/mods/`, in the author's own `<data>/Workshop/<item>/
  Contents/mods/`, or in Steam's `workshop/content/108600/<item>/mods/`. Build 42 mods keep a `mod.info` per game version folder
  (`42`, `42.15`); the one for the highest version not above the game's is read, else the folder's own.
- `require`, `incompatible`, `loadModAfter` and `loadModBefore` list ids separated by commas, each with a leading backslash in
  Build 42, which the lists themselves do not carry.

Not confirmed, and said so where it matters: the game's process names, whether the game sorts the list itself, and whether
Build 42 ids are compared with case.
"""
from __future__ import annotations

import os
from pathlib import Path
import re

from ...game_files import libraries, parse_vdf, steam_root
from ...game_folders import FOLDERS
from ...mod_list import Mod, ModList, Need
from ...steam.client import library_path as steam_library_path
from ...paths import resolve

APP_ID = 108600
PROCESSES = ("ProjectZomboid64.exe", "ProjectZomboid32.exe", "ProjectZomboid.exe")   # usual names, unconfirmed here
MANAGERS = ()
DATA = next((key, env) for key, env, *_ in FOLDERS if key == "zomboidDataPath")
DATA_DEFAULT = next(default for key, _, _, _, default in FOLDERS if key == "zomboidDataPath")
ENTRY = re.compile(r"^\s*mod\s*=\s*(.*?),?\s*$")
MODS_BLOCK = re.compile(r"(?P<open>^mods[ \t\r]*\n?\{[ \t]*)(?P<body>.*?)(?P<close>^\}[ \t\r]*$)", re.S | re.M)
VERSION_FOLDER = re.compile(r"^\d+(\.\d+)*$")
WORKSHOP_NUMBER = re.compile(r"id=(\d{6,})")
CLUE_SUFFIXES = frozenset({".lua", ".txt", ".info", ".xml", ".json"})
CLUE_FILE_BYTES = 4 * 1024 * 1024
CLUE_TOTAL_BYTES = 64 * 1024 * 1024


def _version_key(text):
    return tuple(int(p) for p in re.findall(r"\d+", text or ""))


def _ids(text):
    return [part.strip().lstrip("\\").strip() for part in (text or "").split(",") if part.strip().lstrip("\\").strip()]


def read_info(path):
    """{key: [values]} of one mod.info."""
    found = {}
    try:
        lines = Path(path).read_text(encoding="utf-8-sig", errors="replace").splitlines()
    except OSError:
        return found
    for line in lines:
        key, sep, value = line.partition("=")
        if sep and key.strip():
            found.setdefault(key.strip().lower(), []).append(value.strip())
    return found


def info_file(mod_folder, version):
    """The mod.info the game reads for this version: the highest version folder not above it, else the folder's own."""
    best, best_key = None, ()
    game = _version_key(version)
    try:
        children = list(Path(mod_folder).iterdir())
    except OSError:
        return None
    for child in children:
        if child.is_dir() and VERSION_FOLDER.match(child.name) and (child / "mod.info").is_file():
            key = _version_key(child.name)
            if (not game or key <= game) and key >= best_key:
                best, best_key = child / "mod.info", key
    if best is None and (Path(mod_folder) / "mod.info").is_file():
        best = Path(mod_folder) / "mod.info"
    return best


def read_mod(mod_folder, source, workshop_id, version):
    path = info_file(mod_folder, version)
    if path is None:
        return None
    info = read_info(path)
    first = lambda key: (info.get(key) or [""])[0]
    mod_id = first("id")
    if not mod_id:
        return None
    url_id = WORKSHOP_NUMBER.search(first("url"))
    return Mod(mod_id, first("name") or mod_id, source, str(mod_folder), workshop_id or (url_id.group(1) if url_id else ""),
               first("authors") or first("author"), [Need((i,)) for i in _ids(first("require"))],
               _ids(first("loadmodafter")), _ids(first("loadmodbefore")), _ids(first("incompatible")), [],
               first("versionmin"), first("versionmax"), preview=_poster(path.parent, first("poster")))


def _poster(info_folder, poster):
    """The picture mod.info names as its poster, beside that mod.info (1.82.0); "" when it names none or the file is not there."""
    name = poster.strip().replace("\\", "/")
    if not name or name.startswith("/") or ".." in name.split("/"):
        return ""
    path = Path(info_folder) / name
    return str(path) if path.is_file() else ""


def read_list(path):
    ids = []
    match = MODS_BLOCK.search(Path(path).read_bytes().decode("utf-8-sig"))
    for line in (match.group("body").splitlines() if match else []):
        found = ENTRY.match(line)
        if found and found.group(1):
            ids.append(found.group(1))
    return ids


class Zomboid:
    game = "project-zomboid"
    name = "Project Zomboid"
    app_id = APP_ID
    processes = PROCESSES
    managers = MANAGERS

    def __init__(self, environ=None, settings=None, data=None, steam=None):
        self.environ = os.environ if environ is None else environ
        self.data = Path(data) if data else Path(resolve(*DATA, DATA_DEFAULT(self.environ), None, self.environ, settings))
        self.steam = Path(steam) if steam else Path(steam_root(self.environ))
        self.library = self._library()
        self.workshop = self.library / "steamapps" / "workshop" / "content" / str(APP_ID) if self.library else None

    def _library(self):
        for library in libraries(self.steam):
            if (library / "steamapps" / f"appmanifest_{APP_ID}.acf").is_file():
                return library
        return None

    def notes(self):
        found = []
        if not self.data.is_dir():
            found.append(f"Project Zomboid's own folder was not found at {self.data}: set it in the tools' settings.")
        if self.library is None:
            found.append("Project Zomboid is not installed on this PC, so its Workshop mods are not here to look at: only your "
                         "own mods were checked. Install it in Steam, then check again.")
        found.append("Project Zomboid's own load order rules are not confirmed: the order warnings follow what each mod's "
                     "mod.info asks for.")
        return found

    def key(self, mod_id):
        return mod_id.strip()

    def pick(self, candidates, listed):
        return candidates[0] if candidates else None

    def listed_id(self, mod):
        return mod.id

    def can_check_missing(self):
        return self.library is not None

    def is_local_id(self, listed):
        return False

    def why_unchecked(self):
        return ("Project Zomboid is not installed on this PC, so the Workshop mods these name are not here to look for. Install "
                "it in Steam, then check again.")

    def how_to_get(self, need):
        return "Find it on the Workshop by its name or id, subscribe, then check again."

    def game_version(self):
        try:
            return (self.data / "version.txt").read_text(encoding="utf-8", errors="replace").split()[0]
        except (OSError, IndexError):
            return ""

    def version_misfit(self, mod, version):
        game = _version_key(version)
        if mod.version_min and _version_key(mod.version_min) > game:
            return f"{mod.name} needs version {mod.version_min} of the game or later; this is {version}."
        if mod.version_max and _version_key(mod.version_max) < game:
            return f"{mod.name} says it works up to version {mod.version_max} of the game; this is {version}."
        return ""

    def _roots(self):
        roots = [("local", self.data / "mods", ""), ]
        workshop_uploads = self.data / "Workshop"
        if workshop_uploads.is_dir():
            for item in sorted(workshop_uploads.iterdir()):
                roots.append(("local", item / "Contents" / "mods", ""))
        if self.workshop and self.workshop.is_dir():
            for item in sorted(self.workshop.iterdir()):
                roots.append(("workshop", item / "mods", item.name))
        return roots

    def installed(self):
        found = []
        version = self.game_version()
        for source, root, workshop_id in self._roots():
            if not root.is_dir():
                continue
            for mod_folder in sorted(root.iterdir(), key=lambda p: p.name):
                if mod_folder.is_dir():
                    mod = read_mod(mod_folder, source, workshop_id, version)
                    if mod is not None:
                        found.append(mod)
        return found

    def lists(self):
        found = []
        default = self.data / "mods" / "default.txt"
        if default.is_file():
            found.append(ModList("default", "The mods the game starts with (mods/default.txt)", default, read_list(default)))
        saves = self.data / "Saves"
        for listed in sorted(saves.glob("*/*/mods.txt")) if saves.is_dir() else []:
            mode, save = listed.parent.parent.name, listed.parent.name
            found.append(ModList(f"save:{mode}/{save}", f"The save {save} ({mode})", listed, read_list(listed)))
        return found

    def subscribed(self):
        if self.library is None:
            return None
        record = self.library / "steamapps" / "workshop" / f"appworkshop_{APP_ID}.acf"
        if not record.is_file():
            return None
        data = parse_vdf(record.read_text(encoding="utf-8", errors="replace")).get("AppWorkshop", {})
        found = set()
        for part in ("WorkshopItemsInstalled", "WorkshopItemDetails"):
            if isinstance(data.get(part), dict):
                found.update(data[part].keys())
        return found

    def steam_library(self):
        """The game's own Steam library, which subscribing borrows (1.77.0); None while the game is not installed."""
        if not self.library:
            return None
        return steam_library_path(self.library / "steamapps" / "common" / "ProjectZomboid")

    def mentions(self, mod, words):
        needles = [w.lower().encode("utf-8") for w in words]
        read = 0
        for current, _, files in os.walk(mod.folder):
            for name in files:
                path = Path(current) / name
                if path.suffix.lower() not in CLUE_SUFFIXES:
                    continue
                try:
                    size = path.stat().st_size
                    if size > CLUE_FILE_BYTES:
                        continue
                    data = path.read_bytes().lower()
                except OSError:
                    continue
                if any(n in data for n in needles):
                    return True
                read += size
                if read > CLUE_TOTAL_BYTES:
                    return False
        return False

    def render(self, text, ids):
        """The list file with only its mods block changed, in the file's own line endings."""
        newline = "\r\n" if "\r\n" in text else "\n"
        match = MODS_BLOCK.search(text)
        if match is None:
            raise ValueError("This list has no mods { } block.")
        body = "".join(f"{newline}    mod = {i}," for i in ids)
        return text[:match.start("body")] + body + newline + text[match.start("close"):]


def adapter(environ=None, settings=None, data=None, steam=None):
    return Zomboid(environ, settings, data, steam)
