"""A repository's in-game test list, what the game has seen working, and the owner's verdicts, brought together.

Three inputs, each written by someone else:

- **The test list**: a Markdown file of tables whose first column is "#" and last column says what passes. The repository's
  `config/test-evidence.json` names it (`doc`), maps each row to the notes that stand as evidence for it (`rows`, with
  `prefixes` for keys built at run time), and may name the game whose adapter knows where the notes are (`game`).
- **Seen-in-play notes**: JSON lines a mod writes when a feature is first seen working in a session (`key`, `time`, `mod`,
  `version`, `detail`). A note says the code ran without an error, never that the result looked right.
- **Verdicts**: JSON lines the owner's clicks write (D'thorga Companion's Tests page): `row`, `verdict` (`passed`, `partial`,
  `failed` or `cleared`), `time`, an optional `note`, and an optional `via` (`companion`, the default, or `conversation`). Only a
  verdict passes or fails a row. A verdict the owner gives an agent in conversation comes in on the command line instead
  (`apply --verdict ROW:WORD:NOTE`), and is written the same way, saying so.

`apply` writes each new verdict into its row's last cell, and "seen working, awaiting the owner's word" for a row the notes flag
that has no verdict. It writes nothing else, and only inside the test list. Game-free: a game enters through the repository's file.

Since 1.19.0 (phobos-rimworld's seen-in-play checks, 18 Nov 2026) a note may also say what it was seen on (`on`), what kind of thing
that is (`kind`), which case of the feature (`variant`) and its figures (`values`), and the evidence map may narrow and judge a row's
evidence: parts (`{"parts": {name: [...]}}`), a case or a wildcard on the detail, expected figures (`expect`), rules on the order of
notes on one thing (`order`), keys shared by rows on purpose (`shared`), keys that need no row (`unrowed`) and how each mod is
written in the rows (`versionNames`, so a sighting older than its row is known). The owner's decisions on notes no row names come
from D'thorga Companion (`make-row` or `no-row`, per key). None of it passes a row: it only says a sighting is weaker than it looked.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from fnmatch import fnmatchcase
import json
from pathlib import Path
import re

CONFIG = Path("config") / "test-evidence.json"
VERDICTS = ("passed", "partial", "failed", "cleared")
# The owner's word on a note no row names (D'thorga Companion, 1.19.0).
DECISIONS = ("make-row", "no-row", "cleared")
# Where a verdict was given, and how the test list says so.
VIA = {"companion": "through D'thorga Companion", "conversation": "in conversation"}
_WORDS = {"passed": "Passed", "partial": "Passed in part", "failed": "Failed"}
SEEN_TEXT = "Seen working by the game"
_SEEN_MARK = re.compile(r"\s*\*\*Seen working by the game[^*]*awaiting the owner's word\.\*\*")
_PARTS_MARK = re.compile(r"Seen working by the game[^*]*?: (\d+) of \d+ parts")
# A part of a row passed is written in lower case ("Diagnose passed: the owner, 11 Nov 2026"), a whole row with a capital.
_STATUS = [("partial", re.compile(r"Passed in part")), ("partial", re.compile(r"\bpassed[:,] the owner")),
           ("passed", re.compile(r"\bPassed\b")),
           ("failed", re.compile(r"\*\*Failed\b")), ("seen", re.compile(re.escape(SEEN_TEXT)))]
# A verdict or seen sentence in a row's cell: left out when reading which versions the row was written for.
_STATUS_SENTENCE = re.compile(r"\*\*[^*]*(?:the owner|" + re.escape(SEEN_TEXT) + r")[^*]*\*\*")
_HEADING = re.compile(r"^(#{2,6})\s+(.*\S)\s*$")
_BOLD = re.compile(r"\*\*(.+?)\*\*")
_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
_CHECK = re.compile(r"^\s*(>=|<=|>|<|=)\s*(-?\d+(?:\.\d+)?)\s*$")
_RANGE = re.compile(r"^\s*(-?\d+(?:\.\d+)?)\s*\.\.\s*(-?\d+(?:\.\d+)?)\s*$")
_ITEM_FIELDS = {"key", "variant", "detail", "expect"}


class TestPassError(Exception):
    """A file the tool needs is missing or unreadable; the message says which and what to do."""


@dataclass
class Row:
    id: str
    section: str
    columns: list
    cells: list
    line: int                       # 0-based line in the test list

    @property
    def title(self):
        found = _BOLD.search(self.cells[1]) if len(self.cells) > 1 else None
        return found.group(1) if found else (self.cells[1] if len(self.cells) > 1 else "")

    @property
    def status(self):
        """open, partial, passed, failed or seen: the last marker in the last cell decides."""
        text = self.cells[-1] if self.cells else ""
        best, where = "open", -1
        for name, pattern in _STATUS:
            for match in pattern.finditer(text):
                if match.start() > where or (match.start() == where and name == "partial"):
                    best, where = name, match.start()
        return best


@dataclass
class Sighting:
    """A key's notes taken together: when first and last seen, how often, and the last one's mod, version and detail."""
    key: str
    first: str
    last: str
    count: int = 1
    mod: str = ""
    version: str = ""
    detail: str = ""


@dataclass
class Note:
    """One seen-in-play line. `on`, `kind`, `variant` and `values` are optional (1.19.0); older lines have none. A note read from a
    save's history (1.121.0) carries its game `tick`, which orders notes sharing one save's time, and `source` "save"."""
    key: str
    time: str
    mod: str = ""
    version: str = ""
    detail: str = ""
    on: str = ""
    kind: str = ""
    variant: str = ""
    values: dict = field(default_factory=dict)
    tick: int = None
    source: str = ""


@dataclass
class Verdict:
    row: str
    verdict: str
    time: str
    note: str = ""
    via: str = "companion"


@dataclass
class Decision:
    """The owner's word on a note no row names: make-row (a request for one) or no-row."""
    key: str
    decision: str
    time: str
    note: str = ""


