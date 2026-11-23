"""connections: how a repository's code fits together, in every language its mods are written in.

    connections summary --root REPO                      what was read, how exactly, and how much of it
    connections find --root REPO --name "*Tick*"         things by name (types, methods, Defs, functions), ours only
    connections around --root REPO --node ID            everything one connection away from one thing, grouped by kind
    connections flow --root REPO --node ID [--depth 2]   who calls it and what it calls, a few steps each way
    connections changed --root REPO --commit HASH        the things a commit changed, by the lines it changed
    connections history --root REPO --node ID           the commits that changed a thing's lines, with the entries they wrote
    connections names --root REPO --file F [--commit HASH]   what every name in one file is, and where it is declared
    connections calls --root REPO --commit HASH [--game G]   what a commit did to its C# methods' calls; rings made or cut
    connections jumps --root REPO --game G               what each rule for names between data files and code reads here

C# is read exactly from the assemblies the repository builds (calls, fields, inheritance, overrides, Harmony patches), and by
name from the source where none is built; XML Defs from the files; Lua by name; Python by its own parser. Every connection says
whether it is exact. The graph is kept in the kit's cache and read again when a file it came from changes (docs/connections.md).
`names` reads a C# file's project from source with Roslyn instead (the names reader; needs the .NET SDK), and a Lua, Python or
XML file by name from the graph. With `--game`, a game that has a table of them (data_names) adds the names that cross between
its data files and its code: to the graph as things and uses, and to `names` as names to follow. It only reads.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import re
import subprocess
import sys
import time

from . import changes, code_calls, code_names, connections, data_names
from .connections import csharp, defs, lineage, lua, pycode
from .manifest import READS
from .progress import Progress
from .report import Bullets, Report, Table, envelope_text, home_redactor, keep, render_markdown

EXIT_OK, EXIT_REFUSED, EXIT_USAGE = 0, 1, 2
COMMIT = re.compile(r"^[0-9a-f]{7,40}$")
NODE = re.compile(r"^(cs|def|lua|py|data):[^\n\r\0]{1,400}$")
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
                           ("names", "what every name in one file is, and where it is declared"),
                           ("calls", "what a commit did to its C# methods' calls, and the rings of calls it made or cut"),
                           ("jumps", "what each rule for names between data files and code reads in this repository")):
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
            s.add_argument("--file", required=True, help="the file (C#, Lua, Python or XML), relative to the repository")
            s.add_argument("--commit", help="read the file as it stood at this commit (other files as they stand now)")
        if name == "calls":
            s.add_argument("--commit", required=True, help="the commit")
        s.add_argument("--game", required=name == "jumps",
                       help="the game the repository's mods are for (rimworld, ostranauts): adds the names its table says "
                            "cross between data files and code; for calls, also follows a ring through the game's own code")
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


def changed_report(conn, root, args, table=None):
    if not COMMIT.match(args.commit):
        raise connections.ConnectionsError(f"{args.commit!r} is not a commit.")
    described = changes.describe(root, args.commit)
    if described is None:
        raise connections.ConnectionsError(f"{args.commit!r} is not a commit of this repository.")
    things, files = {}, []
    for path, lines in sorted(_changed_lines(root, args.commit).items()):
        reader = READERS.get(Path(path).suffix.lower())
        declares = bool(table) and any(thing.holds(path) for thing in table.things.values() if not thing.alias_of)
        if reader is None and not declares:
            continue
        text = changes.git(root, "show", f"{args.commit}:{path}", check=False)
        declared = list(reader.declared_in(text, path)) if (text and reader) else []
        if text and declares:      # the things a game's data files declare (a translation key, a data object), 1.117.0
            declared += [(item["id"], item["line"], item["end"]) for item in data_names.declared_in(table, text, path)]
        counted = 0
        for line in lines:
            holding = [d for d in declared if d[1] <= line <= d[2]]
            if holding:
                inner = min(holding, key=lambda d: d[2] - d[1])
                entry = things.setdefault(inner[0], {"id": inner[0], "file": path, "linesChanged": 0,
                                                     "at": {"file": path, "line": inner[1], "end": inner[2]}})
                entry["linesChanged"] += 1
                counted += 1
        files.append({"file": path, "lines": len(lines), "placed": counted})
    found = []
    for item in sorted(things.values(), key=lambda t: -t["linesChanged"]):
        current = connections.node(conn, item["id"])
        found.append({**(current or {"id": item["id"], "name": item["id"].split(":", 1)[1].rsplit(".", 1)[-1], "file": item["file"]}),
                      "linesChanged": item["linesChanged"], "inGraph": current is not None, "at": item["at"]})
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


def _file_text(root, file, commit):
    """A file of the repository as it stands, or as it stood at a commit."""
    target = (root / file).resolve()
    if root not in target.parents:
        raise connections.ConnectionsError(f"{file} is not inside the repository.")
    if commit:
        text = changes.git(root, "show", f"{commit}:{Path(file).as_posix()}", check=False)
        if not text:
            raise connections.ConnectionsError(f"{file} did not exist at {commit[:8]}.")
        return text
    try:
        return target.read_text(encoding="utf-8", errors="replace")
    except OSError as error:
        raise connections.ConnectionsError(f"{file} could not be read: {error}") from None


def _no_names(file, commit):
    return {"file": file, "project": None, "projects": [], "names": [], "snippets": {}, "errors": 0, "missingReferences": 0,
            "seconds": 0, "commit": commit, "exact": False, "limits": []}


def _also(ruled):
    """What a C# name also stands for in the game's data, as a rule read it: a DefOf field's Def."""
    return {"rule": ruled["rule"], "ruleWords": ruled["ruleWords"], "candidates": ruled["candidates"], "more": ruled["more"]}


