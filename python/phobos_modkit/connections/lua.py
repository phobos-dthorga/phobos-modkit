"""Lua connections (Project Zomboid, Farming Simulator and any game whose mods are Lua), by name.

Lua decides what a name means only while it runs, so every connection here is by name and says so: a function is declared by
`function A.b(`, `function A:b(`, `local function b(` or `b = function(`; it calls another wherever its body names one followed by
`(` (a method call `x:b(` matching the functions named b); a file imports what its `require "x"` names.
"""
from __future__ import annotations

import re

from . import Node, source_files

LANGUAGE = "lua"
_DECLARED = [
    re.compile(r"^\s*(local\s+)?function\s+([A-Za-z_][\w.:]*)\s*\("),
    re.compile(r"^\s*(local\s+)?([A-Za-z_][\w.]*)\s*=\s*function\s*\("),
]
_CALLED = re.compile(r"([A-Za-z_][\w]*)\s*\(")
_REQUIRE = re.compile(r"""require\s*\(?\s*["']([^"']+)["']""")
_COMMENT = re.compile(r"--\[\[.*?\]\]|--[^\n]*", re.S)
_STRING = re.compile(r"\"(?:\\.|[^\"\\\n])*\"|'(?:\\.|[^'\\\n])*'")


def inputs(root):
    return [p for _, p in source_files(root, (".lua",))]


def _code(text):
    """The text with comments and strings blanked, keeping line breaks so line numbers hold."""
    blank = lambda m: re.sub(r"[^\n]", " ", m.group(0))   # noqa: E731
    return _STRING.sub(blank, _COMMENT.sub(blank, text))


def read(root, graph, environ=None):
    files = source_files(root, (".lua",))
    if not files:
        return None
    declared, by_short = [], {}
    for relative, path in files:
        raw = path.read_text(encoding="utf-8", errors="replace")
        code_lines = _code(raw).splitlines()
        module = graph.add(Node(f"lua:file:{relative}", relative.rsplit("/", 1)[-1], "module", LANGUAGE, relative, 1,
                                len(code_lines)))
        found = []
        for number, line in enumerate(code_lines, 1):
            for pattern in _DECLARED:
                match = pattern.match(line)
                if match:
                    local, name = bool(match.group(1)), match.group(2)
                    node_id = f"lua:{relative}:{name}" if local else f"lua:{name.replace(':', '.')}"
                    node = graph.add(Node(node_id, name, "function", LANGUAGE, relative, number, owner=module.id))
                    graph.link(module.id, node.id, "holds")
                    found.append(node)
                    by_short.setdefault(re.split(r"[.:]", name)[-1], []).append(node.id)
                    break
        for index, node in enumerate(found):        # a function runs until the next declaration starts
            node.end = (found[index + 1].line - 1) if index + 1 < len(found) else len(code_lines)
        for required in set(_REQUIRE.findall(raw)):
            target = graph.ensure(f"lua:module:{required}", required, "module", LANGUAGE)
            graph.link(module.id, target.id, "imports", exact=False)
        declared.append((code_lines, found))
    for code_lines, found in declared:
        for node in found:
            body = "\n".join(code_lines[node.line:node.end])     # the body: the lines after the declaration
            for called in set(_CALLED.findall(body)):
                targets = by_short.get(called, [])
                if 0 < len(targets) <= 3:
                    for target in targets:
                        graph.link(node.id, target, "calls", exact=False)
    return "by name (Lua is only exact when it runs)"


def declared_in(text, relative):
    """Every function a Lua file's text declares, as (id, first line, last line)."""
    code_lines = _code(text).splitlines()
    found = []
    for number, line in enumerate(code_lines, 1):
        for pattern in _DECLARED:
            match = pattern.match(line)
            if match:
                name = match.group(2)
                found.append([f"lua:{relative}:{name}" if match.group(1) else f"lua:{name.replace(':', '.')}", number, None])
                break
    for index, item in enumerate(found):
        item[2] = (found[index + 1][1] - 1) if index + 1 < len(found) else len(code_lines)
    return [tuple(item) for item in found] + [(f"lua:file:{relative}", 1, len(code_lines))]
