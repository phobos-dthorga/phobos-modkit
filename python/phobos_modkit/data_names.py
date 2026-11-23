"""Names that cross between a game's data files and its code: a translation key the code asks for, a class a data file names, a
data thing another one names (D'thorga Companion's `docs/code-reading.md`, step 7). Game-free.

Which pieces of text count is a table of the game's adapter, `games/<game>/data-names.json`, never this module: its **things** (what
a name may stand for: things the connections graph already holds, such as a Def or a class, and things declared in files the table
names, such as a line of an English translation file) and its **rules** (where a name of one is written: a pattern over a file's
text, the first argument of a call, or what a call is made on). A rule either reads any name its place holds, and says so when no
thing of this repository has it (the game's own, another mod's, or a mistake), or is `known`: it reads only names that are things,
for places where most text is something else.

Every rule was counted on two games' repositories before it was kept (`connections jumps` repeats the count on any repository):
a rule that matched wrongly more than rarely was narrowed or left out. What the count found is in docs/connections.md.

It only reads. Comments are never read; a string joined to something else (`"Bottler." + what`) is a piece of a name, not one.
"""
from __future__ import annotations

from bisect import bisect_right
import json
from pathlib import Path
import re

from .connections import source_files


class DataNamesError(ValueError):
    """A table that cannot be used, or a request this reader refuses; the words say why."""


MAX_CANDIDATES = 8
#: How far a thing declared in a file is followed to its last line, at most.
MAX_THING_LINES = 60
_BLOCK_LIMIT = 200_000
#: How many lines after another name for a graph thing that thing may start (a Def's `Name` is on its opening line, its own
#: name a line or two below).
ALIAS_REACH = 12

# ---------------------------------------------------------------- a file's text, readied

_TOKENS = {
    "c": re.compile(r'//[^\n]*|/\*.*?\*/|"""[\s\S]*?"""|\$@"(?:[^"]|"")*"|@\$"(?:[^"]|"")*"|@"(?:[^"]|"")*"'
                    r'|\$"(?:\\.|[^"\\\n])*"|"(?:\\.|[^"\\\n])*"|\'(?:\\.|[^\'\\\n])+\'', re.S),
    "json": re.compile(r'"(?:\\.|[^"\\\n])*"'),
    "lua": re.compile(r'--\[\[.*?\]\]|--[^\n]*|"(?:\\.|[^"\\\n])*"|\'(?:\\.|[^\'\\\n])*\'', re.S),
    "python": re.compile(r'#[^\n]*|"""[\s\S]*?"""|\'\'\'[\s\S]*?\'\'\'|"(?:\\.|[^"\\\n])*"|\'(?:\\.|[^\'\\\n])*\'', re.S),
    "xml": re.compile(r"<!--.*?-->", re.S),
}
_FAMILY = {".cs": "c", ".json": "json", ".lua": "lua", ".py": "python", ".xml": "xml"}
_COMMENT_STARTS = {"c": ("//", "/*"), "lua": ("--",), "python": ("#",), "xml": ("<!--",), "json": ()}
#: What joins two pieces of text into one, by family: a string beside one is a piece of a name.
_JOINS = {"c": ("+",), "lua": ("..",), "python": ("+", "%"), "json": (), "xml": ()}
#: What tests one text against another: a string beside one is being asked about, not used.
_COMPARES = ("==", "!=", "~=")


