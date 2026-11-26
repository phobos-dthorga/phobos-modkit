"""Checks: rules, written as data, that say when a game's saved or running state is wrong. Game-free.

A repository writes its checks in a JSON file (phobos-rimworld's `config/checks.json`). Each check names where it reads (`save` or
`live`), which things or objects, the values to read from each by path, and a small condition saying when that is a fault. A game's
adapter reads the values (from a save, or from a snapshot of the running game) and hands this module one row per thing; this module
judges the rows and writes the report. The design: phobos-rimworld's `docs/development/test-automation.md`; how it is used:
`docs/checks.md`.

Conditions are expressions in a small language: names of the values read, numbers, text in quotes, `True`, `False` and `None`;
comparisons, `and`, `or`, `not`, `+ - * / %`, and the functions in FUNCTIONS. Anything else is refused when the file is read, so a
check file can never run code.

**Figures for a test list** (1.129.0): a rule may also carry a `note`, naming figures to read from each thing it applies to. Those
figures become notes in the seen-in-play format (`notes_of`), which a test list's evidence map judges with its own `expect`, so a
row's claim about a number is read from the game's own state rather than taken on trust. A note is evidence for the owner, never a
verdict.
"""
from __future__ import annotations

import ast
from dataclasses import dataclass, field
import json
import math
from pathlib import Path
import re

from . import games_list
from .report import Bullets, Report, Table

SOURCES = ("save", "live")
LEVELS = ("fault", "look")
LEVEL_WORDS = {"fault": "Fault", "look": "Worth a look"}
MAX_SHOWN = 20          # findings listed per check; the count says how many in all


class CheckError(ValueError):
    """A check file that cannot be used; the message says where and why, in words for a person."""


# ---- Values ----

_NUMBER = re.compile(r"[+-]?(\d+(\.\d*)?|\.\d+)([eE][+-]?\d+)?")


def value_of(text):
    """A read value as the expressions use it: a number when it reads as one, True or False, None, else its text. Lists stay lists,
    each item converted. NaN and infinity read as numbers, so a check can find them with isnan()."""
    if isinstance(text, list):
        return [value_of(t) for t in text]
    if text is None or isinstance(text, (bool, int, float)):
        return text
    stripped = str(text).strip()
    if _NUMBER.fullmatch(stripped):
        number = float(stripped)
        return int(number) if number.is_integer() and "." not in stripped and "e" not in stripped.lower() else number
    lower = stripped.lower()
    if lower in ("nan", "infinity", "-infinity", "+infinity", "inf", "-inf"):
        return float(lower.replace("infinity", "inf"))
    if lower in ("true", "false"):
        return lower == "true"
    return stripped


# ---- Expressions ----

def _numbers(values):
    return [v for v in _flat(values) if isinstance(v, (int, float)) and not isinstance(v, bool)]


def _flat(values):
    if isinstance(values, list):
        for v in values:
            yield from _flat(v)
    elif values is not None:
        yield values


def _sum(values):
    return sum(_numbers(values))


def _count(values):
    return len(list(_flat(values)))


def _max(values, default=None):
    found = _numbers(values)
    return max(found) if found else default


def _min(values, default=None):
    found = _numbers(values)
    return min(found) if found else default


def _isnan(value):
    return any(isinstance(v, float) and (math.isnan(v) or math.isinf(v)) for v in _flat(value))


def _unique(values):
    found = []
    for v in _flat(values):
        if v not in found:
            found.append(v)
    return found


def _contains(values, wanted):
    return any(v == wanted for v in _flat(values))


FUNCTIONS = {
    "sum": _sum,          # the numbers in a list (or one value), added up; text and None are left out
    "count": _count,      # how many values there are; None is left out
    "max": _max,          # the largest number, or the default (None) when there is none
    "min": _min,
    "any": lambda values: any(bool(v) for v in _flat(values)),
    "all": lambda values: all(bool(v) for v in _flat(values)),
    "abs": lambda v: abs(v) if isinstance(v, (int, float)) else None,
    "round": lambda v, places=0: round(v, int(places)) if isinstance(v, (int, float)) else None,
    "isnan": _isnan,      # whether a value, or any in a list, is NaN or infinite
    "contains": _contains,  # whether a list holds a value
    "unique": _unique,    # a list's values, each once, in their first order
}

_ALLOWED = (ast.Expression, ast.BoolOp, ast.And, ast.Or, ast.UnaryOp, ast.Not, ast.USub, ast.UAdd, ast.BinOp, ast.Add, ast.Sub,
            ast.Mult, ast.Div, ast.Mod, ast.Compare, ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE, ast.Name, ast.Load,
            ast.Constant, ast.Call, ast.IfExp, ast.List, ast.Tuple)
