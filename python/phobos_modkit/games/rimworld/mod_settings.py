"""A RimWorld mod's settings read from its C# source and its language files, for doc-tables' `mod-settings` kind (1.108.0).

Format facts, summarised in our own words from the 1.7 game code (Verse.ModSettings, Verse.Scribe_Values.Look, Verse.Translator
and Verse.Listing_Standard, read November 2026):

- A mod's settings are a `ModSettings` subclass. Its `ExposeData` saves each value with `Scribe_Values.Look(ref field, "key",
  default)`; a key missing on load takes that default, or the type's own default when none is named (as rimworld-settings
  explains). `Scribe_Collections.Look` saves a list, written even when empty. A settings class may hand on to another's
  `ExposeData`, which then writes into the same file.
- The settings window is drawn by the mod's own code, so there is no format to read, only a habit almost every mod follows: a
  drawing call whose first argument is a translated label (`"Key".Translate()`) and which names the setting's field among its
  other arguments (`listing.CheckboxLabeled("Key".Translate(), ref settings.field, "TipKey".Translate())`, or a mod's own helper
  shaped the same way). The label is the key's text in the mod's `Languages/<language>/Keyed/*.xml`; a translated argument after
  the field is its tooltip.
- **Sections** are calls named in the `sectionCalls` option (default `Section`) with a translated first argument. **Pages** are
  calls that pass a translated label beside a drawing method (`new SettingsPage("id", 10f, () => "Key".Translate(), DrawX)`), a
  number among their arguments ordering them; a drawing method's calls to other drawing methods are followed.

Regular expressions over source text, not a C# compiler: what they cannot read is said, never guessed.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import re
import xml.etree.ElementTree as ET

from ...code.scan import blank, declarations, uncommented
from ...mod_settings import Setting, SettingsRead

NAMESPACE = re.compile(r"^\s*namespace\s+([\w.]+)\s*[;{]", re.MULTILINE)
SETTINGS_CLASS = re.compile(r"\bclass\s+(\w+)\s*:\s*(?:Verse\.)?ModSettings\b")
ENUM = re.compile(r"\benum\s+(\w+)\s*(?::\s*\w+\s*)?\{([^}]*)\}")
FIELD = re.compile(r"^\s*(?:\[[^\]]*\]\s*)*(?:public|internal|private|protected)(?:\s+(?:static|readonly|const))*\s+"
                   r"(?P<type>[A-Za-z_][\w.<>,?\[\] ]*?)\s+(?P<name>\w+)\s*(?:=\s*(?P<init>[^;]+?))?\s*;", re.MULTILINE)
EXPOSE = re.compile(r"\bvoid\s+ExposeData\s*\(\s*\)")
SCRIBE = re.compile(r"\bScribe_(?P<kind>Values|Collections|Defs)\s*\.\s*Look\s*(?:<[^>]*>)?\s*\(")
DELEGATE = re.compile(r"\b(\w+)\s*\.\s*ExposeData\s*\(\s*\)")
NUMERIC = re.compile(r"^-?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?[fFdDmM]?$")
NUMBER_TYPES = {"int", "float", "double", "long", "short", "byte", "uint", "decimal", "Int32", "Single", "Double"}
CONSTANT = re.compile(r"\b(?:const|static\s+readonly)\s+[\w.<>?]+\s+(?P<name>\w+)\s*=\s*(?P<value>[^;]+?)\s*;")
OWNER = re.compile(r"\b(?:class|struct|record)\s+(\w+)")
TRANSLATED = re.compile(r'"(?P<key>[A-Za-z_][\w.\-]*)"\s*\.\s*Translate\w*\s*\(')
TRANSLATED_ARG = re.compile(r'^(?:\w+\s*:\s*)?(?:\(\s*\)\s*=>\s*)?"(?P<key>[A-Za-z_][\w.\-]*)"\s*\.\s*Translate\w*\s*\(')
CHAINED = re.compile(r"(?:\s*\.\s*\w+\s*\(\s*\))*\s*")
REFERENCE = re.compile(r"^(?:(?:ref|out|in)\s+)?(?P<path>[A-Za-z_]\w*(?:\s*\.\s*[A-Za-z_]\w*)*)$")
LOCAL = re.compile(r"\b(?P<type>[A-Z]\w*)\s+(?P<names>\w+\s*=[^;]*?)\s*;")
OPTION_PREFIX = re.compile(r'"(?P<prefix>\w+)"\s*\+\s*\w+\s*\)')
OPTION_INTERPOLATED = re.compile(r'\$"(?P<prefix>\w+)\{\w+\}"')
CALL = re.compile(r"(?<![\w.])(?:(?P<qualifier>\w+)\s*\.\s*)?(?P<name>\w+)\s*\(")
NUMBER_ARG = re.compile(r"^-?\d+(?:\.\d+)?[fFdD]?$")
PLACEHOLDER = re.compile(r"\{[A-Za-z_0-9]+\}")
TAG = re.compile(r"</?(?:color|b|i|size)\b[^>]*>")
NOT_CALLS = {"if", "for", "foreach", "while", "switch", "using", "lock", "return", "new", "typeof", "sizeof", "nameof",
             "default", "catch", "when", "Translate", "Named", "ToString"}
DESCRIPTION_SUFFIXES = ("Desc", "Tip", "Tooltip", "Description")
EMPTY_LIST = "(empty)"


# ---- Reading the saved keys (the format the game reads) ----

def read_constants(sources):
    """Constants and static readonly fields with a literal value: {'Owner.Name': value, 'Name': value when unique}."""
    qualified, bare = {}, {}
    for text in sources.values():
        for found in CONSTANT.finditer(text):
            owners = OWNER.findall(text, 0, found.start())
            name, value = found.group("name"), found.group("value").strip()
            if owners:
                qualified[f"{owners[-1]}.{name}"] = value
            bare.setdefault(name, set()).add(value)
    constants = dict(qualified)
    constants.update({name: values.pop() for name, values in bare.items() if len(values) == 1})
    return constants


def _closing(text, start, opener="(", closer=")"):
    """The index of the partner of the bracket at start in blanked text, or -1."""
    depth = 0
    for index in range(start, len(text)):
        if text[index] == opener:
            depth += 1
        elif text[index] == closer:
            depth -= 1
            if depth == 0:
                return index
    return -1


def _arguments(code, plain, start):
    """[(start, text)] of the call's top-level arguments, the call's "(" at start; split in blanked code, read from plain."""
    end = _closing(code, start)
    if end < 0:
        return [], start
    parts, depth, begin = [], 0, start + 1
    for index in range(start + 1, end):
        char = code[index]
        if char in "([{":
            depth += 1
        elif char in ")]}":
            depth -= 1
        elif char == "," and depth == 0:
            parts.append((begin, plain[begin:index].strip()))
            begin = index + 1
    if plain[begin:end].strip():
        parts.append((begin, plain[begin:end].strip()))
    return parts, end


def translated(arg):
    """(key, the text of Translate's own arguments) when the whole argument is one translated literal (a named argument, a
    `() =>` lambda and calls such as `.ToString()` after it allowed), else None."""
    found = TRANSLATED_ARG.match(arg)
    if not found:
        return None
    code = blank(arg)
    close = _closing(code, found.end() - 1)
    if close < 0 or not CHAINED.fullmatch(code[close + 1:]):
        return None
    return found.group("key"), arg[found.end():close]


def _tip(args):
    return next((t[0] for t in map(translated, args) if t), "")


def _block(code, start):
    """(start, end) of the first {...} at or after start in blanked code, or None."""
    at = code.find("{", start)
    if at < 0:
        return None
    end = _closing(code, at, "{", "}")
    return (at + 1, end) if end > 0 else None


@dataclass
class SavedKey:
    key: str
    field: str
    kind: str                      # Values, Collections or Defs
    default: str                   # what a missing key loads as, written the way RimWorld writes it
    initial: str = None            # the field's starting value, when it has one
    type: str = ""
    path: str = ""
    line: int = 0


@dataclass
class SettingsClass:
    name: str
    namespace: str
    path: str
    fields: dict = field(default_factory=dict)        # name -> (type, initialiser or None)
    keys: list = field(default_factory=list)          # SavedKey, in ExposeData order
    delegates: list = field(default_factory=list)     # field names whose ExposeData this class calls

    @property
    def full_name(self):
        return f"{self.namespace}.{self.name}" if self.namespace else self.name


def written(literal, enums, constants=None):
    """A C# literal as RimWorld writes the value: True/False, 0.5 not 0.5f, an enum member's name, a string's text."""
    text = literal.strip()
    constants = constants or {}
    for _ in range(4):          # a constant may be defined as another constant, and named with its namespace
        parts = text.split(".")
        if not re.fullmatch(r"[A-Za-z_][\w.]*", text) or (len(parts) > 1 and parts[-2] in enums):
            break
        # Type.Name, or a bare Name; never the bare tail of a dotted name, which could be another type's member
        known = next((".".join(parts[i:]) for i in range(len(parts)) if len(parts) - i >= min(2, len(parts))
                      and ".".join(parts[i:]) in constants), None)
        if known is None:
            break
        text = constants[known].strip()
    if text in ("true", "false"):
        return text.capitalize()
    if NUMERIC.match(text):
        text = text.rstrip("fFdDmM")
        return text[:-2] if text.endswith(".0") else text
    if text.startswith('"') and text.endswith('"'):
        return text[1:-1]
    if text in ("null", "default"):
        return ""
    if re.fullmatch(r"[A-Za-z_]\w*(\.\w+)+", text) and text.split(".")[-2] in enums:
        return text.rsplit(".", 1)[1]
    return text