class Prepared:
    """A file's text as the rules read it: `code` with comments blanked, `bare` with strings' insides blanked too (so brackets
    can be counted), every string's place, and where each line starts. Places hold: nothing is moved."""

    def __init__(self, text, suffix):
        self.family = _FAMILY.get(suffix.lower(), "")
        self.strings = []                          # (start, end, value start, value end, plain)
        code, bare = list(text), list(text)
        pattern = _TOKENS.get(self.family)
        for match in pattern.finditer(text) if pattern else ():
            token = match.group(0)
            if token.startswith(_COMMENT_STARTS[self.family]):
                for at in range(match.start(), match.end()):
                    if text[at] != "\n":
                        code[at] = bare[at] = " "
                continue
            if self.family == "c" and token.startswith("'"):
                inner = (match.start() + 1, match.end() - 1)
                plain = False
            else:
                lead = len(token) - len(token.lstrip("$@"))
                quote = 3 if token[lead:lead + 3] in ('"""', "'''") else 1
                inner = (match.start() + lead + quote, match.end() - quote)
                plain = "$" not in token[:lead]
            for at in range(inner[0], inner[1]):
                if text[at] != "\n":
                    bare[at] = " "
            self.strings.append((match.start(), match.end(), inner[0], inner[1], plain))
        self.text, self.code, self.bare = text, "".join(code), "".join(bare)
        self.starts = [0] + [at + 1 for at, char in enumerate(text) if char == "\n"]
        self._by_end = {s[1]: s for s in self.strings}

    def place(self, at):
        """(line from 1, column from 0) of a place in the text."""
        line = bisect_right(self.starts, at)
        return line, at - self.starts[line - 1]

    def line_before(self, at):
        """The code of the line a place is on, up to it."""
        line = bisect_right(self.starts, at)
        return self.code[self.starts[line - 1]:at]

    def string_ending(self, end):
        return self._by_end.get(end)

    def joined(self, start, end):
        """Whether a string (or a bracketed group) stands beside something that joins it to more text, or tests it against some."""
        joins = _JOINS.get(self.family, ()) + _COMPARES
        before = self.bare[max(0, start - 12):start].rstrip()
        after = self.bare[end:end + 12].lstrip()
        return any(before.endswith(j) or after.startswith(j) for j in joins)

    def whole_strings(self, start, end):
        """The plain strings between two places that are names by themselves: not joined to or tested against anything, and not
        inside a call, an index or a list within that span. A bracket that only groups is looked into, unless the group itself is
        joined or tested (`"Upkeep." + (on ? "on" : "off")`)."""
        found, stack = [], []
        strings = [s for s in self.strings if s[0] >= start and s[1] <= end]
        at, pending = start, iter(strings)
        nxt = next(pending, None)
        while at < end:
            if nxt and at == nxt[0]:
                if nxt[4] and not any(stack) and not self.joined(nxt[0], nxt[1]):
                    found.append(nxt)
                at = nxt[1]
                nxt = next(pending, None)
                continue
            char = self.bare[at]
            if char == "(":
                before = self.bare[max(0, at - 40):at].rstrip()
                call = bool(before) and (before[-1].isalnum() or before[-1] in "_>]")
                if not call:
                    close = self.closing(at + 1)
                    call = close is None or self.joined(at, close + 1)
                stack.append(call)
            elif char in "[{":
                stack.append(True)
            elif char in ")]}" and stack:
                stack.pop()
            at += 1
        return found

    def closing(self, at, opener="(", closer=")"):
        """Where the bracket opened just before `at` closes, or None."""
        depth = 1
        for index in range(at, min(len(self.bare), at + _BLOCK_LIMIT)):
            char = self.bare[index]
            if char == opener:
                depth += 1
            elif char == closer:
                depth -= 1
                if depth == 0:
                    return index
        return None

    def first_argument(self, at):
        """Where the first argument of a call ends, from just inside its bracket: its comma, or the call's own closing bracket."""
        depth = 0
        for index in range(at, min(len(self.bare), at + 4000)):
            char = self.bare[index]
            if char in "([{":
                depth += 1
            elif char in ")]}":
                if depth == 0:
                    return index
                depth -= 1
            elif char == "," and depth == 0:
                return index
        return None

    def opening_back(self, at):
        """Where the bracket closed at `at` opened, or None."""
        depth = 0
        for index in range(at, max(-1, at - 4000), -1):
            char = self.bare[index]
            if char == ")":
                depth += 1
            elif char == "(":
                depth -= 1
                if depth == 0:
                    return index
        return None


# ---------------------------------------------------------------- the table

