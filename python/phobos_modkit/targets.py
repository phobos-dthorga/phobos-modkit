"""Members that C# source names by string, checked against assemblies' metadata.

A compiler checks a member named with nameof(); it cannot check one named in a string: a Harmony patch on a private
method, a reflected private field, an overload chosen by a list of parameter types, or the injected parameters of a patch
(__instance, __result, ___field) that Harmony resolves at run time. Those break silently or at start-up when the other
assembly changes. This module finds every such name in a source tree and checks each against a listing of the real
assemblies' members, read through their metadata by the kit's reader (dotnet/PhobosModKit.Assemblies members).

What it reads from the source: [HarmonyPatch(...)] attributes on classes and methods (typeof, strings, nameof,
MethodType, overload types, constructors) and the parameters of their patch methods; AccessTools.Field, Method, Property,
PropertyGetter, PropertySetter, Constructor and their Declared forms, FieldRefAccess; typeof(T).GetField, GetMethod and
GetProperty. A lookup whose type is worked out at run time (a variable, TypeByName) cannot be checked and is listed.

No game is named here: the source is C#, the attributes are Harmony's public names, and the listing comes from whatever
assemblies the caller chose.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import re

HARMONY_METHOD_NAMES = ("Prefix", "Postfix", "Finalizer", "Transpiler")
MARKER_ATTRIBUTES = {"HarmonyPrefix", "HarmonyPostfix", "HarmonyFinalizer", "HarmonyTranspiler"}
STOP_TYPES = {"System.Object", "System.ValueType", "System.Enum", "Object", "ValueType", "Enum"}
ALIASES = {
    "bool": "Boolean", "byte": "Byte", "sbyte": "SByte", "char": "Char", "short": "Int16", "ushort": "UInt16",
    "int": "Int32", "uint": "UInt32", "long": "Int64", "ulong": "UInt64", "float": "Single", "double": "Double",
    "string": "String", "object": "Object", "void": "Void", "decimal": "Decimal", "nint": "IntPtr", "nuint": "UIntPtr",
}
PRIMITIVES = set(ALIASES.values()) - {"Object", "Void"}


@dataclass
class Target:
    """One member a source file names on another assembly's type."""
    file: str
    line: int
    type_name: str                    # as written: VehiclePawn, Outer.Inner, or a full name
    member: str                       # "" for a constructor
    member_kind: str                  # method, field, property, getter, setter, ctor, cctor
    arguments: list[str] | None       # the overload's parameter types as written, or None for any
    source: str                       # HarmonyPatch, AccessTools.Method, GetField, ...
    compiler_checked: bool = False    # named with nameof(): the build already checks the member exists
    note: str = ""

    @property
    def label(self):
        kind = {"getter": " (getter)", "setter": " (setter)", "ctor": " (constructor)", "cctor": " (static constructor)"}.get(self.member_kind, "")
        member = self.member or ("" if self.member_kind in ("ctor", "cctor") else "?")
        args = "" if self.arguments is None else "(" + ", ".join(self.arguments) + ")"
        return f"{self.type_name}.{member}{args}{kind}" if member else f"{self.type_name}{args}{kind}"


@dataclass
class Injection:
    """A patch method's parameter Harmony fills at run time: __instance, __result or ___field."""
    file: str
    line: int
    target: Target
    name: str
    declared_type: str


@dataclass
class Unresolved:
    file: str
    line: int
    source: str
    member: str
    reason: str


@dataclass
class Scan:
    targets: list[Target] = field(default_factory=list)
    injections: list[Injection] = field(default_factory=list)
    unresolved: list[Unresolved] = field(default_factory=list)
    usings: dict[str, set[str]] = field(default_factory=dict)   # file -> namespaces in scope
    files: int = 0

    def type_names(self):
        names = {t.type_name for t in self.targets}
        for injection in self.injections:
            names.add(injection.target.type_name)
            names.add(_strip_modifiers(injection.declared_type))
        return sorted(n for n in names if n)