_CONSTANTS = {"True": True, "False": False, "None": None}


class Expression:
    """A condition or figure in the small language, checked when read and evaluated against one row's values."""

    def __init__(self, text, where=""):
        self.text = str(text)
        try:
            self.tree = ast.parse(self.text, mode="eval")
        except SyntaxError as problem:
            raise CheckError(f"{where}: \"{self.text}\" is not an expression ({problem.msg}).") from None
        for node in ast.walk(self.tree):
            if not isinstance(node, _ALLOWED):
                raise CheckError(f"{where}: \"{self.text}\" uses {type(node).__name__}, which checks do not allow.")
            if isinstance(node, ast.Call):
                if not isinstance(node.func, ast.Name) or node.func.id not in FUNCTIONS or node.keywords:
                    raise CheckError(f"{where}: \"{self.text}\" calls something other than "
                                     + ", ".join(sorted(FUNCTIONS)) + ".")
        self.names = sorted({n.id for n in ast.walk(self.tree) if isinstance(n, ast.Name)} - set(FUNCTIONS) - set(_CONSTANTS))

    def __call__(self, values):
        return _evaluate(self.tree.body, values)


def _compare(op, left, right):
    if left is None or right is None:
        return isinstance(op, ast.Eq) and left is right or isinstance(op, ast.NotEq) and left is not right
    try:
        if isinstance(op, ast.Eq):
            return left == right
        if isinstance(op, ast.NotEq):
            return left != right
        if isinstance(op, ast.Lt):
            return left < right
        if isinstance(op, ast.LtE):
            return left <= right
        if isinstance(op, ast.Gt):
            return left > right
        return left >= right
    except TypeError:  # text against a number: never true, so a check never faults on a value it cannot compare
        return False


def _arith(op, left, right):
    if not all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in (left, right)):
        return None
    if isinstance(op, ast.Add):
        return left + right
    if isinstance(op, ast.Sub):
        return left - right
    if isinstance(op, ast.Mult):
        return left * right
    if right == 0:
        return None
    return left / right if isinstance(op, ast.Div) else left % right


def _evaluate(node, values):
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Name):
        if node.id in _CONSTANTS:
            return _CONSTANTS[node.id]
        return values.get(node.id)
    if isinstance(node, (ast.List, ast.Tuple)):
        return [_evaluate(e, values) for e in node.elts]
    if isinstance(node, ast.BoolOp):
        results = (_evaluate(v, values) for v in node.values)
        return all(bool(r) for r in results) if isinstance(node.op, ast.And) else any(bool(r) for r in results)
    if isinstance(node, ast.UnaryOp):
        operand = _evaluate(node.operand, values)
        if isinstance(node.op, ast.Not):
            return not operand
        if not isinstance(operand, (int, float)):
            return None
        return -operand if isinstance(node.op, ast.USub) else operand
    if isinstance(node, ast.BinOp):
        return _arith(node.op, _evaluate(node.left, values), _evaluate(node.right, values))
    if isinstance(node, ast.Compare):
        left = _evaluate(node.left, values)
        for op, comparator in zip(node.ops, node.comparators):
            right = _evaluate(comparator, values)
            if not _compare(op, left, right):
                return False
            left = right
        return True
    if isinstance(node, ast.IfExp):
        return _evaluate(node.body, values) if _evaluate(node.test, values) else _evaluate(node.orelse, values)
    if isinstance(node, ast.Call):
        return FUNCTIONS[node.func.id](*[_evaluate(a, values) for a in node.args])
    raise CheckError(f"Unexpected {type(node).__name__} in an expression.")  # never reached: the tree was checked when read


_PLACEHOLDER = re.compile(r"\{([^{}]+)\}")


def _say(template, values, where):
    """A check's sentence for one finding: each {expression} replaced by its value."""
    def one(match):
        result = Expression(match.group(1), where)(values)
        if isinstance(result, float):
            return f"{result:,.4g}" if not result.is_integer() else f"{int(result):,}"
        if isinstance(result, int) and not isinstance(result, bool):
            return f"{result:,}"
        if isinstance(result, list):
            return ", ".join(str(v) for v in result[:10]) + (" …" if len(result) > 10 else "")
        return "" if result is None else str(result)
    return _PLACEHOLDER.sub(one, template)


# ---- Checks ----

