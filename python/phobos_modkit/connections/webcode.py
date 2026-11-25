"""TypeScript and Svelte connections (D'thorga Companion's window, and any repository's), by name (1.128.0; the owner's answer on
D'thorga Companion's Decisions page, "All three").

A function is declared by `function name(`, `const name = (` or `const name = async (` (exported or not), and a class by
`class Name`; it runs until the next declaration. A file imports what its `import ... from "./x"` names, followed to the file. A
Svelte file is a component: its `<script>` is read as TypeScript, and its markup uses each component it names as `<Name`. A call is
a name followed by `(` in a function's body, joined to the function the file imported by that name, else to the repository's
functions of that name when there are at most three. What a window asks its host is kept for `join`: `ask<…>("command"` and
`invoke("command"`.
"""
from __future__ import annotations

from pathlib import PurePosixPath
import re

from . import Node, source_files

LANGUAGE = "typescript"
SVELTE = "svelte"
SUFFIXES = (".ts", ".svelte")
_NAME = r"[A-Za-z_$][\w$]*"
_DECLARED = [
    (re.compile(rf"^\s*(?:export\s+)?(?:default\s+)?(?:async\s+)?function\s*\*?\s*({_NAME})\s*[<(]"), "function"),
    (re.compile(rf"^\s*(?:export\s+)?(?:const|let)\s+({_NAME})\s*(?::[^=]+)?=\s*(?:async\s+)?(?:function\b|\(|{_NAME}\s*=>|<)"),
     "function"),
    (re.compile(rf"^\s*(?:export\s+)?(?:default\s+)?(?:abstract\s+)?class\s+({_NAME})"), "class"),
]
_IMPORT = re.compile(r"""import\s+(?:type\s+)?([^'";]*?)\s*from\s*["']([^"']+)["']""", re.S)
_CALLED = re.compile(rf"(?<![\w$.])({_NAME})\s*(?:<[^<>()]*>)?\s*\(")
_ASKED = re.compile(r"""\b(?:ask|invoke)\s*(?:<[^()]*?>)?\s*\(\s*["']([a-z][a-z0-9_]*)["']""", re.S)
_COMPONENT = re.compile(r"<([A-Z][\w$]*)[\s/>]")
_SCRIPT = re.compile(r"(<script\b[^>]*>)(.*?)</script>", re.S)
_COMMENT = re.compile(r"/\*.*?\*/|(?<![:\\])//[^\n]*", re.S)
_STRING = re.compile(r"`(?:\\.|[^`\\])*`|\"(?:\\.|[^\"\\\n])*\"|'(?:\\.|[^'\\\n])*'")
_KEYWORDS = {"if", "for", "while", "switch", "catch", "return", "function", "typeof", "new", "await", "import", "super", "void"}


def inputs(root):
    return [p for _, p in source_files(root, SUFFIXES)]


def _blank(match):
    return re.sub(r"[^\n]", " ", match.group(0))


def code_of(text, svelte=False):
    """The text with comments and strings blanked, line breaks kept; in a Svelte file, the markup blanked too but for its tags."""
    if svelte:
        kept = [" " if c != "\n" else "\n" for c in text]
        for match in _SCRIPT.finditer(text):
            start, end = match.span(2)
            kept[start:end] = list(text[start:end])
        script = "".join(kept)
    else:
        script = text
    return _STRING.sub(_blank, _COMMENT.sub(_blank, script))


def declared(code_lines):
    """[(name, kind, first line)] of what the lines declare, in order."""
    found = []
    for number, line in enumerate(code_lines, 1):
        for pattern, kind in _DECLARED:
            match = pattern.match(line)
            if match and match.group(1) not in _KEYWORDS:
                found.append((match.group(1), kind, number))
                break
    return found


def _resolve(relative, spec, known):
    """The repository's file an import names, or None for a package's."""
    if not spec.startswith("."):
        return None
    base = PurePosixPath(relative).parent
    joined = PurePosixPath(*[p for p in (base / spec).parts])
    parts = []
    for part in joined.parts:
        if part == "..":
            if parts:
                parts.pop()
        elif part != ".":
            parts.append(part)
    target = "/".join(parts)
    for candidate in (target, target + ".ts", target + ".svelte", target.removesuffix(".js") + ".ts", target + "/index.ts"):
        if candidate in known:
            return candidate
    return None


