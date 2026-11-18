"""history: what happened to a game's products over time, and any changelog as it stood at any moment.

    history timeline --root REPO [--root REPO ...] [--game NAME]     every fact, newest first: from git, and from the history log
    history timeline ... --since 2026-11-01                           only facts from that day on
    history at --root REPO --changelog PATH --commit HASH             a changelog as it stood at a commit, marked by what changed since
    history at --root REPO --changelog PATH --when 2026-11-12T15:00   ... as it stood at a moment

Facts from git go back to each repository's first commit and are cached, so only new commits are read after the first time.
Facts about this PC (installed, went back, backed up, built, encoded) come from the history log named by historyPath, by default
in D'thorga Companion's folder; --game names the game whose log to read. It only reads (docs/history.md).
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime
import os
from pathlib import Path
import re
import sys

from . import changes, history
from .manifest import READS
from .progress import Progress
from .report import Bullets, Report, Table, envelope_text, home_redactor, keep, render_markdown

EXIT_OK, EXIT_REFUSED, EXIT_USAGE = 0, 1, 2
COMMIT = re.compile(r"^[0-9a-f]{7,40}$")
KIND_WORDS = {
    "product-started": "changelog started", "version-written": "version written", "entries-added": "entries added",
    "entries-reworded": "entries reworded", "entries-removed": "entries removed", "version-removed": "version removed",
    "version-released": "version released", "product-renamed": "renamed", "product-ended": "ended",
    "installed": "installed", "went-back": "went back", "backed-up": "backed up", "built": "built", "encoded": "textures encoded"}


def _parser():
    p = argparse.ArgumentParser(prog="history", description=__doc__.split("\n\n")[0],
                                formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__.split("\n\n", 1)[1])
    sub = p.add_subparsers(dest="report", required=True)
    for name, helptext in (("timeline", "every fact about a game's products, newest first"),
                           ("at", "a changelog as it stood at a commit or a moment")):
        s = sub.add_parser(name, help=helptext)
        if name == "timeline":
            s.add_argument("--root", action="append", help="a repository (repeatable; default: the current folder)")
            s.add_argument("--game", help="the game whose history log to read (default: none, git facts only)")
            s.add_argument("--since", help="only facts from this day on (YYYY-MM-DD)")
            s.add_argument("--top", type=int, default=40, help="facts in the summary's table (default 40)")
        else:
            s.add_argument("--root", help="the repository (default: the current folder)")
            s.add_argument("--changelog", required=True, help="the changelog's path in the repository")
            s.add_argument("--commit", help="the commit to read it at")
            s.add_argument("--when", help="the moment to read it at (an ISO date or time)")
        s.add_argument("--settings", help="a JSON settings file naming historyPath")
        s.add_argument("--json", action="store_true", help="print JSON instead of Markdown")
        s.add_argument("--no-redact", action="store_true", help="show the home folder instead of ~")
    return p


def _words(fact):
    who = fact.get("product") or fact.get("mod") or fact.get("repository") or ""
    version = f" {fact['version']}" if fact.get("version") else ""
    count = f" ({fact['count']})" if fact.get("count") else ""
    return f"{who}{version}: {KIND_WORDS.get(fact['kind'], fact['kind'])}{count}"


def timeline_report(roots, game, since, top, environ, settings, progress):
    facts = []
    for position, root in enumerate(roots, 1):
        progress(f"Reading the history of {Path(root).name}", position, len(roots) + 1)
        facts += history.repository_facts(root, environ, settings, progress)
    if game:
        progress("Reading what happened on this PC", len(roots) + 1, len(roots) + 1)
        names = {Path(r).name for r in roots}
        facts += [f for f in history.read_log(game, environ, settings) if not f.get("repository") or f["repository"] in names]
    if since:
        facts = [f for f in facts if f["time"][:10] >= since]
    facts.sort(key=lambda f: f["time"], reverse=True)
    kinds = Counter(f["kind"] for f in facts)
    report = Report(f"History: {len(facts):,} facts" + (f" since {since}" if since else ""))
    report.lines.append("From git, back to each repository's first commit, and from this PC's history log since it began.")
    if kinds:
        report.section("Kinds", Table(["Kind", "Facts"], [[KIND_WORDS.get(k, k), f"{n:,}"] for k, n in kinds.most_common()]))
    report.section("Newest", Table(["When", "What", "Commit"],
                                   [[f["time"][:16].replace("T", " "), _words(f), (f.get("commit") or "")[:8]] for f in facts[:top]],
                                   total=len(facts)))
    log = history.log_file(game, environ, settings) if game else None
    data = {"facts": facts, "repositories": [Path(r).name for r in roots], "game": game,
            "log": str(log) if log else None, "logExists": bool(log and log.is_file())}
    return report, data


def at_report(root, path, commit, when):
    if commit and not COMMIT.match(commit):
        raise ValueError(f"{commit!r} is not a commit")
    if not commit:
        if not when:
            raise ValueError("Name a commit or a moment.")
        datetime.fromisoformat(when.replace("Z", "+00:00"))
        commit = history.commit_at(root, path, when)
        if not commit:
            raise ValueError(f"{path} did not exist yet at {when}.")
    found = history.as_it_stood(root, path, commit)
    if found is None:
        raise ValueError(f"{path} was not there at {commit[:8]}.")
    since = found["since"]
    report = Report(f"History: {found['product']} as it stood at {found['commit']['hash'][:8]} ({found['commit']['time'][:10]})")
    report.lines.append(f"{found['commit']['subject']}.")
    report.lines.append(f"Since then: {since['added']:,} entries added, {since['reworded']:,} reworded, {since['removed']:,} removed"
                        + ("." if found["stillThere"] else "; the changelog itself is gone."))
    report.section("Versions then", Bullets([f"{v['version']}: {len(v['entries']):,} entries" for v in found["versions"][:12]]))
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
    code = EXIT_OK
    try:
        if args.report == "timeline":
            roots = [Path(r).resolve() for r in (args.root or ["."])]
            if args.since:
                datetime.strptime(args.since, "%Y-%m-%d")
            report, data = timeline_report(roots, args.game, args.since, args.top, environ, args.settings, progress)
        else:
            root = Path(args.root or ".").resolve()
            path = args.changelog.replace("\\", "/")
            if path not in changes.changelogs(root) + history.deleted_changelogs(root):
                raise ValueError(f"{path!r} is not a changelog this repository has, or had.")
            progress("Reading the changelog as it stood", 1, 1)
            report, data = at_report(root, path, args.commit, args.when)
    except (ValueError, changes.ChangesError, OSError) as error:
        if not args.json:
            print(redact(str(error)), file=sys.stderr)
            return EXIT_REFUSED
        report, data = Report("Refused"), {"ok": False, "refusal": str(error)}
        report.lines.append(str(error))
        code = EXIT_REFUSED
    out.write((envelope_text("history", report, redact, data) if args.json else render_markdown(report, redact)) + "\n")
    return code


MANIFEST = {"game": None, "parser": _parser, "effect": READS,
            "reports": {"timeline": {"question": "What happened to my mods over time?", "surface": "timeline"},
                        "at": {"note": "a changelog as it stood at a commit or a moment; needs the changelog"}}}
