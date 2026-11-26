"""Declared effects: what a repository's data says a thing does, and whether anything reads it. Game-free.

A game's data often declares a thing's effects by name: a fitting grants "HouseBattery", moves a system's "batteryAmpHours", goes on
a "HouseBatteryTray". The name does nothing unless something else reads it: another data file naming it in a reading place, or the
code naming it as a string. A name nothing reads is a promise the game never keeps, found only by reading every file by hand (the
owner's report of 27 Nov 2026, in phobos-rimworld, that the house battery "might not be appropriately modelled", and the audit of
every fitting that followed).

Which things, which effects and which readers count is the repository's own table, `config/effects.json`, never this module:

- `data` and `skip`: globs of the data files to read (XML), `code`: globs of the code files whose quoted strings count as readers.
- `kinds`: each a data element (`element`, its tag), the child that names an entry (`id`), a word for it (`label`), and its
  `effects`: each a `path` from the entry to the elements whose text is the declared name (`grants/li`), a word for it (`what`),
  and its `readers`: `tags`, data elements of these tags holding the same text; `tagEndings`, data elements whose tag ends so
  (`Node`: an upgrade node named in a `strawChopperNode`); `anyTag`, any data element holding it; `code`, the name as a quoted
  string in code; `built`, a regular expression for names the code puts together at run time (`"Engine" + i`), which no search
  for a quoted string finds. An effect may be `unless` a child the element above its last step has (an upgrade node with
  upgrades of its own declares its effect there), and may need `definedBy`: `tagNamed`, an element named after it somewhere (a
  system's figure is declared as `<batteryAmpHours>`).
- `accepted`: entries whose unread name is known and why (`entry`, `value`, `why`), so the check passes while saying so.

A declaring element never counts as its own reader, nor as another's: two fittings that both grant the same name do not read it.
It only reads; comments are never read.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET

CONFIG = Path("config") / "effects.json"


class EffectsError(ValueError):
    """A table that cannot be used; the words say why."""


@dataclass
class Finding:
    kind: str          # the kind's label: "fitting"
    entry: str         # the entry's id: "PhobosFitting_HouseBattery"
    what: str          # the effect's word: "grant"
    value: str         # the declared name: "HouseBattery"
    file: str          # where it is declared, relative to the root
    problem: str       # "read by nothing" or "defined nowhere"
    readers: int = 0   # what read it (0 for a finding)
    why: str | None = None  # an accepted finding's reason


@dataclass
class Audit:
    kinds: int = 0
    entries: int = 0
    effects: int = 0
    findings: list[Finding] = field(default_factory=list)
    accepted: list[Finding] = field(default_factory=list)
    stale: list[dict] = field(default_factory=list)      # accepted entries that no longer find anything
    unreadable: list[str] = field(default_factory=list)  # data files that would not parse


def load_config(root: Path, path: Path | None = None) -> dict:
    """The repository's table; EffectsError when it is missing or malformed."""
    path = path or root / CONFIG
    try:
        config = json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise EffectsError(f"{_rel(root, path)} does not exist: a repository opts in by writing it") from None
    except json.JSONDecodeError as fault:
        raise EffectsError(f"{_rel(root, path)} is not JSON: {fault}") from None
    if not isinstance(config.get("kinds"), list) or not config["kinds"]:
        raise EffectsError("the table names no kinds")
    for kind in config["kinds"]:
        for key in ("element", "id", "effects"):
            if key not in kind:
                raise EffectsError(f"a kind lacks '{key}'")
        for effect in kind["effects"]:
            if "path" not in effect or "readers" not in effect:
                raise EffectsError(f"an effect of {kind['element']} lacks 'path' or 'readers'")
    return config


def _rel(root: Path, path: Path) -> str:
    try:
        return Path(path).resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return str(path)