# ---- Reading C# ----

def _blank_comments(text):
    """Comments replaced by spaces (newlines kept), strings left alone: the strings are what we are after."""
    out = []
    i = 0
    n = len(text)
    while i < n:
        c = text[i]
        if c == '"':
            j = i + 1
            if i > 0 and text[i - 1] == '@':
                while j < n:
                    if text[j] == '"' and j + 1 < n and text[j + 1] == '"':
                        j += 2
                        continue
                    if text[j] == '"':
                        break
                    j += 1
            else:
                while j < n and text[j] != '"':
                    j += 2 if text[j] == '\\' else 1
            out.append(text[i:j + 1])
            i = j + 1
        elif c == "'" :
            j = i + 1
            while j < n and text[j] != "'":
                j += 2 if text[j] == '\\' else 1
            out.append(text[i:j + 1])
            i = j + 1
        elif text.startswith("//", i):
            j = text.find("\n", i)
            j = n if j < 0 else j
            out.append(" " * (j - i))
            i = j
        elif text.startswith("/*", i):
            j = text.find("*/", i + 2)
            j = n if j < 0 else j + 2
            out.append(re.sub(r"[^\n]", " ", text[i:j]))
            i = j
        else:
            out.append(c)
            i += 1
    return "".join(out)


def _match_close(text, open_index):
    """The index just past the bracket matching the one at open_index, honouring nesting and strings; -1 if none."""
    pairs = {"(": ")", "[": "]", "{": "}", "<": ">"}
    close = pairs[text[open_index]]
    depth = 0
    i = open_index
    n = len(text)
    while i < n:
        c = text[i]
        if c == '"':
            j = i + 1
            while j < n and text[j] != '"':
                j += 2 if text[j] == '\\' else 1
            i = j + 1
            continue
        if c == text[open_index]:
            depth += 1
        elif c == close:
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    return -1


def _split_args(text):
    """Top-level comma split, honouring brackets and strings."""
    parts, depth, start, i, n = [], 0, 0, 0, len(text)
    while i < n:
        c = text[i]
        if c == '"':
            j = i + 1
            while j < n and text[j] != '"':
                j += 2 if text[j] == '\\' else 1
            i = j + 1
            continue
        if c in "([{<":
            depth += 1
        elif c in ")]}>":
            depth -= 1
        elif c == "," and depth == 0:
            parts.append(text[start:i].strip())
            start = i + 1
        i += 1
    tail = text[start:].strip()
    if tail:
        parts.append(tail)
    return parts


def _line_of(text, index):
    return text.count("\n", 0, index) + 1


def _strip_modifiers(type_text):
    text = type_text.strip()
    text = re.sub(r"^(ref readonly|ref|out|in|params)\s+", "", text)
    return text.rstrip("?").strip()


def _typeof_inner(text):
    m = re.fullmatch(r"typeof\s*\((.+)\)", text.strip(), re.S)
    return m.group(1).strip() if m else None


def _type_array(text):
    """The types in new[] { typeof(A), typeof(B) } or new Type[] { ... }; None if text is not one."""
    m = re.fullmatch(r"new\s*(?:System\.)?(?:Type)?\s*\[\s*\]\s*\{(.*)\}", text.strip(), re.S)
    if not m:
        return None
    types = []
    for item in _split_args(m.group(1)):
        by_ref = re.fullmatch(r"(typeof\s*\(.+\))\s*\.\s*MakeByRefType\s*\(\s*\)", item.strip(), re.S)
        inner = _typeof_inner(by_ref.group(1) if by_ref else item)
        types.append(inner if inner is not None else "?")        # worked out at run time: matches anything
    return types


def _member_of_nameof(text):
    m = re.fullmatch(r"nameof\s*\((.+)\)", text.strip(), re.S)
    if not m:
        return None
    return m.group(1).strip().split(".")[-1]


