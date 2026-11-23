"""connections: how a repository's code fits together, in every language its mods are written in.

    connections summary --root REPO                      what was read, how exactly, and how much of it
    connections find --root REPO --name "*Tick*"         things by name (types, methods, Defs, functions), ours only
    connections around --root REPO --node ID            everything one connection away from one thing, grouped by kind
    connections flow --root REPO --node ID [--depth 2]   who calls it and what it calls, a few steps each way
    connections changed --root REPO --commit HASH        the things a commit changed, by the lines it changed
    connections history --root REPO --node ID           the commits that changed a thing's lines, with the entries they wrote
    connections names --root REPO --file F.cs [--commit HASH]   what every name in one C# file is, and where it is declared

C# is read exactly from the assemblies the repository builds (calls, fields, inheritance, overrides, Harmony patches), and by
name from the source where none is built; XML Defs from the files; Lua by name; Python by its own parser. Every connection says
whether it is exact. The graph is kept in the kit's cache and read again when a file it came from changes (docs/connections.md).
`names` reads one C# file's project from source with Roslyn instead (the names reader; needs the .NET SDK). It only reads.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import re
import subprocess
import sys

from . import changes, code_names, connections
from .connections import csharp, defs, lineage, lua, pycode
from .manifest import READS
from .progress import Progress
from .report import Bullets, Report, Table, envelope_text, home_redactor, keep, render_markdown

EXIT_OK, EXIT_REFUSED, EXIT_USAGE = 0, 1, 2
COMMIT = re.compile(r"^[0-9a-f]{7,40}$")
NODE = re.compile(r"^(cs|def|lua|py):[^\n\r\0]{1,400}$")
READERS = {".cs": csharp, ".xml": defs, ".lua": lua, ".py": pycode}
RELATION_WORDS = {
    "calls": "Calls", "called-by": "Called by", "holds": "Holds", "belongs-to": "Belongs to", "builds-on": "Builds on",
    "built-on-by": "Built on by", "overrides": "Overrides", "overridden-by": "Overridden by", "patches": "Patches",
    "patched-by": "Patched by", "uses": "Uses", "used-by": "Used by", "imports": "Imports", "imported-by": "Imported by"}


def _parser():
    p = argparse.ArgumentParser(prog="connections", description=__doc__.split("\n\n")[0],
                                formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__.split("\n\n", 1)[1])
    sub = p.add_subparsers(dest="report", required=True)
    for name, helptext in (("summary", "what was read, how exactly, and how much"),
                           ("find", "things by name"),
                           ("around", "everything one connection away from one thing"),
                           ("flow", "who calls one thing and what it calls, a few steps each way"),
                           ("changed", "the things a commit changed"),
                           ("history", "the commits that changed one thing's lines, with the changelog entries they wrote"),
                           ("names", "what every name in one C# file is, and where it is declared")):
        s = sub.add_parser(name, help=helptext)
        s.add_argument("--root", help="the repository (default: the current folder)")
        if name == "find":
            s.add_argument("--name", required=True, help="a name or pattern (* and ?)")
            s.add_argument("--kind", action="append", default=[], help="only this kind (repeatable): method, class, def...")
            s.add_argument("--outside", action="store_true", help="also the game's and other mods' things the code uses")
        if name in ("around", "flow", "history"):
            s.add_argument("--node", required=True, help="a thing's id, as find gives it (cs:..., def:..., lua:..., py:...)")
        if name == "flow":
            s.add_argument("--depth", type=int, default=2, choices=(1, 2, 3), help="steps each way (default 2)")
        if name == "history":
            s.add_argument("--limit", type=int, default=lineage.MAX_COMMITS,
                           help=f"commits to give, newest first (default {lineage.MAX_COMMITS}, at most {lineage.LIMIT_CEILING})")
        if name == "changed":
            s.add_argument("--commit", required=True, help="the commit")
        if name == "names":
            s.add_argument("--file", required=True, help="the C# file, relative to the repository")
            s.add_argument("--commit", help="read the file as it stood at this commit (other files as they stand now)")
        s.add_argument("--rebuild", action="store_true", help="read every file again, whatever the cache holds")
        s.add_argument("--top", type=int, default=60, help="rows per table (default 60)")
        s.add_argument("--json", action="store_true", help="print JSON instead of Markdown")
        s.add_argument("--no-redact", action="store_true", help="show the home folder instead of ~")
    return p


def _label(n):
    where = f" ({n['file']}:{n['line']})" if n.get("file") and n.get("line") else (f" [{n['assembly']}]" if n.get("assembly") else "")
    return f"{n['name']}{where}"


def summary_report(conn, root):
    found = connections.summary(conn)
    report = Report(f"Connections: {Path(root).name}")
    if not found["readers"]:
        report.lines.append("No code this tool reads was found (C#, XML Defs, Lua or Python).")
    report.section("Read", Table(["Language", "How", "Things", "Connections"],
                                 [[r["language"], r["how"], f"{r['nodes']:,}", f"{r['edges']:,}"] for r in found["readers"]]))
    report.section("Connections", Table(["Kind", "Exact", "Count"],
                                        [[c["kind"], "yes" if c["exact"] else "by name", f"{c['count']:,}"] for c in found["connections"]]))
    return report, found


def find_report(conn, args):
    found = connections.find(conn, args.name, tuple(args.kind), args.top, ours_only=not args.outside)
    report = Report(f"Connections: {len(found):,} things named like {args.name!r}")
    report.section("Found", Table(["Thing", "Kind", "Where", "Id"],
                                  [[n["name"], n["kind"], f"{n['file']}:{n['line']}" if n["file"] else (n["assembly"] or "-"), n["id"]]
                                   for n in found]))
    return report, {"things": found}


def around_report(conn, args):
    found = connections.around(conn, args.node)
    centre = found["centre"]
    report = Report(f"Connections: {_label(centre)}, {centre['connections']:,} connections")
    for group in found["groups"]:
        words = RELATION_WORDS.get(group["relation"], group["relation"])
        more = f" (showing {len(group['nodes'])})" if group["count"] > len(group["nodes"]) else ""
        report.section(f"{words}: {group['count']:,}{'' if group['exact'] else ', some by name'}{more}",
                       Bullets([_label(n) + ("" if n["exact"] else " (by name)") for n in group["nodes"][:args.top]]))
    return report, found


def flow_report(conn, args):
    found = connections.flow(conn, args.node, args.depth)
    report = Report(f"Connections: the calls around {args.node}")
    for column in found["columns"]:
        step = column["step"]
        title = "It" if step == 0 else (f"Calls it ({-step} step{'s' if step < -1 else ''} away)" if step < 0
                                        else f"It calls ({step} step{'s' if step > 1 else ''} away)")
        report.section(title, Bullets([_label(n) for n in column["nodes"][:args.top]]))
    return report, found


def _changed_lines(root, commit):
    """{file: set of new line numbers} a commit changed; a hunk that only removes lines counts the line where they were."""
    found, path = {}, None
    for line in changes.git(root, "show", "--format=", "--unified=0", "--no-color", "--no-ext-diff", commit, check=False).splitlines():
        if line.startswith("+++ "):
            path = line[6:].strip() if line.startswith("+++ b/") else None
        elif line.startswith("@@") and path:
            match = re.match(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@", line)
            if match:
                start, count = int(match.group(1)), int(match.group(2) or 1)
                found.setdefault(path, set()).update(range(start, start + max(count, 1)))
    return found


def changed_report(conn, root, args):
    if not COMMIT.match(args.commit):
        raise connections.ConnectionsError(f"{args.commit!r} is not a commit.")
    described = changes.describe(root, args.commit)
    if described is None:
        raise connections.ConnectionsError(f"{args.commit!r} is not a commit of this repository.")
    things, files = {}, []
    for path, lines in sorted(_changed_lines(root, args.commit).items()):
        reader = READERS.get(Path(path).suffix.lower())
        if reader is None:
            continue
        text = changes.git(root, "show", f"{args.commit}:{path}", check=False)
        declared = reader.declared_in(text, path) if text else []
        counted = 0
        for line in lines:
            holding = [d for d in declared if d[1] <= line <= d[2]]
            if holding:
                inner = min(holding, key=lambda d: d[2] - d[1])
                entry = things.setdefault(inner[0], {"id": inner[0], "file": path, "linesChanged": 0})
                entry["linesChanged"] += 1
                counted += 1
        files.append({"file": path, "lines": len(lines), "placed": counted})
    found = []
    for item in sorted(things.values(), key=lambda t: -t["linesChanged"]):
        current = connections.node(conn, item["id"])
        found.append({**(current or {"id": item["id"], "name": item["id"].split(":", 1)[1].rsplit(".", 1)[-1], "file": item["file"]}),
                      "linesChanged": item["linesChanged"], "inGraph": current is not None})
    report = Report(f"Connections: {described.hash[:8]} changed {len(found):,} things")
    report.lines.append(f"{described.subject}.")
    report.section("Changed", Table(["Thing", "Kind", "Lines changed", "Still there"],
                                    [[t["name"], t.get("kind", "-"), f"{t['linesChanged']:,}", "yes" if t["inGraph"] else "no"]
                                     for t in found[:args.top]], total=len(found)))
    return report, {"commit": {"hash": described.hash, "subject": described.subject}, "things": found, "files": files}


def history_report(conn, root, args):
    found = connections.node(conn, args.node)
    if found is None:
        raise connections.ConnectionsError(f"{args.node!r} is not in this repository's connections.")
    if found["external"] or not found["file"] or not found["line"]:
        raise connections.ConnectionsError(f"{found['name']} is not in this repository's files, so it has no history here.")
    data = lineage.history(root, found, max(1, min(getattr(args, "limit", lineage.MAX_COMMITS), lineage.LIMIT_CEILING)))
    report = Report(f"Connections: {found['name']} changed in {len(data['commits']):,} commit{'' if len(data['commits']) == 1 else 's'}"
                    + (" (the newest shown)" if data["more"] else ""))
    report.lines.append(f"Lines {data['lines'][0]} to {data['lines'][1]} of {data['file']}, followed back as they moved.")
    report.section("Commits", Table(["When", "Commit", "Subject", "Entries it wrote"],
                                    [[c["time"][:10], c["hash"][:8], c["subject"], f"{len(c['entries']):,}"] for c in data["commits"]]))
    return report, {"node": found, **data}


def names_report(root, args, environ, progress, run=subprocess.run, tool=None):
    """Every name in one C# file: what it is and where it is declared (the names reader)."""
    if args.commit and not COMMIT.match(args.commit):
        raise connections.ConnectionsError(f"{args.commit!r} is not a commit.")
    try:
        found = code_names.read(root, args.file, args.commit, environ, run, progress, tool)
    except code_names.NamesError as error:
        raise connections.ConnectionsError(str(error)) from None
    kinds, ours = code_names.counts(found)
    when = f" as it stood at {args.commit[:8]}" if args.commit else ""
    report = Report(f"Names: {found['file']}{when}, {len(found['names']):,} names, {ours:,} declared in this repository")
    report.lines.append(f"Read with Roslyn from {', '.join(found['projects'])} in {found['seconds']:.1f} s; "
                        f"{found['errors']:,} errors in the file as the reader built it.")
    for limit in found["limits"]:
        report.lines.append(limit)
    report.section("Kinds", Table(["Kind", "Names"], [[kind, f"{count:,}"] for kind, count in kinds.items()]))
    elsewhere = {}
    for name in found["names"]:
        assembly = name["declared"].get("assembly")
        if assembly:
            elsewhere[assembly] = elsewhere.get(assembly, 0) + 1
    report.section("Declared outside this repository", Table(
        ["Assembly", "Names"], [[a, f"{n:,}"] for a, n in sorted(elsewhere.items(), key=lambda kv: -kv[1])[:args.top]]))
    return report, found