def implicit_default(type_name, enums):
    """What a missing key loads as when Scribe_Values.Look names no default: the type's default value."""
    bare = type_name.strip().rstrip("?")
    if bare == "bool":
        return "False"
    if bare in NUMBER_TYPES:
        return "0"
    if bare in enums and enums[bare]:
        return enums[bare][0]
    return ""


def read_enums(sources):
    """Every enum's members in order, by simple name (the first member is its default)."""
    enums = {}
    for text in sources.values():
        for found in ENUM.finditer(text):
            members = [re.sub(r"\[[^\]]*\]", "", m.split("=")[0]).strip() for m in found.group(2).split(",")]
            enums.setdefault(found.group(1), [m for m in members if m])
    return enums


def read_settings_classes(sources, enums=None):
    """Every ModSettings subclass in {path: comment-free text}, with its fields and the keys its ExposeData saves."""
    enums = read_enums(sources) if enums is None else enums
    every_constant = read_constants(sources)
    classes = {}
    for path, text in sorted(sources.items()):
        code = blank(text)
        namespace = NAMESPACE.search(text)
        for found in SETTINGS_CLASS.finditer(code):
            span = _block(code, found.end())
            if span is None:
                continue
            body = text[span[0]:span[1]]
            cls = SettingsClass(found.group(1), namespace.group(1) if namespace else "", path)
            constants = dict(every_constant)
            constants.update({c.group("name"): c.group("value").strip() for c in CONSTANT.finditer(body)})
            for f in FIELD.finditer(body):
                cls.fields[f.group("name")] = (f.group("type").strip(), f.group("init"))
            expose = EXPOSE.search(code, span[0], span[1])
            if expose:
                inner = _block(code, expose.end())
                if inner:
                    for d in DELEGATE.finditer(code, inner[0], inner[1]):
                        if d.group(1) not in ("base", "this"):
                            cls.delegates.append(d.group(1))
                    for call in SCRIBE.finditer(code, inner[0], inner[1]):
                        parts = [p for _, p in _arguments(code, text, call.end() - 1)[0]]
                        if len(parts) < 2 or not parts[0].startswith("ref ") or not parts[1].startswith('"'):
                            continue
                        field_name = parts[0][4:].strip().split(".")[-1]
                        type_name, init = cls.fields.get(field_name, ("", None))
                        kind = call.group("kind")
                        if kind == "Values":
                            default = written(parts[2], enums, constants) if len(parts) > 2 else implicit_default(type_name, enums)
                        else:
                            default = EMPTY_LIST if kind == "Collections" else ""
                        initial = None
                        if kind == "Values" and init is not None and not init.strip().startswith("new"):
                            initial = written(init, enums, constants)
                        elif kind == "Values" and init is None and type_name:
                            initial = implicit_default(type_name, enums)
                        cls.keys.append(SavedKey(parts[1].strip('"'), field_name, kind, default, initial, type_name, path,
                                                 text.count("\n", 0, call.start()) + 1))
            classes[cls.full_name] = cls
    return classes


