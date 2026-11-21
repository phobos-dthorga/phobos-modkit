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

import os
from pathlib import Path
import re

from ...game_files import libraries, parse_vdf, steam_root
from ...mod_list import Mod, ModList, Need
from .installs import PROCESSES
from .loading import STEAM_SUFFIX, bare_id, read_mods_config
from .mods import _about_root, _child, _text
from .paths import config_path, game_path, workshop_path

APP_ID = 294100
MANAGERS = ("RimSort.exe", "RimPy.exe")
WORKSHOP_NUMBER = re.compile(r"(?:id=|CommunityFilePage/|filedetails/\?id=)(\d{6,})|^(\d{6,})$")
CLUE_SUFFIXES = frozenset({".xml", ".txt", ".dll", ".json"})
CLUE_FILE_BYTES = 4 * 1024 * 1024       # larger files are skipped when looking for a clue (agent default)
CLUE_TOTAL_BYTES = 64 * 1024 * 1024     # and the look stops after this much of one mod (agent default)
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
               _items(_child(root, "supportedVersions")))


class RimWorld:
    game = "rimworld"
    name = "RimWorld"
    app_id = APP_ID
    processes = PROCESSES
    managers = MANAGERS

    def __init__(self, environ=None, settings=None, steam=None):
        self.environ = os.environ if environ is None else environ
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
        if not self.config.is_file():
            return []
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
