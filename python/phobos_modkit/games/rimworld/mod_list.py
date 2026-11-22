"""RimWorld's side of the mod-list check (1.72.0): its one list (Config/ModsConfig.xml), and its mods as their About.xml files
describe them.

Summarised in our own words from the 1.7 game code (Verse.ModMetaData and Verse.ModsConfig, read 22 Nov 2026):

- A mod's version list (modDependenciesByVersion, loadAfterByVersion, loadBeforeByVersion, incompatibleWithByVersion) for the
  running version ("v1.7" or "1.7", any case) **replaces** its plain list; it does not add to it.
- The game warns, per active mod, about a second copy with the same package ID, mods it is incompatible with, mods it must load
  before or after (loadBefore/forceLoadBefore, loadAfter/forceLoadAfter) and needs not met. A need is not an order rule.
- Package IDs are compared without case; "x_steam" in ModsConfig.xml is the Workshop copy of x when a local copy exists too.
"""
from __future__ import annotations

from datetime import datetime, timezone
from html import unescape
import json
import os
from pathlib import Path
import re
import sys
from xml.etree import ElementTree

from ...game_files import libraries, parse_vdf, steam_root
from ...mod_list import Mod, ModList, Need
from ...installs import game_running
from ...steam.client import library_path as steam_library_path
from ...mod_lists import FILE, MANAGER, SAVE, SavedList
from ...mod_sort import CODE, COMMUNITY, WORKSHOP, YOURS, RuleSet
from .installs import PROCESSES
from .loading import STEAM_SUFFIX, bare_id, load_folders, read_mods_config
from .mods import _about_root, _child, _text
from .paths import LOG_NAME, PREVIOUS_LOG_NAME, config_path, game_path, logs_path, saves_path, workshop_path

APP_ID = 294100
MANAGERS = ("RimSort.exe", "RimPy.exe")
WORKSHOP_NUMBER = re.compile(r"(?:id=|CommunityFilePage/|filedetails/\?id=)(\d{6,})|^(\d{6,})$")
CLUE_SUFFIXES = frozenset({".xml", ".txt", ".dll", ".json"})
CLUE_FILE_BYTES = 4 * 1024 * 1024       # larger files are skipped when looking for a clue (agent default)
CLUE_TOTAL_BYTES = 64 * 1024 * 1024     # and the look stops after this much of one mod (agent default)
# Where RimSort keeps its rules (1.74.0), read only: its Community Rules database (downloaded from GitHub by RimSort) and the
# owner's own rules made in RimSort. Each is {"rules": {packageId: {"loadAfter": {id: {...}}, "loadBefore": {...},
# "loadTop": {"value": true}, "loadBottom": {"value": true}}}}; seen in RimSort 1.17.4 on 22 Nov 2026.
RIMSORT_COMMUNITY = ("dbs/Community-Rules-Database/communityRules.json", "communityRules.json")
RIMSORT_USER = ("dbs/userRules.json", "userRules.json")
# RimSort's Steam Workshop Database (1.79.0): {"version": time, "database": {Workshop number or app id: {"packageId", "name",
# "dependencies": {Workshop number: [name, url]}}}}, the items each mod's Workshop page lists as required. CC0; about 50 MB and
# 57,679 entries on 23 Nov 2026, read in a quarter of a second. Read once per file version and kept while the tools run.
RIMSORT_WORKSHOP = ("dbs/Steam-Workshop-Database/steamDB.json", "steamDB.json")
_WORKSHOP_CACHE = {}
_VERSIONS_CACHE = {}
# The community's two lists RimSort also keeps (1.85.0), both Mlie's, MIT: No Version Warning (`<version>/ModIdsToFix.xml`, the
# package ids known to work on a version though they do not say so) and Use This Instead (`replacements.json`: {"rules": [{
# "oldWorkshopId", "oldName", "oldPackageId", "newWorkshopId", "newName", "newAuthor", "newPackageId", "newVersions", ...}]}).
# Seen 23 Nov 2026: 1 id for 1.7, and 2,846 replacements.
RIMSORT_NO_VERSION_WARNING = "dbs/NoVersionWarning"
RIMSORT_USE_THIS_INSTEAD = "dbs/UseThisInstead/replacements.json"
# Lists the game and RimSort keep (1.75.0). A save (.rws) starts with <meta>: gameVersion, then modIds, modSteamIds and modNames
# in load order (Verse.ScribeMetaHeaderUtility.WriteMetaHeader); the game's own saved list (.rml, ModLists folder) is that header
# and a <modList> of <ids> and <names> (Verse.GameDataSaveLoader.SaveModList). RimSort keeps a history of lists as JSON
# ({"version", "activeMods"}) under modlists/history/<instance>/. Read from the 1.7 game code and RimSort 1.17.4, 22 Nov 2026.
LIST_SUFFIX = ".rml"
SAVE_SUFFIX = ".rws"
META_BYTES = 8 * 1024 * 1024          # a save's header is read up to its </meta>, never further than this (agent default)
LIST_FILE_BYTES = 64 * 1024 * 1024    # a list file larger than this is not read (agent default)
STARTED = re.compile(r"^Started:\s+(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d(?:\.\d+)?)(?: ([+-]\d\d:\d\d))?", re.M)
ACTIVE = re.compile(r"(?P<open><activeMods>)(?P<body>.*?)(?P<close>[ \t]*</activeMods>)|<activeMods\s*/>", re.S)


