"""The shared rules: the files in this repository's rules/ folder, and whether a repository reads them.

rules/ holds what the owner has decided for every game, mod, framework and tool repository (rules/README.md). A repository reads
the copy its pin of this kit holds: its CLAUDE.md imports rules/every-session.md, and its AGENTS.md points to the same file for a
reader that does not follow imports. This module lists the rule files and checks those two lines; it never judges whether a rule
was followed.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import re

FOLDER = Path(__file__).resolve().parents[2] / "rules"
INDEX = "README.md"
EVERY_SESSION = "every-session.md"
PIN = "external/phobos-modkit"
CLAUDE, AGENTS = "CLAUDE.md", "AGENTS.md"

_LINK = re.compile(r"\]\(([^)#\s]+\.md)\)")
_ROW = re.compile(r"^\|\s*\[[^\]]+\]\((?P<file>[^)]+\.md)\)\s*\|\s*(?P<read>[^|]*)\|\s*(?P<covers>[^|]*)\|\s*$")
_RULE = re.compile(r"^- \*\*")
_DESIGN = re.compile(r"^\*\*Status[^*]*:\*\*.*not yet rules", re.IGNORECASE)


@dataclass
class RuleFile:
    name: str
    title: str = ""
    read: str = ""              # when it is read, from the index
    covers: str = ""            # what it covers, from the index
    sections: list = field(default_factory=list)
    rules: int = 0              # top-level entries that open in bold: the rules themselves
    design: bool = False        # a design for the owner to edit, whose status says "not yet rules": it holds no rules


def rule_files(folder=FOLDER):
    """Every rules file but the index, in name order with the every-session file first, each with its title, sections and rule count,
    and what the index says of it."""
    folder = Path(folder)
    listed = indexed(folder)
    found = []
    for path in sorted(folder.glob("*.md"), key=lambda p: (p.name != EVERY_SESSION, p.name)):
        if path.name == INDEX:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        lines = text.splitlines()
        read, covers = listed.get(path.name, ("", ""))
        design = any(_DESIGN.match(l) for l in lines[:6])
        found.append(RuleFile(path.name, next((l[2:].strip() for l in lines if l.startswith("# ")), ""), read, covers,
                              [l[3:].strip() for l in lines if l.startswith("## ")],
                              0 if design else sum(1 for l in lines if _RULE.match(l)), design))
    return found


def indexed(folder=FOLDER):
    """{file name: (when it is read, what it covers)} from the index's table."""
    try:
        text = (Path(folder) / INDEX).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return {}
    found = {}
    for line in text.splitlines():
        row = _ROW.match(line)
        if row:
            found[row.group("file")] = (row.group("read").strip(), row.group("covers").strip())
    return found


def problems(folder=FOLDER):
    """What is wrong with the rules folder itself: a file the index does not list, or a listed file that is not there."""
    folder = Path(folder)
    listed = set(indexed(folder))
    present = {p.name for p in folder.glob("*.md")} - {INDEX}
    found = [f"{name} is not in the table in {INDEX}" for name in sorted(present - listed)]
    found += [f"{INDEX} lists {name}, which is not in the folder" for name in sorted(listed - present)]
    if EVERY_SESSION not in present:
        found.append(f"{EVERY_SESSION} is missing")
    return found


@dataclass
class Uptake:
    """How one repository reads the shared rules."""
    kind: str                   # "kit" (this repository), "pinned" or "none"
    path: str = ""              # the every-session file's path as the repository names it
    present: bool = False       # that file is there (the pin is fetched)
    imports: bool = False       # CLAUDE.md imports it
    points: bool = False        # AGENTS.md names it
    missing: list = field(default_factory=list)

    @property
    def ok(self):
        return self.kind != "none" and not self.missing


def _text(path):
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def uptake(root):
    """Whether the repository at root reads the shared rules: the two lines, and the file they name."""
    root = Path(root)
    if (root / "rules" / EVERY_SESSION).is_file() and (root / "python" / "phobos_modkit").is_dir():
        kind, path = "kit", f"rules/{EVERY_SESSION}"
    elif (root / PIN).exists():
        kind, path = "pinned", f"{PIN}/rules/{EVERY_SESSION}"
    else:
        return Uptake("none", missing=[f"this repository does not pin the kit at {PIN}, so it has no copy of the rules to read"])
    found = Uptake(kind, path, (root / path).is_file())
    found.imports = any(line.strip() == f"@{path}" for line in _text(root / CLAUDE).splitlines())
    found.points = path in _text(root / AGENTS)
    if not found.present:
        found.missing.append(f"{path} is not there: fetch the kit with git submodule update --init, or move the pin to 1.25.0 or later")
    if not found.imports:
        found.missing.append(f"{CLAUDE} has no line @{path}")
    if not found.points:
        found.missing.append(f"{AGENTS} does not name {path}")
    return found