@dataclass(frozen=True)
class Check:
    """An expected figure: its name, the test as written ("> 0", "0.9..1"), and the bounds it sets."""
    name: str
    text: str
    low: float | None = None
    high: float | None = None
    low_open: bool = False
    high_open: bool = False

    def holds(self, values):
        value = values.get(self.name) if isinstance(values, dict) else None
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return False
        if self.low is not None and (value <= self.low if self.low_open else value < self.low):
            return False
        if self.high is not None and (value >= self.high if self.high_open else value > self.high):
            return False
        return True

    @property
    def shown(self):
        return f"{self.name} {self.text}"


@dataclass(frozen=True)
class Item:
    """One piece of a row's evidence: a key, narrowed by a case and a wildcard on the detail, with the figures it should show."""
    key: str
    variant: str | None = None
    detail: str | None = None
    expect: tuple = ()

    @property
    def narrowed(self):
        return self.variant is not None or self.detail is not None

    def matches(self, note):
        return (note.key == self.key and (self.variant is None or note.variant == self.variant)
                and (self.detail is None or fnmatchcase(note.detail.lower(), self.detail.lower())))

    def meets(self, note):
        return all(check.holds(note.values) for check in self.expect)


@dataclass(frozen=True)
class Part:
    name: str
    items: tuple


@dataclass(frozen=True)
class OrderRule:
    """A note that must come before another on the same thing: before each `then`, a `first` since the last `then`. With `since`
    (1.154.0), notes from older builds than that version are left out: a rule a fix made true from that build on."""
    name: str
    row: str
    first: Item
    then: Item
    since: tuple = ()

    def counts(self, note):
        """Whether a note is from a build the rule holds for: any, without `since`; a note that names no version is kept."""
        if not self.since:
            return True
        version = version_tuple(note.version) if note.version else None
        return version is None or version >= self.since


@dataclass
class OrderProblem:
    rule: str
    row: str
    on: str
    kind: str
    time: str
    detail: str


@dataclass
class PartCheck:
    """What the notes say of one part. state: none; seen; expected (seen, with the figures the row expects); off (seen, but
    never with them); or stale (seen only on a version older than the row)."""
    name: str
    state: str
    good: list
    off: list
    stale: list
    expected: list


@dataclass
class RowCheck:
    parts: list
    versions: dict

    @property
    def seen_parts(self):
        return [p for p in self.parts if p.state in ("seen", "expected")]

    @property
    def good(self):
        return sorted({id(n): n for p in self.parts for n in p.good}.values(), key=lambda n: n.time)

    @property
    def kinds(self):
        return kinds_of(self.good)