@dataclass
class Check:
    """One rule from a check file."""
    id: str
    title: str
    source: str
    level: str = "fault"
    kind: str = "rule"                  # "rule", or a kind the game's adapter builds its own rows for
    select: dict = field(default_factory=dict)
    read: dict = field(default_factory=dict)
    when: Expression = None
    fault: Expression = None
    says: str = ""
    row: str = ""
    why: str = ""
    options: dict = field(default_factory=dict)
    note: dict = field(default_factory=dict)  # figures for a test list: key, mod, figures {name: Expression}, variant, detail


def _text(entry, name, where, required=True):
    value = entry.get(name)
    if value is None or value == "":
        if required:
            raise CheckError(f"{where}: it needs \"{name}\".")
        return ""
    if not isinstance(value, str):
        raise CheckError(f"{where}: \"{name}\" is text.")
    return value


NOTE_FIELDS = ("key", "mod", "figures", "variant", "detail")


def _parse_note(entry, where):
    """A rule's `note` (1.129.0), checked: the key and mod its notes carry, and each figure's expression."""
    note = entry.get("note")
    if note is None:
        return {}
    if not isinstance(note, dict):
        raise CheckError(f"{where}: \"note\" is an object, with its \"key\", \"mod\" and \"figures\".")
    unknown = sorted(set(note) - set(NOTE_FIELDS))
    if unknown:
        raise CheckError(f"{where}: \"note\" takes " + ", ".join(NOTE_FIELDS) + ", not " + ", ".join(unknown) + ".")
    parsed = {"key": _text(note, "key", f"{where} note"), "mod": _text(note, "mod", f"{where} note"),
              "variant": _text(note, "variant", f"{where} note", False), "detail": _text(note, "detail", f"{where} note", False)}
    figures = note.get("figures")
    if not isinstance(figures, dict) or not figures:
        raise CheckError(f"{where}: \"note\" needs \"figures\": each figure's name and the expression that gives it.")
    parsed["figures"] = {}
    for name, text in figures.items():
        if not isinstance(name, str) or not name.isidentifier():
            raise CheckError(f"{where}: \"{name}\" cannot name a figure; use letters, digits and _.")
        parsed["figures"][name] = Expression(text, f"{where} note figure {name}")
    return parsed


def parse_check(entry, where, kinds=()):
    """A Check from one entry of a check file; CheckError says what is wrong. <kinds> are the adapter's own kinds besides rule."""
    if not isinstance(entry, dict):
        raise CheckError(f"{where}: each check is an object.")
    check_id = _text(entry, "id", where)
    where = f"{where} ({check_id})"
    source = _text(entry, "source", where)
    if source not in SOURCES:
        raise CheckError(f"{where}: \"source\" is one of " + ", ".join(SOURCES) + ".")
    level = entry.get("level", "fault")
    if level not in LEVELS:
        raise CheckError(f"{where}: \"level\" is one of " + ", ".join(LEVELS) + ".")
    kind = entry.get("kind", "rule")
    if kind != "rule" and kind not in kinds:
        raise CheckError(f"{where}: \"kind\" is rule" + "".join(f", {k}" for k in kinds) + ".")
    read = entry.get("read") or {}
    if not isinstance(read, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in read.items()):
        raise CheckError(f"{where}: \"read\" names each value with its path, as text.")
    for name in read:
        if not name.isidentifier() or name in FUNCTIONS or name in _CONSTANTS:
            raise CheckError(f"{where}: \"{name}\" cannot name a value; use letters, digits and _, and not a function's name.")
    select = entry.get("select") or {}
    if not isinstance(select, dict):
        raise CheckError(f"{where}: \"select\" is an object.")
    check = Check(check_id, _text(entry, "title", where), source, level, kind, select, read,
                  Expression(entry["when"], f"{where} when") if entry.get("when") else None,
                  Expression(entry["fault"], f"{where} fault") if entry.get("fault") else None,
                  _text(entry, "says", where, required=False), str(entry.get("row") or ""), _text(entry, "why", where, False),
                  {k: v for k, v in entry.items() if k not in ("id", "title", "source", "level", "kind", "select", "read", "when",
                                                                "fault", "says", "row", "why", "note")},
                  _parse_note(entry, where))
    if check.note and kind != "rule":
        raise CheckError(f"{where}: only a rule takes \"note\"; {kind} has no figures of its own.")
    if check.note and source != "save":
        raise CheckError(f"{where}: figures are noted from saves only, so far; a live check cannot take \"note\".")
    if kind == "rule":
        if check.fault is None and not check.note:
            raise CheckError(f"{where}: a rule needs \"fault\", the condition that makes it one, or \"note\", the figures it "
                             "notes for a test list.")
        known = set(read) | {"id", "label"}
        for expression in (check.when, check.fault, *check.note.get("figures", {}).values()):
            unknown = [n for n in (expression.names if expression else []) if n not in known]
            if unknown:
                raise CheckError(f"{where}: \"{expression.text}\" names {', '.join(unknown)}, which \"read\" does not.")
        for template in (check.says, check.note.get("key", ""), check.note.get("variant", ""), check.note.get("detail", "")):
            for match in _PLACEHOLDER.finditer(template):
                expression = Expression(match.group(1), f"{where} says")
                unknown = [n for n in expression.names if n not in known]
                if unknown:
                    raise CheckError(f"{where}: \"{{{expression.text}}}\" names {', '.join(unknown)}, which \"read\" does not.")
    return check