# ---- Reading the window (a habit, not a format) ----

@dataclass
class Event:
    position: tuple                # (path, offset)
    kind: str                      # row, section or call
    label_key: str = ""
    owner: object = None           # row: (class, SavedKey); call: the method it calls
    tip_key: str = ""
    option_prefixes: list = field(default_factory=list)
    weak: bool = False             # row: the field is named only inside the label's own arguments (a label above a slider)


@dataclass
class Method:
    path: str
    name: str
    owner: str                     # the enclosing type's full name
    start: int                     # lines
    end: int
    span: tuple = (0, 0)           # offsets of its text
    events: list = field(default_factory=list)

    @property
    def owner_short(self):
        return self.owner.rsplit(".", 1)[-1]


def keyed_texts(folder, language="English"):
    """{key: text} from every Keyed language file of the language under the mod's folder; the first file (by path) wins."""
    texts = {}
    for file in sorted(Path(folder).glob(f"**/Languages/{language}/Keyed/*.xml")):
        try:
            root = ET.parse(file).getroot()
        except (ET.ParseError, OSError):
            continue
        for element in root:
            if isinstance(element.tag, str) and element.text and element.text.strip():
                texts.setdefault(element.tag, element.text.strip())
    return texts


def shown_text(text):
    """A language file's text as a reader sees it in a table: placeholders as "...", markup and line breaks gone."""
    text = TAG.sub("", text.replace("\\n", " "))
    return " ".join(PLACEHOLDER.sub("...", text).split())