def main(argv=None, environ=None, out=None):
    out = out or sys.stdout
    environ = os.environ if environ is None else environ
    try:
        args = _parser().parse_args(list(sys.argv[1:] if argv is None else argv))
    except SystemExit as stop:
        return EXIT_USAGE if stop.code else EXIT_OK
    redact = keep if args.no_redact else home_redactor()
    progress = Progress(environ)
    root = Path(args.root or ".").resolve()
    code = EXIT_OK
    try:
        if not root.is_dir():
            raise connections.ConnectionsError(f"{root} is not a folder.")
        if getattr(args, "node", None) and not NODE.match(args.node):
            raise connections.ConnectionsError(f"{args.node!r} is not a thing's id.")
        if args.report == "names":
            report, data = names_report(root, args, environ, progress)
            data = {"repository": root.name, **data}
            out.write((envelope_text("connections", report, redact, data) if args.json else render_markdown(report, redact)) + "\n")
            return code
        conn = connections.open_graph(root, environ, None, progress, args.rebuild)
        try:
            if args.report == "summary":
                report, data = summary_report(conn, root)
            elif args.report == "find":
                report, data = find_report(conn, args)
            elif args.report == "around":
                report, data = around_report(conn, args)
            elif args.report == "flow":
                report, data = flow_report(conn, args)
            elif args.report == "history":
                report, data = history_report(conn, root, args)
            else:
                report, data = changed_report(conn, root, args)
        finally:
            conn.close()
        data = {"repository": root.name, **data}
    except (connections.ConnectionsError, changes.ChangesError, OSError) as error:
        if not args.json:
            print(redact(str(error)), file=sys.stderr)
            return EXIT_REFUSED
        report, data = Report("Refused"), {"ok": False, "refusal": str(error)}
        report.lines.append(str(error))
        code = EXIT_REFUSED
    out.write((envelope_text("connections", report, redact, data) if args.json else render_markdown(report, redact)) + "\n")
    return code


MANIFEST = {"game": None, "parser": _parser, "effect": READS,
            "reports": {"summary": {"question": "How does this repository's code fit together?", "surface": "connections"},
                        "find": {"note": "things by name; needs the name"},
                        "around": {"note": "everything one connection away from one thing; needs its id"},
                        "flow": {"note": "the calls around one thing, a few steps each way; needs its id"},
                        "changed": {"note": "the things a commit changed; needs the commit"},
                        "history": {"note": "the commits that changed one thing, with the entries they wrote; needs its id"},
                        "names": {"note": "what every name in one C# file is and where it is declared; needs the file"}}}