@dataclass
class Evidence:
    rows: list
    seen: dict                      # key -> Sighting, over every note read
    verdicts: dict                  # row id -> latest Verdict (cleared ones removed)
    mapping: dict                   # row id -> [Part]
    prefixes: tuple
    unreadable: int = 0             # note, verdict or decision lines that could not be read
    unmapped: list = field(default_factory=list)   # keys seen that no row names, nor unrowed, nor decided no-row
    notes: list = field(default_factory=list)
    checks: dict = field(default_factory=dict)     # row id -> RowCheck
    order: list = field(default_factory=list)      # OrderProblem
    unchecked_order: int = 0        # notes an order rule names that say nothing of what they were seen on
    decisions: dict = field(default_factory=dict)  # key -> Decision
    unrowed: dict = field(default_factory=dict)    # key -> why it needs no row

    def keys(self, row_id):
        return list(dict.fromkeys(item.key for part in self.mapping.get(row_id, []) for item in part.items))

    def sightings(self, row_id):
        """The row's notes that count, by key: not older than the row, and with any figures it expects."""
        check = self.checks.get(row_id)
        return aggregate(check.good) if check else []

    def pending(self, row):
        """The sentence apply would add to this row now, or None."""
        verdict = self.verdicts.get(row.id)
        cell = row.cells[-1]
        if verdict is not None:
            text = verdict_text(verdict)
            return None if text in cell else text
        check = self.checks.get(row.id)
        if check is None or not check.seen_parts or row.status not in ("open", "partial", "seen"):
            return None
        if SEEN_TEXT not in cell or (len(check.parts) > 1 and _parts_marked(cell) < len(check.seen_parts)):
            return seen_text(self.sightings(row.id), check)
        return None

    def withdraws(self, row):
        """Whether apply takes back its own "seen working" sentence from this row (1.19.1): the row has no verdict, and no note read
        stands for it now (its notes are older than the row, miss its figures, or no longer fit its evidence). Never when no notes
        were read at all, so a missing or moved notes file takes nothing back."""
        if not self.notes or row.id in self.verdicts or not _SEEN_MARK.search(row.cells[-1] if row.cells else ""):
            return False
        check = self.checks.get(row.id)
        return check is None or not check.seen_parts


# ---- Reading ----

def load_config(root):
    path = Path(root) / CONFIG
    try:
        config = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise TestPassError(f"{path} is missing: it names the test list and maps each row to its evidence") from None
    except ValueError as problem:
        raise TestPassError(f"{path} is not valid JSON: {problem}") from None
    if not config.get("doc"):
        raise TestPassError(f"{path} names no test list: add \"doc\", the Markdown file's path in the repository")
    return config


def parse_check(name, text, where=""):
    """An expected figure as written: ">= 300", "> 0", "<= 5", "< 5", "= 1" or "0.9..1"."""
    text = str(text).strip()
    found = _RANGE.match(text)
    if found:
        return Check(name, text, float(found.group(1)), float(found.group(2)))
    found = _CHECK.match(text)
    if not found:
        raise TestPassError(f"{CONFIG}{where}: expect {name!r} is {text!r}; give >= N, > N, <= N, < N, = N or A..B")
    op, value = found.group(1), float(found.group(2))
    return {">=": Check(name, text, low=value), ">": Check(name, text, low=value, low_open=True),
            "<=": Check(name, text, high=value), "<": Check(name, text, high=value, high_open=True),
            "=": Check(name, text, value, value)}[op]


def parse_item(value, where=""):
    """A key, or {"key", "variant", "detail", "expect"}."""
    if isinstance(value, str) and value:
        return Item(value)
    if not isinstance(value, dict) or not isinstance(value.get("key"), str) or not value["key"]:
        raise TestPassError(f"{CONFIG}{where}: evidence is a key or an object with a \"key\"; found {value!r}")
    unknown = sorted(set(value) - _ITEM_FIELDS)
    if unknown:
        raise TestPassError(f"{CONFIG}{where}: evidence for {value['key']} has fields it does not know: {', '.join(unknown)}")
    expect = value.get("expect") or {}
    if not isinstance(expect, dict):
        raise TestPassError(f"{CONFIG}{where}: expect is an object of figures, such as {{\"W\": \">= 300\"}}")
    variant, detail = value.get("variant"), value.get("detail")
    return Item(value["key"], None if variant is None else str(variant), None if detail is None else str(detail),
                tuple(parse_check(str(n), t, where) for n, t in sorted(expect.items())))


