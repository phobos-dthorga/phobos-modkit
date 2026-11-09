"""code: find, outline and show C# declarations, and every line using a name, across indexed source trees.

    code --corpus NAME=PATH ... find "*ApplyDamage*"          declarations whose name matches (* and ?)
    code --corpus NAME=PATH ... outline VehicleStatHandler    a type's members with their lines
    code --corpus NAME=PATH ... show VehicleStatHandler.ApplyDamage   the source, numbered (every overload)
    code --corpus NAME=PATH ... refs HighlightedComponent     every line using the name, by the member it is in
    code --each-in DIR ... summary                            each child of DIR is a corpus; their sizes

Indexes are built on first use and again when a corpus's files change; --in narrows a query to matching corpora.
"""
from __future__ import annotations

import argparse
import fnmatch
from pathlib import Path
import re
import sys

from .. import cache as derived
from ..report import Code, Report, Table, envelope_text, home_redactor, keep, render_markdown
from . import index
from ..manifest import READS

EXIT_OK, EXIT_FAILED, EXIT_USAGE = 0, 1, 2
REPORTS = ("summary", "find", "outline", "show", "refs")
FLAGS = ("--rebuild", "--json", "--no-redact", "--raw")      # options that take no value
DECOMPILER_NOTE = re.compile(r"^\s*//IL_[0-9A-Fa-f]+:")
SHOW_LINES = 150
TEXT_WIDTH = 150


def _parser():
    common = argparse.ArgumentParser(add_help=False)
    s = common.add_argument_group("which source")
    s.add_argument("--corpus", action="append", default=[], metavar="NAME=PATH",
                   help="a source tree (a folder or one .cs file) under a name; repeatable")
    s.add_argument("--each-in", action="append", default=[], metavar="DIR",
                   help="every folder and .cs file directly inside DIR is a corpus, named after it; repeatable")
    s.add_argument("--in", dest="within", action="append", default=[], metavar="PATTERN",
                   help="query only corpora whose name matches (* and ?); repeatable")
    s.add_argument("--cache", help="where indexes are kept (else PHOBOS_MODKIT_CACHE, settings, the temp folder)")
    s.add_argument("--settings", help="a JSON settings file with modkitCachePath")
    s.add_argument("--rebuild", action="store_true", help="index the chosen corpora again")
    o = common.add_argument_group("output")
    o.add_argument("--top", type=int, default=40, help="rows per table (default 40)")
    o.add_argument("--json", action="store_true", help="print JSON instead of Markdown")
    o.add_argument("--no-redact", action="store_true", help="show the home folder instead of ~")
    p = argparse.ArgumentParser(prog="code", description=__doc__.split("\n\n")[0],
                                formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__.split("\n\n", 1)[1])
    sub = p.add_subparsers(dest="report", metavar="report")
    sub.add_parser("summary", parents=[common], help="the corpora, their files and declarations")
    f = sub.add_parser("find", parents=[common], help="declarations whose name or full name matches")
    f.add_argument("pattern")
    f.add_argument("--kind", action="append", default=[], help="only these kinds (class, method, property, field, ...)")
    o = sub.add_parser("outline", parents=[common], help="a type's members, in source order")
    o.add_argument("name", help="a type's name or dotted full name")
    w = sub.add_parser("show", parents=[common], help="a declaration's source, numbered")
    w.add_argument("name", help="Type, Type.Member or Namespace.Type.Member")
    w.add_argument("--lines", type=int, default=SHOW_LINES, help=f"lines shown per declaration (default {SHOW_LINES}; 0 for all)")
    w.add_argument("--raw", action="store_true", help="keep the decompiler's //IL_ notes")
    r = sub.add_parser("refs", parents=[common], help="every line using a name, grouped by the member it is in")
    r.add_argument("name", help="an identifier; a dotted name searches for its last part")
    return p