class _Attribute:
    """One [HarmonyPatch(...)]'s arguments, read."""

    def __init__(self, args):
        self.type_name = ""
        self.member = ""
        self.method_type = ""
        self.arguments = None
        self.compiler_checked = False
        strings = []
        for arg in args:
            inner = _typeof_inner(arg)
            if inner is not None:
                if not self.type_name:
                    self.type_name = inner
                else:
                    self.arguments = (self.arguments or []) + [inner]
                continue
            types = _type_array(arg)
            if types is not None:
                self.arguments = types
                continue
            name = _member_of_nameof(arg)
            if name is not None:
                self.member = name
                self.compiler_checked = True
                continue
            m = re.fullmatch(r'"(.*)"', arg.strip(), re.S)
            if m:
                strings.append(m.group(1))
                continue
            m = re.fullmatch(r"(?:HarmonyLib\.)?MethodType\.(\w+)", arg.strip())
            if m:
                self.method_type = m.group(1)
        if len(strings) >= 2 and not self.type_name:
            self.type_name, self.member = strings[0], strings[1]
        elif strings:
            self.member = strings[0]

    def merge(self, over):
        merged = _Attribute([])
        merged.type_name = over.type_name or self.type_name
        merged.member = over.member or self.member
        merged.method_type = over.method_type or self.method_type
        merged.arguments = over.arguments if over.arguments is not None else self.arguments
        merged.compiler_checked = over.compiler_checked if over.member else self.compiler_checked
        return merged

    def target(self, file, line, note=""):
        kind = {"Getter": "getter", "Setter": "setter", "Constructor": "ctor", "StaticConstructor": "cctor"}.get(self.method_type, "method")
        return Target(file, line, self.type_name, self.member, kind, self.arguments, "HarmonyPatch", self.compiler_checked, note)


def _declaration_after(text, index):
    """(kind, header_text, header_end) for the declaration following index: 'class', 'method' or ''."""
    i = index
    n = len(text)
    while i < n:
        while i < n and text[i].isspace():
            i += 1
        if i < n and text[i] == "[":
            end = _match_close(text, i)
            if end < 0:
                return "", "", i
            i = end
            continue
        break
    stop = min(x for x in (text.find("{", i), text.find(";", i), n) if x >= 0)
    arrow = text.find("=>", i)
    if 0 <= arrow < stop:
        stop = arrow
    header = text[i:stop]
    if re.search(r"\b(class|struct|record)\s+\w+", header):
        return "class", header, stop
    if "(" in header:
        return "method", header, stop
    return "", header, stop


def _params_of_header(header):
    open_index = header.find("(")
    if open_index < 0:
        return []
    end = _match_close(header, open_index)
    inner = header[open_index + 1:end - 1] if end > 0 else header[open_index + 1:]
    return _split_args(inner)


def _injections_from_params(params, target, file, line, found):
    for param in params:
        param = re.sub(r"\[[^\]]*\]\s*", "", param).strip()          # a [HarmonyArgument] mark
        m = re.fullmatch(r"(.+?)\s+(__instance|__result|___\w+)\s*(=.*)?", param, re.S)
        if m:
            found.append(Injection(file, line, target, m.group(2), _strip_modifiers(m.group(1))))


ATTRIBUTE_PATTERN = re.compile(r"\[\s*HarmonyPatch\b\s*")


def _attribute_at(text, m):
    """(the attribute, where its arguments end) for a match of ATTRIBUTE_PATTERN; a bare [HarmonyPatch] has no arguments."""
    if m.end() < len(text) and text[m.end()] == "(":
        end = _match_close(text, m.end())
        if end < 0:
            return None, -1
        return _Attribute(_split_args(text[m.end() + 1:end - 1])), end
    return _Attribute([]), m.end()