def parse_parts(row, value):
    """A row's evidence: a list (one part, the whole row) or {"parts": {name: [evidence, ...]}}."""
    where = f" row {row}"
    if isinstance(value, list):
        return [Part("", tuple(parse_item(v, where) for v in value))]
    if isinstance(value, dict) and set(value) == {"parts"} and isinstance(value["parts"], dict) and value["parts"]:
        parts = []
        for name, items in value["parts"].items():
            if not isinstance(items, list) or not items:
                raise TestPassError(f"{CONFIG}{where}: part {name!r} names no evidence")
            parts.append(Part(str(name), tuple(parse_item(v, f"{where}, part {name!r}") for v in items)))
        return parts
    raise TestPassError(f"{CONFIG}{where}: give a list of evidence, or {{\"parts\": {{\"name\": [evidence]}}}}")


def parse_mapping(config):
    return {str(r): parse_parts(r, v) for r, v in (config.get("rows") or {}).items()}


def parse_order(config):
    rules = []
    for number, rule in enumerate(config.get("order") or []):
        where = f" order rule {number + 1}"
        if not isinstance(rule, dict) or "first" not in rule or "then" not in rule:
            raise TestPassError(f"{CONFIG}{where}: an order rule names \"first\" and \"then\"")
        since = ()
        if rule.get("since") is not None:
            since = version_tuple(rule["since"]) or ()
            if not since:
                raise TestPassError(f"{CONFIG}{where}: \"since\" is a version, such as \"0.197.0\"")
        rules.append(OrderRule(str(rule.get("name") or f"rule {number + 1}"), str(rule.get("row") or ""),
                               parse_item(rule["first"], where), parse_item(rule["then"], where), since))
    return rules


def mapped_keys(config):
    """Every key the evidence map names, in rows and order rules: for a repository's own checks."""
    keys = {item.key for parts in parse_mapping(config).values() for part in parts for item in part.items}
    return keys | {item.key for rule in parse_order(config) for item in (rule.first, rule.then)}


def map_problems(config):
    """What is wrong with the evidence map beyond its form: a key with nothing narrowing it that stands for more than one row,
    unless `shared` says why."""
    shared = config.get("shared") or {}
    rows_of = {}
    for row, parts in parse_mapping(config).items():
        for part in parts:
            for item in part.items:
                if not item.narrowed:
                    rows_of.setdefault(item.key, set()).add(row)
    return [f"{key} stands for rows {', '.join(sorted(rows))} with nothing narrowing it: narrow it with a case or a detail, "
            f"or list it under \"shared\" with why" for key, rows in sorted(rows_of.items()) if len(rows) > 1 and key not in shared]


def split_cells(line):
    """A Markdown table row's cells, splitting on bars that are not escaped."""
    inner = line.strip()
    inner = inner[1:] if inner.startswith("|") else inner
    inner = inner[:-1] if inner.endswith("|") and not inner.endswith("\\|") else inner
    return [cell.strip() for cell in re.split(r"(?<!\\)\|", inner)]


def parse_rows(text):
    """Every row of every table whose first column is "#", with the heading it sits under."""
    rows, section, columns = [], "", None
    lines = text.splitlines()
    for number, line in enumerate(lines):
        heading = _HEADING.match(line)
        if heading:
            section, columns = heading.group(2), None
            continue
        if not line.startswith("|"):
            columns = None
            continue
        cells = split_cells(line)
        if columns is None:
            columns = cells if cells and cells[0] == "#" else None
            continue
        if all(set(c) <= set("-: ") for c in cells):
            continue
        if cells and cells[0]:
            rows.append(Row(cells[0], section, columns, cells, number))
    return rows


def _lines(path):
    """The JSON objects of a JSON-lines file, and how many lines could not be read. A missing file holds none."""
    try:
        text = Path(path).read_text(encoding="utf-8-sig")
    except FileNotFoundError:
        return [], 0
    found, bad = [], 0
    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except ValueError:
            bad += 1
            continue
        if isinstance(value, dict):
            found.append(value)
        else:
            bad += 1
    return found, bad


