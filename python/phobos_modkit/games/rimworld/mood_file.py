"""The colony mood file a running game writes at each save, and the advice the mood report gives.

phobos-rimworld's D'thorga Framework (0.64.0 and later) writes `PhobosSnapshots/ColonyMood.xml` while the game saves: every
colonist's, slave's and prisoner's thought groups as the game adds them up, situational ones included, with each pawn's mood and
break thresholds. A save holds only remembered thoughts, so the file is the only exact source for the rest. It names the tick
count and world seed it was written at; the report uses it only when both match the save it reads.

The advice (`mood-advice.json` beside this module) is authored by us, not the game: plain suggestions keyed by ThoughtDef or
NeedDef name, with * and ? as wildcards. Anyone may add to it; the report always labels it as advice.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import fnmatch
import json
from pathlib import Path
import xml.etree.ElementTree as ET

FORMAT = "1"
ADVICE = Path(__file__).with_name("mood-advice.json")


class MoodFileError(ValueError):
    pass


@dataclass
class FileThought:
    def_name: str
    label: str
    kind: str          # memory or situational
    count: int
    mood: float
    precept: str = None


@dataclass
class FilePawn:
    thing_id: str
    name: str
    group: str
    mood: float
    instant: float
    limits: tuple      # (minor, major, extreme), or None when the game gave none
    thoughts: list = field(default_factory=list)


@dataclass
class MoodFile:
    ticks: int
    seed: str
    written: str
    pawns: dict        # thing ID -> FilePawn

    def matches(self, ticks, seed):
        """Whether the file was written at the same moment as a save with these ticks and world seed."""
        return ticks is not None and self.ticks == ticks and (seed or "") == (self.seed or "")


def _float(element, name, default=None):
    try:
        return float(element.get(name))
    except (TypeError, ValueError):
        return default


def read(path):
    """The mood file at path, or None when there is none. A file of another shape raises MoodFileError."""
    path = Path(path)
    if not path.is_file():
        return None
    try:
        root = ET.parse(path).getroot()
    except (ET.ParseError, OSError) as problem:
        raise MoodFileError(f"The colony mood file {path} could not be read ({problem}).") from None
    if root.tag != "ColonyMood" or root.get("format") != FORMAT:
        raise MoodFileError(f"The colony mood file {path} is not in a shape this kit reads (format {root.get('format')}).")
    pawns = {}
    for element in root.findall("pawn"):
        limits = tuple(_float(element, k) for k in ("minor", "major", "extreme"))
        pawn = FilePawn(element.get("id", ""), element.get("name", ""), element.get("group", ""),
                        _float(element, "mood", 0.0), _float(element, "instantMood", 0.0),
                        limits if None not in limits else None)
        for t in element.findall("thought"):
            pawn.thoughts.append(FileThought(t.get("def", ""), t.get("label", ""), t.get("kind", "situational"),
                                             int(_float(t, "count", 1)), _float(t, "mood", 0.0), t.get("precept")))
        pawns[pawn.thing_id] = pawn
    try:
        ticks = int(root.get("ticksGame"))
    except (TypeError, ValueError):
        ticks = None
    return MoodFile(ticks, root.get("seed", ""), root.get("written", ""), pawns)


class Advice:
    """Authored suggestions by Def name: exact names first, then the first wildcard that matches."""

    def __init__(self, path=ADVICE):
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        self.thoughts = data.get("thoughts", {})
        self.needs = data.get("needs", {})
        self.drug = data.get("drug_need", "")

    @staticmethod
    def _find(table, name):
        if name in table:
            return table[name]
        for pattern, text in table.items():
            if any(c in pattern for c in "*?") and fnmatch.fnmatchcase(name, pattern):
                return text
        return None

    @staticmethod
    def _text(entry):
        return entry.get("text") if isinstance(entry, dict) else entry

    def thought(self, def_name):
        return self._text(self._find(self.thoughts, def_name))

    def fixable(self, def_name):
        """Whether the advice for a thought is something the player can do, not only wait out."""
        entry = self._find(self.thoughts, def_name)
        return entry is not None and not (isinstance(entry, dict) and entry.get("fix") is False)

    def need(self, def_name):
        return self._text(self._find(self.needs, def_name))