def _scan_harmony(text, file, scan, processed):
    for m in ATTRIBUTE_PATTERN.finditer(text):
        if m.start() in processed:
            continue
        processed.add(m.start())
        attribute, end = _attribute_at(text, m)
        if attribute is None:
            continue
        bracket_end = text.find("]", end)
        after = bracket_end + 1 if bracket_end >= 0 else end
        kind, header, header_end = _declaration_after(text, after)
        line = _line_of(text, m.start())
        if kind == "class":
            body_start = text.find("{", header_end)
            body_end = _match_close(text, body_start) if body_start >= 0 else -1
            body = text[body_start:body_end] if body_end > 0 else ""
            # Every [HarmonyPatch] on this class, in order, merged as Harmony merges them.
            class_attribute = attribute
            for other in ATTRIBUTE_PATTERN.finditer(text, m.end(), body_start if body_start >= 0 else len(text)):
                processed.add(other.start())
                other_attribute, _ = _attribute_at(text, other)
                if other_attribute is not None:
                    class_attribute = class_attribute.merge(other_attribute)
            _scan_patch_class(text, body, body_start, class_attribute, file, line, scan, processed)
        elif kind == "method":
            target = attribute.target(file, line)
            if attribute.type_name and (attribute.member or attribute.method_type in ("Constructor", "StaticConstructor")):
                scan.targets.append(target)
                _injections_from_params(_params_of_header(header), target, file, line, scan.injections)


def _scan_patch_class(text, body, body_start, class_attribute, file, line, scan, processed):
    has_target_method = re.search(r"\bTargetMethods?\s*\(|\[\s*HarmonyTargetMethods?\s*\]", body) is not None
    if has_target_method:
        scan.unresolved.append(Unresolved(file, line, "HarmonyPatch", class_attribute.member or "?", "the target is chosen at run time by TargetMethod"))
    class_target = class_attribute.target(file, line)
    class_complete = bool(class_attribute.type_name) and (bool(class_attribute.member) or class_attribute.method_type in ("Constructor", "StaticConstructor"))
    if class_complete:
        scan.targets.append(class_target)
    # Method-level attributes inside the body refine the class's target for that method alone.
    method_level = {}
    for m in ATTRIBUTE_PATTERN.finditer(body):
        processed.add(body_start + m.start())
        own, end = _attribute_at(body, m)
        if own is None:
            continue
        merged = class_attribute.merge(own)
        bracket_end = body.find("]", end)
        kind, header, header_end = _declaration_after(body, bracket_end + 1 if bracket_end >= 0 else end)
        if kind != "method":
            continue
        method_line = _line_of(text, body_start + m.start())
        target = merged.target(file, method_line)
        if merged.type_name and (merged.member or merged.method_type in ("Constructor", "StaticConstructor")):
            scan.targets.append(target)
            method_level[header_end] = (target, header, method_line)
    # The patch methods: named Prefix/Postfix/Finalizer/Transpiler, or marked [HarmonyPrefix] and kin.
    for name_match in re.finditer(r"\b(" + "|".join(HARMONY_METHOD_NAMES) + r")\s*\(", body):
        header_start = body.rfind("\n", 0, name_match.start()) + 1
        end = _match_close(body, name_match.end() - 1)
        if end < 0:
            continue
        header = body[header_start:end]
        if any(k <= header_start + len(header) and k >= header_start for k in method_level):
            continue
        if not class_complete or has_target_method:
            continue
        _injections_from_params(_params_of_header(header), class_target, file, _line_of(text, body_start + name_match.start()), scan.injections)
    for marker in re.finditer(r"\[\s*(" + "|".join(MARKER_ATTRIBUTES) + r")\s*\]", body):
        kind, header, _ = _declaration_after(body, marker.end())
        if kind != "method" or not class_complete or has_target_method:
            continue
        if re.search(r"\b(" + "|".join(HARMONY_METHOD_NAMES) + r")\s*\(", header):
            continue   # counted above
        _injections_from_params(_params_of_header(header), class_target, file, _line_of(text, body_start + marker.start()), scan.injections)
    for _, (target, header, method_line) in method_level.items():
        _injections_from_params(_params_of_header(header), target, file, method_line, scan.injections)