def _items(element):
    return [(li.text or "").strip() for li in (element if element is not None else []) if (li.text or "").strip()]


def _versioned(root, tag, version):
    """The list for this game version when the mod gives one (it replaces the plain list, as the game reads it), else the plain."""
    by_version = _child(root, f"{tag}ByVersion")
    if by_version is not None and version:
        for node in by_version:
            if isinstance(node.tag, str) and node.tag.lower().lstrip("v") == version:
                return node
    return _child(root, tag)


def _workshop_number(text):
    match = WORKSHOP_NUMBER.search((text or "").strip())
    return (match.group(1) or match.group(2)) if match else ""


def _needs(root, version):
    found = []
    listed = _versioned(root, "modDependencies", version)
    for li in (listed if listed is not None else []):
        if not isinstance(li.tag, str):
            continue
        package_id = _text(li, "packageId")
        if not package_id:
            continue
        alternatives = tuple(_items(_child(li, "alternativePackageIds")))
        found.append(Need((package_id.lower(),) + tuple(a.lower() for a in alternatives), _text(li, "displayName"),
                          _workshop_number(_text(li, "steamWorkshopUrl"))))
    return found


def rimsort_folder(environ):
    """RimSort's own data folder on this system (PHOBOS_RIMSORT names another, as the tests do)."""
    if environ.get("PHOBOS_RIMSORT"):
        return Path(environ["PHOBOS_RIMSORT"])
    home = Path(environ.get("USERPROFILE") or environ.get("HOME") or Path.home())
    if sys.platform == "win32" or environ.get("LOCALAPPDATA"):
        return Path(environ.get("LOCALAPPDATA") or home / "AppData" / "Local") / "RimSort"
    if sys.platform == "darwin":
        return home / "Library" / "Application Support" / "RimSort"
    return Path(environ.get("XDG_DATA_HOME") or home / ".local" / "share") / "RimSort"


def _words_of(value):
    if isinstance(value, list):
        return "; ".join(str(v) for v in value if v)
    return str(value or "")


def read_rimsort_rules(path):
    """{key: {"after": [(id, note)], "before": [...], "top": note|None, "bottom": note|None}} from one RimSort rules file."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return None
    rules = {}
    for package_id, entry in (data.get("rules") or {}).items() if isinstance(data, dict) else ():
        if not isinstance(entry, dict):
            continue
        found = {"after": [], "before": [], "top": None, "bottom": None}
        for word, tag in (("after", "loadAfter"), ("before", "loadBefore")):
            for other, info in (entry.get(tag) or {}).items():
                found[word].append((other, _words_of(info.get("comment")) if isinstance(info, dict) else ""))
        for word, tag in (("top", "loadTop"), ("bottom", "loadBottom")):
            info = entry.get(tag)
            if isinstance(info, dict) and info.get("value") is True:
                found[word] = _words_of(info.get("comment"))
        rules[package_id] = found
    return rules


def _items_of(block, tag):
    match = re.search(rf"<{tag}>(.*?)</{tag}>", block, re.S)
    return [unescape(i.strip()) for i in re.findall(r"<li>(.*?)</li>", match.group(1), re.S)] if match else []


def read_save_meta(path):
    """(version, ids, steam numbers, names) from a save's header, reading no further than its </meta>; None when it has none."""
    try:
        with open(path, "rb") as handle:
            head = b""
            while b"</meta>" not in head and len(head) < META_BYTES:
                chunk = handle.read(256 * 1024)
                if not chunk:
                    break
                head += chunk
    except OSError:
        return None
    text = head.decode("utf-8-sig", errors="replace")
    end = text.find("</meta>")
    if end < 0:
        return None
    meta = text[:end]
    version = re.search(r"<gameVersion>(.*?)</gameVersion>", meta, re.S)
    ids = _items_of(meta, "modIds")
    return (version.group(1).strip() if version else ""), ids, _items_of(meta, "modSteamIds"), _items_of(meta, "modNames")