#: The C# names that may be declared where a rule reads a data thing's name (a DefOf field), and how many files are read for them.
_ALSO_KINDS = {"field", "property", "constant"}
_ALSO_FILES = 60


def _add_rule_names(found, table, conn, root, file, text, exact_base):
    """Adds the names a game's table reads in the file (1.117.0) to what was read from it. Over names read by name, a rule's
    reading takes their place. A C# name keeps its own exact reading and gains what the rule says it `also` stands for: at its own
    place, and wherever it is used, by the rule's reading of the line that declares it."""
    held = data_names.index(table, root, data_names.store_nodes(conn))
    ruled = data_names.as_names(data_names.read(table, held, file, text), file) + data_names.declarations(table, file, text)
    by_line = {}
    for name in ruled:
        by_line.setdefault(name["line"], []).append(name)
    kept = []
    for name in found["names"]:
        over = [r for r in by_line.get(name["line"], ())
                if r["column"] < name["column"] + name["length"] and name["column"] < r["column"] + r["length"]]
        if over and not exact_base:
            continue
        for rule_name in over:
            rule_name["dropped"] = True
            if rule_name["candidates"] and (rule_name["column"], rule_name["length"]) == (name["column"], name["length"]):
                name["also"] = _also(rule_name)
        kept.append(name)
    ruled = [name for name in ruled if not name.pop("dropped", False)]
    if exact_base:
        wanted = {}
        for name in kept:
            where = name["declared"].get("file")
            if where and "also" not in name and name["kind"] in _ALSO_KINDS:
                wanted.setdefault(where, []).append(name)
        for where, names in list(wanted.items())[:_ALSO_FILES]:
            try:
                other = text if where == file else (root / where).read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            declared = {(r["line"], r["text"]): r for r in data_names.as_names(data_names.read(table, held, where, other), where)
                        if r["candidates"]}
            for name in names:
                rule_name = declared.get((name["declared"].get("line"), name["text"]))
                if rule_name:
                    name["also"] = _also(rule_name)
    files = {}
    for name in ruled + [n for n in kept if "also" in n]:
        for thing in (name["also"]["candidates"] if "also" in name else name["candidates"]):
            key = f"{thing['file']}:{thing['line']}"
            if key not in found["snippets"]:
                snippet = code_names.snippet(root, thing, files)
                if snippet:
                    found["snippets"][key] = snippet
    found["names"] = sorted(kept + ruled, key=lambda n: (n["line"], n["column"]))
    found["game"] = table.source
    found["limits"].append(f"Names between data files and code are read by the rules for {table.source}, from the text: each "
                           "says which rule read it, and one may be wrong.")


