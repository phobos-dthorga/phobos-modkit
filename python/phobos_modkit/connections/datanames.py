"""The names that cross between a game's data files and its code, as things and connections (1.117.0).

Read last, over what the other readers found, and only when the game is named and has a table (`data_names`): the things the
table's files declare become things of the graph (a translation key, a data object), and wherever a rule reads a name of one of the
table's things, whatever holds that line (a method, a Def, a data object) uses it. A use is exact when its rule reads a place that
can only hold such a name and one thing has it; every other use is by name. What the Def reader already links (a Def's own values)
is not linked twice: the table marks those rules.
"""
from __future__ import annotations

from .. import data_names
from . import Node, source_files

#: A thing's language in the graph, by the file that declares it.
LANGUAGES = {".xml": "xml", ".json": "json", ".lua": "lua", ".py": "python", ".cs": "csharp"}
#: The things one name is linked to at most: more is a name too common to mean one of them.
MAX_LINKED = 4


def inputs(root, table):
    """Every file this reader reads that may not be another reader's: the files that declare the table's things, and the files
    its rules read."""
    found = [path for _, _, path in table.thing_files(root)]
    found += [path for relative, path in source_files(root, table.suffixes())
              if any(rule.reads(relative) for rule in table.rules)]
    return found


def _language(file):
    return LANGUAGES.get(file[file.rfind("."):].lower(), "data")


def read(root, graph, environ, table):
    nodes = [(n.id, n.name, n.kind, n.language, n.file, n.line, n.end) for n in graph.nodes.values()
             if not n.external and n.file]
    found = data_names.index(table, root, nodes)
    declared = 0
    for thing in table.things.values():
        if not thing.files or thing.alias_of:
            continue
        seen = set()
        for items in found.by[thing.id].values():
            for item in items:
                if item["id"] not in seen:
                    seen.add(item["id"])
                    graph.add(Node(item["id"], item["name"], item["kind"], _language(item["file"]), item["file"], item["line"],
                                   item["end"]))
        declared += len(seen)
    holders = {}
    for node in graph.nodes.values():
        if not node.external and node.file and node.line:
            holders.setdefault(node.file, []).append((node.line, node.end or node.line, node.id))
    rules = {rule.id: rule for rule in table.rules}
    linked = 0
    for relative, item in data_names.references(table, found, root):
        things = item["things"]
        if not things or len(things) > MAX_LINKED or not rules[item["rule"]].graph:
            continue
        holding = [h for h in holders.get(relative, ()) if h[0] <= item["line"] <= h[1]]
        if not holding:
            continue
        source = min(holding, key=lambda h: h[1] - h[0])[2]
        for thing in things:
            graph.link(source, thing["id"], "uses", exact=not item["known"] and len(things) == 1)
            linked += 1
    return f"the table for {table.source}: {declared:,} things declared in data files, {linked:,} uses of a name"