def _when(path):
    try:
        return datetime.fromtimestamp(Path(path).stat().st_mtime, timezone.utc).isoformat(timespec="seconds")
    except OSError:
        return ""


def _known(ids, names, steam_ids):
    named = {bare_id(i): n for i, n in zip(ids, names) if n}
    # The game records a Steam number only for its expansions (their app ids); Workshop mods get 0, so none is a Workshop item.
    workshop = {bare_id(i): s for i, s in zip(ids, steam_ids) if s and s != "0" and not bare_id(i).startswith("ludeon.")}
    return named, workshop


def read_list_file(path):
    """A list from a file: the game's .rml, a save, an exported RimSort list (ModsConfig.xml's form) or RimSort's JSON."""
    path = Path(path)
    try:
        if path.stat().st_size > LIST_FILE_BYTES and path.suffix.lower() != SAVE_SUFFIX:
            return None
    except OSError:
        return None
    if path.suffix.lower() == SAVE_SUFFIX:
        meta = read_save_meta(path)
        if not meta or not meta[1]:
            return None
        names, workshop = _known(meta[1], meta[3], meta[2])
        return SavedList(FILE, str(path), path.stem, _when(path), meta[1], names, workshop, meta[0])
    try:
        text = path.read_bytes().decode("utf-8-sig", errors="replace")
    except OSError:
        return None
    if text.lstrip().startswith("{"):
        try:
            data = json.loads(text)
        except ValueError:
            return None
        ids = data.get("activeMods") if isinstance(data, dict) else None
        if not isinstance(ids, list) or not ids:
            return None
        return SavedList(FILE, str(path), path.stem, _when(path), [str(i) for i in ids], version=str(data.get("version", "")))
    try:
        root = ElementTree.fromstring(text)
    except ElementTree.ParseError:
        return None
    if root.tag == "savedModList":
        ids = _items(root.find("modList/ids"))
        names = _items(root.find("modList/names"))
        version = (root.findtext("meta/gameVersion") or "").strip()
        named, _ = _known(ids, names, [])
        return SavedList(FILE, str(path), path.stem, _when(path), ids, named, {}, version) if ids else None
    if root.tag == "ModsConfigData":
        ids = _items(root.find("activeMods"))
        return SavedList(FILE, str(path), path.stem, _when(path), ids, version=(root.findtext("version") or "").strip()) \
            if ids else None
    return None


def _escaped(text):
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def render_list_file(saved, newline="\r\n"):
    """A list as the game's own saved list (.rml), which the game's mod menu can load too."""
    names = [saved.names.get(bare_id(i), i) for i in saved.ids]
    steam = [saved.workshop.get(bare_id(i), "0") for i in saved.ids]

    def block(tag, values, indent):
        inner = "".join(f"{newline}{indent}\t<li>{_escaped(v)}</li>" for v in values)
        return f"{newline}{indent}<{tag}>{inner}{newline}{indent}</{tag}>"

    return ("<?xml version=\"1.0\" encoding=\"utf-8\"?>" + newline + "<savedModList>" + newline + "\t<meta>"
            + f"{newline}\t\t<gameVersion>{_escaped(saved.version)}</gameVersion>"
            + block("modIds", saved.ids, "\t\t") + block("modSteamIds", steam, "\t\t") + block("modNames", names, "\t\t")
            + newline + "\t</meta>" + newline + "\t<modList>" + block("ids", saved.ids, "\t\t")
            + block("names", names, "\t\t") + newline + "\t</modList>" + newline + "</savedModList>" + newline)