def _imported_names(clause):
    """The local names an import clause brings in: default, `{ a, b as c }`, `* as d`."""
    names = []
    clause = clause.strip()
    braces = re.search(r"\{([^}]*)\}", clause)
    if braces:
        for item in braces.group(1).split(","):
            item = item.strip().removeprefix("type ").strip()
            if item:
                names.append((item.split(" as ")[0].strip(), item.split(" as ")[-1].strip()))
        clause = clause.replace(braces.group(0), "")
    for item in clause.split(","):
        item = item.strip()
        if item.startswith("* as "):
            names.append(("*", item[5:].strip()))
        elif re.fullmatch(_NAME, item):
            names.append(("default", item))
    return names


def read(root, graph, environ=None):
    files = source_files(root, SUFFIXES)
    if not files:
        return None
    known = {relative for relative, _ in files}
    by_short, parsed = {}, []
    for relative, path in files:
        raw = path.read_text(encoding="utf-8", errors="replace")
        svelte = relative.endswith(".svelte")
        lines = code_of(raw, svelte).splitlines()
        language = SVELTE if svelte else LANGUAGE
        name = relative.rsplit("/", 1)[-1]
        module = graph.add(Node(f"ts:file:{relative}", name, "component" if svelte else "module", language, relative, 1,
                                len(lines)))
        found = []
        for short, kind, number in declared(lines):
            node = graph.add(Node(f"ts:{relative}:{short}", short, kind, language, relative, number, owner=module.id))
            graph.link(module.id, node.id, "holds")
            found.append(node)
            by_short.setdefault(short, []).append(node.id)
        for index, node in enumerate(found):
            node.end = (found[index + 1].line - 1) if index + 1 < len(found) else len(lines)
        imports = {}
        for clause, spec in _IMPORT.findall(raw):
            target = _resolve(relative, spec, known)
            if target is None:
                continue
            graph.link(module.id, graph.ensure(f"ts:file:{target}", target.rsplit("/", 1)[-1], "module", LANGUAGE).id,
                       "imports")
            for exported, local in _imported_names(clause):
                imports[local] = f"ts:file:{target}" if exported in ("default", "*") else f"ts:{target}:{exported}"
        parsed.append((relative, raw, lines, module, found, imports, svelte))
    for relative, raw, lines, module, found, imports, svelte in parsed:
        for node in found:
            body = "\n".join(lines[node.line:node.end])
            for called in set(_CALLED.findall(body)):
                if called in _KEYWORDS:
                    continue
                if called in imports and imports[called] in graph.nodes:
                    graph.link(node.id, imports[called], "calls")
                    continue
                targets = [t for t in by_short.get(called, []) if t != node.id]
                own = [t for t in targets if t.startswith(f"ts:{relative}:")]
                if own:
                    graph.link(node.id, own[0], "calls")
                elif 0 < len(targets) <= 3:
                    for target in targets:
                        graph.link(node.id, target, "calls", exact=False)
        if svelte:
            markup = _SCRIPT.sub(_blank, raw)
            for component in set(_COMPONENT.findall(markup)):
                target = imports.get(component)
                if target and target in graph.nodes:
                    graph.link(module.id, target, "uses")
    return "by name (calls), exactly (imports, components)"


def asked(root):
    """[(the window function's id, the command it asks the host)] in every TypeScript and Svelte file."""
    found = []
    for relative, path in source_files(root, SUFFIXES):
        raw = path.read_text(encoding="utf-8", errors="replace")
        svelte = relative.endswith(".svelte")
        stripped = _COMMENT.sub(_blank, code_of_strings_kept(raw) if svelte else raw)
        decls = declared(code_of(raw, svelte).splitlines())
        for match in _ASKED.finditer(stripped):
            line = stripped.count("\n", 0, match.start()) + 1
            holder = None
            for short, _, first in decls:
                if first <= line:
                    holder = short
            found.append((f"ts:{relative}:{holder}" if holder else f"ts:file:{relative}", match.group(1)))
    return found


def code_of_strings_kept(text):
    """A Svelte file's script with its markup blanked, strings kept (for the commands its asks name)."""
    kept = [" " if c != "\n" else "\n" for c in text]
    for match in _SCRIPT.finditer(text):
        start, end = match.span(2)
        kept[start:end] = list(text[start:end])
    return "".join(kept)


def declared_in(text, relative):
    """Every function and class a TypeScript or Svelte file's text declares, as (id, first line, last line), and the file."""
    lines = code_of(text, relative.endswith(".svelte")).splitlines()
    found = [[f"ts:{relative}:{short}", number, None] for short, _, number in declared(lines)]
    for index, item in enumerate(found):
        item[2] = (found[index + 1][1] - 1) if index + 1 < len(found) else len(lines)
    return [tuple(item) for item in found] + [(f"ts:file:{relative}", 1, len(lines))]
