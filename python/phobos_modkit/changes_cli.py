"""changes: what a repository's changelogs say changed lately, and the code behind any one entry.

    changes list --root REPO                         every changelog, its newest versions and their entries
    changes list --root REPO --versions 10           more versions of each
    changes entry --root REPO --changelog mods/Thing/CHANGELOG.md --text "A slung vehicle could be set down"
                                                     the commit that wrote that entry, and what it changed, file by file
    changes commits --root REPO [--top 40] [--skip 0]  the newest commits, for a repository with no changelog (1.82.0)
    changes entry --root REPO --commit HASH           what one commit changed; --changelog only names the entries it wrote
    changes pending --root REPO [--root REPO ...]    what each changelog has not released yet: entries with no version, drafts

The code behind an entry is the commit that first wrote it into its changelog, found by git; an entry no commit holds yet shows the
uncommitted changes. One commit may have written several entries: the answer names the others, and cannot say which lines are whose
(docs/changes.md). It works on any repository with a changelog and only reads.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import os
from pathlib import Path
import sys

from . import changes
from .installs import UNRELEASED
from .manifest import READS
from .progress import Progress
from .report import Bullets, Report, Table, envelope_text, home_redactor, keep, render_markdown

EXIT_OK, EXIT_REFUSED, EXIT_USAGE = 0, 1, 2
MAX_TEXT = 4000


def _parser():
    p = argparse.ArgumentParser(prog="changes", description=__doc__.split("\n\n")[0],
                                formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__.split("\n\n", 1)[1])
    sub = p.add_subparsers(dest="report", required=True)
    for name, helptext in (("list", "every changelog in the repository, its newest versions and their entries"),
                           ("entry", "the commit that wrote one changelog entry, and what it changed"),
                           ("commits", "the newest commits, for a repository with no changelog (1.82.0)"),
                           ("pending", "what each changelog has not released yet, for one or more repositories")):
        s = sub.add_parser(name, help=helptext)
        if name == "pending":
            s.add_argument("--root", action="append", help="a repository (repeatable; default: the current folder)")
        else:
            s.add_argument("--root", help="the repository (default: the current folder)")
        if name == "pending":
            pass
        elif name == "list":
            s.add_argument("--versions", type=int, default=5,
                           help="versions of each changelog to list, newest first (default 5; 0 for every version)")
        elif name == "commits":
            s.add_argument("--skip", type=int, default=0, help="newer commits to pass over first (default 0)")
        else:
            s.add_argument("--changelog", help="the changelog's path in the repository, as list gives it; needed with --text")
            s.add_argument("--text", help="the entry's text, or its bold opening")
            s.add_argument("--commit", help="instead of an entry, a commit: what it changed, with every entry it wrote")
        s.add_argument("--top", type=int, default=40, help="rows per table (default 40)")
        s.add_argument("--json", action="store_true", help="print JSON instead of Markdown")
        s.add_argument("--no-redact", action="store_true", help="show the home folder instead of ~")
    return p


def _entry(entry, commits=None):
    commit = changes.commit_of(entry, commits) if commits is not None else None
    return {"version": entry.version, "section": entry.section, "text": entry.text, "lead": entry.lead,
            "aboutSaves": entry.about_saves, "commit": commit[:12] if commit else None}


def list_report(root, versions, top, progress):
    found = changes.changelogs(root)
    logs = []
    for position, path in enumerate(found, 1):
        progress(f"Reading {path}", position, len(found))
        log = changes.read_listed(root, path)
        commits = changes.entry_commits(root, path)
        order = [v for v in log.headings if v == UNRELEASED and any(e.version == v for e in log.entries)]
        named = [v for v in log.headings if v != UNRELEASED]
        order += named if versions == 0 else named[:max(1, versions)]
        logs.append({"changelog": path, "product": changes.product_name(log.title, path, root),
                     "versionsInAll": sum(v != UNRELEASED for v in log.headings),
                     "versions": [{"version": v, "heading": log.headings.get(v, ""), "summary": log.summaries.get(v, ""),
                                   "entries": [_entry(e, commits) for e in log.entries if e.version == v]} for v in order]})
    report = Report(f"Changes: {len(logs):,} changelog{'' if len(logs) == 1 else 's'}")
    report.lines.append("Each entry's code is the commit that wrote it: changes entry --changelog PATH --text \"its opening\".")
    report.section("Changelogs", Table(
        ["Product", "Changelog", "Newest version", "Its entries", "Versions"],
        [[log["product"], log["changelog"], _newest(log), f"{_newest_count(log):,}", f"{log['versionsInAll']:,}"] for log in logs[:top]],
        total=len(logs)))
    return report, {"repository": Path(root).name, "changelogs": logs}


def _newest(log):
    named = [v for v in log["versions"] if v["version"] != UNRELEASED]
    return named[0]["version"] if named else UNRELEASED


def _newest_count(log):
    named = [v for v in log["versions"] if v["version"] != UNRELEASED]
    return len(named[0]["entries"]) if named else sum(len(v["entries"]) for v in log["versions"])


def pending_report(roots, top, progress):
    repositories = []
    for position, root in enumerate(roots, 1):
        progress(f"Reading {Path(root).name}'s changelogs", position, len(roots))
        repositories.append({"repository": Path(root).name, "pending": changes.pending(root)})
    rows = [[r["repository"], p["product"], f"{p['unreleased']:,}", p["draftVersion"] or "-", p["draftDate"] or "-"]
            for r in repositories for p in r["pending"]]
    report = Report(f"Changes: {len(rows):,} changelog{'' if len(rows) == 1 else 's'} with something not yet released")
    report.section("Not yet released", Table(["Repository", "Product", "Entries with no version", "Newest draft", "Its date"],
                                             rows[:top], total=len(rows)))
    return report, {"repositories": repositories}


def _when(seconds):
    return datetime.fromtimestamp(seconds, timezone.utc).isoformat(timespec="seconds") if seconds else None


def entry_report(root, changelog, text, top, progress, commit=None):
    progress("Finding the commit that wrote this entry" if not commit else "Reading the commit", 1, 2)
    found = changes.commit_code(root, changelog, commit) if commit else changes.entry_code(root, changelog, text)
    progress("Reading what it changed", 2, 2)
    commit = found.commit
    files = [{"path": f.path, "oldPath": f.old_path if f.change == "renamed" else None, "change": f.change, "kind": f.kind,
              "language": f.language, "binary": f.binary, "additions": f.additions, "deletions": f.deletions, "hunks": f.hunks,
              "truncated": f.truncated, "media": f.media, "sizeBefore": f.size_before, "sizeAfter": f.size_after}
             for f in found.files]
    if commit:
        title = f"Changes: this entry was written by {commit.hash[:8]}, which changed {len(files):,} other files"
    else:
        title = f"Changes: this entry is in no commit yet; {len(files):,} files have uncommitted changes"
    report = Report(title)
    if commit:
        report.lines.append(f"{commit.subject} ({_when(commit.time)}).")
    else:
        report.lines.append("Files git does not track yet are not shown.")
    if found.written_with:
        report.lines.append(f"**The same commit wrote {len(found.written_with):,} other entries; which lines are whose is not known.**")
        report.section("Written with it", Bullets([w[:120] for w in found.written_with[:top]]))
    report.section("Files", Table(["File", "Kind", "Change", "Added", "Removed"],
                                  [[f["path"], f["kind"], f["change"], f"{f['additions']:,}", f"{f['deletions']:,}"] for f in files[:top]],
                                  total=len(files)))
    data = {"repository": Path(root).name, "changelog": changelog,
            "commit": {"hash": commit.hash, "time": _when(commit.time), "author": commit.author, "subject": commit.subject}
            if commit else None,
            "writtenWith": found.written_with, "files": files, "filesLeftOut": found.files_left_out,
            "additions": sum(f["additions"] for f in files), "deletions": sum(f["deletions"] for f in files)}
    return report, data


def commits_report(root, top, skip, progress):
    progress("Reading the commits", 1, 1)
    found = changes.commits(root, top, skip)
    listed = found["commits"]
    report = Report(f"Changes: {found['total']:,} commit{'' if found['total'] == 1 else 's'}, the newest {len(listed):,} listed"
                    if not skip else f"Changes: commits {skip + 1:,} to {skip + len(listed):,} of {found['total']:,}")
    report.lines.append("Each commit's code: changes entry --commit HASH (no changelog needed).")
    report.section("Commits", Table(["Commit", "When", "Subject", "Files", "Not text"],
                                    [[c["hash"][:8], _when(c["time"]), c["subject"][:100], f"{c['files']:,}", f"{c['binary']:,}"]
                                     for c in listed[:top]], total=len(listed)))
    return report, {"repository": Path(root).name, "total": found["total"], "skip": skip,
                    "commits": [{**c, "time": _when(c["time"])} for c in listed]}


def main(argv=None, environ=None, out=None):
    out = out or sys.stdout
    environ = os.environ if environ is None else environ
    try:
        args = _parser().parse_args(list(sys.argv[1:] if argv is None else argv))
    except SystemExit as stop:
        return EXIT_USAGE if stop.code else EXIT_OK
    redact = keep if args.no_redact else home_redactor()
    progress = Progress(environ)
    root = Path(args.root or ".").resolve() if args.report != "pending" else None
    code = EXIT_OK
    try:
        if args.report == "pending":
            report, data = pending_report([Path(r).resolve() for r in (args.root or ["."])], args.top, progress)
        elif args.report == "list":
            report, data = list_report(root, args.versions, args.top, progress)
        elif args.report == "commits":
            report, data = commits_report(root, args.top, args.skip, progress)
        else:
            if not args.text and not args.commit:
                raise changes.ChangesError("Name an entry (--text) or a commit (--commit).")
            if args.text and not args.changelog:
                raise changes.ChangesError("An entry is looked for in a changelog: name it with --changelog.")
            if args.text and len(args.text) > MAX_TEXT:
                raise changes.ChangesError("That entry's text is too long to look for.")
            changelog = args.changelog.replace("\\", "/") if args.changelog else None
            report, data = entry_report(root, changelog, args.text, args.top, progress, args.commit)
    except (changes.ChangesError, OSError) as error:
        if not args.json:
            print(redact(str(error)), file=sys.stderr)
            return EXIT_REFUSED
        report, data = Report("Refused"), {"ok": False, "refusal": str(error)}
        report.lines.append(str(error))
        code = EXIT_REFUSED
    out.write((envelope_text("changes", report, redact, data) if args.json else render_markdown(report, redact)) + "\n")
    return code


MANIFEST = {"game": None, "parser": _parser, "effect": READS,
            "reports": {"list": {"question": "What do the changelogs say changed lately?", "surface": "changes"},
                        "entry": {"note": "the commit that wrote one entry, and its diff; needs the changelog and the entry"},
                        "pending": {"note": "what each changelog has not released yet; reads files only, for a program's first page"}}}