def _figures(values):
    if not isinstance(values, dict):
        return {}
    return {str(k): v for k, v in values.items() if isinstance(v, (int, float)) and not isinstance(v, bool)}


def note_from(line):
    """A Note from one line's object, or None when it has no key or time."""
    key, time = str(line.get("key") or ""), str(line.get("time") or "")
    if not key or not time:
        return None
    tick = line.get("tick")
    return Note(key, time, str(line.get("mod") or ""), str(line.get("version") or ""), str(line.get("detail") or ""),
                str(line.get("on") or ""), str(line.get("kind") or ""), str(line.get("variant") or ""), _figures(line.get("values")),
                tick if isinstance(tick, int) and not isinstance(tick, bool) else None, str(line.get("source") or ""))


def read_notes(paths, extra=()):
    """Every note, in the order written, then the extra notes' objects (saved histories, 1.121.0), and how many lines could not
    be read."""
    notes, bad = [], 0
    for path in paths:
        lines, unread = _lines(path)
        bad += unread
        for line in lines:
            note = note_from(line)
            if note is None:
                bad += 1
            else:
                notes.append(note)
    for line in extra:
        note = note_from(line)
        if note is None:
            bad += 1
        else:
            notes.append(note)
    return notes, bad


def aggregate(notes):
    """Notes taken together by key, in key order."""
    seen = {}
    for note in notes:
        found = seen.get(note.key)
        if found is None:
            seen[note.key] = Sighting(note.key, note.time, note.time, 1, note.mod, note.version, note.detail)
            continue
        found.count += 1
        found.first = min(found.first, note.time)
        if note.time >= found.last:
            found.last, found.mod, found.version, found.detail = note.time, note.mod, note.version, note.detail
    return [seen[k] for k in sorted(seen)]


def read_seen(paths):
    """Each key's notes taken together, and how many lines could not be read."""
    notes, bad = read_notes(paths)
    return {s.key: s for s in aggregate(notes)}, bad


def read_verdicts(paths):
    """Each row's latest verdict; a later "cleared" removes it."""
    latest, bad = {}, 0
    for path in paths:
        entries, unread = _lines(path)
        bad += unread
        for entry in entries:
            row, verdict, time = str(entry.get("row") or ""), str(entry.get("verdict") or ""), str(entry.get("time") or "")
            if not row or verdict not in VERDICTS or not time:
                bad += 1
                continue
            if row in latest and latest[row].time > time:
                continue
            via = str(entry.get("via") or "companion")
            latest[row] = Verdict(row, verdict, time, " ".join(str(entry.get("note") or "").split()), via if via in VIA else "companion")
    return {r: v for r, v in latest.items() if v.verdict != "cleared"}, bad


def read_decisions(paths):
    """Each key's latest decision; a later "cleared" removes it."""
    latest, bad = {}, 0
    for path in paths:
        entries, unread = _lines(path)
        bad += unread
        for entry in entries:
            key, decision, time = str(entry.get("key") or ""), str(entry.get("decision") or ""), str(entry.get("time") or "")
            if not key or decision not in DECISIONS or not time:
                bad += 1
                continue
            if key in latest and latest[key].time > time:
                continue
            latest[key] = Decision(key, decision, time, " ".join(str(entry.get("note") or "").split()))
    return {k: d for k, d in latest.items() if d.decision != "cleared"}, bad


def parse_verdict(text, time):
    """A verdict given on the command line, "ROW:WORD" or "ROW:WORD:NOTE" (WORD passed, partial or failed), stamped with
    <time> and marked as given in conversation. Raises TestPassError, saying what is wrong, for anything else."""
    parts = text.split(":", 2)
    if len(parts) < 2 or not parts[0].strip() or parts[1].strip() not in _WORDS:
        raise TestPassError(f"--verdict {text!r}: give ROW:WORD or ROW:WORD:NOTE, WORD one of " + ", ".join(_WORDS))
    note = " ".join(parts[2].split()) if len(parts) == 3 else ""
    return Verdict(parts[0].strip(), parts[1].strip(), time, note, "conversation")


# ---- Judging ----

