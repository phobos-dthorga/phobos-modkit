"""Rust connections (D'thorga Companion's host, and any repository's), by name (1.128.0; the owner's answer on D'thorga Companion's
Decisions page, "All three").

A function is `fn name` (public or not, async or not); inside `impl Type` it is that type's, `Type::name`; `struct`, `enum` and
`trait` are types. Each runs to the brace that closes it. A file holds the modules its `mod name;` names, followed to their files.
A call is a name followed by `(` (or `Type::name(`) in a function's body, joined to the repository's functions of that name when
there are at most three. A function under `#[tauri::command]` is a command the window may ask for: `join` links each `ask` to it.
"""
from __future__ import annotations

from pathlib import PurePosixPath
import re

from . import Node, source_files

LANGUAGE = "rust"
_NAME = r"[A-Za-z_]\w*"
_FN = re.compile(rf"^\s*(?:pub(?:\([^)]*\))?\s+)?(?:const\s+)?(?:async\s+)?(?:unsafe\s+)?(?:extern\s+\"[^\"]*\"\s+)?fn\s+({_NAME})")
_TYPE = re.compile(rf"^\s*(?:pub(?:\([^)]*\))?\s+)?(struct|enum|trait)\s+({_NAME})")
_IMPL = re.compile(rf"^\s*impl\b(?:\s*<[^{{]*?>)?\s+(?:[\w:<>, ]+\s+for\s+)?({_NAME})")
_MOD = re.compile(rf"^\s*(?:pub(?:\([^)]*\))?\s+)?mod\s+({_NAME})\s*;")
_PATH_ATTR = re.compile(r'#\[path\s*=\s*"([^"]+)"\]')
_CALLED = re.compile(rf"(?<![\w.])(?:({_NAME})::)?({_NAME})\s*(?:::<[^()]*>)?\s*\(")
_METHOD = re.compile(rf"\.({_NAME})\s*(?:::<[^()]*>)?\s*\(")
_COMMAND = re.compile(r"#\[\s*tauri::command\b")
_COMMENT = re.compile(r"/\*.*?\*/|//[^\n]*", re.S)
_STRING = re.compile(r'r#*"(?:.|\n)*?"#*|b?"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])\'')
_KEYWORDS = {"if", "for", "while", "match", "loop", "return", "fn", "Some", "Ok", "Err", "None", "Box", "Vec", "move", "as", "in",
             "let", "mut", "ref", "where", "impl", "dyn", "self", "Self", "super", "crate"}


def inputs(root):
    return [p for _, p in source_files(root, (".rs",))]


def _blank(match):
    return re.sub(r"[^\n]", " ", match.group(0))


def code_of(text):
    """The text with comments and strings blanked, line breaks kept."""
    return _STRING.sub(_blank, _COMMENT.sub(_blank, text))


def _closing(code, start):
    """The index just after the block that opens at the first `{` after `start` (or `;` before it: no body)."""
    depth, index = 0, start
    while index < len(code):
        char = code[index]
        if char == ";" and depth == 0:
            return index + 1
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return index + 1
        index += 1
    return len(code)


def declared(text):
    """[(name, kind, first line, last line, owner type or None, is a Tauri command)] of what a Rust file declares."""
    code = code_of(text)
    starts = [0]
    for line in code.splitlines(keepends=True):
        starts.append(starts[-1] + len(line))
    line_of = lambda index: next(n for n in range(len(starts) - 1, -1, -1) if starts[n] <= index) + 1   # noqa: E731
    impls = []
    for number, line in enumerate(code.splitlines(), 1):
        match = _IMPL.match(line)
        if match:
            end = _closing(code, starts[number - 1])
            impls.append((starts[number - 1], end, match.group(1)))
    raw_lines = text.splitlines()
    found = []
    for number, line in enumerate(code.splitlines(), 1):
        fn = _FN.match(line)
        kind = None
        if fn:
            name, kind = fn.group(1), "function"
        else:
            typed = _TYPE.match(line)
            if typed:
                name, kind = typed.group(2), "type"
        if not kind:
            continue
        begin = starts[number - 1]
        end_index = _closing(code, begin)
        owner = next((t for s, e, t in impls if s < begin < e), None) if kind == "function" else None
        above = [raw_lines[n].strip() for n in range(max(0, number - 4), number - 1)]
        command = kind == "function" and any(_COMMAND.match(a) for a in above)
        found.append((name, kind, number, line_of(max(begin, end_index - 1)), owner, command))
    return found