def corpora(args):
    found = []
    for spec in args.corpus:
        name, sep, path = spec.partition("=")
        if not sep or not name or not path:
            raise index.CodeError(f"--corpus takes NAME=PATH, not {spec!r}")
        found.append(index.Corpus(name, Path(path)))
    for folder in args.each_in:
        folder = Path(folder)
        if not folder.is_dir():
            raise index.CodeError(f"--each-in: no folder at {folder}")
        for child in sorted(folder.iterdir(), key=lambda p: p.name.lower()):
            if child.is_dir() or child.suffix.lower() == ".cs":
                found.append(index.Corpus(child.name, child))
    if not found:
        raise index.CodeError("Name the source with --corpus NAME=PATH or --each-in DIR")
    if args.within:
        found = [c for c in found if any(fnmatch.fnmatchcase(c.name.lower(), p.lower()) for p in args.within)]
        if not found:
            raise index.CodeError(f"No corpus matches {', '.join(args.within)}")
    return found


def _where(hit):
    return f"{hit.corpus}:{hit.path}:{hit.start}" + (f"-{hit.end}" if hit.end != hit.start else "")


def _cut(text, width):
    return text if len(text) <= width else text[:width - 3] + "..."


def find_report(chosen, args):
    hits = []
    for corpus, path in chosen:
        hits += index.find(path, corpus.name, args.pattern, args.kind, args.top)
    report = Report(f"code find {args.pattern}")
    report.lines.append(f"{len(hits)} declarations match." if len(hits) <= args.top else
                        f"More than {args.top} declarations match; showing {args.top}.")
    report.section("Declarations", Table(["Kind", "Name", "Signature", "Where"],
                                         [[h.kind, h.full, _cut(h.signature, 110), _where(h)] for h in hits[:args.top]],
                                         total=len(hits), widths={2: 110}))
    return report


def _resolve_all(chosen, name, kinds=()):
    hits = []
    for corpus, path in chosen:
        hits += index.resolve(path, corpus.name, name, kinds)
    return hits


def outline_report(chosen, args):
    types = _resolve_all(chosen, args.name, index.TYPE_KINDS)
    report = Report(f"code outline {args.name}")
    if not types:
        report.lines.append(f"No type named {args.name}. Try: code find \"*{args.name.rsplit('.', 1)[-1]}*\" --kind class")
        return report, EXIT_FAILED
    for hit in types[:5]:
        rows = []
        for corpus, path in chosen:
            if corpus.name == hit.corpus:
                rows = [[str(m.start), m.kind, _cut(m.signature, 120)] for m in index.members(path, corpus.name, hit.full)
                        if m.path == hit.path]
        report.section(f"{hit.kind} {hit.full} ({_where(hit)})", Table(["Line", "Kind", "Signature"], rows[:args.top * 3],
                                                                       total=len(rows), widths={2: 120}))
    if len(types) > 5:
        report.lines.append(f"{len(types)} types match; showing 5. Narrow with a dotted name or --in.")
    return report, EXIT_OK


def show_report(chosen, args):
    hits = _resolve_all(chosen, args.name)
    report = Report(f"code show {args.name}")
    if not hits:
        report.lines.append(f"Nothing named {args.name}. Try: code find \"*{args.name.rsplit('.', 1)[-1]}*\"")
        return report, EXIT_FAILED
    roots = {c.name: c for c, _ in chosen}
    shown = hits[:8]
    if len(hits) > len(shown):
        report.lines.append(f"{len(hits)} declarations match; showing {len(shown)}. Narrow with a dotted name or --in.")
    for hit in shown:
        corpus = roots[hit.corpus]
        root = Path(corpus.root)
        source = root if root.is_file() else root / hit.path
        lines = source.read_text(encoding="utf-8", errors="replace").split("\n")[hit.start - 1:hit.end]
        width = len(str(hit.end))
        kept = [(hit.start + i, line) for i, line in enumerate(lines) if args.raw or not DECOMPILER_NOTE.match(line)]
        hidden = len(lines) - len(kept)
        limit = args.lines if args.lines > 0 else len(kept)
        numbered = [f"{number:>{width}}| {line.rstrip()}" for number, line in kept[:limit]]
        if len(kept) > limit:
            numbered.append(f"... {len(kept) - limit} more lines (--lines 0 shows all; outline lists the members)")
        if hidden:
            numbered.append(f"({hidden} decompiler notes such as //IL_0047 hidden; --raw shows them)")
        report.section(f"{hit.kind} {hit.full} ({_where(hit)})", Code(numbered, "csharp"))
    return report, EXIT_OK