def _files(root: Path, globs, skip) -> list[Path]:
    found = []
    for pattern in globs or []:
        found.extend(p for p in root.glob(pattern) if p.is_file())
    skipped = set()
    for pattern in skip or []:
        skipped.update(root.glob(pattern))
    return sorted(set(found) - skipped)


def _text(element) -> str:
    return (element.text or "").strip()


def _walk(element, steps):
    """The elements at a slash path below this one; a step `li` is every list item."""
    current = [element]
    for step in steps:
        current = [child for parent in current for child in parent if child.tag == step]
    return current


def audit(root: Path, config: dict) -> Audit:
    root = Path(root)
    result = Audit(kinds=len(config["kinds"]))
    trees = []
    for path in _files(root, config.get("data"), config.get("skip")):
        try:
            trees.append((path, ET.parse(path).getroot()))
        except ET.ParseError:
            result.unreadable.append(_rel(root, path))
    code = "\n".join(p.read_text(encoding="utf-8", errors="replace") for p in _files(root, config.get("code"), None))

    # Every declaration first, so no declaring element counts as a reader of anything.
    declarations = []  # (kind, entry id, effect, element, file)
    declaring = set()
    for path, tree in trees:
        for kind in config["kinds"]:
            for entry in tree.iter(kind["element"]):
                entry_id = (entry.findtext(kind["id"]) or "").strip() or "(unnamed)"
                result.entries += 1
                for effect in kind["effects"]:
                    steps = effect["path"].split("/")
                    parents = _walk(entry, steps[:-1])
                    if effect.get("unless"):
                        parents = [p for p in parents if p.find(effect["unless"]) is None]
                    for parent in parents:
                        for element in (c for c in parent if c.tag == steps[-1]):
                            if not _text(element):
                                continue
                            declarations.append((kind, entry_id, effect, element, path))
                            declaring.add(id(element))
    result.effects = len(declarations)

    # What each piece of text is held by, outside the declarations; and every tag, for definedBy.
    held: dict[str, list[str]] = {}
    tags: set[str] = set()
    for _, tree in trees:
        for element in tree.iter():
            if isinstance(element.tag, str):
                tags.add(element.tag)
            if id(element) in declaring:
                continue
            text = _text(element)
            if text and len(text) < 200:
                held.setdefault(text, []).append(element.tag)
    quoted: dict[str, int] = {}

    def code_count(value):
        if value not in quoted:
            quoted[value] = len(re.findall('"' + re.escape(value) + '"', code))
        return quoted[value]

    accepted = {(a.get("entry"), a.get("value")): a for a in config.get("accepted", [])}
    used = set()
    for kind, entry_id, effect, element, path in declarations:
        value = _text(element)
        readers = effect["readers"]
        count = 0
        holders = held.get(value, [])
        if readers.get("anyTag"):
            count += len(holders)
        else:
            wanted = set(readers.get("tags", []))
            endings = tuple(readers.get("tagEndings", []))
            count += sum(1 for tag in holders if tag in wanted or (endings and tag.endswith(endings)))
        if readers.get("code"):
            count += code_count(value)
        if readers.get("built") and re.fullmatch(readers["built"], value):
            count += 1
        problems = []
        if count == 0:
            problems.append("read by nothing")
        if effect.get("definedBy", {}).get("tagNamed") and value not in tags:
            problems.append("defined nowhere")
        for problem in problems:
            finding = Finding(kind.get("label", kind["element"]), entry_id, effect.get("what", effect["path"]), value,
                              _rel(root, path), problem, count)
            known = accepted.get((entry_id, value))
            if known:
                finding.why = known.get("why")
                result.accepted.append(finding)
                used.add((entry_id, value))
            else:
                result.findings.append(finding)
    result.stale = [a for key, a in accepted.items() if key not in used]
    order = lambda f: (f.kind, f.entry, f.what, f.value, f.problem)
    result.findings.sort(key=order)
    result.accepted.sort(key=order)
    return result
