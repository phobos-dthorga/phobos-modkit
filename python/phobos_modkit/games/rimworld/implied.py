"""Defs the game generates in code rather than reading from XML, so the Def index (and save grids) can name them.

Summarised in our own words from the RimWorld 1.7 code (DefGenerator, TerrainDefGenerator_Stone and
TerrainDefGenerator_Carpet, read November 2026):

- For every natural rock ThingDef (building.isNaturalRock, and not building.isResourceRock) the game makes
  "<rock>_Rough" unless the rock names a naturalTerrain, "<rock>_RoughHewn" unless it names a leaveTerrain, and
  "<rock>_Smooth" when either was missing. They belong to the rock's mod.
- For every TerrainTemplateDef and every ColorDef whose colorType is Structure, it makes a carpet named the template's
  defName followed by the colour's defName without its "Structure_" prefix.

Fields are read through ParentName inheritance the way the game picks parents: the same Name from the latest mod at
or before the child's in load order; a child's own value wins over its parents'. Only these generators are covered;
others (blueprints, frames, meat, corpses, techprints and any a mod adds) are not, so Defs they make stay unnamed.
"""
from __future__ import annotations

FIELDS = {
    "ThingDef": {"rock": "building/isNaturalRock", "resource_rock": "building/isResourceRock",
                 "natural_terrain": "building/naturalTerrain", "leave_terrain": "building/leaveTerrain"},
    "ColorDef": {"color_type": "colorType"},
}
ALL_FIELDS = {path for fields in FIELDS.values() for path in fields.values()}
CHAIN_LIMIT = 50


def own_fields(element):
    """{field path: text} for the inheritance-relevant fields this element writes itself."""
    found = {}
    for path in ALL_FIELDS:
        child = element.find(path)
        if child is not None and (child.text or "").strip():
            found[path] = child.text.strip()
    return found


class Facts:
    """What generation needs from every Def element: its fields, Name, ParentName and place in load order."""

    def __init__(self):
        self.by_key = {}      # (mod position, load folder, file, element index) -> (fields, parent, position)
        self.names = {}       # Name -> [(mod position, order, fields, parent)] for nodes that can be parents
        self._order = 0

    def add(self, key, element, registers):
        fields = own_fields(element)
        parent = element.get("ParentName")
        self.by_key[key] = (fields, parent, key[0])
        if registers and element.get("Name"):
            self._order += 1
            self.names.setdefault(element.get("Name"), []).append((key[0], self._order, fields, parent))

    def _parent(self, name, position):
        candidates = [c for c in self.names.get(name, []) if c[0] <= position]
        if not candidates:
            return None
        best = max(c[0] for c in candidates)
        return min((c for c in candidates if c[0] == best), key=lambda c: c[1])

    def resolved(self, key, path):
        """A field's value after inheritance, or None."""
        fields, parent, position = self.by_key.get(key, ({}, None, 0))
        seen = set()
        while True:
            if path in fields:
                return fields[path]
            if not parent or parent in seen or len(seen) > CHAIN_LIMIT:
                return None
            seen.add(parent)
            found = self._parent(parent, position)
            if found is None:
                return None
            position, _, fields, parent = found


def _true(text):
    return (text or "").strip().lower() == "true"


def generate(conn, facts):
    """[(def_type, def_name, mod_position, made from)] the game would add, from the index's winning Defs."""
    made = []
    rocks = conn.execute("SELECT def_name, mod_position, load_folder, file, element_index FROM def "
                         "WHERE wins AND def_type = 'ThingDef'").fetchall()
    for name, position, folder, file, index in rocks:
        key = (position, folder, file, index)
        if not _true(facts.resolved(key, "building/isNaturalRock")) or \
                _true(facts.resolved(key, "building/isResourceRock")):
            continue
        has_natural = facts.resolved(key, "building/naturalTerrain") is not None
        has_leave = facts.resolved(key, "building/leaveTerrain") is not None
        if not has_natural:
            made.append(("TerrainDef", f"{name}_Rough", position, f"ThingDef {name}"))
        if not has_leave:
            made.append(("TerrainDef", f"{name}_RoughHewn", position, f"ThingDef {name}"))
        if not has_natural or not has_leave:
            made.append(("TerrainDef", f"{name}_Smooth", position, f"ThingDef {name}"))
    colours = [name for name, position, folder, file, index in conn.execute(
        "SELECT def_name, mod_position, load_folder, file, element_index FROM def WHERE wins AND def_type = 'ColorDef'")
        if facts.resolved((position, folder, file, index), "colorType") == "Structure"]
    for template, position in conn.execute("SELECT def_name, mod_position FROM def "
                                           "WHERE wins AND def_type = 'TerrainTemplateDef'").fetchall():
        for colour in colours:
            made.append(("TerrainDef", template + colour.replace("Structure_", ""), position,
                         f"TerrainTemplateDef {template} and ColorDef {colour}"))
    return made