def version_tuple(text):
    found = re.fullmatch(r"v?(\d+(?:\.\d+)*)", str(text).strip())
    return tuple(int(x) for x in found.group(1).split(".")) if found else None


def row_versions(row, names):
    """The newest version of each mod the row names, {mod: version tuple}. <names> says how each mod is written in rows
    ({"D'thorga Framework": "Framework"}, or a list of ways). Verdict and seen sentences are left out, and a name straight after
    another capitalised word ("Vehicle Framework 1.7.2537") is someone else's."""
    text = _STATUS_SENTENCE.sub("", " ".join(row.cells[1:]))
    found = {}
    for mod, aliases in names.items():
        for alias in [aliases] if isinstance(aliases, str) else list(aliases):
            pattern = re.compile(r"(\S+ )?(?<![\w'])" + re.escape(alias) + r" v?(\d+(?:\.\d+){1,3})\b")
            for match in pattern.finditer(text):
                before = (match.group(1) or "").strip()
                if before and before[0].isupper() and before[-1].isalpha() and before != "D'thorga":
                    continue
                version = version_tuple(match.group(2))
                if version and version > found.get(mod, ()):
                    found[mod] = version
    return found


def is_stale(note, versions):
    """Whether the note came from an older version of its mod than the newest its row names."""
    newest, version = versions.get(note.mod), version_tuple(note.version)
    return bool(newest and version and version < newest)


def kinds_of(notes):
    """What kinds of thing the notes were seen on: their kind, or the detail's words before its first colon."""
    return sorted({n.kind or n.detail.split(":")[0].strip() for n in notes if n.kind or n.detail.split(":")[0].strip()})


def index_by_key(notes):
    """Each note's place in the list, under its key: a part can match only notes with one of its items' keys, so it looks at those
    alone, in the list's order (1.147.1; every part scanning every note took most of a minute on a long-kept list)."""
    found = {}
    for place, note in enumerate(notes):
        found.setdefault(note.key, []).append(place)
    return found


def check_part(part, notes, versions, by_key=None):
    """How one part of a row stands. `by_key`, from `index_by_key(notes)`, narrows the notes first; the answer is the same."""
    if by_key is not None:
        notes = [notes[place] for place in sorted({place for item in part.items for place in by_key.get(item.key, ())})]
    matched = [n for n in notes if any(item.matches(n) for item in part.items)]
    stale = [n for n in matched if is_stale(n, versions)]
    fresh = [n for n in matched if not is_stale(n, versions)]
    good = [n for n in fresh if any(item.matches(n) and item.meets(n) for item in part.items)]
    off = [n for n in fresh if not any(item.matches(n) and item.meets(n) for item in part.items)]
    expected = [c.shown for item in part.items for c in item.expect]
    if good:
        figures = any(item.expect and item.matches(n) and item.meets(n) for n in good for item in part.items)
        state = "expected" if figures else "seen"
    elif off:
        state = "off"
    elif stale:
        state = "stale"
    else:
        state = "none"
    return PartCheck(part.name, state, good, off, stale, expected)


def check_order(rules, notes):
    """Every `then` note on a thing with no `first` note on it since its last `then`, and how many notes the rules name could not
    be checked because they say nothing of what they were seen on."""
    problems, unchecked = [], 0
    for rule in rules:
        by_thing = {}
        for note in notes:
            if (rule.first.matches(note) or rule.then.matches(note)) and rule.counts(note):
                if not note.on:
                    unchecked += 1
                    continue
                by_thing.setdefault(note.on, []).append(note)
        for on in sorted(by_thing):
            warned = False
            # Within one time, a saved history's tick says which came first (1.121.0): its notes share their save's time.
            for note in sorted(by_thing[on], key=lambda n: (n.time, n.tick if n.tick is not None else -1)):
                if rule.first.matches(note):
                    warned = True
                if rule.then.matches(note):
                    if not warned:
                        problems.append(OrderProblem(rule.name, rule.row, on, note.kind, note.time, note.detail))
                    warned = False
    return problems, unchecked