def _lines(text):
    starts = [0]
    for index, char in enumerate(text):
        if char == "\n":
            starts.append(index + 1)
    return starts


def _enclosing_call(code, at):
    """(index of the "(" of the call whose argument list holds offset at, the call's name), or (-1, None)."""
    depth = 0
    for index in range(at - 1, -1, -1):
        char = code[index]
        if char in ")]}":
            depth += 1
        elif char in "([{":
            if depth == 0:
                if char != "(":
                    return -1, None
                name = re.search(r"(\w+)\s*(?:<[^<>()]*>)?\s*$", code[:index])
                return index, (name.group(1) if name and name.group(1) not in NOT_CALLS else None)
            depth -= 1
        elif char == ";" and depth == 0:
            return -1, None
    return -1, None


class Window:
    """What the settings window's code draws, read from the sources."""

    def __init__(self, sources, classes, enums, section_calls, rank=None):
        self.sources, self.classes, self.enums = sources, classes, enums
        self.rank = rank or {}     # pages group by the source pattern that named their file, then by their own number
        self.section_calls = set(section_calls)
        self.methods, self.pages = [], []      # pages: (order, appearance, label key, [Method])
        by_field = {}
        for cls in classes.values():
            for key in cls.keys:
                by_field.setdefault(key.field, []).append((cls, key))
        self.by_field = by_field
        self.ambiguous = set()
        self._read()

    def _method_at(self, path, line):
        inside = [m for m in self.methods if m.path == path and m.start <= line <= m.end]
        return min(inside, key=lambda m: m.end - m.start) if inside else None

    def _resolve_field(self, reference, method_text):
        """(class, SavedKey) the argument names, or None. Several classes with the field: the one a local of the drawing method
        is typed as, else the one a delegating field's type names, else the first (and the field is noted as ambiguous)."""
        parts = [p.strip() for p in reference.split(".")]
        found = self.by_field.get(parts[-1], [])
        if len(found) <= 1:
            return found[0] if found else None
        if len(parts) > 1:
            locals_ = {}
            for local in LOCAL.finditer(method_text):
                for name in re.findall(r"(\w+)\s*=", local.group("names")):
                    locals_[name] = local.group("type")
            typed = locals_.get(parts[-2])
            for cls, key in found:
                if typed and cls.name == typed:
                    return cls, key
            for owner in self.classes.values():
                type_name = owner.fields.get(parts[-2], ("", None))[0].split(".")[-1]
                for cls, key in found:
                    if type_name == cls.name:
                        return cls, key
        self.ambiguous.add(parts[-1])
        return found[0]

    def _read(self):
        texts = {path: (uncommented(text), blank(text)) for path, text in self.sources.items()}
        for path, text in self.sources.items():
            starts = _lines(text)
            for d in declarations(text):
                if d.kind in ("method", "constructor", "property"):
                    span = (starts[d.start - 1], starts[d.end] if d.end < len(starts) else len(text))
                    self.methods.append(Method(path, d.name, d.owner, d.start, d.end, span))
        registrations = []
        for path, (plain, code) in texts.items():
            starts = _lines(plain)
            for found in TRANSLATED.finditer(plain):
                if code[found.start()] != '"':      # inside another literal: blanked there
                    continue
                paren, name = _enclosing_call(code, found.start())
                if paren < 0 or name is None:
                    continue
                args, end = _arguments(code, plain, paren)
                index = sum(1 for at, _ in args if at <= found.start()) - 1
                if index < 0:
                    continue
                line = plain.count("\n", 0, found.start()) + 1
                method = self._method_at(path, line)
                if index == 0:
                    if not translated(args[0][1]):
                        continue
                    if name in self.section_calls:
                        if method:
                            method.events.append(Event((path, found.start()), "section", found.group("key")))
                        continue
                    if method:
                        event = self._row(args, plain[method.span[0]:method.span[1]], (path, found.start()), found.group("key"))
                        if event:
                            method.events.append(event)
                elif translated(args[index][1]):
                    refs = [REFERENCE.match(a) for i, (_, a) in enumerate(args) if i != index]
                    number = next((float(a.rstrip("fFdD")) for _, a in args if NUMBER_ARG.match(a)), None)
                    registrations.append((path, line, method, found.group("key"), [r.group("path") for r in refs if r],
                                          number, (paren, end)))
        for method in self.methods:     # a weak row counts only in a method that draws settings otherwise too
            if all(e.weak for e in method.events):
                method.events = []
        self._link_calls(texts)
        appearance = 0
        for path, line, method, label_key, refs, number, (begin, end) in registrations:
            targets = []
            for ref in refs:
                targets += self._find_methods(ref, method)
            first, last = self.sources[path].count("\n", 0, begin) + 1, self.sources[path].count("\n", 0, end) + 1
            targets += [m for m in self.methods if m.path == path and first <= m.start and m.end <= last
                        and m is not method and m.events]
            targets = [t for t in targets if t.events]
            if targets:
                self.pages.append((self.rank.get(path, 0), number if number is not None else float("inf"), appearance, label_key,
                                   targets))
                appearance += 1
        self.pages.sort(key=lambda p: p[:3])

    def _row(self, args, method_text, position, label_key):
        """The row a drawing call makes, or None: the first later argument naming a settings field, else (weakly) a field
        named inside the label's own arguments, as a label drawn above a bare slider names the value it shows."""
        for i, (_, arg) in enumerate(args[1:], 1):
            ref = REFERENCE.match(arg)
            target = self._resolve_field(ref.group("path"), method_text) if ref else None
            if target:
                tip = _tip(a for _, a in args[i + 1:])
                rest = " ".join(a for _, a in args[i + 1:])
                prefixes = [m.group("prefix") for m in OPTION_PREFIX.finditer(rest)]
                prefixes += [m.group("prefix") for m in OPTION_INTERPOLATED.finditer(rest)]
                return Event(position, "row", label_key, target, tip, prefixes)
        inside = translated(args[0][1])[1]
        for ref in re.finditer(r"(?<![\w.\"])([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)+)", inside):
            target = self._resolve_field(ref.group(1).rsplit(".", 1)[0] if ref.group(1).split(".")[-1] in ("ToString", "Named")
                                         else ref.group(1), method_text)
            if target:
                tip = _tip(a for _, a in args[1:])
                return Event(position, "row", label_key, target, tip, weak=True)
        return None

    def _find_methods(self, reference, caller):
        parts = [p.strip() for p in reference.split(".")]
        named = [m for m in self.methods if m.name == parts[-1]]
        if len(parts) > 1:
            return [m for m in named if m.owner_short == parts[-2]]
        same = [m for m in named if caller and m.owner == caller.owner]
        return same or (named if len(named) == 1 else [])

    def _link_calls(self, texts):
        """Each drawing method's calls to other drawing methods, as events, so a page's traversal follows them."""
        drawing = {m.name for m in self.methods if m.events}
        for method in self.methods:
            plain, code = texts[method.path]
            for call in CALL.finditer(code, method.span[0], method.span[1]):
                if call.group("name") not in drawing or call.group("name") == method.name:
                    continue
                reference = ".".join(p for p in (call.group("qualifier"), call.group("name")) if p)
                for target in self._find_methods(reference, method)[:1]:
                    method.events.append(Event((method.path, call.start()), "call", owner=target))
        for method in self.methods:
            method.events.sort(key=lambda e: e.position)

    def walk(self):
        """[(page label key, section label key, Event)] for every row, in the order the window draws them."""
        rows, seen = [], set()

        def visit(method, page, state, stack):
            if id(method) in stack:
                return
            for event in method.events:
                if event.kind == "section":
                    state["section"] = event.label_key
                elif event.kind == "call":
                    visit(event.owner, page, state, stack | {id(method)})
                elif id(event) not in seen:
                    seen.add(id(event))
                    rows.append((page, state["section"], event))

        for *_, label_key, targets in self.pages:
            state = {"section": ""}
            for target in targets:
                visit(target, label_key, state, frozenset())
        for method in sorted(self.methods, key=lambda m: (m.path, m.start)):
            if any(e.kind == "row" and id(e) not in seen for e in method.events):
                visit(method, "", {"section": ""}, frozenset())
        return rows