def _glob(pattern):
    """A path pattern as a regular expression: `**/` any folders, `*` anything but a slash."""
    out, at = "", 0
    while at < len(pattern):
        if pattern.startswith("**/", at):
            out += "(?:.*/)?"
            at += 3
        elif pattern.startswith("**", at):
            out += ".*"
            at += 2
        elif pattern[at] == "*":
            out += "[^/]*"
            at += 1
        else:
            out += re.escape(pattern[at])
            at += 1
    return re.compile(f"^{out}$")


def _compiled(owner, key, flags=0):
    value = owner.get(key)
    if value is None:
        return None
    try:
        return re.compile(value, flags)
    except re.error as error:
        raise DataNamesError(f"{owner.get('id', '?')}: its {key} is not a pattern ({error}).") from None


class Thing:
    """One kind of thing a name may stand for."""

    def __init__(self, raw):
        self.id = raw.get("id") or ""
        self.kind = raw.get("kind") or self.id
        self.graph = raw.get("graph")
        self.files = [_glob(g) for g in raw.get("files", [])]
        self.suffixes = tuple(sorted({Path(g).suffix.lower() for g in raw.get("files", []) if Path(g).suffix}))
        self.declared = _compiled(raw, "declared", re.M)
        self.skip = set(raw.get("except", []))
        self.ends = raw.get("ends")
        self.block = raw.get("block")
        self.scope = _compiled(raw, "scope")
        self.namespaces = list(raw.get("namespaces", []))
        self.alias_of = raw.get("aliasOf")
        if not re.fullmatch(r"[a-z][a-z0-9-]*", self.id):
            raise DataNamesError(f"{self.id!r} is not a thing's id: small letters, digits and hyphens.")
        if bool(self.graph) == bool(self.files):
            raise DataNamesError(f"{self.id}: a thing is either the graph's or declared in files, one of the two.")
        if self.files and (self.declared is None or "name" not in self.declared.groupindex):
            raise DataNamesError(f"{self.id}: a thing declared in files needs a `declared` pattern with a `name` group.")
        if self.alias_of and not self.files:
            raise DataNamesError(f"{self.id}: another name for a graph thing is declared in files.")

    def holds(self, relative):
        return any(g.match(relative) for g in self.files)


class Rule:
    """One place a name is written."""

    def __init__(self, raw, things):
        self.id = raw.get("id") or ""
        self.words = raw.get("words") or self.id
        self.suffixes = tuple(s.lower() for s in raw.get("in", []))
        self.files = [_glob(g) for g in raw.get("files", [])]
        self.not_files = [_glob(g) for g in raw.get("notFiles", [])]
        self.match = _compiled(raw, "match")
        self.argument_of = _compiled(raw, "argumentOf")
        self.receiver_of = _compiled(raw, "receiverOf")
        self.inside = _compiled(raw, "inside")
        self.names = list(raw.get("names", []))
        self.known = bool(raw.get("known"))
        self.min_length = int(raw.get("minLength", 1))
        self.unless_before = [re.compile(p) for p in raw.get("unlessBefore", [])]
        self.scope = _compiled(raw, "scope")
        self.their = bool(raw.get("their"))
        self.graph = raw.get("graph", True)
        if not self.id or not self.suffixes:
            raise DataNamesError(f"{self.id or 'a rule'}: a rule needs an id and the file suffixes it reads (`in`).")
        if sum(x is not None for x in (self.match, self.argument_of, self.receiver_of)) != 1:
            raise DataNamesError(f"{self.id}: a rule has one of `match`, `argumentOf` and `receiverOf`.")
        if self.match is not None and "name" not in self.match.groupindex:
            raise DataNamesError(f"{self.id}: its `match` needs a `name` group.")
        unknown = [n for n in self.names if n not in things]
        if unknown or not self.names:
            raise DataNamesError(f"{self.id}: it names {', '.join(unknown) or 'nothing'}, which the table's things do not hold.")

    def reads(self, relative):
        if not relative.lower().endswith(self.suffixes):
            return False
        if self.files and not any(g.match(relative) for g in self.files):
            return False
        return not any(g.match(relative) for g in self.not_files)


