"""Log reports: a short Markdown summary built on the kit's report model, or complete JSON for programs.

The Markdown goes through phobos_modkit.report, like every tool's. The JSON is this tool's own data export (format
1), richer than a report: every group with its lines, evidence and first message.
"""
from __future__ import annotations

import re

from ..report import Bullets, Code, Report, Table, home_redactor, keep as _keep, render_markdown
from .triage import clusters

__all__ = ["DEFAULT_LEVELS", "group_detail", "home_redactor", "summary_report", "to_json", "to_markdown"]

DEFAULT_LEVELS = ("FATAL", "ERROR", "WARN", "UNKNOWN")
CLUSTERS_SHOWN = 10
CHANGES_SHOWN = 10
DETAIL_LINES = 60
JSON_BODY_LINES = 80
JSON_FORMAT = 1
POINTS_AT_WIDTH = 100
EXCEPTION_WIDTH = 160


def _time_part(stamp):
    """20:34:32 from 2026-11-07 20:34:32.690; the text unchanged when it has no time."""
    match = re.search(r"\d{2}:\d{2}:\d{2}", stamp or "")
    return match.group(0) if match else (stamp or "")


def _where(time, line):
    when = _time_part(time)
    return f"{when}, line {line:,}" if when else f"line {line:,}"


def describe_evidence(evidence):
    """Short text for one clue, naming the mod when it was resolved."""
    name = evidence.mod or evidence.value
    return f"{name} ({evidence.kind})"


def _points_at(group, limit=3):
    """Each mod once, by its strongest clue; clues no mod matched are shown as written."""
    seen, shown = set(), []
    for evidence in group.top_evidence(len(group.evidence)):
        name = (evidence.mod or evidence.value).lower()
        if name in seen:
            continue
        seen.add(name)
        shown.append(describe_evidence(evidence))
    extra = len(shown) - limit
    shown = shown[:limit]
    if extra > 0:
        shown.append(f"+{extra} more")
    return "; ".join(shown)


# ---- The summary ----

def summary_report(report, top=20, levels=DEFAULT_LEVELS):
    """The summary as a Report: notices, counts, the top signatures, shared exceptions and what changed."""
    log = report.log
    out = Report(f"Log triage: {log.name}")
    header = log.header
    summary = " ".join(header[k] for k in ("game", "version") if header.get(k))
    if header.get("started"):
        summary += f", started {header['started']}" if summary else f"Started {header['started']}"
    out.lines.append(f"{summary + '. ' if summary else ''}{log.line_total:,} lines, {len(log.entries):,} messages "
                     f"({log.layout} layout).")
    if report.comparison is not None:
        out.lines.append(f"Compared with {report.comparison.previous_name}.")

    if log.notices:
        out.section("Notices", Bullets([n.text for n in log.notices]))

    counts = out.section("Counts", Table(["Level", "Messages", "Signatures"],
                                         [(level, e, s) for level, (e, s) in report.level_counts().items()]))

    shown = [g for g in report.groups if g.level in levels]
    if shown:
        listed = ", ".join(l for l in levels if any(g.level == l for g in shown))
        out.section(f"Signatures ({listed}): top {min(top, len(shown))} of {len(shown)}", Table(
            ["ID", "Count", "Level", "First seen", "Message", "Points at"],
            [(g.id, g.count, g.level, _where(g.first_time, g.first_line), g.example.headline, _points_at(g))
             for g in shown[:top]],
            widths={5: POINTS_AT_WIDTH}))
        shared = clusters(shown)[:CLUSTERS_SHOWN]
        if shared:
            out.section("One exception, several messages",
                        "These signatures' first messages share one exception trace, so each row is most likely one "
                        "problem worded several ways.",
                        Table(["Signatures", "Messages", "Exception", "Points at"],
                              [(", ".join(g.id for g in c.groups[:6]) +
                                (f" (+{len(c.groups) - 6})" if len(c.groups) > 6 else ""),
                                c.count, c.fingerprint, _points_at(c.groups[0])) for c in shared],
                              widths={2: EXCEPTION_WIDTH, 3: POINTS_AT_WIDTH}))
    else:
        counts.blocks.append(f"No messages at the levels shown ({', '.join(levels)}).")

    comparison = report.comparison
    if comparison is not None:
        pick = lambda changes: [c for c in changes if c.group.level in levels]
        new, gone, changed = pick(comparison.new), pick(comparison.gone), pick(comparison.changed)
        out.section(f"Compared with {comparison.previous_name}",
                    f"{len(new):,} new, {len(gone):,} gone and {len(changed):,} changed signatures at the levels "
                    f"shown.")
        for title, changes in (("New", new), ("Gone", gone), ("Changed", changed)):
            if changes:
                out.section(title, Table(["ID", "Before", "Now", "Level", "Message"],
                                         [(c.group.id, c.previous, c.current, c.group.level, c.group.example.headline)
                                          for c in changes[:min(top, CHANGES_SHOWN)]]), level=3)

    out.section("Reading this", Bullets([
        "Mods under \"Points at\" are named from evidence in the log: source lines, file paths, assemblies and "
        "namespaces in exception traces, the code that wrote the message, and Harmony patches on the stack. A mod "
        "named there was involved; it is not necessarily at fault.",
        "Messages that differ only in numbers, IDs and codes share a signature. Show one in full with `--show <ID>`.",
        *log.limits]))
    return out


