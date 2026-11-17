"""A repository's in-game test list, what the game has seen working, and the owner's verdicts, brought together.

Three inputs, each written by someone else:

- **The test list**: a Markdown file of tables whose first column is "#" and last column says what passes. The repository's
  `config/test-evidence.json` names it (`doc`), maps each row to the keys of the notes that stand as evidence for it (`rows`,
  with `prefixes` for keys built at run time), and may name the game whose adapter knows where the notes are (`game`).
- **Seen-in-play notes**: JSON lines a mod writes when a feature is first seen working in a session (`key`, `time`, `mod`,
  `version`, `detail`). A note says the code ran without an error, never that the result looked right.
- **Verdicts**: JSON lines the owner's clicks write (D'thorga Companion's Tests page): `row`, `verdict` (`passed`, `partial`,
  `failed` or `cleared`), `time`, an optional `note`, and an optional `via` (`companion`, the default, or `conversation`). Only a
  verdict passes or fails a row. A verdict the owner gives an agent in conversation comes in on the command line instead
  (`apply --verdict ROW:WORD:NOTE`), and is written the same way, saying so.

`apply` writes each new verdict into its row's last cell, and "seen working, awaiting the owner's word" for a row the notes flag
that has no verdict. It writes nothing else, and only inside the test list. Game-free: a game enters through the repository's file.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import json
from pathlib import Path
import re

CONFIG = Path("config") / "test-evidence.json"
VERDICTS = ("passed", "partial", "failed", "cleared")
# Where a verdict was given, and how the test list says so.
VIA = {"companion": "through D'thorga Companion", "conversation": "in conversation"}
_WORDS = {"passed": "Passed", "partial": "Passed in part", "failed": "Failed"}
SEEN_TEXT = "Seen working by the game"
_SEEN_MARK = re.compile(r"\s*\*\*Seen working by the game[^*]*awaiting the owner's word\.\*\*")
# A part of a row passed is written in lower case ("Diagnose passed: the owner, 11 Nov 2026"), a whole row with a capital.
_STATUS = [("partial", re.compile(r"Passed in part")), ("partial", re.compile(r"\bpassed[:,] the owner")),
           ("passed", re.compile(r"\bPassed\b")),
           ("failed", re.compile(r"\*\*Failed\b")), ("seen", re.compile(re.escape(SEEN_TEXT)))]
_HEADING = re.compile(r"^(#{2,6})\s+(.*\S)\s*$")
_BOLD = re.compile(r"\*\*(.+?)\*\*")
_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


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
    key: str
    first: str
    last: str
    count: int = 1
    mod: str = ""
    version: str = ""
    detail: str = ""


@dataclass
class Verdict:
    row: str
    verdict: str
    time: str
    note: str = ""
    via: str = "companion"


@dataclass
class Evidence:
    rows: list
    seen: dict                      # key -> Sighting
    verdicts: dict                  # row id -> latest Verdict (cleared ones removed)
    mapping: dict                   # row id -> keys
    prefixes: tuple
    unreadable: int = 0             # note or verdict lines that could not be read
    unmapped: list = field(default_factory=list)   # keys seen that no row names

    def sightings(self, row_id):
        return [self.seen[k] for k in self.mapping.get(row_id, []) if k in self.seen]

    def pending(self, row):
        """The sentence apply would add to this row now, or None."""
        verdict = self.verdicts.get(row.id)
        cell = row.cells[-1]
        if verdict is not None:
            text = verdict_text(verdict)
            return None if text in cell else text
        sightings = self.sightings(row.id)
        if sightings and row.status in ("open", "partial") and SEEN_TEXT not in cell:
            return seen_text(sightings)
        return None


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


def read_seen(paths):
    seen, bad = {}, 0
    for path in paths:
        notes, unread = _lines(path)
        bad += unread
        for note in notes:
            key, time = str(note.get("key") or ""), str(note.get("time") or "")
            if not key or not time:
                bad += 1
                continue
            found = seen.get(key)
            if found is None:
                seen[key] = Sighting(key, time, time, 1, str(note.get("mod") or ""), str(note.get("version") or ""),
                                     str(note.get("detail") or ""))
                continue
            found.count += 1
            found.first = min(found.first, time)
            if time >= found.last:
                found.last, found.mod, found.version, found.detail = (time, str(note.get("mod") or ""),
                                                                      str(note.get("version") or ""), str(note.get("detail") or ""))
    return seen, bad


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


def parse_verdict(text, time):
    """A verdict given on the command line, "ROW:WORD" or "ROW:WORD:NOTE" (WORD passed, partial or failed), stamped with
    <time> and marked as given in conversation. Raises TestPassError, saying what is wrong, for anything else."""
    parts = text.split(":", 2)
    if len(parts) < 2 or not parts[0].strip() or parts[1].strip() not in _WORDS:
        raise TestPassError(f"--verdict {text!r}: give ROW:WORD or ROW:WORD:NOTE, WORD one of " + ", ".join(_WORDS))
    note = " ".join(parts[2].split()) if len(parts) == 3 else ""
    return Verdict(parts[0].strip(), parts[1].strip(), time, note, "conversation")


def gather(root, seen_paths, verdict_paths, config=None, given=()):
    """Everything the reports need. <given> are verdicts from the command line; each replaces the file's for its row."""
    config = config or load_config(root)
    doc = Path(root) / config["doc"]
    try:
        rows = parse_rows(doc.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise TestPassError(f"the test list {doc} named in {CONFIG} is missing") from None
    mapping = {str(r): list(keys) for r, keys in config.get("rows", {}).items()}
    prefixes = tuple(config.get("prefixes", {}))
    seen, bad_seen = read_seen(seen_paths)
    verdicts, bad_verdicts = read_verdicts(verdict_paths)
    for verdict in given:
        verdicts[verdict.row] = verdict
    mapped = {k for keys in mapping.values() for k in keys}
    unmapped = sorted(k for k in seen if k not in mapped)
    return Evidence(rows, seen, verdicts, mapping, prefixes, bad_seen + bad_verdicts, unmapped)


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


def seen_text(sightings):
    last = max(sightings, key=lambda s: s.last)
    made = f" ({_clean(last.mod)} {_clean(last.version)})".rstrip() if last.mod or last.version else ""
    made = "" if made == " ()" else made
    return f"**{SEEN_TEXT}, {day(last.last)}{made}; awaiting the owner's word.**"


def apply_to_text(text, evidence):
    """The test list with every pending sentence added, and the rows changed. A verdict replaces an awaiting note."""
    newline = "\r\n" if "\r\n" in text else "\n"
    lines = text.split(newline)
    changed = []
    for row in evidence.rows:
        sentence = evidence.pending(row)
        if sentence is None:
            continue
        cells = list(row.cells)
        last = cells[-1]
        if row.id in evidence.verdicts:
            last = _SEEN_MARK.sub("", last)
        cells[-1] = (last.rstrip() + " " + sentence).strip()
        lines[row.line] = "| " + " | ".join(cells) + " |"
        changed.append((row, sentence))
    return newline.join(lines), changed
