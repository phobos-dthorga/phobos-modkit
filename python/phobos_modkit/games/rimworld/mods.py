"""Installed RimWorld mods, indexed so clues in a log can be turned into mod names.

Reads only each mod's About/About.xml and the names of the files in its Assemblies folders. Assemblies are never
opened, loaded or run.
"""
from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import re
import xml.etree.ElementTree as ET

from ...logs.model import Evidence

APP_ID = "294100"
ASSEMBLY_SEARCH_DEPTH = 4   # Assemblies sit at most a few folders down: 1.7/Assemblies, Mods/X/1.7/Assemblies
BARE_AMPERSAND = re.compile(r"&(?!(?:[A-Za-z]+|#\d+|#x[0-9A-Fa-f]+);)")
SHARED_ASSEMBLIES = frozenset({"0harmony", "harmony", "prepatcher"})  # copies many mods ship; they name no one mod


@dataclass(frozen=True)
class InstalledMod:
    package_id: str          # lower case, as the game compares them
    name: str
    source: str              # "Ludeon", "Local" or "Workshop"
    folder: Path
    workshop_id: str = ""
    assemblies: tuple = ()   # lower-case file names without .dll


def _child(element, tag):
    for child in element:
        if isinstance(child.tag, str) and child.tag.lower() == tag.lower():
            return child
    return None


def _text(element, tag):
    found = _child(element, tag)
    return (found.text or "").strip() if found is not None else ""


def _about_root(folder):
    """The root of folder/About/About.xml (any letter case), forgiving bare ampersands; None if unreadable."""
    try:
        about_dirs = [d for d in folder.iterdir() if d.is_dir() and d.name.lower() == "about"]
    except OSError:
        return None
    for about_dir in about_dirs:
        for candidate in about_dir.iterdir():
            if candidate.name.lower() != "about.xml":
                continue
            raw = candidate.read_text(encoding="utf-8-sig", errors="replace")
            for attempt in (raw, BARE_AMPERSAND.sub("&amp;", raw)):
                try:
                    return ET.fromstring(attempt)
                except ET.ParseError:
                    continue
    return None


def _assemblies(folder):
    """Lower-case names, without .dll, of the files in every Assemblies folder of a mod."""
    found = set()
    base_depth = len(folder.parts)
    for current, dirnames, filenames in os.walk(folder):
        here = Path(current)
        if len(here.parts) - base_depth >= ASSEMBLY_SEARCH_DEPTH:
            dirnames[:] = []
        if here.name.lower() == "assemblies":
            found.update(n[:-4].lower() for n in filenames if n.lower().endswith(".dll"))
    return tuple(sorted(found - SHARED_ASSEMBLIES))


def read_mod(folder, source, workshop_id=""):
    """The InstalledMod in folder, or None when it has no readable About.xml with a packageId."""
    folder = Path(folder)
    root = _about_root(folder)
    if root is None:
        return None
    package_id = _text(root, "packageId").lower()
    if not package_id:
        return None
    return InstalledMod(package_id, _text(root, "name") or package_id, source, folder, workshop_id,
                        _assemblies(folder))


def default_roots(game, workshop):
    """(source, folder) pairs to scan: the game's Data (the DLCs), its Mods folder, and the Workshop folder."""
    roots = []
    if game:
        roots += [("Ludeon", Path(game) / "Data"), ("Local", Path(game) / "Mods")]
    if workshop:
        roots.append(("Workshop", Path(workshop)))
    return roots


def default_workshop(game):
    """steamapps/workshop/content/294100 beside steamapps/common/RimWorld."""
    return Path(game).parents[1] / "workshop" / "content" / APP_ID


class ModIndex:
    """Looks up installed mods by the clues logs carry."""

    def __init__(self, mods):
        self.mods = list(mods)
        self._by_package = {m.package_id: m for m in self.mods}
        self._by_name = {m.name.lower(): m for m in self.mods}
        self._by_workshop = {m.workshop_id: m for m in self.mods if m.workshop_id}
        self._by_local_folder = {m.folder.name.lower(): m for m in self.mods if m.source == "Local"}
        self._by_assembly = {}
        for mod in self.mods:
            for assembly in mod.assemblies:
                self._by_assembly.setdefault(assembly, []).append(mod)
        self._by_package_tail = {}
        for mod in self.mods:
            self._by_package_tail.setdefault(mod.package_id.rsplit(".", 1)[-1], []).append(mod)

    @classmethod
    def scan(cls, roots):
        """Every mod with an About.xml directly inside each root folder."""
        mods = []
        for source, root in roots:
            root = Path(root)
            if not root.is_dir():
                continue
            for folder in sorted(root.iterdir(), key=lambda p: p.name):
                if folder.is_dir():
                    mod = read_mod(folder, source, folder.name if source == "Workshop" else "")
                    if mod is not None:
                        mods.append(mod)
        return cls(mods)

    @staticmethod
    def _names(mods):
        names = sorted({m.name for m in mods})
        if len(names) > 3:
            return " or ".join(names[:3]) + f" (+{len(names) - 3})"
        return " or ".join(names)

    def resolve(self, evidence):
        """The display name of the mod one clue points at, or "" when no installed mod matches."""
        kind, value = evidence.kind, evidence.value
        if kind == "source":
            mod = self._by_name.get(value.lower())
            return mod.name if mod else ""
        if kind == "file":
            prefix, _, rest = value.partition(":")
            mod = (self._by_workshop.get(rest) if prefix == "workshop"
                   else self._by_local_folder.get(rest.lower()) if prefix == "mods" else None)
            return mod.name if mod else ""
        if kind == "assembly":
            stem = value[:-4] if value.lower().endswith(".dll") else value
            return self._names(self._by_assembly.get(stem.lower(), []))
        if kind in ("namespace", "caller"):
            key = value.lower()
            return self._names(self._by_assembly.get(key, []) or self._by_package_tail.get(key, []))
        if kind in ("patch", "finalizer"):
            mod = self._by_package.get(value.lower())
            if mod:
                return mod.name
            return self._names(self._by_assembly.get(value.lower(), []))
        return ""

    def annotate(self, entries):
        """Fill in each clue's mod name where an installed mod matches it."""
        cache = {}
        for entry in entries:
            named = []
            for evidence in entry.evidence:
                if evidence not in cache:
                    cache[evidence] = Evidence(evidence.kind, evidence.value, self.resolve(evidence))
                named.append(cache[evidence])
            entry.evidence = named