def _module_files(relative, text, known):
    """The files a file's `mod name;` lines name: name.rs or name/mod.rs beside it (or under its own folder for a non-root file),
    or the `#[path = "..."]` the line above names."""
    folder = PurePosixPath(relative).parent
    stem = PurePosixPath(relative).stem
    own = folder if stem in ("lib", "main", "mod") else folder / stem
    lines = text.splitlines()
    found = []
    for index, line in enumerate(lines):
        match = _MOD.match(line)
        if not match:
            continue
        name = match.group(1)
        attr = _PATH_ATTR.search(lines[index - 1]) if index else None
        candidates = [str(folder / attr.group(1))] if attr else [str(own / f"{name}.rs"), str(own / name / "mod.rs")]
        hit = next((c.replace("\\", "/") for c in candidates if c.replace("\\", "/") in known), None)
        if hit:
            found.append(hit)
    return found


def node_id(relative, name, owner=None):
    return f"rs:{relative}:{owner}::{name}" if owner else f"rs:{relative}:{name}"


def read(root, graph, environ=None):
    files = source_files(root, (".rs",))
    if not files:
        return None
    known = {relative for relative, _ in files}
    by_short, parsed = {}, []
    for relative, path in files:
        text = path.read_text(encoding="utf-8", errors="replace")
        code_lines = code_of(text).splitlines()
        module = graph.add(Node(f"rs:file:{relative}", relative.rsplit("/", 1)[-1], "module", LANGUAGE, relative, 1,
                                len(code_lines)))
        found = []
        for name, kind, first, last, owner, command in declared(text):
            node = graph.add(Node(node_id(relative, name, owner), f"{owner}::{name}" if owner else name, kind, LANGUAGE,
                                  relative, first, last, owner=module.id))
            graph.link(module.id, node.id, "holds")
            if kind == "function":
                found.append((node, owner))
                by_short.setdefault(name, []).append(node.id)
                if owner:
                    by_short.setdefault(f"{owner}::{name}", []).append(node.id)
        for target in _module_files(relative, text, known):
            graph.link(module.id, graph.ensure(f"rs:file:{target}", target.rsplit("/", 1)[-1], "module", LANGUAGE).id, "holds")
        parsed.append((code_lines, found))
    for code_lines, found in parsed:
        for node, owner in found:
            body = "\n".join(code_lines[node.line:node.end])
            names = set()
            for typed, called in _CALLED.findall(body):
                names.add(f"{'Self' if typed == 'Self' else typed}::{called}" if typed else called)
            names |= set(_METHOD.findall(body))
            for called in names:
                if called.startswith("Self::") and owner:
                    called = f"{owner}::{called[6:]}"
                short = called.rsplit("::", 1)[-1]
                if short in _KEYWORDS:
                    continue
                targets = [t for t in by_short.get(called, by_short.get(short, [])) if t != node.id]
                if 0 < len(targets) <= 3:
                    for target in targets:
                        graph.link(node.id, target, "calls", exact=False)
    return "by name (calls), exactly (modules, impl blocks)"


def commands(root):
    """{command name: its function's id}: every function under `#[tauri::command]`."""
    found = {}
    for relative, path in source_files(root, (".rs",)):
        text = path.read_text(encoding="utf-8", errors="replace")
        for name, kind, _, _, owner, command in declared(text):
            if command and not owner:
                found[name] = node_id(relative, name)
    return found


def declared_in(text, relative):
    """Every function and type a Rust file's text declares, as (id, first line, last line), and the file."""
    found = [(node_id(relative, name, owner), first, last) for name, kind, first, last, owner, _ in declared(text)]
    return found + [(f"rs:file:{relative}", 1, len(text.splitlines()))]