def read_workshop_rules(path):
    """{packageId: {"after": [(the required mod's packageId, note)], ...}} from RimSort's Steam Workshop Database, or None."""
    path = Path(path)
    try:
        stamp = path.stat().st_mtime_ns
    except OSError:
        return None
    cached = _WORKSHOP_CACHE.get(str(path))
    if cached and cached[0] == stamp:
        return cached[1]
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return None
    database = data.get("database") if isinstance(data, dict) else None
    if not isinstance(database, dict):
        return None
    package_of = {number: (entry.get("packageId") or entry.get("packageid") or "").lower()
                  for number, entry in database.items() if isinstance(entry, dict)}
    rules = {}
    for number, entry in database.items():
        if not isinstance(entry, dict) or not package_of.get(number) or not isinstance(entry.get("dependencies"), dict):
            continue
        needed = []
        for required, info in entry["dependencies"].items():
            other = package_of.get(str(required))
            if other and other != package_of[number]:
                name = info[0] if isinstance(info, list) and info else other
                needed.append((other, f"Its Workshop page lists {name} as required."))
        if needed:
            found = rules.setdefault(package_of[number], {"after": [], "before": [], "top": None, "bottom": None})
            found["after"].extend(needed)
    _WORKSHOP_CACHE[str(path)] = (stamp, rules)
    return rules


def _version_tuple(text):
    return tuple(int(p) for p in re.findall(r"\d+", text or ""))


def read_workshop_versions(path):
    """{Workshop number: {the game versions its Workshop page names}} from RimSort's Steam Workshop Database, or None."""
    path = Path(path)
    try:
        stamp = path.stat().st_mtime_ns
    except OSError:
        return None
    cached = _VERSIONS_CACHE.get(str(path))
    if cached and cached[0] == stamp:
        return cached[1]
    try:
        database = json.loads(path.read_text(encoding="utf-8-sig")).get("database")
    except (OSError, ValueError, AttributeError):
        return None
    versions = {}
    for number, entry in (database or {}).items():
        if not isinstance(entry, dict):
            continue
        found = {str(v) for v in entry.get("gameVersions") or []}
        found |= {str(tag.get("tag")) for tag in entry.get("tags") or [] if isinstance(tag, dict)}
        if found:
            versions[str(number)] = found
    _VERSIONS_CACHE[str(path)] = (stamp, versions)
    return versions


def read_known_working(folder, version):
    """The package ids (bare) the No Version Warning list says work on this version, from its `<version>/ModIdsToFix.xml`."""
    path = Path(folder) / version / "ModIdsToFix.xml"
    try:
        root = ElementTree.fromstring(path.read_bytes().decode("utf-8-sig"))
    except (OSError, ElementTree.ParseError):
        return set()
    return {bare_id((li.text or "").strip()) for li in root.iter("li") if (li.text or "").strip()}


def read_replacements(path):
    """The Use This Instead rules, as given, or [] when the file is missing or not as expected."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return []
    rules = data.get("rules") if isinstance(data, dict) else None
    return [r for r in rules or [] if isinstance(r, dict) and r.get("newWorkshopId")]


LOADED_SAVE = re.compile(r"Loading game from file (.+?) with mods")


def _save_loaded(text):
    """The save a run loaded (the first), or ""."""
    found = LOADED_SAVE.search(text or "")
    return found.group(1).strip() if found else ""


def read_about(folder, source, workshop_id, version):
    root = _about_root(Path(folder))
    if root is None:
        return None
    package_id = _text(root, "packageId")
    if not package_id:
        return None
    authors = _text(root, "author") or ", ".join(_items(_child(root, "authors")))
    if source == "local" and not workshop_id:
        published = Path(folder) / "About" / "PublishedFileId.txt"
        try:
            workshop_id = _workshop_number(published.read_text(encoding="utf-8-sig", errors="replace"))
        except OSError:
            pass
    return Mod(package_id.lower(), _text(root, "name") or package_id, source, str(folder), workshop_id, authors,
               _needs(root, version),
               _items(_versioned(root, "loadAfter", version)) + _items(_child(root, "forceLoadAfter")),
               _items(_versioned(root, "loadBefore", version)) + _items(_child(root, "forceLoadBefore")),
               _items(_versioned(root, "incompatibleWith", version)),
               _items(_child(root, "supportedVersions")), preview=_preview(folder))


def _preview(folder):
    """About/Preview.png, the picture the game's mod menu and the Workshop show (1.82.0); "" when the mod has none."""
    path = Path(folder) / "About" / "Preview.png"
    return str(path) if path.is_file() else ""


