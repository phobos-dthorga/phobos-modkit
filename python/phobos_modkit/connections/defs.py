"""XML Def connections (RimWorld's, and any game's XML laid out the same way: a <Defs> file of named definitions).

Exact from the files: a Def builds on the Def its ParentName names. By name: a Def uses another Def wherever one of its values is
that Def's defName (the game resolves cross-references the same way, by name), and uses a C# class wherever a Class attribute or
a ...Class element names one (thingClass, compClass, workerClass and the like), joining the Def to the C# connections.
"""
from __future__ import annotations

from pathlib import Path
import re
import xml.etree.ElementTree as ElementTree

from . import Node, source_files

LANGUAGE = "xml"
_TYPE_NAME = re.compile(r"^[A-Za-z_][\w]*(\.[A-Za-z_][\w]*)+$")


def inputs(root):
    return [p for _, p in _def_files(root)]


def _def_files(root):
    found = []
    for relative, path in source_files(root, (".xml",)):
        try:
            with open(path, "rb") as handle:
                head = handle.read(4096).decode("utf-8", "replace")
        except OSError:
            continue
        if "<Defs" in head:
            found.append((relative, path))
    return found


def def_id(tag, name):
    return f"def:{tag}/{name}"


def _line_of(lines, needles, start=0):
    for index in range(start, len(lines)):
        if any(n in lines[index] for n in needles):
            return index + 1
    return None


def read(root, graph, environ=None):
    files = _def_files(root)
    if not files:
        return None
    parsed, by_def_name, by_abstract_name = [], {}, {}
    for relative, path in files:
        text = path.read_text(encoding="utf-8", errors="replace")
        try:
            tree = ElementTree.fromstring(text.encode("utf-8"))
        except ElementTree.ParseError:
            continue
        lines = text.splitlines()
        cursor = 0
        found = []
        for element in list(tree):
            if not isinstance(element.tag, str):
                continue
            def_name = (element.findtext("defName") or "").strip()
            abstract_name = element.get("Name")
            name = def_name or abstract_name
            if not name:
                continue
            needles = [f"<defName>{def_name}</defName>"] if def_name else [f'Name="{abstract_name}"']
            line = _line_of(lines, needles, cursor) or _line_of(lines, needles)
            if line:
                cursor = line
            node = graph.add(Node(def_id(element.tag, name), name, "abstract def" if not def_name else "def", LANGUAGE,
                                  relative, line, owner=None))
            node.def_type = element.tag
            found.append((node, element))
            if def_name:
                by_def_name.setdefault(def_name, []).append(node.id)
            if abstract_name:
                by_abstract_name.setdefault(abstract_name, []).append(node.id)
        for index, (node, _) in enumerate(found):      # a Def runs until the next one starts
            following = [n.line for n, _ in found[index + 1:] if n.line]
            node.end = (following[0] - 1) if following else len(lines)
        parsed.extend(found)
    for node, element in parsed:
        parent = element.get("ParentName")
        if parent:
            targets = by_abstract_name.get(parent) or [graph.ensure(def_id(element.tag, parent), parent, "abstract def", LANGUAGE).id]
            for target in targets:
                graph.link(node.id, target, "builds-on", exact=True)
        for inner in element.iter():
            if inner is element:
                continue
            for value in [inner.get("Class")] + [inner.text if isinstance(inner.tag, str) and inner.tag.endswith("Class") else None]:
                if value and _TYPE_NAME.match(value.strip()):
                    type_name = value.strip()
                    target = graph.ensure(f"cs:{type_name}", type_name.rsplit(".", 1)[-1], "type", "csharp")
                    graph.link(node.id, target.id, "uses", exact=True)
            text = (inner.text or "").strip()
            if text and text in by_def_name and len(text) > 2:
                for target in by_def_name[text]:
                    graph.link(node.id, target, "uses", exact=len(by_def_name[text]) == 1)
    return "exact parents; uses by defName and class name"


def declared_in(text, relative):
    """Every Def an XML file's text declares, as (id, first line, last line)."""
    if "<Defs" not in text[:4096]:
        return []
    try:
        tree = ElementTree.fromstring(text.encode("utf-8"))
    except ElementTree.ParseError:
        return []
    lines = text.splitlines()
    found, cursor = [], 0
    for element in list(tree):
        if not isinstance(element.tag, str):
            continue
        def_name = (element.findtext("defName") or "").strip()
        name = def_name or element.get("Name")
        if not name:
            continue
        needles = [f"<defName>{def_name}</defName>"] if def_name else [f'Name="{name}"']
        line = _line_of(lines, needles, cursor) or _line_of(lines, needles)
        if line:
            cursor = line
            found.append([def_id(element.tag, name), line, None])
    for index, item in enumerate(found):
        item[2] = (found[index + 1][1] - 1) if index + 1 < len(found) else len(lines)
    return [tuple(item) for item in found]