def to_markdown(report, top=20, levels=DEFAULT_LEVELS, redact=None):
    """The summary, short enough to read whole."""
    return render_markdown(summary_report(report, top, levels), redact)


def detail_report(report, group, max_lines=DETAIL_LINES):
    """One signature in full as a Report: its first message as written, its evidence and where else it occurs."""
    entry = group.example
    out = Report(f"Signature {group.id}")
    out.blocks.append(f"{group.level}{' [' + group.category + ']' if group.category else ''}, {group.count:,} times, "
                      f"first at {_where(group.first_time, group.first_line)}, last at "
                      f"{_where(group.last_time, group.last_line)}.")
    out.blocks.append(f"Signature: {group.signature}")
    if entry.fingerprint:
        out.blocks.append(f"Exception: {entry.fingerprint}")
        siblings = [g.id for g in report.groups
                    if g is not group and g.level == group.level and g.example is not None
                    and g.example.fingerprint == entry.fingerprint]
        if siblings:
            out.blocks.append(f"The same exception also starts: {', '.join(siblings[:20])}.")
    lines = [entry.headline, *entry.body[:max_lines]]
    if len(entry.body) > max_lines:
        lines.append(f"... {len(entry.body) - max_lines:,} more lines")
    last = out.section("First occurrence", Code(lines))
    if group.evidence:
        last = out.section("Evidence", Table(
            ["Kind", "Clue", "Mod", "Messages"],
            [(e.kind, e.value, e.mod or "", n)
             for e, n in sorted(group.evidence.items(), key=lambda item: (item[0].rank, -item[1]))]))
    more = "" if group.count <= len(group.lines) else f" (the first {len(group.lines)} of {group.count:,})"
    last.blocks.append(f"Lines{more}: " + ", ".join(str(n) for n in group.lines))
    return out


def group_detail(report, group, max_lines=DETAIL_LINES, redact=None):
    return render_markdown(detail_report(report, group, max_lines), redact)


# ---- JSON ----

def _evidence_json(group):
    return [{"kind": e.kind, "value": e.value, "mod": e.mod, "messages": n}
            for e, n in sorted(group.evidence.items(), key=lambda item: (item[0].rank, -item[1]))]


def _group_json(group, redact):
    entry = group.example
    return {
        "id": group.id, "level": group.level, "category": group.category,
        "signature": redact(group.signature), "fingerprint": redact(entry.fingerprint), "count": group.count,
        "first": {"line": group.first_line, "time": group.first_time},
        "last": {"line": group.last_line, "time": group.last_time},
        "lines": group.lines,
        "example": {"headline": redact(entry.headline), "body": [redact(l) for l in entry.body[:JSON_BODY_LINES]],
                    "bodyLines": len(entry.body)},
        "evidence": [{**item, "value": redact(item["value"])} for item in _evidence_json(group)],
    }


def to_json(report, redact=None):
    """Everything the report holds, with stable keys."""
    redact = redact or _keep
    log = report.log
    result = {
        "format": JSON_FORMAT,
        "log": {"name": log.name, "layout": log.layout, "lines": log.line_total, "messages": len(log.entries),
                "header": {k: redact(v) for k, v in log.header.items()}},
        "notices": [{"kind": n.kind, "text": redact(n.text), "data": n.data} for n in log.notices],
        "limits": [redact(limit) for limit in log.limits],
        "levels": {level: {"messages": e, "signatures": s} for level, (e, s) in report.level_counts().items()},
        "groups": [_group_json(g, redact) for g in report.groups],
        "clusters": [{"fingerprint": redact(c.fingerprint), "messages": c.count, "groups": [g.id for g in c.groups]}
                     for c in clusters(report.groups)],
    }
    if report.comparison is not None:
        c = report.comparison
        change = lambda ch: {"id": ch.group.id, "level": ch.group.level, "previous": ch.previous,
                             "current": ch.current, "headline": redact(ch.group.example.headline)}
        result["comparison"] = {"previous": c.previous_name, "new": [change(x) for x in c.new],
                                "gone": [change(x) for x in c.gone], "changed": [change(x) for x in c.changed]}
    return result