ACCESS_KINDS = {
    "Field": "field", "DeclaredField": "field", "FieldRefAccess": "field", "StaticFieldRefAccess": "field",
    "Method": "method", "DeclaredMethod": "method",
    "Property": "property", "DeclaredProperty": "property",
    "PropertyGetter": "getter", "DeclaredPropertyGetter": "getter",
    "PropertySetter": "setter", "DeclaredPropertySetter": "setter",
    "Constructor": "ctor", "DeclaredConstructor": "ctor",
}
ACCESS_PATTERN = re.compile(r"AccessTools\s*\.\s*(" + "|".join(ACCESS_KINDS) + r")\s*(<[^(]*?>)?\s*\(")
GET_PATTERN = re.compile(r"\.\s*Get(Field|Method|Property)\s*\(")


def _scan_reflection(text, file, scan):
    for m in ACCESS_PATTERN.finditer(text):
        end = _match_close(text, m.end() - 1)
        if end < 0:
            continue
        args = _split_args(text[m.end():end - 1])
        line = _line_of(text, m.start())
        kind_name = m.group(1)
        kind = ACCESS_KINDS[kind_name]
        source = "AccessTools." + kind_name
        type_name = None
        generic = m.group(2)
        if generic:
            type_name = _split_args(generic.strip("<>"))[0].strip()
            name_arg = args[0] if args else ""
            rest = args[1:]
        else:
            if not args:
                continue
            type_name = _typeof_inner(args[0])
            if type_name is None:
                scan.unresolved.append(Unresolved(file, line, source, _string_or_nameof(args[1]) if len(args) > 1 else "?",
                                                  "the type is worked out at run time"))
                continue
            name_arg = args[1] if len(args) > 1 else ""
            rest = args[2:]
        if kind == "ctor":
            arguments = _type_array(name_arg) if name_arg else None
            scan.targets.append(Target(file, line, type_name, "", "ctor", arguments, source))
            continue
        member = _string_or_nameof(name_arg)
        if member is None:
            scan.unresolved.append(Unresolved(file, line, source, name_arg or "?", "the member's name is worked out at run time"))
            continue
        arguments = None
        for extra in rest:
            types = _type_array(extra)
            if types is not None:
                arguments = types
        compiler_checked = _member_of_nameof(name_arg) is not None
        scan.targets.append(Target(file, line, type_name, member, kind, arguments, source, compiler_checked))
    for m in GET_PATTERN.finditer(text):
        end = _match_close(text, m.end() - 1)
        if end < 0:
            continue
        args = _split_args(text[m.end():end - 1])
        if not args:
            continue
        member = _string_or_nameof(args[0])
        if member is None:
            continue
        line = _line_of(text, m.start())
        kind = {"Field": "field", "Method": "method", "Property": "property"}[m.group(1)]
        source = "Get" + m.group(1)
        before = text[:m.start()].rstrip()
        receiver = None
        if before.endswith(")"):
            open_index = before.rfind("typeof")
            if open_index >= 0:
                candidate = before[open_index:]
                if _match_close(candidate, candidate.find("(")) == len(candidate):
                    receiver = _typeof_inner(candidate)
        if receiver is None:
            scan.unresolved.append(Unresolved(file, line, source, member, "the type is worked out at run time"))
            continue
        arguments = None
        for extra in args[1:]:
            types = _type_array(extra)
            if types is not None:
                arguments = types
        scan.targets.append(Target(file, line, receiver, member, kind, arguments, source, _member_of_nameof(args[0]) is not None))