class RimWorld:
    game = "rimworld"
    name = "RimWorld"
    app_id = APP_ID
    processes = PROCESSES
    managers = MANAGERS

    def __init__(self, environ=None, settings=None, steam=None):
        self.environ = os.environ if environ is None else environ
        self.settings = settings
        self.running = game_running   # which of the named programs run; tests hand in their own
        self.game_folder = Path(game_path(None, self.environ, settings))
        self.workshop = Path(workshop_path(self.game_folder, None, self.environ, settings))
        self.config = Path(config_path(None, self.environ, settings)) / "ModsConfig.xml"
        self.steam = Path(steam) if steam else Path(steam_root(self.environ))
        self._version, self._ids = "", []
        if self.config.is_file():
            self._version, _, self._ids = read_mods_config(self.config)

    # -------------------------------------------------- what the core asks

    def notes(self):
        found = []
        if not self.game_folder.is_dir():
            found.append(f"RimWorld was not found at {self.game_folder}: set its folder in the tools' settings.")
        if not self.workshop.is_dir():
            found.append("RimWorld's Workshop folder was not found, so Workshop mods could not be looked for.")
        if not self.config.is_file():
            found.append(f"ModsConfig.xml was not found at {self.config}: start the game once, or set its Config folder.")
        return found

    def key(self, package_id):
        return bare_id(package_id)

    def pick(self, candidates, listed):
        if not candidates:
            return None
        if listed.strip().lower().endswith(STEAM_SUFFIX):
            return next((m for m in candidates if m.source == "workshop"), None)
        return next((m for m in candidates if m.source != "workshop"), candidates[0])

    def listed_id(self, mod):
        return mod.id

    def can_check_missing(self):
        return self.game_folder.is_dir() and self.workshop.is_dir()

    def is_local_id(self, listed):
        return False

    def why_unchecked(self):
        return "RimWorld's folders were not found, so the tools could not see which mods are on this PC."

    def how_to_get(self, need):
        if need.ids[0].startswith("ludeon.rimworld."):
            return f"{need.name or need.ids[0]} is one of the game's expansions: it needs that DLC."
        if need.workshop_id:
            return "Subscribe to it on the Workshop (Open in Steam), then check again."
        return "Its page is not named in the mod's files: look for it on the Workshop by its name."

    def game_version(self):
        return self._version

    def version_misfit(self, mod, version):
        if mod.versions and version not in mod.versions:
            return f"{mod.name} says it works with {', '.join(mod.versions)}, not {version}."
        return ""

    def installed(self):
        roots = [("game", self.game_folder / "Data"), ("local", self.game_folder / "Mods"), ("workshop", self.workshop)]
        found = []
        for source, root in roots:
            if not root.is_dir():
                continue
            for mod_folder in sorted(root.iterdir(), key=lambda p: p.name):
                if mod_folder.is_dir():
                    mod = read_about(mod_folder, source, mod_folder.name if source == "workshop" else "", self._version)
                    if mod is not None:
                        found.append(mod)
        return found

    def lists(self):
        """Read afresh each time: a change or an undo answers with the list as it now stands."""
        if not self.config.is_file():
            return []
        self._version, _, self._ids = read_mods_config(self.config)
        return [ModList("active", "Your active mods (ModsConfig.xml)", self.config, list(self._ids))]

    def subscribed(self):
        """The Workshop items Steam keeps for RimWorld on this PC (appworkshop_294100.acf), or None when it has no record."""
        candidates = [self.workshop.parent.parent / f"appworkshop_{APP_ID}.acf"]
        candidates += [library / "steamapps" / "workshop" / f"appworkshop_{APP_ID}.acf" for library in libraries(self.steam)]
        for record in candidates:
            if record.is_file():
                data = parse_vdf(record.read_text(encoding="utf-8", errors="replace")).get("AppWorkshop", {})
                found = set()
                for part in ("WorkshopItemsInstalled", "WorkshopItemDetails"):
                    if isinstance(data.get(part), dict):
                        found.update(data[part].keys())
                return found
        return None

    def assemblies_of(self, mods, active):
        """{mod key: [the .dll files the game loads from it]}: its Assemblies folders, in the folders LoadFolders.xml (or the game's
        default) chooses for this version with these mods active, compat folders included."""
        found = {}
        for mod in mods:
            files = []
            for folder in load_folders(mod.folder, self._version_number(), active):
                assemblies = Path(folder) / "Assemblies"
                if assemblies.is_dir():
                    files += sorted(str(p) for p in assemblies.rglob("*.dll"))
            if files:
                found[self.key(mod.id)] = files
        return found

    def _version_number(self):
        return ".".join(self._version.split(".")[:2]) if self._version else ""

    def _active_assemblies(self, reader=None):
        """(the active mods in load order, {key: [their loaded .dll files]}, {path: what the reader says of it})."""
        from ...assembly_refs import read_references
        found = self.lists()
        if not found:
            return [], {}, {}
        by_key = {}
        for mod in self.installed():
            by_key.setdefault(self.key(mod.id), mod)
        active_keys = [self.key(i) for i in found[0].ids]
        mods = [by_key[k] for k in dict.fromkeys(active_keys) if k in by_key and by_key[k].source != "game"]
        files = self.assemblies_of(mods, set(active_keys))
        read = read_references([f for fs in files.values() for f in fs], self.environ, reader=reader)
        return mods, files, read

    def library_copies(self, reader=None):
        """Libraries several active mods carry their own copy of, where the copy loaded first is older than another (1.85.0):
        [{"assembly", "first": {...}, "newest": {...}, "copies": [{"key", "name", "version", "path"}]}]. RimWorld loads every
        copy (Verse.ModAssemblyHandler, Assembly.LoadFrom, no check for a name already loaded); the rest of the game's code most
        likely binds to the first one loaded."""
        mods, files, read = self._active_assemblies(reader)
        copies = {}
        for mod in mods:
            key = self.key(mod.id)
            for path in files.get(key, []):
                record = read.get(path)
                if record and record.get("version"):
                    copies.setdefault(record["assembly"].lower(), []).append(
                        {"key": key, "id": mod.id, "name": mod.name, "version": record["version"], "path": path,
                         "assembly": record["assembly"], "workshop_id": mod.workshop_id})
        found = []
        for items in copies.values():
            if len({c["key"] for c in items}) < 2:
                continue
            first = items[0]
            newest = max(items, key=lambda c: _version_tuple(c["version"]))
            if _version_tuple(first["version"]) < _version_tuple(newest["version"]):
                found.append({"assembly": first["assembly"], "first": first, "newest": newest, "copies": items})
        return found

    def code_rules(self, reader=None):
        """{key: {"after": [(the mod whose assembly its code builds on, note)], ...}} for the active list (1.84.0): where a type in
        one of its loaded assemblies has a parent class or an interface from another mod's assembly, which the game needs loaded
        first; a reference used only inside a method does not tie the order (Combat Extended calls into Dubs Rimatomics from
        far above it without fault). An assembly name
        shipped by more than one mod counts only when the mod names one of them as a need; the game's own are never mods'."""
        from ...assembly_refs import read_references
        found = self.lists()
        if not found:
            return {}
        installed = self.installed()
        by_key = {}
        for mod in installed:
            by_key.setdefault(self.key(mod.id), mod)
        active_keys = [self.key(i) for i in found[0].ids]
        mods = [by_key[k] for k in dict.fromkeys(active_keys) if k in by_key and by_key[k].source != "game"]
        files = self.assemblies_of(mods, set(active_keys))
        read = read_references([f for fs in files.values() for f in fs], self.environ, reader=reader)
        providers, owned = {}, {}
        for key, paths in files.items():
            for path in paths:
                record = read.get(path)
                if record:
                    providers.setdefault(record["assembly"].lower(), set()).add(key)
                    owned.setdefault(key, []).append(record)
        rules = {}
        for key, records in owned.items():
            mod = by_key[key]
            needed = {self.key(i) for n in mod.needs for i in n.ids}
            mine = {r["assembly"].lower() for r in records}
            seen = set()
            for record in records:
                for reference in record["inherits"]:
                    name = reference.lower()
                    if name in mine:
                        continue
                    others = providers.get(name, set()) - {key}
                    if len(others) > 1:
                        others &= needed
                    if len(others) != 1:
                        continue
                    other = next(iter(others))
                    if other in seen:
                        continue
                    seen.add(other)
                    entry = rules.setdefault(key, {"after": [], "before": [], "top": None, "bottom": None})
                    entry["after"].append((by_key[other].id, f"Its code ({record['assembly']}) builds on classes from "
                                                             f"{reference}, which {by_key[other].name} brings: the game must load that "
                                                             "first."))
        return rules

    def works_anyway(self, mod, version):
        """Why a mod that does not say it works with this version likely does, in words, or "" (1.85.0): it has a folder for the
        version (or a LoadFolders block), its Workshop page names the version, or the community's No Version Warning list names
        it."""
        folder = Path(mod.folder)
        if (folder / version).is_dir():
            return f"it has a {version} folder"
        load_file = folder / "LoadFolders.xml"
        try:
            if load_file.is_file() and f"<v{version}>" in load_file.read_text(encoding="utf-8-sig", errors="replace"):
                return f"its LoadFolders.xml has a {version} section"
        except OSError:
            pass
        base = rimsort_folder(self.environ)
        if mod.workshop_id:
            for name in RIMSORT_WORKSHOP:
                versions = read_workshop_versions(base / name)
                if versions is not None:
                    if version in versions.get(mod.workshop_id, set()):
                        return f"its Workshop page names {version}"
                    break
        if not hasattr(self, "_known_working"):
            self._known_working = {}
        if version not in self._known_working:
            self._known_working[version] = read_known_working(base / RIMSORT_NO_VERSION_WARNING, version)
        if self.key(mod.id) in self._known_working[version]:
            return "the community's No Version Warning list says it works"
        return ""

    def replacements(self):
        """The community's Use This Instead rules (1.85.0), read where RimSort keeps them."""
        if not hasattr(self, "_replacements"):
            self._replacements = read_replacements(rimsort_folder(self.environ) / RIMSORT_USE_THIS_INSTEAD)
        return self._replacements

    def rule_sets(self):
        """The rules RimSort keeps on this PC: the owner's own, and the community's, each read as it is (1.74.0); and what each active
        mod's code is built on (1.84.0)."""
        base = rimsort_folder(self.environ)
        found = []
        try:
            code = self.code_rules()
        except Exception:   # the sort still stands without them: the reader may be missing (.NET not installed)
            code = None
        if code is not None:
            found.append(RuleSet(CODE, "What their code is built on (their assemblies)", "the active mods' assemblies", code))
        for source, label, names in ((YOURS, "Your rules in RimSort", RIMSORT_USER),
                                     (WORKSHOP, "The Workshop's required items (RimSort's database)", RIMSORT_WORKSHOP),
                                     (COMMUNITY, "The community rules (RimSort's database)", RIMSORT_COMMUNITY)):
            reader = read_workshop_rules if source == WORKSHOP else read_rimsort_rules
            for name in names:
                rules = reader(base / name)
                if rules is not None:
                    found.append(RuleSet(source, label, str(base / name), rules))
                    break
        return found

    # -------------------------------------------------- lists kept elsewhere (1.75.0)

    list_suffix = LIST_SUFFIX

    def save_lists(self):
        """Each save's own record of its mods, newest first. Saves are only read, and only up to their header."""
        saves = Path(saves_path(None, self.environ, self.settings))
        found = []
        files = sorted(saves.glob(f"*{SAVE_SUFFIX}"), key=lambda p: p.stat().st_mtime, reverse=True) if saves.is_dir() else []
        for path in files:
            meta = read_save_meta(path)
            if not meta or not meta[1]:
                continue
            names, workshop = _known(meta[1], meta[3], meta[2])
            found.append(SavedList(SAVE, path.name, path.stem, _when(path), meta[1], names, workshop, meta[0]))
        return found

    def manager_lists(self):
        """RimSort's history of lists, newest first, read where RimSort keeps them."""
        base = rimsort_folder(self.environ) / "modlists" / "history"
        found = []
        files = sorted(base.glob("*/*.json"), key=lambda p: p.stat().st_mtime, reverse=True) if base.is_dir() else []
        for path in files:
            saved = read_list_file(path)
            if saved is None:
                continue
            stamp = datetime.fromisoformat(_when(path)).astimezone() if _when(path) else None
            label = f"RimSort, {stamp.strftime('%d %b %Y %H:%M')}" if stamp else f"RimSort, {path.stem}"
            found.append(SavedList(MANAGER, f"{path.parent.name}/{path.name}", label, saved.when, saved.ids,
                                   version=saved.version))
        return found

    def steam_library(self):
        """The game's own Steam library, which subscribing borrows (1.77.0)."""
        return steam_library_path(self.game_folder)

    def read_list_file(self, path):
        return read_list_file(path)

    def render_list_file(self, saved):
        return render_list_file(saved)

    def last_start(self):
        """When the game last started (its log's Started line, else the time the log was begun), when it last wrote its log,
        and whether it runs now; None when it has no log."""
        found = self.runs()
        if not found:
            return None
        return {"started": found[0]["started"], "ended": found[0]["ended"],
                "running": bool(self.running(list(self.processes)))}

    def runs(self):
        """The game's last two runs, newest first (1.85.0): [{"path", "started", "ended"}]. A run starts at its log's Started line
        (else, for the newest, when the Logs folder was last written, since the game renames the old log as it starts) and ends
        when its log was last written; an older log without a Started line has no start."""
        logs = Path(logs_path(None, self.environ, self.settings))
        found = []
        for name in (LOG_NAME, PREVIOUS_LOG_NAME):
            path = logs / name
            try:
                with open(path, "rb") as handle:
                    head = handle.read(4096).decode("utf-8", errors="replace")
                ended = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
                begun = datetime.fromtimestamp(logs.stat().st_mtime, timezone.utc) if name == LOG_NAME else None
            except OSError:
                continue
            started = begun
            match = STARTED.search(head)
            if match:
                parsed = datetime.fromisoformat(match.group(1) + (match.group(2) or ""))
                started = (parsed if parsed.tzinfo else parsed.astimezone()).astimezone(timezone.utc)
            found.append({"path": path, "started": started, "ended": ended})
        return found

    def run_report(self, path, previous=None):
        """A run's errors, the mods they name (by the clues the log carries) and the error signatures new since the previous
        run (1.85.0), from the kit's log reader."""
        from ...logs.triage import compare, group
        from ...textfile import read_text_shared
        from .log import parse
        from .mods import ModIndex, default_roots
        if not hasattr(self, "_mod_index"):
            self._mod_index = ModIndex.scan(default_roots(self.game_folder, self.workshop))
        text = read_text_shared(path)
        now = parse(text, Path(path).name)
        self._mod_index.annotate(now.entries)
        groups = group(now.entries)
        errors = [g for g in groups if g.level in ("ERROR", "FATAL")]
        named = sorted({evidence.mod for g in errors for evidence in g.evidence if evidence.mod})
        new, previous_loaded = [], ""
        if previous is not None:
            previous_text = read_text_shared(previous)
            previous_loaded = _save_loaded(previous_text)
            before = parse(previous_text, Path(previous).name)
            self._mod_index.annotate(before.entries)
            new = [c.group for c in compare(groups, group(before.entries)).new if c.group.level in ("ERROR", "FATAL")]
        return {"errors": sum(g.count for g in errors), "error_mods": named, "loaded": _save_loaded(text),
                "previous_loaded": previous_loaded,
                "new": [{"id": g.id, "level": g.level, "count": g.count, "message": g.signature[:300],
                         "mods": [e.mod for e in g.top_evidence() if e.mod]} for g in new]}

    def mentions(self, mod, words):
        """Whether any of a mod's text files or assemblies name one of the words (any case)."""
        needles = [w.lower().encode("utf-8") for w in words] + [w.lower().encode("utf-16-le") for w in words]
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
        """ModsConfig.xml with only its active list changed, in the file's own indentation and line endings."""
        newline = "\r\n" if "\r\n" in text else "\n"
        match = ACTIVE.search(text)
        if match is None:
            raise ValueError("ModsConfig.xml has no <activeMods> list.")
        line_start = text.rfind("\n", 0, match.start()) + 1
        outer = re.match(r"[ \t]*", text[line_start:]).group(0)
        inner = outer + "  "
        if match.group("body"):
            first = re.search(r"\n([ \t]*)<li>", match.group("body"))
            inner = first.group(1) if first else inner
        escaped = [i.replace("&", "&amp;").replace("<", "&lt;") for i in ids]
        body = "".join(f"{newline}{inner}<li>{i}</li>" for i in escaped)
        block = f"<activeMods>{body}{newline}{outer}</activeMods>"
        return text[:match.start()] + block + text[match.end():]


def adapter(environ=None, settings=None, data=None, steam=None):
    return RimWorld(environ, settings, steam)
