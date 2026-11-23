"""Which methods C# source patches with Harmony, read from the source text alone (1.107.0, for doc-tables).

Game-free: Harmony is the patching library most Unity and .NET game mods use, and its attributes are public API
(https://harmony.pardeike.net/articles/annotations.html, by Andreas Pardeike). Nothing is compiled, loaded or run.

What it reads:

- **Attributes on a patch class and on its methods, combined** as Harmony combines them (later ones fill in or replace):
  `[HarmonyPatch(typeof(T), "M")]`, `nameof(T.M)`, `MethodType.Getter` (and the other method types), the argument types that
  follow (ignored here), and `[HarmonyPatch(typeof(T))]` with `[HarmonyPatch("M")]` on a method.
- **Patch kinds** from the method's name (Prefix, Postfix, Transpiler, Finalizer) or its `[HarmonyPrefix]`-style attribute.
- **A class with `TargetMethod()` or `TargetMethods()`** finds its target by name at run time: shown as "by name in TargetMethod".
- **Manual `.Patch(...)` calls** are counted, never followed: their targets are found at run time.

Anything else in a HarmonyPatch attribute (a constant, a call) is "not read", with its file and line, never guessed.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import re

from .scan import blank, declarations, uncommented

KINDS = ("prefix", "postfix", "transpiler", "finalizer")
_ATTRIBUTE = re.compile(r"(?<![\w.])(?:global::)?(?:HarmonyLib\.)?(?P<name>HarmonyPatch|HarmonyPrefix|HarmonyPostfix|"
                        r"HarmonyTranspiler|HarmonyFinalizer)(?:Attribute)?\b\s*(?P<open>\()?")
_TYPEOF = re.compile(r"^typeof\s*\(\s*(?:global::)?(?P<type>.+?)\s*\)$", re.S)
_NAMEOF = re.compile(r"^nameof\s*\(\s*(?P<name>[\w.<>\[\], ]+?)\s*\)$", re.S)
_STRING = re.compile(r'^@?"(?P<text>[^"]*)"$')
_METHOD_TYPE = re.compile(r"^(?:HarmonyLib\.)?MethodType\.(?P<kind>\w+)$")
_ARRAY = re.compile(r"^new\s*(?:[\w.]+\s*)?\[\s*\]\s*\{", re.S)
_NAMED = re.compile(r"^(?P<name>\w+)\s*:(?!:)\s*(?P<value>.+)$", re.S)
_MANUAL = re.compile(r"\.Patch\s*\(\s*(?!\))")
_TARGET_METHODS = ("TargetMethod", "TargetMethods")
_SHOWN_METHOD_TYPES = {"Getter": "getter", "Setter": "setter", "Constructor": "constructor",
                       "StaticConstructor": "static constructor", "Enumerator": "enumerator", "Async": "async"}
SHOWN_LIMIT = 100


@dataclass
class Info:
    """What one or more HarmonyPatch attributes say: the declaring type, the method's name and its method type."""
    type: str = None
    method: str = None
    method_type: str = None
    unread: list = field(default_factory=list)    # (line, the attribute as written) Harmony would read but we could not

    def merged(self, other):
        return Info(other.type or self.type, other.method or self.method, other.method_type or self.method_type,
                    self.unread + other.unread)


@dataclass(frozen=True)
class Patch:
    target: str           # "Type.Method", "Type.Method (getter)", "Type (constructor)", "by name in TargetMethod"
    kinds: tuple          # of KINDS, in that order
    file: str
    line: int             # the patch class's first line


@dataclass(frozen=True)
class Unread:
    file: str
    line: int
    text: str             # what could not be read, as written, cut short


@dataclass
class Found:
    patches: list = field(default_factory=list)
    unread: list = field(default_factory=list)
    manual: list = field(default_factory=list)    # (file, line) of each .Patch(...) call