# ---- The adapter's answer ----

def _sources(root, patterns):
    """({path: text} of the C# files the patterns name, {path: the index of the first pattern that named it})."""
    found, rank = {}, {}
    for index, pattern in enumerate(patterns):
        for base in sorted(Path(root).glob(pattern)):
            files = [base] if base.is_file() else sorted(base.rglob("*.cs"))
            for file in files:
                parts = file.relative_to(root).parts
                if file.suffix == ".cs" and "obj" not in parts and "bin" not in parts:
                    name = file.relative_to(root).as_posix()
                    if name not in found:
                        found[name] = file.read_text(encoding="utf-8", errors="replace")
                        rank[name] = index
    return found, rank


def _shown_default(key, prefixes, texts, enums, unresolved):
    """The default as a player sees it: On or Off, an option's label, a number; the raw value when nothing better is known."""
    value = key.default
    bare_type = key.type.strip().rstrip("?").split(".")[-1]
    if key.kind == "Collections":
        return "none"
    if bare_type == "bool" and value in ("True", "False"):
        return "On" if value == "True" else "Off"
    if bare_type in enums and value in enums[bare_type]:
        for prefix in prefixes:
            if prefix + value in texts:
                return shown_text(texts[prefix + value])
        unresolved.append(f"`{key.key}`: no label found for its default option `{value}`")
        return f"`{value}`"
    if value and not NUMERIC.match(value) and re.fullmatch(r"[A-Za-z_][\w.]*", value) and bare_type != "string":
        unresolved.append(f"`{key.key}`: its default `{value}` is a name the reader could not follow to a value or a label")
        return f"`{value.rsplit('.', 1)[-1]}`"
    return value if value != "" else "empty"