def _string_or_nameof(arg):
    if arg is None:
        return None
    m = re.fullmatch(r'"(.*)"', arg.strip(), re.S)
    if m:
        return m.group(1)
    return _member_of_nameof(arg)


def _usings(text):
    found = set()
    for m in re.finditer(r"^\s*using\s+(?:static\s+)?([\w.]+)\s*;", text, re.M):
        found.add(m.group(1))
    for m in re.finditer(r"^\s*namespace\s+([\w.]+)", text, re.M):
        parts = m.group(1).split(".")
        for i in range(1, len(parts) + 1):
            found.add(".".join(parts[:i]))
    return found


def scan_file(path, root=None):
    text = Path(path).read_text(encoding="utf-8", errors="replace")
    return scan_text(text, str(Path(path).relative_to(root)) if root else str(path))


def scan_text(text, file):
    scan = Scan(files=1)
    clean = _blank_comments(text)
    processed = set()
    _scan_harmony(clean, file, scan, processed)
    _scan_reflection(clean, file, scan)
    scan.usings[file] = _usings(clean)
    return scan


def scan_tree(root, globs=("src/**/*.cs",), exclude=("/obj/", "/bin/", "\\obj\\", "\\bin\\")):
    """Every target in the files the globs name under root, paths relative to root with forward slashes."""
    root = Path(root)
    total = Scan()
    seen = set()
    for pattern in globs:
        for path in sorted(root.glob(pattern)):
            text = str(path)
            if path in seen or any(part in text for part in exclude):
                continue
            seen.add(path)
            relative = path.relative_to(root).as_posix()
            one = scan_text(path.read_text(encoding="utf-8", errors="replace"), relative)
            total.targets.extend(one.targets)
            total.injections.extend(one.injections)
            total.unresolved.extend(one.unresolved)
            total.usings.update(one.usings)
            total.files += 1
    return total


# ---- The listing and the check ----

def normalise(type_text):
    """A type as written or as read, reduced to what both can agree on: simple names, C# aliases mapped, no modifiers."""
    text = _strip_modifiers(type_text or "")
    text = re.sub(r"\bNullable<(.+)>", r"\1", text)
    text = text.replace("&", "")
    text = re.sub(r"\b(?:[A-Za-z_]\w*\.)+(?=[A-Za-z_])", "", text)
    text = re.sub(r"\b[A-Za-z_]\w*\b", lambda m: ALIASES.get(m.group(0), m.group(0)), text)
    text = re.sub(r"`\d+", "", text)
    return re.sub(r"\s+", "", text)


class Listing:
    """Types read by the kit's reader (members records), indexed for lookups by any dotted suffix of a full name."""

    def __init__(self, records):
        self.types = {}
        self.by_suffix = {}
        for record in records:
            if "type" not in record:
                continue
            name = record["type"]
            self.types.setdefault(name, record)
            parts = name.split(".")
            for i in range(len(parts)):
                self.by_suffix.setdefault(".".join(parts[i:]), []).append(name)

    def resolve(self, name, usings=()):
        """Full names matching a written type name; several usings narrow a bare name to the namespaces in scope."""
        bare = name.split("<")[0].strip()
        if bare in self.types:
            return [bare]
        candidates = sorted(set(self.by_suffix.get(bare, [])))
        if len(candidates) > 1 and usings:
            narrowed = [c for c in candidates if c[: -len(bare) - 1] in usings or c[: -len(bare) - 1].rsplit(".", 1)[0] in usings]
            if narrowed:
                return narrowed
        return candidates

    def chain(self, full_name):
        """The type and its base types, as far as the listing holds them."""
        out = []
        seen = set()
        current = full_name
        while current and current not in seen and current in self.types:
            seen.add(current)
            out.append(current)
            current = (self.types[current].get("base") or "").split("<")[0]
            if current in STOP_TYPES:
                break
        return out

    def fields(self, full_name, name):
        for owner in self.chain(full_name):
            found = [f for f in self.types[owner]["fields"] if f["name"] == name]
            if found:
                return owner, found
        return None, []

    def methods(self, full_name, name):
        """Every method of the name along the chain, with its owner."""
        out = []
        for owner in self.chain(full_name):
            out.extend((owner, m) for m in self.types[owner]["methods"] if m["name"] == name)
        return out

    def properties(self, full_name, name):
        for owner in self.chain(full_name):
            found = [p for p in self.types[owner]["properties"] if p["name"] == name]
            if found:
                return owner, found
        return None, []


