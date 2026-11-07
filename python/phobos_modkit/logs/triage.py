"""Grouping entries by signature, and comparing two runs' groups."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
import hashlib

from .model import LEVEL_ORDER
from .signature import normalise

LINES_KEPT = 50  # line numbers kept per group, so a reader can open the log at them


def level_rank(level):
    return LEVEL_ORDER.index(level) if level in LEVEL_ORDER else len(LEVEL_ORDER)


@dataclass
class Group:
    """Every entry with one signature at one level in one category."""
    id: str
    level: str
    category: str
    signature: str
    count: int = 0
    first_line: int = 0
    last_line: int = 0
    first_time: str = ""
    last_time: str = ""
    lines: list = field(default_factory=list)       # the first LINES_KEPT line numbers
    example: object = None                          # the first Entry
    evidence: Counter = field(default_factory=Counter)  # Evidence -> how many entries carried it

    @property
    def key(self):
        return (self.level, self.category, self.signature)

    def top_evidence(self, limit=3):
        """The strongest evidence first, then the most frequent, then the first found."""
        ranked = sorted(self.evidence.items(), key=lambda item: (item[0].rank, -item[1]))
        return [evidence for evidence, _ in ranked[:limit]]


def group_id(level, category, signature):
    """A short, stable name for a group: the same signature gives the same ID in every run and on every machine."""
    digest = hashlib.sha1(f"{level}\0{category}\0{signature}".encode("utf-8")).hexdigest()
    return digest[:8]


def group(entries):
    """Groups, most severe level first, then most frequent, then earliest."""
    groups = {}
    for entry in entries:
        signature = normalise(entry.headline)
        key = (entry.level, entry.category, signature)
        found = groups.get(key)
        if found is None:
            found = groups[key] = Group(group_id(*key), entry.level, entry.category, signature,
                                        first_line=entry.line, first_time=entry.time, example=entry)
        found.count += 1
        found.last_line = entry.line
        found.last_time = entry.time
        if len(found.lines) < LINES_KEPT:
            found.lines.append(entry.line)
        for evidence in dict.fromkeys(entry.evidence):  # each clue once per message, in the order found
            found.evidence[evidence] += 1
    return sorted(groups.values(), key=lambda g: (level_rank(g.level), -g.count, g.first_line))


@dataclass
class Cluster:
    """Signatures whose first messages share one exception: most likely one problem worded several ways."""
    fingerprint: str
    groups: list

    @property
    def count(self):
        return sum(g.count for g in self.groups)


def clusters(groups):
    """Clusters of two or more groups with the same exception fingerprint, largest first."""
    by_fingerprint = {}
    for g in groups:
        if g.example is not None and g.example.fingerprint:
            by_fingerprint.setdefault((g.level, g.example.fingerprint), []).append(g)
    found = [Cluster(fp, members) for (_, fp), members in by_fingerprint.items() if len(members) > 1]
    return sorted(found, key=lambda c: (level_rank(c.groups[0].level), -c.count, c.groups[0].first_line))


@dataclass
class Change:
    """One signature's counts in the previous and current runs."""
    group: Group           # the current run's group, or the previous run's when it is gone
    previous: int
    current: int


@dataclass
class Comparison:
    previous_name: str
    new: list       # Change, only in the current run, most frequent first
    gone: list      # Change, only in the previous run, most frequent first
    changed: list   # Change, in both runs with different counts, largest rise first


def compare(current, previous, previous_name=""):
    """How the current run's groups differ from the previous run's."""
    before = {g.key: g for g in previous}
    now = {g.key: g for g in current}
    new = [Change(g, 0, g.count) for g in current if g.key not in before]
    gone = [Change(g, g.count, 0) for g in previous if g.key not in now]
    changed = [Change(g, before[g.key].count, g.count) for g in current
               if g.key in before and before[g.key].count != g.count]
    order = lambda c: (level_rank(c.group.level), -max(c.current, c.previous), c.group.first_line)
    new.sort(key=order)
    gone.sort(key=order)
    changed.sort(key=lambda c: (level_rank(c.group.level), -(c.current - c.previous), c.group.first_line))
    return Comparison(previous_name, new, gone, changed)


@dataclass
class Report:
    """Everything a renderer needs: the parsed log, its groups and an optional comparison."""
    log: object                    # LogFile
    groups: list
    comparison: object = None      # Comparison

    def level_counts(self):
        """Level -> (entries, signatures), most severe first."""
        counts = {}
        for g in self.groups:
            entries, signatures = counts.get(g.level, (0, 0))
            counts[g.level] = (entries + g.count, signatures + 1)
        return dict(sorted(counts.items(), key=lambda item: level_rank(item[0])))

    def find(self, group_id_prefix):
        """The group whose ID starts with the given text, or None (also None when several match)."""
        found = [g for g in self.groups if g.id.startswith(group_id_prefix)]
        return found[0] if len(found) == 1 else None


def build_report(log, previous_log=None):
    groups = group(log.entries)
    comparison = None
    if previous_log is not None:
        comparison = compare(groups, group(previous_log.entries), previous_log.name)
    return Report(log, groups, comparison)
