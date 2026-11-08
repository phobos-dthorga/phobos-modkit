"""RimWorld's mod settings files: which mod each belongs to, whether it is active, and what it holds.

Summarised in our own words from the 1.7 game code (Verse.Mod.GetSettings, Verse.LoadedModManager.ReadModSettings and
Verse.Scribe_Values.Look, read November 2026):

- A mod's settings live in the game's Config folder as Mod_<folder>_<class>.xml: <folder> is the folder the mod was
  loaded from (a Workshop item's number, or a local folder's name) and <class> the name of its Mod class. The file holds
  <SettingsBlock><ModSettings Class="..."> with one element per saved value.
- **A value equal to its default is not written** (unless the mod forces it), and a key missing on load takes the
  default. So a file lists only what differs from the defaults the mod's code names; a value never saved does not appear.
- A file stays after its mod is removed or renamed; the game never deletes it. Other settings systems (HugsLib's folder,
  Mod Settings Framework's files) are not this format, and are only counted.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET

FILE_NAME = re.compile(r"^Mod_(?P<rest>.+)\.xml$")
LIST_SHOWN = 8


class SettingsError(ValueError):
    pass


@dataclass
class SettingsFile:
    path: Path
    folder: str                 # the mod folder the name points at
    handle: str                 # the Mod class's name
    settings_class: str = ""    # the ModSettings class the file was written by
    values: dict = field(default_factory=dict)   # flattened key -> text, in file order
    problem: str = ""
    mod: object = None          # the InstalledMod it belongs to, when one is installed
    active: bool = False
    position: int = -1          # load-order position when active

    @property
    def saved(self):
        return datetime.fromtimestamp(self.path.stat().st_mtime, timezone.utc).strftime("%Y-%m-%d")

    @property
    def label(self):
        return self.mod.name if self.mod else self.folder


def split_name(name, known_folders):
    """(folder, class) from a file name: the longest installed mod folder it starts with (a class name may hold underscores,
    as Vanilla Expanded Framework's AnimalBehaviours_Mod does), else the split at the last underscore."""
    found = FILE_NAME.match(name)
    if not found:
        return None
    rest = found["rest"]
    for folder in sorted(known_folders, key=len, reverse=True):
        if rest.startswith(folder + "_") and len(rest) > len(folder) + 1:
            return folder, rest[len(folder) + 1:]
    if "_" not in rest:
        return None
    folder, handle = rest.rsplit("_", 1)
    return folder, handle


def _leaf_text(element):
    text = (element.text or "").strip()
    return text if text else "(empty)"


def flatten(element, prefix=""):
    """Every saved value under element as key -> text: a list of plain items becomes one value, "[3] a; b; c"."""
    values = {}
    for child in element:
        key = f"{prefix}{child.tag}"
        items = list(child)
        if not items:
            values[key] = _leaf_text(child)
        elif all(item.tag == "li" and not list(item) for item in items):
            texts = [_leaf_text(item) for item in items]
            values[key] = f"[{len(texts)}] " + "; ".join(texts)
        else:
            for index, item in enumerate(items):
                if item.tag == "li":
                    sub = flatten(item, f"{key}[{index}]/") if list(item) else {f"{key}[{index}]": _leaf_text(item)}
                else:
                    sub = flatten(item, f"{key}/") if list(item) else {f"{key}/{item.tag}": _leaf_text(item)}
                values.update(sub)
    return values


def read_file(path, folder, handle):
    found = SettingsFile(Path(path), folder, handle)
    try:
        root = ET.parse(path).getroot()
    except (ET.ParseError, OSError) as error:
        found.problem = f"unreadable: {error}"
        return found
    block = root.find("ModSettings") if root.tag == "SettingsBlock" else None
    if block is None:
        found.problem = "not a mod settings file (no SettingsBlock/ModSettings)"
        return found
    found.settings_class = block.get("Class", "")
    found.values = flatten(block)
    return found


def scan(config, installed=(), active=()):
    """(settings files, other file names) in the Config folder. installed are InstalledMods; active are ActiveMods."""
    config = Path(config)
    if not config.is_dir():
        raise SettingsError(f"No Config folder at {config}. Name it with --config.")
    by_folder = {}
    for mod in installed:
        by_folder.setdefault(mod.folder.name, []).append(mod)
    active_at = {}
    for entry in active:
        if entry.mod is not None:
            active_at[entry.mod.folder] = entry.position
    files, others = [], []
    for path in sorted(config.iterdir(), key=lambda p: p.name.lower()):
        if not path.is_file():
            others.append(path.name + "/")
            continue
        split = split_name(path.name, by_folder)
        if split is None:
            others.append(path.name)
            continue
        found = read_file(path, *split)
        candidates = by_folder.get(found.folder, [])
        live = [m for m in candidates if m.folder in active_at]
        found.mod = (live or candidates or [None])[0]
        if found.mod is not None and found.mod.folder in active_at:
            found.active, found.position = True, active_at[found.mod.folder]
        files.append(found)
    return files, others


# ---- Defaults a consumer supplies (read from its own source) ----

def read_defaults(path):
    """{settings class: {key: {"default": text, ...}}} from a defaults file (schemaVersion 1)."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise SettingsError(f"Cannot read defaults from {path}: {error}") from None
    if data.get("schemaVersion") != 1 or not isinstance(data.get("classes"), dict):
        raise SettingsError(f"{path}: expected schemaVersion 1 and a classes object")
    return data["classes"]


def same_value(saved, default):
    """Whether a saved text equals a default as RimWorld would compare them (True/true, 1.0/1)."""
    if saved.lower() == str(default).lower():
        return True
    try:
        return float(saved) == float(default)
    except ValueError:
        return False


# ---- Snapshots: every file's values, to compare later ----

def snapshot(files):
    return {"schemaVersion": 1, "files": {f.path.name: {"mod": f.label, "class": f.settings_class, "values": f.values}
                                          for f in files}}


def read_snapshot(path):
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise SettingsError(f"Cannot read the snapshot {path}: {error}") from None
    if data.get("schemaVersion") != 1 or "files" not in data:
        raise SettingsError(f"{path} is not a settings snapshot")
    return data


def compare(before, after):
    """Rows of (file, mod, key, before, after) for every value added, removed or changed, and files that came or went."""
    rows = []
    old, new = before["files"], after["files"]
    for name in sorted(set(old) | set(new), key=str.lower):
        a, b = old.get(name), new.get(name)
        mod = (b or a)["mod"]
        if a is None:
            rows.append((name, mod, "(the whole file)", "(none)", f"{len(b['values'])} values"))
            continue
        if b is None:
            rows.append((name, mod, "(the whole file)", f"{len(a['values'])} values", "(gone)"))
            continue
        for key in list(dict.fromkeys(list(a["values"]) + list(b["values"]))):
            x, y = a["values"].get(key), b["values"].get(key)
            if x != y:
                rows.append((name, mod, key, x if x is not None else "(default)", y if y is not None else "(default)"))
    return rows
