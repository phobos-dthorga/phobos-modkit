"""How RimWorld chooses what to load: the active mods in order, each mod's load folders, and which files in them.

Summarised in our own words from the 1.7 game code (Verse.ModContentPack, Verse.DirectXmlLoader and
Verse.LoadedModManager, read November 2026) and from phobos-rimworld's checks, which were run against a real
install:

- ModsConfig.xml lists the active mods' package IDs in load order. A Workshop copy of a mod that is also installed
  locally is listed with the suffix "_steam".
- A mod's LoadFolders.xml has a block per game version (<v1.7>); the game uses its own version's block, or the
  newest lower one. Each <li> names a folder; IfModActive (any of the listed mods), IfModActiveAll (all of them) and
  IfModNotActive (none of them) make it conditional. Without LoadFolders.xml the game loads the mod's root, Common
  and the newest version folder not above its own.
- Defs and Patches files are keyed by their path inside a load folder; when two load folders hold the same path,
  the later-listed folder's file loads and the other is skipped without a message.
- A top-level Def with MayRequire loads only when every listed mod is active; with MayRequireAnyOf, when at least one
  is. Package IDs are compared without case and without the "_steam" suffix. Abstract="true" Defs never load.
- ParentName: a node with a Name registers as a parent when its MayRequire is met; a second node with that Name in
  the same mod is refused. A child takes the parent from the latest mod at or before its own in load order.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import xml.etree.ElementTree as ET

STEAM_SUFFIX = "_steam"
VERSION_FOLDER = re.compile(r"^\d+\.\d+$")


@dataclass(frozen=True)
class ActiveMod:
    position: int        # load order, from 0
    listed_id: str       # as ModsConfig.xml lists it, lower case
    mod: object          # the InstalledMod, or None when it is not installed


def _version_key(text):
    return tuple(int(p) for p in text.split("."))


def bare_id(package_id):
    """A package ID without case or the Workshop suffix, as the game compares them for MayRequire and IfModActive."""
    package_id = package_id.strip().lower()
    return package_id[:-len(STEAM_SUFFIX)] if package_id.endswith(STEAM_SUFFIX) else package_id


def read_mods_config(path):
    """(game version like "1.7", the full version text, active package IDs in load order, lower case)."""
    root = ET.parse(path).getroot()
    full = (root.findtext("version") or "").strip()
    match = re.match(r"(\d+\.\d+)", full)
    active_list = root.find("activeMods")
    active = [li.text.strip().lower() for li in (active_list if active_list is not None else []) if li.text]
    return (match.group(1) if match else ""), full, active


def resolve_active(installed, active_ids):
    """ActiveMod for each listed ID, in load order. "x_steam" is the Workshop copy of x; plain "x" prefers a local or
    game copy over a Workshop one."""
    by_id = {}
    for mod in installed:
        by_id.setdefault((mod.package_id, mod.source == "Workshop"), mod)
    found = []
    for position, listed in enumerate(active_ids):
        if listed.endswith(STEAM_SUFFIX):
            mod = by_id.get((bare_id(listed), True))
        else:
            mod = by_id.get((listed, False)) or by_id.get((listed, True))
        found.append(ActiveMod(position, listed, mod))
    return found


def _child_file(folder, name):
    try:
        return next((p for p in Path(folder).iterdir() if p.is_file() and p.name.lower() == name), None)
    except OSError:
        return None


def _condition_met(li, active):
    any_of = li.get("IfModActive")
    if any_of and not any(bare_id(pid) in active for pid in any_of.split(",")):
        return False
    all_of = li.get("IfModActiveAll")
    if all_of and not all(bare_id(pid) in active for pid in all_of.split(",")):
        return False
    none_of = li.get("IfModNotActive")
    if none_of and any(bare_id(pid) in active for pid in none_of.split(",")):
        return False
    return True


def load_folders(mod_folder, version, active):
    """The folders the game loads from a mod, in LoadFolders order. active: bare package IDs of every active mod."""
    mod_folder = Path(mod_folder)
    load_file = _child_file(mod_folder, "loadfolders.xml")
    if load_file is None:
        folders = [mod_folder, mod_folder / "Common"]
        try:
            versions = sorted((p for p in mod_folder.iterdir() if p.is_dir() and VERSION_FOLDER.match(p.name)
                               and (not version or _version_key(p.name) <= _version_key(version))),
                              key=lambda p: _version_key(p.name))
        except OSError:
            versions = []
        if versions:
            folders.append(versions[-1])
        return [f for f in folders if f.is_dir()]
    try:
        root = ET.parse(load_file).getroot()
    except ET.ParseError:
        return [mod_folder]
    blocks = {child.tag[1:]: child for child in root
              if isinstance(child.tag, str) and child.tag.startswith("v") and VERSION_FOLDER.match(child.tag[1:])}
    usable = sorted((v for v in blocks if not version or _version_key(v) <= _version_key(version)), key=_version_key)
    if not usable:
        return [mod_folder]
    folders = []
    for li in blocks[usable[-1]].findall("li"):
        if not _condition_met(li, active):
            continue
        relative = (li.text or "").strip().strip("/").replace("\\", "/")
        folder = mod_folder / relative if relative else mod_folder
        if folder.is_dir() and folder not in folders:
            folders.append(folder)
    return folders


def files_the_game_loads(folder_files):
    """Which files load when several load folders hold the same relative path.

    folder_files is [(folder, [paths inside it])] in LoadFolders order. The game walks the folders from the last to
    the first and the first to claim a path wins. Returns ({path: folder that loads it}, [(skipped folder, path,
    winning folder)])."""
    loaded, skipped = {}, []
    for folder, paths in reversed(folder_files):
        for path in paths:
            if path in loaded:
                skipped.append((folder, path, loaded[path]))
            else:
                loaded[path] = folder
    return loaded, skipped


def xml_files(folders, kind):
    """[(load folder, path inside it)] of the XML files under each folder's Defs or Patches that the game loads, in
    a stable order, and the skipped ones as [(file, file loaded instead)]."""
    folder_files = []
    for folder in folders:
        try:
            sub = next((p for p in folder.iterdir() if p.is_dir() and p.name.lower() == kind.lower()), None)
        except OSError:
            sub = None
        paths = sorted(p.relative_to(folder).as_posix() for p in sub.rglob("*")
                       if p.is_file() and p.suffix.lower() == ".xml") if sub is not None else []
        folder_files.append((folder, paths))
    loaded, skipped = files_the_game_loads(folder_files)
    order = {folder: i for i, folder in enumerate(folders)}
    files = sorted(((folder, path) for path, folder in loaded.items()), key=lambda fp: (order[fp[0]], fp[1]))
    return files, [(folder / path, winner / path) for folder, path, winner in skipped]


def may_register_parent(element, active):
    """Whether a Def element with a Name can serve as a ParentName: its MayRequire mods must all be active (the
    game's XmlInheritance checks MayRequire only, not MayRequireAnyOf)."""
    every = element.get("MayRequire")
    return not every or all(bare_id(pid) in active for pid in every.split(","))


def may_load(element, active):
    """Whether the game loads a top-level Def element, by its MayRequire and MayRequireAnyOf attributes."""
    every = element.get("MayRequire")
    if every and not all(bare_id(pid) in active for pid in every.split(",")):
        return False
    any_of = element.get("MayRequireAnyOf")
    if any_of and not any(bare_id(pid) in active for pid in any_of.split(",")):
        return False
    return True