class Table:
    def __init__(self, raw, source=""):
        self.source = source
        self.ids = [str(i) for i in raw.get("ids", [])]
        self.things = {}
        for item in raw.get("things", []):
            thing = Thing(item)
            self.things[thing.id] = thing
        self.rules = [Rule(item, self.things) for item in raw.get("rules", [])]
        if len({r.id for r in self.rules}) != len(self.rules):
            raise DataNamesError("Two rules share an id.")
        self.prose = [_glob(g) for g in raw.get("prose", [])]
        self.sha = json.dumps(raw, sort_keys=True)

    def is_prose(self, relative):
        """Whether a file holds words for people (a translation file): only its own declarations and the rules' names are read
        there, never every word that happens to be some thing's name."""
        return any(g.match(relative) for g in self.prose)

    def suffixes(self):
        found = set()
        for rule in self.rules:
            found.update(rule.suffixes)
        return tuple(sorted(found))

    def thing_files(self, root):
        """Every file a thing of this table is declared in, as (thing, relative, path)."""
        found = []
        for thing in self.things.values():
            if not thing.files:
                continue
            for relative, path in source_files(root, thing.suffixes or (".xml", ".json")):
                if thing.holds(relative):
                    found.append((thing, relative, path))
        return found


def _plain(text):
    return "".join(ch for ch in str(text or "").lower() if ch.isalnum())


def table_for(game, folder=None):
    """The game's table, or None when no game is named or it has none yet. `folder` is where the games' folders are."""
    if not game:
        return None
    folder = Path(folder) if folder else Path(__file__).parent / "games"
    for path in sorted(folder.glob("*/data-names.json")):
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            raise DataNamesError(f"{path.parent.name}'s data-names.json could not be read ({error}).") from None
        if _plain(game) in {_plain(i) for i in raw.get("ids", [])} | {_plain(path.parent.name)}:
            return Table(raw, path.parent.name)
    return None


def tables(folder=None):
    """The games that have a table, by their folders' names."""
    folder = Path(folder) if folder else Path(__file__).parent / "games"
    return sorted(path.parent.name for path in folder.glob("*/data-names.json"))


def read_suffixes(folder=None):
    """Every kind of file some game's table reads names in, by suffix: a file of one that no rule of the game named reads has
    no names, which is an answer, not a refusal."""
    found = set()
    for game in tables(folder):
        table = table_for(game, folder)
        found.update(table.suffixes())
        for thing in table.things.values():
            found.update(thing.suffixes)
    return found


# ---------------------------------------------------------------- the things

def node_id(thing, name, scope=None):
    """A file-declared thing's id in the connections graph."""
    return f"data:{thing.id}/{scope}/{name}" if scope else f"data:{thing.id}/{name}"


def declared_in(table, text, relative, aliases=False):
    """Every thing of the table a file's text declares, each `{id, name, kind, thing, file, line, end, scope}`. Other names for
    graph things (`aliasOf`) are things of the graph, not of their own, and are given only when asked for."""
    found = []
    for thing in table.things.values():
        if not thing.files or not thing.holds(relative) or bool(thing.alias_of) != aliases:
            continue
        scope = thing.scope.search(relative) if thing.scope else None
        scope = scope.group("scope") if scope else None
        starts = [0] + [at + 1 for at, char in enumerate(text) if char == "\n"]
        for match in thing.declared.finditer(text):
            name = match.group("name")
            if name in thing.skip:
                continue
            line = bisect_right(starts, match.start("name"))
            found.append({"id": node_id(thing, name, scope), "name": name, "kind": thing.kind, "thing": thing.id,
                          "file": relative, "line": line, "end": _last_line(thing, text, starts, match, name, line),
                          "scope": scope, "column": match.start("name") - starts[line - 1]})
    return found