def _same(a, b):
    if a is None or b is None or a.lower() == b.lower():
        return True
    try:
        return float(a) == float(b)
    except ValueError:
        return False


def mod_settings(root, options):
    """SettingsRead for the mod: `sources` (folders or glob patterns of its C# source, relative to root), `mod` (its folder, for
    the language files), `language` (default English), `sectionCalls` (default ["Section"])."""
    root = Path(root)
    raw, rank = _sources(root, options.get("sources") or ["."])
    sources = {path: uncommented(text) for path, text in raw.items()}
    enums = read_enums(sources)
    classes = read_settings_classes(sources, enums)
    texts = keyed_texts(root / options["mod"], options.get("language") or "English") if options.get("mod") else {}
    window = Window(sources, classes, enums, options.get("sectionCalls") or ["Section"], rank)
    read = SettingsRead()
    done = set()
    rows = window.walk()
    strong = {(e.owner[0].full_name, e.owner[1].key) for _, _, e in rows if not e.weak}
    for page_key, section_key, event in rows:
        cls, key = event.owner
        if event.weak and (cls.full_name, key.key) in strong:
            continue
        if (cls.full_name, key.key) in done:
            continue
        done.add((cls.full_name, key.key))
        label = texts.get(event.label_key)
        if label is None:
            read.unresolved.append(f"`{key.key}`: its label key `{event.label_key}` is in no language file")
        description_key = event.tip_key or next((event.label_key + s for s in DESCRIPTION_SUFFIXES
                                                 if event.label_key + s in texts), "")
        description = texts.get(description_key) if description_key else None
        if event.tip_key and description is None:
            read.unresolved.append(f"`{key.key}`: its tooltip key `{event.tip_key}` is in no language file")
        default = _shown_default(key, event.option_prefixes, texts, enums, read.unresolved)
        note = ""
        if key.kind == "Values" and not _same(key.initial, key.default):
            initial = _shown_default(SavedKey(key.key, key.field, key.kind, key.initial, None, key.type), event.option_prefixes,
                                     texts, enums, [])
            note = f"a new player starts at {initial}"
        read.settings.append(Setting(
            key.key, shown_text(label) if label else None, event.label_key,
            shown_text(description) if description else None, default,
            shown_text(texts.get(page_key, page_key)) if page_key else "",
            shown_text(texts.get(section_key, section_key)) if section_key else "",
            event.position[0], sources[event.position[0]].count("\n", 0, event.position[1]) + 1, True, note))
    for cls in sorted(classes.values(), key=lambda c: c.full_name):
        for key in cls.keys:
            if (cls.full_name, key.key) not in done:
                done.add((cls.full_name, key.key))
                read.settings.append(Setting(key.key, default=_shown_default(key, [], texts, enums, []), file=key.path,
                                             line=key.line, shown=False))
    for name in sorted(window.ambiguous):
        read.unresolved.append(f"`{name}`: a field of that name is in more than one settings class; the first was taken")
    return read