def refs_report(chosen, args):
    name = args.name.rsplit(".", 1)[-1]
    if not re.fullmatch(r"@?\w+", name):
        raise index.CodeError("refs takes an identifier, such as HighlightedComponent or Vehicles.VehiclePawn.Kill")
    pattern = re.compile(r"(?<![\w@])" + re.escape(name) + r"(?!\w)")
    rows, total, by_corpus = [], 0, {}
    for corpus, path in chosen:
        for relative, source in corpus.files():
            text = source.read_text(encoding="utf-8", errors="replace")
            if name not in text:
                continue
            spans = None
            for number, line in enumerate(text.split("\n"), 1):
                if not pattern.search(line):
                    continue
                stripped = line.strip()
                if stripped.startswith(("//", "///", "*", "using ")):
                    continue
                total += 1
                by_corpus[corpus.name] = by_corpus.get(corpus.name, 0) + 1
                if len(rows) > args.top:
                    continue
                if spans is None:
                    spans = index.enclosing(path, relative)
                holder = [s for s in spans if s[0] <= number <= s[1] and s[2] != "namespace"]
                inside = min(holder, key=lambda s: s[1] - s[0])[3] if holder else "(file level)"
                rows.append([inside, f"{corpus.name}:{relative}:{number}", _cut(stripped, TEXT_WIDTH)])
    report = Report(f"code refs {name}")
    report.lines.append(f"{total} lines use {name}" + (": " + ", ".join(f"{n} in {c}" for c, n in by_corpus.items())
                                                       if by_corpus else "") + ". Comments and using lines are left out.")
    report.section("Uses", Table(["In", "Where", "Line"], rows[:args.top], total=total, widths={2: TEXT_WIDTH}))
    return report


def summary_report(chosen, built):
    report = Report("code: corpora")
    rows = []
    for corpus, path in chosen:
        files, decls = index.counts(path)
        rows.append([corpus.name, files, decls, "built now" if corpus.name in built else "current"])
    report.lines.append(f"{len(rows)} corpora indexed; queries read the indexes, refs reads the files.")
    report.section("Corpora", Table(["Corpus", "Files", "Declarations", "Index"], rows))
    return report


def main(argv=None, settings_file=None, environ=None, out=None):
    out = out or sys.stdout
    argv = list(sys.argv[1:] if argv is None else argv)
    # The report may come after the corpus options ("code --each-in DIR show X"): move it to the front.
    if argv and argv[0] not in REPORTS and argv[0] not in ("-h", "--help"):
        at = next((i for i, a in enumerate(argv) if a in REPORTS and (i == 0 or not argv[i - 1].startswith("--")
                                                                       or argv[i - 1] in FLAGS)), None)
        argv.insert(0, argv.pop(at) if at is not None else "summary")
    elif not argv:
        argv = ["summary"]
    try:
        args = _parser().parse_args(argv)
    except SystemExit as stop:
        return EXIT_USAGE if stop.code else EXIT_OK
    settings_file = args.settings or settings_file
    redact = keep if args.no_redact else home_redactor()
    code = EXIT_OK
    try:
        cache = derived.folder(index.CACHE_FOLDER, args.cache, environ, settings_file)
        chosen, built = [], []
        for corpus in corpora(args):
            path, fresh = index.ensure(corpus, cache, args.rebuild)
            chosen.append((corpus, path))
            if fresh:
                built.append(corpus.name)
        if args.report == "find":
            report = find_report(chosen, args)
        elif args.report == "outline":
            report, code = outline_report(chosen, args)
        elif args.report == "show":
            report, code = show_report(chosen, args)
        elif args.report == "refs":
            report = refs_report(chosen, args)
        else:
            report = summary_report(chosen, built)
        if built and args.report != "summary":
            report.lines.append(f"Indexed now: {', '.join(built)}.")
    except index.CodeError as error:
        report, code = Report("code: error", [str(error)]), EXIT_FAILED
    print(envelope_text("code", report, redact) if args.json
          else render_markdown(report, redact), file=out)
    return code


MANIFEST = {"game": None, "parser": _parser, "effect": READS}
