"""Python connections (the tools, and any game's Python), read by Python's own parser.

Exact: modules, classes, functions and methods with their lines, what holds what, a class's bases when they are the repository's,
and a module's imports. By name: a call, wherever a function's body calls a name that only one or two of the repository's functions
or classes carry.
"""
from __future__ import annotations

import ast

from . import Node, source_files

LANGUAGE = "python"


def inputs(root):
    return [p for _, p in source_files(root, (".py",))]


def _module_name(relative):
    parts = relative[:-3].split("/")
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def read(root, graph, environ=None):
    files = source_files(root, (".py",))
    if not files:
        return None
    trees, by_short, modules = [], {}, {}
    for relative, path in files:
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"), filename=relative)
        except (SyntaxError, ValueError):
            continue
        module_name = _module_name(relative)
        module = graph.add(Node(f"py:{module_name}", module_name.rsplit(".", 1)[-1] or relative, "module", LANGUAGE, relative, 1,
                                max((getattr(n, "end_lineno", 1) or 1) for n in tree.body) if tree.body else 1))
        modules[module_name] = module.id
        trees.append((relative, module, tree))

        def visit(body, owner_id, prefix):
            for item in body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    kind = "class" if isinstance(item, ast.ClassDef) else ("method" if owner_id != module.id else "function")
                    node = graph.add(Node(f"{prefix}.{item.name}", item.name, kind, LANGUAGE, relative, item.lineno,
                                          item.end_lineno, owner=owner_id))
                    node.tree = item
                    graph.link(owner_id, node.id, "holds")
                    by_short.setdefault(item.name, []).append(node.id)
                    if isinstance(item, ast.ClassDef):
                        visit(item.body, node.id, node.id)

        visit(tree.body, module.id, module.id)
    for relative, module, tree in trees:
        for item in ast.walk(tree):
            if isinstance(item, ast.ImportFrom) and item.module:
                package = module.id[3:].rsplit(".", item.level)[0] if item.level else ""
                name = f"{package}.{item.module}" if item.level and package else item.module
                if name in modules:
                    graph.link(module.id, modules[name], "imports")
            elif isinstance(item, ast.Import):
                for alias in item.names:
                    if alias.name in modules:
                        graph.link(module.id, modules[alias.name], "imports")
    for node in [n for n in graph.nodes.values() if n.language == LANGUAGE and hasattr(n, "tree")]:
        item = node.tree
        if isinstance(item, ast.ClassDef):
            for base in item.bases:
                base_name = base.id if isinstance(base, ast.Name) else base.attr if isinstance(base, ast.Attribute) else None
                for target in by_short.get(base_name, [])[:2]:
                    graph.link(node.id, target, "builds-on", exact=len(by_short[base_name]) == 1)
            continue
        called = set()
        for inner in ast.walk(item):
            if isinstance(inner, ast.Call):
                function = inner.func
                called.add(function.id if isinstance(function, ast.Name) else function.attr if isinstance(function, ast.Attribute) else None)
        for name in called - {None}:
            targets = by_short.get(name, [])
            if 0 < len(targets) <= 2:
                for target in targets:
                    graph.link(node.id, target, "calls", exact=False)
    for node in graph.nodes.values():
        if hasattr(node, "tree"):
            del node.tree
    return "exact shape; calls by name"


def declared_in(text, relative):
    """Every module, class and function a Python file's text declares, as (id, first line, last line)."""
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError):
        return []
    module_id = f"py:{_module_name(relative)}"
    found = [(module_id, 1, max((getattr(n, "end_lineno", 1) or 1) for n in tree.body) if tree.body else 1)]

    def visit(body, prefix):
        for item in body:
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                found.append((f"{prefix}.{item.name}", item.lineno, item.end_lineno))
                if isinstance(item, ast.ClassDef):
                    visit(item.body, f"{prefix}.{item.name}")

    visit(tree.body, module_id)
    return found