def _last_line(thing, text, starts, match, name, line):
    """The last line of a thing declared at `match`: where its closing words are, or its enclosing braces close."""
    if thing.ends:
        at = text.find(thing.ends.replace("{name}", name), match.end())
        if at >= 0:
            return min(bisect_right(starts, at), line + MAX_THING_LINES - 1)
    if thing.block == "braces":
        depth = 0
        for at in range(match.start(), min(len(text), match.start() + 20_000)):
            if text[at] == "{":
                depth += 1
            elif text[at] == "}":
                if depth == 0:
                    return min(bisect_right(starts, at), line + MAX_THING_LINES - 1)
                depth -= 1
    return line


class Index:
    """Every thing a name may stand for, by the table's thing ids, then by name."""

    def __init__(self, table):
        self.table = table
        self.by = {thing: {} for thing in table.things}
        self.short = {thing: {} for thing in table.things}

    def add(self, thing_id, item, under=None):
        names = {under or item["name"]}
        full = item.get("full")
        if full:
            names.add(full)
            self.short[thing_id].setdefault(full.rsplit(".", 1)[-1], []).append(item)
        for name in names:
            self.by[thing_id].setdefault(name, []).append(item)

    def count(self, thing_id):
        return len({id(i) for items in self.by[thing_id].values() for i in items})

    def shared(self, thing_id):
        """How many names more than one thing of this kind has."""
        held, seen = {}, set()
        for items in self.by[thing_id].values():
            for item in items:
                if id(item) not in seen:
                    seen.add(id(item))
                    held[item["name"]] = held.get(item["name"], 0) + 1
        return sum(1 for number in held.values() if number > 1)

    def find(self, rule, name, kind=None, relative=None):
        """The things `name` may stand for under a rule, narrowed by the kind the place gives and by the file's own part of the
        repository where the table says things belong to one."""
        found = []
        for thing_id in rule.names:
            thing = self.table.things[thing_id]
            items = self.by[thing_id].get(name)
            if not items:
                for space in thing.namespaces:
                    items = self.by[thing_id].get(f"{space}.{name}")
                    if items:
                        break
            if not items and thing.graph and "." not in name:
                items = self.short[thing_id].get(name)
            for item in items or ():
                if kind and item.get("type") and not (item["type"] == kind or item["type"].endswith("." + kind)):
                    continue
                if item not in found:
                    found.append(item)
        if rule.scope and relative and len(found) > 1:
            scope = rule.scope.search(relative)
            own = [i for i in found if scope and i.get("scope") == scope.group("scope")]
            if own:
                found = own
        return found


def _graph_item(thing, node):
    """A graph node as a thing: a row of the store, or a node of a graph being built."""
    node_id_, name, kind, file, line, end = node
    item = {"id": node_id_, "name": name, "kind": kind, "thing": thing.id, "file": file, "line": line, "end": end or line}
    if node_id_.startswith("def:"):
        item["type"] = node_id_[4:].split("/", 1)[0]
    if node_id_.startswith("cs:"):
        item["full"] = node_id_[3:]
    return item


def index(table, root, nodes):
    """The table's things in a repository. `nodes` are this repository's graph things as (id, name, kind, language, file, line,
    end), from the store or from a graph being built."""
    found = Index(table)
    for thing in table.things.values():
        if not thing.graph:
            continue
        language, kinds = thing.graph.get("language"), set(thing.graph.get("kinds", []))
        for node_id_, name, kind, node_language, file, line, end in nodes:
            if node_language == language and file and (not kinds or kind in kinds):
                found.add(thing.id, _graph_item(thing, (node_id_, name, kind, file, line, end)))
    starts = {}                                   # another name stands for the graph thing that starts at or next after it
    for node in nodes:
        if node[4] and node[5]:
            starts.setdefault(node[4], []).append((node[5], node))
    for held in starts.values():
        held.sort(key=lambda pair: pair[0])
    for thing, relative, path in table.thing_files(root):
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for item in declared_in(table, text, relative, aliases=bool(thing.alias_of)):
            if item["thing"] != thing.id:
                continue
            if not thing.alias_of:
                found.add(thing.id, item)
                continue
            language, kinds = thing.alias_of.get("language"), set(thing.alias_of.get("kinds", []))
            for line, node in starts.get(relative, ()):
                if line >= item["line"] and node[3] == language and (not kinds or node[2] in kinds):
                    if line - item["line"] <= ALIAS_REACH:
                        found.add(thing.id, _graph_item(thing, (node[0], node[1], node[2], node[4], node[5], node[6])),
                                  under=item["name"])
                    break
    return found


