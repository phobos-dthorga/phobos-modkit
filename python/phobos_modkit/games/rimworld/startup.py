"""Loading Progress's StartupImpact sessions, as data.

Format facts, in our own words, from the files that mod writes beside the game's Config folder (read November 2026):
StartupImpactSessions holds one XML file per launch, named by its time (20261108-115914.xml), and an index.xml. Each session's
sessionData has loadingTime, timeToMenu and earlyLaunchTime in milliseconds, modsLoaded, defsParsed, patchOperationsApplied, a
modListHash, stageTimings (stage, wallMs) and mods: each with modName, modPackageId, totalImpact and offThreadTotalImpact in
milliseconds, and a keys-and-values metrics table.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from statistics import median
import xml.etree.ElementTree as ET

METRIC_PREFIX = "LoadingProgress.StartupImpact."
INDEX_FILE = "index.xml"


class StartupError(RuntimeError):
    """The sessions cannot be read at all; the message says why."""


@dataclass(frozen=True)
class ModCost:
    package_id: str          # lower case, as the game compares them
    name: str
    milliseconds: float      # on the main thread and off it
    metrics: tuple = ()      # (metric, milliseconds), dearest first


@dataclass(frozen=True)
class Session:
    id: str
    loading_ms: float
    to_menu_ms: float
    mods_loaded: int
    defs: int
    patch_operations: int
    list_hash: str
    mods: dict = field(default_factory=dict)      # package ID -> ModCost
    stages: tuple = ()                            # (stage, wall milliseconds)


def _number(element, tag):
    try:
        return float((element.findtext(tag) or "0").strip())
    except ValueError:
        return 0.0


def _metrics(element):
    table = element.find("metrics")
    if table is None or table.find("keys") is None or table.find("values") is None:
        return ()
    pairs = []
    for key, value in zip(table.find("keys"), table.find("values")):
        try:
            pairs.append(((key.text or "").replace(METRIC_PREFIX, ""), float(value.text or 0)))
        except ValueError:
            continue
    return tuple(sorted(pairs, key=lambda p: (-p[1], p[0])))


def read_session(path):
    """A Session from one file; ValueError when the file is not one."""
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError as error:
        raise ValueError(str(error)) from error
    data = root.find("sessionData")
    if data is None:
        raise ValueError("no sessionData")
    mods = {}
    for li in data.find("mods") if data.find("mods") is not None else []:
        package = (li.findtext("modPackageId") or "").strip().lower()
        if package:
            mods[package] = ModCost(package, (li.findtext("modName") or package).strip(),
                                    _number(li, "totalImpact") + _number(li, "offThreadTotalImpact"), _metrics(li))
    stages = []
    for li in data.find("stageTimings") if data.find("stageTimings") is not None else []:
        stages.append(((li.findtext("stage") or "").strip(), _number(li, "wallMs")))
    loading = _number(data, "loadingTime")
    return Session(Path(path).stem, loading, _number(data, "timeToMenu") or loading, int(_number(data, "modsLoaded")),
                   int(_number(data, "defsParsed")), int(_number(data, "patchOperationsApplied")),
                   (data.findtext("modListHash") or "").strip(), mods, tuple(stages))


def read_sessions(folder):
    """(sessions, oldest first by their file names; names of files that could not be read)."""
    folder = Path(folder)
    if not folder.is_dir():
        raise StartupError(f"No StartupImpact sessions at {folder}. They are written by the Loading Progress mod; name the "
                           "folder with --sessions.")
    sessions, unreadable = [], []
    for path in sorted(folder.glob("*.xml"), key=lambda p: p.name):
        if path.name.lower() == INDEX_FILE:
            continue
        try:
            sessions.append(read_session(path))
        except (ValueError, OSError):
            unreadable.append(path.name)
    return sessions, unreadable


def list_change(before, after):
    """(mods added, mods removed) between two sessions, as sorted names."""
    added = sorted(after.mods[p].name for p in after.mods.keys() - before.mods.keys())
    removed = sorted(before.mods[p].name for p in before.mods.keys() - after.mods.keys())
    return added, removed


def same_list(sessions):
    """The sessions with the newest session's mod list, oldest first: the fair ones to compare."""
    return [s for s in sessions if s.list_hash == sessions[-1].list_hash] if sessions else []


def median_costs(sessions):
    """[(ModCost from the newest session, median milliseconds over the sessions that have the mod)], dearest first."""
    if not sessions:
        return []
    rows = []
    for package, latest in sessions[-1].mods.items():
        rows.append((latest, median(s.mods[package].milliseconds for s in sessions if package in s.mods)))
    return sorted(rows, key=lambda r: (-r[1], r[0].package_id))


def median_stages(sessions):
    """[(stage, median wall milliseconds)] over the sessions, dearest first."""
    times = {}
    for session in sessions:
        for stage, wall in session.stages:
            times.setdefault(stage, []).append(wall)
    return sorted(((stage, median(values)) for stage, values in times.items()), key=lambda r: (-r[1], r[0]))


def cost_changes(before, after):
    """[(name, before ms, after ms, change)] for mods in both sessions, the largest change first."""
    rows = []
    for package in before.mods.keys() & after.mods.keys():
        was, now = before.mods[package].milliseconds, after.mods[package].milliseconds
        rows.append((after.mods[package].name, was, now, now - was))
    return sorted(rows, key=lambda r: (-abs(r[3]), r[0]))