def _closing(text, at):
    """The index of the bracket closing the one at text[at], with strings skipped; -1 when it never closes."""
    pairs = {"(": ")", "[": "]", "{": "}"}
    stack, i, n = [], at, len(text)
    while i < n:
        char = text[i]
        if char == '"':
            i = text.find('"', i + 1)
            if i < 0:
                return -1
        elif char in pairs:
            stack.append(pairs[char])
        elif stack and char == stack[-1]:
            stack.pop()
            if not stack:
                return i
        i += 1
    return -1


def _split(arguments):
    """Top-level comma-separated arguments."""
    parts, depth, current, in_string = [], 0, [], False
    for char in arguments:
        if char == '"':
            in_string = not in_string
        elif not in_string and char in "([{<":
            depth += 1
        elif not in_string and char in ")]}>":
            depth -= 1
        if char == "," and depth == 0 and not in_string:
            parts.append("".join(current).strip())
            current = []
        else:
            current.append(char)
    if "".join(current).strip():
        parts.append("".join(current).strip())
    return parts


def _short(text):
    text = " ".join(text.split())
    return text if len(text) <= SHOWN_LIMIT else text[:SHOWN_LIMIT].rstrip() + "..."


def _last(name):
    return re.sub(r"<.*>", "", name).strip().rsplit(".", 1)[-1]


def read_arguments(arguments, line=0):
    """Info from one HarmonyPatch attribute's arguments (the text inside its brackets)."""
    info = Info()
    for argument in _split(arguments):
        named = _NAMED.match(argument)
        value = named["value"].strip() if named else argument
        typed, nameof, string = _TYPEOF.match(value), _NAMEOF.match(value), _STRING.match(value)
        method_type = _METHOD_TYPE.match(value)
        if typed:
            if info.type is None and info.method is None:
                info.type = typed["type"].strip()
            # a typeof after the method's name is an argument type: it chooses an overload, not the target
        elif nameof or string:
            if info.method is None:
                info.method = _last(nameof["name"]) if nameof else string["text"]
        elif method_type:
            info.method_type = method_type["kind"]
        elif _ARRAY.match(value) or value.startswith("ArgumentType.") or value.startswith("HarmonyLib.ArgumentType."):
            pass
        else:
            info.unread.append((line, _short(f"[HarmonyPatch({arguments})]")))
    return info


def _attributes(header, first_line):
    """(Info, kinds) from the attribute sections at the start of a declaration's header. header: comment-free text."""
    info, kinds = Info(), set()
    i, n = 0, len(header)
    while i < n:
        while i < n and header[i].isspace():
            i += 1
        if i >= n or header[i] != "[":
            break
        end = _closing(header, i)
        if end < 0:
            break
        section = header[i:end + 1]
        line = first_line + header.count("\n", 0, i)
        for found in _ATTRIBUTE.finditer(section):
            name = found["name"]
            if name != "HarmonyPatch":
                kinds.add(name[len("Harmony"):].lower())
                continue
            if found["open"]:
                at = found.end() - 1
                close = _closing(section, at)
                if close < 0:
                    info.unread.append((line, _short(section)))
                    continue
                info = info.merged(read_arguments(section[at + 1:close], line))
        i = end + 1
    return info, kinds


def _header(lines, decl):
    """The text of a declaration from its first line (its attributes) on, comments blanked."""
    return "\n".join(lines[decl.start - 1:decl.end])


def _shown(info):
    """The target in words, or None when the attributes do not name one fully."""
    shown_type = _SHOWN_METHOD_TYPES.get(info.method_type) if info.method_type else None
    if info.type is None:
        return None
    if info.method_type in ("Constructor", "StaticConstructor"):
        return f"{_last(info.type)} ({shown_type})"
    if info.method is None:
        return None
    target = f"{_last(info.type)}.{info.method}"
    return f"{target} ({shown_type})" if shown_type and info.method_type != "Normal" else target