def names_report(root, args, environ, progress, run=subprocess.run, tool=None):
    """Every name in one file and where it is declared: exactly in C# (the names reader); by name in Lua, Python and XML; and,
    with a game that has a table of them, the names that cross between its data files and its code, by its rules (1.117.0)."""
    if args.commit and not COMMIT.match(args.commit):
        raise connections.ConnectionsError(f"{args.commit!r} is not a commit.")
    file, suffix = Path(args.file).as_posix(), Path(args.file).suffix.lower()
    game = getattr(args, "game", None)
    table = data_names.table_for(game)
    by_name = suffix in code_names.BY_NAME
    ruled = bool(table) and any(rule.reads(file) for rule in table.rules) or \
        bool(table) and any(thing.holds(file) for thing in table.things.values() if not thing.alias_of)
    unread = suffix != ".cs" and not by_name and not ruled
    if unread and suffix not in data_names.read_suffixes():
        raise connections.ConnectionsError(f"{args.file} is not a file whose names are read: C#, Lua, Python or XML, or a data "
                                           "file a game's rules read.")
    conn = None
    try:
        if unread:                 # a data file no rule of this game reads: it has no names, and that is the answer
            found = _no_names(file, args.commit)
            found["limits"].append("No rule reads this file's names" + (f" for {table.source}." if table else
                                   ": name the game its repository is for (--game)."))
        elif suffix == ".cs":
            try:
                found = code_names.read(root, args.file, args.commit, environ, run, progress, tool)
            except code_names.NamesError as error:
                if not ruled:
                    raise
                found = _no_names(file, args.commit)
                found["limits"].append(f"The C# names were not read ({error}): only what the rules for {table.source} read is "
                                       "given.")
        if not unread and (suffix != ".cs" or ruled):
            text = _file_text(root, args.file, args.commit)
            conn = connections.open_graph(root, environ, None, progress, args.rebuild, game)
            if suffix != ".cs":
                found = (code_names.read_by_name(conn, root, file, text, args.commit)
                         if by_name and not (table and table.is_prose(file)) else _no_names(file, args.commit))
            if ruled:
                _add_rule_names(found, table, conn, root, file, text, exact_base=suffix == ".cs")
    except code_names.NamesError as error:
        raise connections.ConnectionsError(str(error)) from None
    finally:
        if conn is not None:
            conn.close()
    by_name = suffix != ".cs"
    kinds, ours = code_names.counts(found)
    when = f" as it stood at {args.commit[:8]}" if args.commit else ""
    report = Report(f"Names: {found['file']}{when}, {len(found['names']):,} names, {ours:,} declared in this repository")
    if not by_name and found["projects"]:
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


def _ring_words(ring):
    return " → ".join(step["display"] for step in ring) + f" → {ring[0]['display']}"


def calls_report(root, args, environ, progress, run=subprocess.run, tool=None, reader=None):
    """What a commit did to its C# methods' calls, and the rings of calls it made or cut (1.116.0)."""
    if not COMMIT.match(args.commit):
        raise connections.ConnectionsError(f"{args.commit!r} is not a commit.")
    try:
        found = code_calls.read(root, args.commit, args.game, environ, run, progress, tool, reader)
    except code_names.NamesError as error:
        raise connections.ConnectionsError(str(error)) from None
    made, cut = found["rings"]["made"], found["rings"]["cut"]
    report = Report(f"Calls: {found['commit']['hash'][:8]} changed {len(found['methods']):,} methods' calls"
                    + (f"; made {len(made)} ring{'s' if len(made) != 1 else ''}" if made else "")
                    + (f"; cut {len(cut)} ring{'s' if len(cut) != 1 else ''}" if cut else ""))
    if found["commit"]["subject"]:
        report.lines.append(f"{found['commit']['subject']}.")
    for limit in found["limits"]:
        report.lines.append(limit)
    report.section("Methods", Table(
        ["Method", "What happened", "Calls gone", "Calls new", "Kept"],
        [[m["display"], m["status"], f"{len(m['gone']):,}", f"{len(m['new']):,}", f"{len(m['kept']):,}"]
         for m in found["methods"][:args.top]], total=len(found["methods"])))
    if made:
        report.section("Rings this commit made", Bullets([_ring_words(r) for r in made]))
    if cut:
        report.section("Rings this commit cut", Bullets([_ring_words(r) for r in cut]))
    return report, found