def store_nodes(conn):
    """This repository's things from the connections store, as `index` takes them."""
    return conn.execute('SELECT id, name, kind, language, file, line, "end" FROM nodes WHERE external = 0 AND file IS NOT NULL '
                        "ORDER BY id").fetchall()


# ---------------------------------------------------------------- reading a file

def _spans(rule, ready):
    """Every place a rule reads in a file, as (start, end, kind, anchor): where a name is, the kind its place gives it, if any,
    and where the words that hold it begin (what stands before that on its line can rule it out)."""
    regions = [(0, len(ready.code))]
    if rule.inside is not None:
        regions = []
        for opener in rule.inside.finditer(ready.code):
            close = ready.closing(opener.end(), "{", "}")
            if close:
                regions.append((opener.end(), close))
    for start, end in regions:
        if rule.match is not None:
            for match in rule.match.finditer(ready.code, start, end):
                kind = match.group("type") if "type" in rule.match.groupindex else None
                yield match.start("name"), match.end("name"), kind, match.start()
        elif rule.argument_of is not None:
            for match in rule.argument_of.finditer(ready.code, start, end):
                stop = ready.first_argument(match.end())
                for string in ready.whole_strings(match.end(), stop) if stop else ():
                    yield string[2], string[3], None, string[0]
        else:
            for match in rule.receiver_of.finditer(ready.code, start, end):
                at = match.start() - 1
                while at >= 0 and ready.bare[at].isspace():
                    at -= 1
                if at < 0:
                    continue
                string = ready.string_ending(at + 1)
                if string is not None:
                    if string[4]:
                        yield string[2], string[3], None, string[0]
                elif ready.bare[at] == ")":
                    opened = ready.opening_back(at)
                    for inner in ready.whole_strings(opened + 1, at) if opened is not None else ():
                        yield inner[2], inner[3], None, inner[0]


def read(table, found, relative, text):
    """Every name in a file's text that a rule of the table reads: `{start, line, column, length, text, rule, words, things,
    outside, their}`. Rules are tried in the table's order at each place: a `known` rule adds the things it finds and lets later
    known rules add theirs; any other rule ends the search, with what it found or as a name of nothing here."""
    suffix = Path(relative).suffix
    rules = [rule for rule in table.rules if rule.reads(relative)]
    if not rules:
        return []
    ready = Prepared(text, suffix)
    places = {}
    for order, rule in enumerate(rules):
        for start, end, kind, anchor in _spans(rule, ready):
            name = ready.code[start:end]
            if len(name) < rule.min_length or not name.strip():
                continue
            if rule.unless_before and any(p.search(ready.line_before(anchor)) for p in rule.unless_before):
                continue
            places.setdefault((start, end), []).append((order, rule, kind))
    names = []
    for (start, end), claims in sorted(places.items()):
        name = ready.code[start:end]
        things, by, closed = [], None, False
        for _, rule, kind in sorted(claims, key=lambda c: c[0]):
            candidates = found.find(rule, name, kind, relative)
            if rule.known:
                if candidates:
                    things += [c for c in candidates if c not in things]
                    by = by or rule
                continue
            if not things:
                things, by = candidates, rule
            closed = True
            break
        if by is None or (not things and not closed):
            continue
        line, column = ready.place(start)
        names.append({"start": start, "line": line, "column": column, "length": end - start, "text": name, "rule": by.id,
                      "words": by.words, "known": by.known, "things": things, "outside": not things,
                      "kind": table.things[by.names[0]].kind,
                      "their": name if (by.their and not things) else None})
    return names