def read_source(text, file=""):
    """Found: the patches, unread attributes and manual .Patch( calls in one C# file's text."""
    found = Found()
    clean = uncommented(text).split("\n")
    blanked = blank(text).split("\n")
    for number, line in enumerate(blanked, 1):
        if _MANUAL.search(line):
            found.manual.append((file, number))
    decls = declarations(text)
    types = [d for d in decls if d.kind in ("class", "struct", "record")]
    for owner in types:
        full = owner.full
        members = [d for d in decls if d.owner == full and d.kind == "method"]
        class_info, _ = _attributes(_header(clean, owner), owner.start)
        class_marked = bool(re.search(r"(?<![\w.])(?:HarmonyLib\.)?HarmonyPatch(?:Attribute)?\b",
                                      _attribute_text(_header(clean, owner))))
        methods = []
        for member in members:
            info, kinds = _attributes(_header(clean, member), member.start)
            if member.name in ("Prefix", "Postfix", "Transpiler", "Finalizer"):
                kinds.add(member.name.lower())
            marked = bool(re.search(r"(?<![\w.])(?:HarmonyLib\.)?HarmonyPatch(?:Attribute)?\b",
                                    _attribute_text(_header(clean, member))))
            methods.append((member, info, kinds, marked))
        if not class_marked and not any(marked for *_, marked in methods):
            continue
        by_name = next((m.name for m, *_ in methods if m.name in _TARGET_METHODS), None)
        rows = {}
        for member, info, kinds, marked in methods:
            if not kinds and not marked:
                continue
            combined = class_info.merged(info) if marked else class_info
            if by_name:
                target = f"by name in {by_name}"
            else:
                target = _shown(combined)
                if target is None:
                    for line, said in combined.unread or [(member.start if marked else owner.start,
                                                           _short(_attribute_text(_header(clean, member if marked else owner))))]:
                        found.unread.append(Unread(file, line, said))
                    continue
            rows.setdefault(target, set()).update(kinds)
        if not rows and class_marked and not by_name and class_info.unread:
            found.unread += [Unread(file, line, said) for line, said in class_info.unread]
        for target, kinds in rows.items():
            found.patches.append(Patch(target, tuple(k for k in KINDS if k in kinds), file, owner.start))
    found.unread = sorted(set(found.unread), key=lambda u: (u.file, u.line, u.text))
    return found


def _attribute_text(header):
    """The attribute sections at the start of a header, as one string."""
    out, i, n = [], 0, len(header)
    while i < n:
        while i < n and header[i].isspace():
            i += 1
        if i >= n or header[i] != "[":
            break
        end = _closing(header, i)
        if end < 0:
            break
        out.append(header[i:end + 1])
        i = end + 1
    return " ".join(out)


def read_folder(folder, relative_to=None, skip=("bin", "obj")):
    """Found for every .cs file under folder, its files named relative to relative_to (default: folder), with forward slashes."""
    folder = Path(folder)
    base = Path(relative_to) if relative_to else folder
    found = Found()
    for path in sorted(folder.rglob("*.cs")):
        if any(part in skip for part in path.relative_to(folder).parts[:-1]):
            continue
        try:
            text = path.read_text(encoding="utf-8-sig", errors="replace")
        except OSError:
            continue
        one = read_source(text, path.relative_to(base).as_posix())
        found.patches += one.patches
        found.unread += one.unread
        found.manual += one.manual
    return found


def uses_harmony(text):
    """Whether C# text uses Harmony: `using HarmonyLib` or a HarmonyPatch attribute, outside comments."""
    clean = uncommented(text)
    return bool(_USING.search(clean) or _MARK.search(clean))


_USING = re.compile(r"^\s*(?:global\s+)?using\s+HarmonyLib\s*;", re.M)
_MARK = re.compile(r"\[\s*(?:global::)?(?:HarmonyLib\.)?HarmonyPatch")