def load_checks(path, source=None, kinds=()):
    """Every check in a check file, or only those of one source. CheckError says what is wrong with the file."""
    path = Path(path)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise CheckError(f"There is no check file at {path}.") from None
    except ValueError as problem:
        raise CheckError(f"{path.name} is not JSON ({problem}).") from None
    entries = data.get("checks") if isinstance(data, dict) else None
    if not isinstance(entries, list):
        raise CheckError(f"{path.name} holds no list of checks under \"checks\".")
    checks, ids = [], set()
    for n, entry in enumerate(entries, 1):
        check = parse_check(entry, f"{path.name}, check {n}", kinds)
        if check.id in ids:
            raise CheckError(f"{path.name}: two checks share the id {check.id}.")
        ids.add(check.id)
        checks.append(check)
    return [c for c in checks if source is None or c.source == source]


CHECK_FILE = Path("config") / "checks.json"


def check_files(game, explicit=None, environ=None, cwd=None):
    """The check files to run (1.122.0): the one named; else config/checks.json in the current folder; else that file in every
    repository the owner's games list gives the game, which is how a program running the kit from its own folder (D'thorga
    Companion) finds them. CheckError when there are none."""
    if explicit:
        return [Path(explicit)]
    here = Path(cwd or Path.cwd()) / CHECK_FILE
    if here.is_file():
        return [here]
    try:
        listed = games_list.entries(games_list.games_file(None, environ))
    except games_list.GamesListError:
        listed = []
    found = [entry.folder / CHECK_FILE for entry in listed if entry.game == game and (entry.folder / CHECK_FILE).is_file()]
    if not found:
        raise CheckError(f"No check file was named, there is none at {CHECK_FILE} here, and no repository the games list gives "
                         f"{game} has one. Name one with --checks.")
    return found


def load_files(paths, source=None, kinds=()):
    """Every check of a source in several check files, in their order: (checks, the files' names for the report)."""
    checks, names = [], []
    for path in paths:
        checks.extend(load_checks(path, source, kinds))
        names.append(f"{Path(path).parent.parent.name}/{CHECK_FILE.as_posix()}")
    return checks, names


# ---- Judging ----

@dataclass
class Row:
    """One thing a check read: its id, a label a person knows it by, its values by name, and what kind of thing it is (a def's name,
    for a note's `kind`; empty when the adapter does not say)."""
    id: str
    label: str
    values: dict
    kind: str = ""


@dataclass
class Finding:
    check: Check
    row: Row
    text: str


@dataclass
class Noted:
    """The figures one thing gave a rule's note (1.129.0): the note's key, case and detail filled in, and the figures by name."""
    row: Row
    key: str
    variant: str
    detail: str
    figures: dict


@dataclass
class Result:
    """One check's outcome: how many things it read, what it found, and why it could not run when it could not."""
    check: Check
    read: int = 0
    findings: list = field(default_factory=list)
    problem: str = ""
    limits: list = field(default_factory=list)
    noted: list = field(default_factory=list)


def judge(check, rows, limits=()):
    """The Result of one rule over the rows read for it."""
    result = Result(check, len(rows), limits=list(limits))
    for row in rows:
        values = {name: value_of(v) for name, v in row.values.items()}
        values.setdefault("id", row.id)
        values.setdefault("label", row.label)
        if check.when is not None and not check.when(values):
            continue
        if check.fault is not None and check.fault(values):
            text = _say(check.says, values, check.id) if check.says else check.title
            result.findings.append(Finding(check, row, text))
        if check.note:
            result.noted.append(_noted(check, row, values))
    return result


def _figure(value):
    """A figure as a note keeps it: a number (a flag as 1 or 0), else nothing."""
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)) and not (isinstance(value, float) and (math.isnan(value) or math.isinf(value))):
        return value
    return None