def as_names(read_names, relative):
    """What `read` found, in the shape `connections names` gives: one name each, with the things it may stand for."""
    found = []
    for item in read_names:
        things = item["things"]
        first = things[0] if things else None
        candidates = [{k: t[k] for k in ("id", "name", "kind", "file", "line", "end")} for t in things[:MAX_CANDIDATES]]
        found.append({
            "line": item["line"], "column": item["column"], "length": item["length"], "text": item["text"],
            "kind": first["kind"] if first else item["kind"], "display": first["name"] if first else item["text"],
            "id": None, "node": first["id"] if first else None, "exact": False,
            "rule": item["rule"], "ruleWords": item["words"], "outside": item["outside"], "their": item["their"],
            "here": bool(first) and len(things) == 1 and first["file"] == relative and first["line"] == item["line"],
            "declared": {"file": first["file"], "line": first["line"], "end": first["end"]} if first else {},
            "candidates": candidates, "more": max(0, len(things) - MAX_CANDIDATES)})
    return found


def declarations(table, relative, text):
    """The things a file itself declares, as names at their own places, so a viewer can go from one to what uses it."""
    return [{"line": item["line"], "column": item["column"], "length": len(item["name"]), "text": item["name"],
             "kind": item["kind"], "display": item["name"], "id": None, "node": item["id"], "exact": False, "rule": None,
             "ruleWords": None, "outside": False, "their": None, "here": True,
             "declared": {"file": item["file"], "line": item["line"], "end": item["end"]},
             "candidates": [{k: item[k] for k in ("id", "name", "kind", "file", "line", "end")}], "more": 0}
            for item in declared_in(table, text, relative)]


# ---------------------------------------------------------------- a whole repository

def references(table, found, root, progress=None):
    """Every name every rule reads in the repository, as (relative, name) pairs, a file at a time."""
    files = [(relative, path) for relative, path in source_files(root, table.suffixes())
             if any(rule.reads(relative) for rule in table.rules)]
    for position, (relative, path) in enumerate(files, 1):
        if progress and position % 200 == 1:
            progress("Reading names that cross between data and code", position, len(files))
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for item in read(table, found, relative, text):
            yield relative, item


def count(table, found, root, samples=12, progress=None):
    """What each rule reads in a repository: how many names, and how many stand for one thing, for several, or for nothing here,
    with some of each to look at. The count every rule passes before it is kept."""
    rows = {rule.id: {"id": rule.id, "words": rule.words, "in": list(rule.suffixes), "names": list(rule.names),
                      "known": rule.known, "matches": 0, "one": 0, "several": 0, "none": 0,
                      "samples": {"one": [], "several": [], "none": []}, "noneNames": {}}
            for rule in table.rules}
    for relative, item in references(table, found, root, progress):
        row = rows[item["rule"]]
        group = "none" if not item["things"] else ("one" if len(item["things"]) == 1 else "several")
        row["matches"] += 1
        row[group] += 1
        if group == "none":
            row["noneNames"][item["text"]] = row["noneNames"].get(item["text"], 0) + 1
        seen = row["samples"][group]
        # Spread the samples over the files, not the first file's first lines: one a file until there is room for no more.
        if len(seen) < samples and not any(s["file"] == relative for s in seen[-3:]):
            seen.append({"file": relative, "line": item["line"], "name": item["text"]})
    for row in rows.values():
        ranked = sorted(row.pop("noneNames").items(), key=lambda kv: (-kv[1], kv[0]))
        row["noneDistinct"] = len(ranked)
        row["noneTop"] = [{"name": name, "count": number} for name, number in ranked[:samples]]
    things = [{"id": thing.id, "kind": thing.kind, "from": "graph" if thing.graph else "files",
               "count": found.count(thing.id), "shared": found.shared(thing.id)} for thing in table.things.values()]
    return {"things": things, "rules": list(rows.values())}