def jumps_report(conn, root, args, table, progress):
    """What each of a game's rules for names between data files and code reads in this repository (1.117.0): how many names, and
    how many stand for one thing, for several, or for nothing here. The count a rule passes before it is kept, and the one to run
    on a next game's table."""
    started = time.monotonic()
    held = data_names.index(table, root, data_names.store_nodes(conn))
    found = data_names.count(table, held, root, samples=max(1, min(args.top, 40)), progress=progress)
    found["game"] = table.source
    found["seconds"] = round(time.monotonic() - started, 2)
    rules = found["rules"]
    total = sum(rule["matches"] for rule in rules)
    report = Report(f"Jumps: {Path(root).name}, {total:,} names read by the {len(rules)} rules for {table.source}")
    report.lines.append("A rule reads text. One thing: the name has one thing to stand for. Several: more than one has the name. "
                        "Nothing here: no thing of this repository has it (the game's, another mod's, or a mistake).")
    report.section("Things a name may stand for", Table(
        ["Thing", "From", "How many", "Names shared"],
        [[thing["kind"], "the connections" if thing["from"] == "graph" else "the files the table names", f"{thing['count']:,}",
          f"{thing['shared']:,}"] for thing in found["things"]]))
    report.section("Rules", Table(
        ["Rule", "What it reads", "In", "Names read", "One thing", "Several", "Nothing here"],
        [[rule["id"], rule["words"] + (" (only names that are things)" if rule["known"] else ""), ", ".join(rule["in"]),
          f"{rule['matches']:,}", f"{rule['one']:,}", f"{rule['several']:,}", f"{rule['none']:,}"] for rule in rules]))
    for rule in rules:
        if rule["noneTop"]:
            more = f" ({rule['noneDistinct']:,} names in all)" if rule["noneDistinct"] > len(rule["noneTop"]) else ""
            report.section(f"{rule['id']}: named nothing here{more}",
                           Bullets([f"{n['name']} ({n['count']:,})" for n in rule["noneTop"]]))
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
        if args.report in ("names", "calls"):
            report, data = (names_report if args.report == "names" else calls_report)(root, args, environ, progress)
            data = {"repository": root.name, **data}
            out.write((envelope_text("connections", report, redact, data) if args.json else render_markdown(report, redact)) + "\n")
            return code
        table = data_names.table_for(args.game)
        if args.report == "jumps" and table is None:
            raise connections.ConnectionsError(f"No game named {args.game!r} has a table of the names between its data files and "
                                               f"its code yet. Those that have: {', '.join(data_names.tables())}.")
        conn = connections.open_graph(root, environ, None, progress, args.rebuild, args.game)
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
            elif args.report == "jumps":
                report, data = jumps_report(conn, root, args, table, progress)
            else:
                report, data = changed_report(conn, root, args, table)
        finally:
            conn.close()
        data = {"repository": root.name, **data}
    except (connections.ConnectionsError, data_names.DataNamesError, changes.ChangesError, OSError) as error:
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
                        "names": {"note": "what every name in one file is and where it is declared; needs the file"},
                        "calls": {"note": "what a commit did to its C# methods' calls, and rings made or cut; needs the commit"},
                        "jumps": {"note": "what each rule for names between data files and code reads; needs the game"}}}