@dataclass
class Finding:
    file: str
    line: int
    source: str
    label: str
    status: str      # ok, inherited, ambiguous, note, type-missing (not read, so not checked); missing, overload, no-getter, no-setter, not-a-property, injection (fail)
    detail: str = ""

    @property
    def fails(self):
        return self.status in ("missing", "overload", "no-getter", "no-setter", "not-a-property", "injection")


def _arguments_match(written, read):
    return len(written) == len(read) and all(w == "?" or normalise(w) == normalise(r) for w, r in zip(written, read))


def _check_member(listing, target, full_name):
    """(status, detail) for the member on one resolved type."""
    kind = target.member_kind
    if kind in ("ctor", "cctor"):
        name = ".cctor" if kind == "cctor" else ".ctor"
        found = [(o, m) for o, m in listing.methods(full_name, name) if o == full_name]
        if not found:
            return "missing", "no constructor"
        if target.arguments is not None and not any(_arguments_match(target.arguments, m["parameters"]) for _, m in found):
            return "overload", "constructors take " + "; ".join("(" + ", ".join(m["parameters"]) + ")" for _, m in found)
        return "ok", ""
    if kind == "field":
        owner, found = listing.fields(full_name, target.member)
        if not found:
            return "missing", ""
        return ("ok" if owner == full_name else "inherited"), ("" if owner == full_name else f"declared on {owner}")
    if kind in ("property", "getter", "setter"):
        owner, found = listing.properties(full_name, target.member)
        if not found:
            if listing.methods(full_name, target.member) or listing.fields(full_name, target.member)[1]:
                return "not-a-property", "a method or field of that name exists, not a property"
            return "missing", ""
        prop = found[0]
        if kind == "getter" and not prop["hasGetter"]:
            return "no-getter", ""
        if kind == "setter" and not prop["hasSetter"]:
            return "no-setter", ""
        return ("ok" if owner == full_name else "inherited"), ("" if owner == full_name else f"declared on {owner}")
    found = listing.methods(full_name, target.member)
    if not found:
        owner, fields = listing.fields(full_name, target.member)
        props = listing.properties(full_name, target.member)[1]
        if fields or props:
            return "missing", "a " + ("field" if fields else "property") + " of that name exists, not a method"
        return "missing", ""
    if target.arguments is not None and not any(_arguments_match(target.arguments, m["parameters"]) for _, m in found):
        return "overload", "overloads take " + "; ".join("(" + ", ".join(m["parameters"]) + ")" for _, m in found)
    declared_here = [m for o, m in found if o == full_name]
    if target.source == "HarmonyPatch":
        # Harmony resolves an attribute's target on the named type alone, so these are worth a look; the wording stays a note
        # because that is read from Harmony's documented behaviour, not from a run.
        if not declared_here:
            return "note", f"declared on {found[0][0]}, not on the patched type: Harmony looks on the named type"
        if target.arguments is None and len(declared_here) > 1:
            return "note", f"{len(declared_here)} overloads and none named: Harmony cannot choose"
    return ("ok" if declared_here else "inherited"), ("" if declared_here else f"declared on {found[0][0]}")