def _noted(check, row, values):
    note = check.note
    figures = {name: _figure(expression(values)) for name, expression in note["figures"].items()}
    kept = {name: value for name, value in figures.items() if value is not None}
    shown = ", ".join(f"{name} {_say('{' + name + '}', kept, check.id)}" for name in kept)
    detail = _say(note["detail"], values, check.id) if note["detail"] else shown
    return Noted(row, _say(note["key"], values, check.id), _say(note["variant"], values, check.id) if note["variant"] else "",
                 detail, kept)


def notes_of(result, time, version, source="check", extra=None):
    """The figures a rule noted, as notes in the seen-in-play format (1.129.0), for a test list's evidence map to judge.
    <time> is when the state was read (a save's time), <version> the version of the note's mod that wrote that state."""
    notes = []
    for noted in result.noted:
        note = {"format": 1, "time": time, "key": noted.key, "mod": result.check.note["mod"], "version": version,
                "on": noted.row.id, "kind": noted.row.kind, "source": source, "check": result.check.id,
                "detail": f"{noted.row.kind}: {noted.detail}" if noted.row.kind else noted.detail}
        if noted.variant:
            note["variant"] = noted.variant
        if noted.figures:
            note["values"] = noted.figures
        note.update(extra or {})
        notes.append(note)
    return notes


def report(title, results, facts=(), caveat=""):
    """The report of a run: faults first, then what is worth a look, then checks that found nothing, then any that could not run."""
    rep = Report(title)
    rep.facts.extend(facts)
    faults = [r for r in results if r.findings and r.check.level == "fault"]
    looks = [r for r in results if r.findings and r.check.level == "look"]
    clean = [r for r in results if not r.findings and not r.problem and r.check.fault is not None]
    noting = [r for r in results if r.check.note and not r.problem]
    failed = [r for r in results if r.problem]
    found = sum(len(r.findings) for r in faults)
    rep.lines.append(f"**{len(results):,} checks: {found:,} faults from {len(faults):,} of them, "
                     f"{sum(len(r.findings) for r in looks):,} things worth a look, {len(clean):,} found nothing"
                     + (f", {len(failed):,} could not run" if failed else "") + ".**")
    if noting:
        rep.lines.append(f"{len(noting):,} checks noted the figures of {sum(len(r.noted) for r in noting):,} things for the test "
                         "list: test-pass reads them from the newest saves and judges them against what each row expects.")
    if caveat:
        rep.lines.append(caveat)
    for heading, chosen in (("Faults", faults), ("Worth a look", looks)):
        for result in chosen:
            rows = [[f.row.label or f.row.id, f.text] for f in result.findings[:MAX_SHOWN]]
            blocks = [Table(["Where", "What"], rows, len(result.findings) if len(result.findings) > MAX_SHOWN else None,
                            more="the JSON lists every one")]
            section = rep.section(f"{heading}: {result.check.title}", *blocks)
            notes = []
            if result.check.why:
                notes.append(result.check.why)
            if result.check.row:
                notes.append(f"Test row {result.check.row}.")
            notes += result.limits
            if notes:
                section.blocks.append(Bullets(notes))
    if clean:
        rep.section("Found nothing", Table(["Check", "Read", "Level"],
                                           [[r.check.title, f"{r.read:,}", LEVEL_WORDS[r.check.level]] for r in clean]))
    if noting:
        rep.section("Figures noted for the test list", Table(
            ["Check", "Things", "Row", "Example"],
            [[r.check.title, f"{len(r.noted):,}", r.check.row,
              f"{(r.noted[0].row.label or r.noted[0].row.id)}: {r.noted[0].detail}" if r.noted else ""] for r in noting]))
    if failed:
        rep.section("Could not run", Table(["Check", "Why"], [[r.check.title, r.problem] for r in failed]))
    return rep


def data(results):
    """Every result for a program: each check, what it read, every finding and every thing's noted figures. `waiting` (1.129.0) is
    the faults and things worth a look together: what waits on the person, which the manifest's `waits` names for a program."""
    faults = sum(len(r.findings) for r in results if r.check.level == "fault")
    looks = sum(len(r.findings) for r in results if r.check.level == "look")
    return {"checks": [{"id": r.check.id, "title": r.check.title, "source": r.check.source, "level": r.check.level,
                        "row": r.check.row, "read": r.read, "problem": r.problem, "limits": r.limits,
                        "findings": [{"id": f.row.id, "label": f.row.label, "text": f.text} for f in r.findings],
                        "noted": [{"id": n.row.id, "label": n.row.label, "key": n.key, "variant": n.variant, "figures": n.figures}
                                  for n in r.noted]}
                       for r in results],
            "faults": faults, "looks": looks, "waiting": faults + looks}
