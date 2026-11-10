"""One Def by type and name, with its parents merged in, for reports that need a Def's values rather than its text.

Two sources, best first: the patched-Defs index (phobos_modkit.games.rimworld.patched_defs: every patch applied, as a
running game wrote it) and the Def index of the installed mods (phobos_modkit.games.rimworld.defs: as the mods wrote
them). Either may be missing; a lookup then returns None and the report says what it could not read.

Inheritance follows the game's XmlInheritance as summarised from the 1.7 code: a child's elements are merged into a copy
of its parent's, element by element; list items (<li>) are added after the parent's; Inherit="False" on an element, or
an element with no children, replaces the parent's whole element. A parent is the Def with that Name from the latest mod
at or before the child's own mod (the written index); the patched file has no load order, so its last such Name is used.
"""
from __future__ import annotations

import copy
from pathlib import Path
import xml.etree.ElementTree as ET

from .defs import _parse

CHAIN_LIMIT = 12   # parents followed before giving up on a loop


def _merge_into(target, source):
    """Merge source's elements into target, as the game merges a child into its parent."""
    if source.get("Inherit", "").lower() == "false" or len(source) == 0:
        target.clear()
        target.text = source.text
        target.attrib.update({k: v for k, v in source.attrib.items() if k != "Inherit"})
        target.extend(copy.deepcopy(list(source)))
        return
    for child in source:
        if not isinstance(child.tag, str):
            continue
        existing = None if child.tag == "li" else target.find(child.tag)
        if existing is None:
            target.append(copy.deepcopy(child))
        else:
            _merge_into(existing, child)


def merge(chain):
    """Elements from the furthest parent to the Def itself, merged into one."""
    result = copy.deepcopy(chain[0])
    for element in chain[1:]:
        for child in element:
            if isinstance(child.tag, str):
                existing = None if child.tag == "li" else result.find(child.tag)
                if existing is None:
                    result.append(copy.deepcopy(child))
                else:
                    _merge_into(existing, child)
    return result


class DefSource:
    """Defs from the patched index when it has them, else from the written index. Every lookup is cached."""

    def __init__(self, written=None, patched=None):
        self.written = written      # sqlite3 connection to defs.sqlite, or None
        self.patched = patched      # sqlite3 connection to patched-defs.sqlite, or None
        self._files = {}
        self._found = {}
        self.used = set()           # which sources answered: "patched", "written"

    @property
    def available(self):
        return self.written is not None or self.patched is not None

    def get(self, def_type, name):
        """The Def merged with its parents, or None when neither source has it."""
        key = (def_type, name)
        if key not in self._found:
            chain = self._patched_chain(def_type, name) or self._written_chain(def_type, name)
            self._found[key] = merge(chain[::-1]) if chain else None
        return self._found[key]

    def _patched_chain(self, def_type, name):
        if self.patched is None:
            return None
        row = self.patched.execute("SELECT xml, parent FROM pdef WHERE def_type = ? AND def_name = ? "
                                   "ORDER BY id DESC LIMIT 1", (def_type, name)).fetchone()
        if row is None:
            return None
        chain, parent = [ET.fromstring(row[0])], row[1]
        while parent and len(chain) < CHAIN_LIMIT:
            found = self.patched.execute("SELECT xml, parent FROM pdef WHERE name = ? COLLATE NOCASE "
                                         "ORDER BY def_type = ? DESC, id DESC LIMIT 1", (parent, def_type)).fetchone()
            if found is None:
                break
            chain.append(ET.fromstring(found[0]))
            parent = found[1]
        self.used.add("patched")
        return chain

    def _element(self, folder, load_folder, file, index):
        path = Path(folder) / load_folder / file if load_folder else Path(folder) / file
        if path not in self._files:
            root, _ = _parse(path)
            self._files[path] = [] if root is None else [e for e in root if isinstance(e.tag, str)]
        elements = self._files[path]
        return elements[index] if 0 <= index < len(elements) else None

    def _written_chain(self, def_type, name):
        if self.written is None:
            return None
        row = self.written.execute("""SELECT m.folder, d.load_folder, d.file, d.element_index, d.mod_position, d.parent
                                      FROM def d JOIN mod m ON m.position = d.mod_position
                                      WHERE d.def_type = ? AND d.def_name = ? AND d.loads AND d.element_index >= 0
                                      ORDER BY d.wins DESC, d.mod_position DESC LIMIT 1""",
                                   (def_type, name)).fetchone()
        element = self._element(*row[:4]) if row else None
        if element is None:
            return None
        chain, position, parent = [element], row[4], row[5]
        while parent and len(chain) < CHAIN_LIMIT:
            found = self.written.execute("""SELECT m.folder, d.load_folder, d.file, d.element_index, d.mod_position,
                                                   d.parent
                                            FROM def d JOIN mod m ON m.position = d.mod_position
                                            WHERE d.name = ? AND d.registers AND d.mod_position <= ?
                                            ORDER BY d.mod_position DESC, d.id ASC LIMIT 1""",
                                         (parent, position)).fetchone()
            element = self._element(*found[:4]) if found else None
            if element is None:
                break
            chain.append(element)
            position, parent = found[4], found[5]
        self.used.add("written")
        return chain


def text(element, path, default=None):
    """The stripped text at a path below element, or default."""
    found = element.find(path) if element is not None else None
    value = (found.text or "").strip() if found is not None else ""
    return value or default


def number(element, path, default=None):
    value = text(element, path)
    try:
        return float(value) if value is not None else default
    except ValueError:
        return default


def flag(element, path, default=False):
    value = text(element, path)
    return default if value is None else value.lower() == "true"