def check_targets(scan, listing):
    """A Finding per target and per injected parameter; ok ones included, so counts can be shown."""
    findings = []
    for target in scan.targets:
        usings = scan.usings.get(target.file, set())
        names = listing.resolve(target.type_name, usings)
        if not names:
            findings.append(Finding(target.file, target.line, target.source, target.label, "type-missing",
                                    f"no type named {target.type_name} in the assemblies read"))
            continue
        results = [(n, *_check_member(listing, target, n)) for n in names]
        passing = [r for r in results if r[1] in ("ok", "inherited", "note")]
        if passing:
            name, status, detail = passing[0]
            if len(names) > 1:
                findings.append(Finding(target.file, target.line, target.source, target.label, "ambiguous",
                                        f"{len(names)} types match ({', '.join(names)}); found on {name}"))
            else:
                findings.append(Finding(target.file, target.line, target.source, target.label, status, detail))
        else:
            name, status, detail = results[0]
            findings.append(Finding(target.file, target.line, target.source, target.label, status, (f"on {name}: " if len(names) > 1 else "") + detail))
    for injection in scan.injections:
        findings.extend(_check_injection(scan, listing, injection))
    return findings


def _check_injection(scan, listing, injection):
    target = injection.target
    usings = scan.usings.get(injection.file, set())
    names = listing.resolve(target.type_name, usings)
    if not names:
        return []   # the target's own finding says the type is missing
    full_name = names[0]
    label = f"{target.label} {injection.name}"
    declared = normalise(injection.declared_type)
    if injection.name == "__instance":
        chain = [normalise(n) for n in listing.chain(full_name)]
        if declared in chain or declared == "Object":
            return [Finding(injection.file, injection.line, "HarmonyPatch", label, "ok")]
        return [Finding(injection.file, injection.line, "HarmonyPatch", label, "injection",
                        f"__instance is declared as {injection.declared_type}, but the patched type is {full_name}")]
    if injection.name.startswith("___"):
        owner, fields = listing.fields(full_name, injection.name[3:])
        if not fields:
            return [Finding(injection.file, injection.line, "HarmonyPatch", label, "injection",
                            f"{full_name} has no field named {injection.name[3:]}")]
        return [_compare_types(listing, injection, label, declared, fields[0]["type"], "the field")]
    if injection.name == "__result":
        expected = _return_type(listing, target, full_name)
        if expected is None:
            return [Finding(injection.file, injection.line, "HarmonyPatch", label, "note", "the original's return type could not be read")]
        if normalise(expected) == "Void":
            return [Finding(injection.file, injection.line, "HarmonyPatch", label, "injection", "the original returns nothing, so there is no __result")]
        return [_compare_types(listing, injection, label, declared, expected, "the original returns")]
    return []


def _return_type(listing, target, full_name):
    if target.member_kind in ("getter", "setter", "property"):
        _, props = listing.properties(full_name, target.member)
        return props[0]["type"] if props else None
    if target.member_kind in ("ctor", "cctor"):
        return "System.Void"
    found = listing.methods(full_name, target.member)
    if target.arguments is not None:
        found = [(o, m) for o, m in found if _arguments_match(target.arguments, m["parameters"])]
    return found[0][1]["returns"] if found else None


def _compare_types(listing, injection, label, declared, actual, what):
    read = normalise(actual)
    if declared == read or declared == "Object":
        return Finding(injection.file, injection.line, "HarmonyPatch", label, "ok")
    if declared in PRIMITIVES or read in PRIMITIVES:
        return Finding(injection.file, injection.line, "HarmonyPatch", label, "injection",
                       f"{injection.name} is declared as {injection.declared_type}, but {what} {actual}")
    actual_names = listing.resolve(actual.split("<")[0])
    if actual_names and declared in {normalise(n) for n in listing.chain(actual_names[0])}:
        return Finding(injection.file, injection.line, "HarmonyPatch", label, "ok")
    return Finding(injection.file, injection.line, "HarmonyPatch", label, "note",
                   f"{injection.name} is declared as {injection.declared_type} and {what} {actual}; not the same name, and whether one is assignable to the other could not be read")
