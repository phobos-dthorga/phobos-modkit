"""Reports as a short Markdown summary for people and agent sessions, or as complete JSON for programs."""
from __future__ import annotations

import re
from pathlib import Path

from .triage import clusters

DEFAULT_LEVELS = ("FATAL", "ERROR", "WARN", "UNKNOWN")
CLUSTERS_SHOWN = 10
CELL_LIMIT = 140
DETAIL_LINES = 60
JSON_BODY_LINES = 80
JSON_FORMAT = 1


# ---- Privacy ----

def home_redactor(home=None):
    """A function that replaces the user's home folder with ~ in any text, whichever slashes the text uses."""
    home = str(Path.home() if home is None else home).rstrip("\\/")
    if len(home) < 3:
        return lambda text: text
    variants = {home, home.replace("\\", "/"), home.replace("/", "\\")}
    pattern = re.compile("|".join(re.escape(v) for v in sorted(variants, key=len, reverse=True)), re.IGNORECASE)
    return lambda text: pattern.sub("~", text)


def _keep(text):
    return text


# ---- Shared formatting ----

def _cell(text, limit=CELL_LIMIT):
    text = " ".join(str(text).split())
    if len(text) > limit:
        text = text[:limit].rstrip() + "..."
    return text.replace("|", "\\|")


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


# ---- Markdown ----

def to_markdown(report, top=20, levels=DEFAULT_LEVELS, redact=None):
    """A summary short enough to read whole: notices, counts, the top signatures and what changed."""
    redact = redact or _keep
    log = report.log
    out = [f"# Log triage: {log.name}", ""]
    header = log.header
    summary = " ".join(header[k] for k in ("game", "version") if header.get(k))
    if header.get("started"):
        summary += f", started {header['started']}" if summary else f"Started {header['started']}"
    out.append(f"{summary + '. ' if summary else ''}{log.line_total:,} lines, {len(log.entries):,} messages "
               f"({log.layout} layout).")
    if report.comparison is not None:
        out.append(f"Compared with {report.comparison.previous_name}.")
    out.append("")

    if log.notices:
        out += ["## Notices", ""]
        out += [f"- {redact(n.text)}" for n in log.notices]
        out.append("")

    out += ["## Counts", "", "| Level | Messages | Signatures |", "| --- | --- | --- |"]
    for level, (entries, signatures) in report.level_counts().items():
        out.append(f"| {level} | {entries:,} | {signatures:,} |")
    out.append("")

    shown = [g for g in report.groups if g.level in levels]
    if shown:
        out += [f"## Signatures ({', '.join(l for l in levels if any(g.level == l for g in shown))}): "
                f"top {min(top, len(shown))} of {len(shown)}", "",
                "| ID | Count | Level | First seen | Message | Points at |", "| --- | --- | --- | --- | --- | --- |"]
        for g in shown[:top]:
            out.append(f"| {g.id} | {g.count:,} | {g.level} | {_where(g.first_time, g.first_line)} | "
                       f"{_cell(redact(g.example.headline))} | {_cell(redact(_points_at(g)), 100)} |")
        out.append("")
        shared = [c for c in clusters(shown)][:CLUSTERS_SHOWN]
        if shared:
            out += ["## One exception, several messages", "",
                    "These signatures' first messages share one exception trace, so each row is most likely one "
                    "problem worded several ways.", "",
                    "| Signatures | Messages | Exception | Points at |", "| --- | --- | --- | --- |"]
            for c in shared:
                ids = ", ".join(g.id for g in c.groups[:6]) + (f" (+{len(c.groups) - 6})" if len(c.groups) > 6 else "")
                out.append(f"| {ids} | {c.count:,} | {_cell(redact(c.fingerprint), 160)} | "
                           f"{_cell(redact(_points_at(c.groups[0])), 100)} |")
            out.append("")
    else:
        out += [f"No messages at the levels shown ({', '.join(levels)}).", ""]

    comparison = report.comparison
    if comparison is not None:
        pick = lambda changes: [c for c in changes if c.group.level in levels]
        new, gone, changed = pick(comparison.new), pick(comparison.gone), pick(comparison.changed)
        out += [f"## Compared with {comparison.previous_name}", "",
                f"{len(new):,} new, {len(gone):,} gone and {len(changed):,} changed signatures at the levels shown.",
                ""]
        for title, changes in (("New", new), ("Gone", gone), ("Changed", changed)):
            if not changes:
                continue
            out += [f"### {title}", "", "| ID | Before | Now | Level | Message |", "| --- | --- | --- | --- | --- |"]
            for c in changes[:min(top, 10)]:
                out.append(f"| {c.group.id} | {c.previous:,} | {c.current:,} | {c.group.level} | "
                           f"{_cell(redact(c.group.example.headline))} |")
            out.append("")

    out += ["## Reading this", ""]
    out.append("- Mods under \"Points at\" are named from evidence in the log: source lines, file paths, assemblies "
               "and namespaces in exception traces, the code that wrote the message, and Harmony patches on the "
               "stack. A mod named there was involved; it is not necessarily at fault.")
    out.append("- Messages that differ only in numbers, IDs and codes share a signature. Show one in full with "
               "`--show <ID>`.")
    out += [f"- {redact(limit)}" for limit in log.limits]
    out.append("")
    return "\n".join(out)


def group_detail(report, group, max_lines=DETAIL_LINES, redact=None):
    """One signature in full: its first message as written, its evidence and where else it occurs."""
    redact = redact or _keep
    entry = group.example
    out = [f"# Signature {group.id}", "",
           f"{group.level}{' [' + group.category + ']' if group.category else ''}, {group.count:,} times, first at "
           f"{_where(group.first_time, group.first_line)}, last at {_where(group.last_time, group.last_line)}.", "",
           f"Signature: {redact(group.signature)}", ""]
    if entry.fingerprint:
        out += [f"Exception: {redact(entry.fingerprint)}", ""]
        siblings = [g.id for g in report.groups
                    if g is not group and g.level == group.level and g.example is not None
                    and g.example.fingerprint == entry.fingerprint]
        if siblings:
            out += [f"The same exception also starts: {', '.join(siblings[:20])}.", ""]
    out += ["## First occurrence", "", "```text", redact(entry.headline)]
    body = entry.body[:max_lines]
    out += [redact(line) for line in body]
    if len(entry.body) > max_lines:
        out.append(f"... {len(entry.body) - max_lines:,} more lines")
    out += ["```", ""]
    if group.evidence:
        out += ["## Evidence", "", "| Kind | Clue | Mod | Messages |", "| --- | --- | --- | --- |"]
        for evidence, count in sorted(group.evidence.items(), key=lambda item: (item[0].rank, -item[1])):
            out.append(f"| {evidence.kind} | {_cell(redact(evidence.value))} | {_cell(evidence.mod or '')} | "
                       f"{count:,} |")
        out.append("")
    more = "" if group.count <= len(group.lines) else f" (the first {len(group.lines)} of {group.count:,})"
    out += [f"Lines{more}: " + ", ".join(str(n) for n in group.lines), ""]
    return "\n".join(out)


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