def gather(root, seen_paths, verdict_paths, config=None, given=(), decision_paths=(), extra_notes=()):
    """Everything the reports need. <given> are verdicts from the command line; each replaces the file's for its row.
    <extra_notes> are note objects from elsewhere than a file: a game's saved histories (1.121.0)."""
    config = config or load_config(root)
    doc = Path(root) / config["doc"]
    try:
        rows = parse_rows(doc.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise TestPassError(f"the test list {doc} named in {CONFIG} is missing") from None
    mapping = parse_mapping(config)
    rules = parse_order(config)
    prefixes = tuple(config.get("prefixes", {}))
    notes, bad_seen = read_notes(seen_paths, extra_notes)
    verdicts, bad_verdicts = read_verdicts(verdict_paths)
    decisions, bad_decisions = read_decisions(decision_paths)
    for verdict in given:
        verdicts[verdict.row] = verdict
    names = config.get("versionNames") or {}
    checks = {}
    by_key = index_by_key(notes)
    for row in rows:
        parts = mapping.get(row.id)
        if parts:
            versions = row_versions(row, names)
            checks[row.id] = RowCheck([check_part(p, notes, versions, by_key) for p in parts], versions)
    order, unchecked = check_order(rules, notes)
    unrowed = {str(k): str(v) for k, v in (config.get("unrowed") or {}).items()}
    mapped = {item.key for parts in mapping.values() for part in parts for item in part.items}
    seen = {s.key: s for s in aggregate(notes)}
    unmapped = sorted(k for k in seen if k not in mapped and k not in unrowed
                      and not (k in decisions and decisions[k].decision == "no-row"))
    return Evidence(rows, seen, verdicts, mapping, prefixes, bad_seen + bad_verdicts + bad_decisions, unmapped, notes, checks,
                    order, unchecked, decisions, unrowed)


# ---- Writing ----

def day(time):
    """"17 Nov 2026" from an ISO time; the text itself when it is not one."""
    try:
        moment = datetime.fromisoformat(time.replace("Z", "+00:00"))
    except ValueError:
        return time
    return f"{moment.day} {_MONTHS[moment.month - 1]} {moment.year}"


def _clean(text):
    return " ".join(text.split()).replace("|", "\\|").replace("**", "")


def verdict_text(verdict):
    word = _WORDS.get(verdict.verdict, "Failed")
    note = f": {_clean(verdict.note)}" if verdict.note else ""
    return f"**{word}: the owner, {day(verdict.time)}, {VIA.get(verdict.via, VIA['companion'])}{note}.**"


def seen_text(sightings, check=None):
    last = max(sightings, key=lambda s: s.last)
    made = f" ({_clean(last.mod)} {_clean(last.version)})".rstrip() if last.mod or last.version else ""
    made = "" if made == " ()" else made
    parts = ""
    if check is not None and len(check.parts) > 1:
        names = [_clean(p.name).replace("*", "") for p in check.seen_parts]
        parts = f": {len(names)} of {len(check.parts)} parts ({', '.join(names)})"
    return f"**{SEEN_TEXT}, {day(last.last)}{made}{parts}; awaiting the owner's word.**"


def _parts_marked(cell):
    """How many parts the row's seen sentence already names; 0 when it names none."""
    found = _PARTS_MARK.search(cell)
    return int(found.group(1)) if found else 0


WITHDRAWN = "takes back its seen-working sentence: no note stands for the row now"


def apply_to_text(text, evidence):
    """The test list with every pending sentence added, and the rows changed. A verdict, or a seen sentence naming more parts,
    replaces an awaiting note; a seen sentence no note stands for any more is taken back (1.19.1)."""
    newline = "\r\n" if "\r\n" in text else "\n"
    lines = text.split(newline)
    changed = []
    for row in evidence.rows:
        sentence = evidence.pending(row)
        if sentence is None:
            if evidence.withdraws(row):
                cells = list(row.cells)
                cells[-1] = _SEEN_MARK.sub("", cells[-1]).rstrip()
                lines[row.line] = "| " + " | ".join(cells) + " |"
                changed.append((row, WITHDRAWN))
            continue
        cells = list(row.cells)
        last = cells[-1]
        if row.id in evidence.verdicts or sentence.startswith("**" + SEEN_TEXT):
            last = _SEEN_MARK.sub("", last)
        cells[-1] = (last.rstrip() + " " + sentence).strip()
        lines[row.line] = "| " + " | ".join(cells) + " |"
        changed.append((row, sentence))
    return newline.join(lines), changed
