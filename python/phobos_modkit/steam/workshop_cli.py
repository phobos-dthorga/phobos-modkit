"""steam-workshop: what players report about Workshop items lately, from Steam's public pages, cached and paced.

    python -m phobos_modkit steam-workshop report 2023507013 3014915404   details and comment research per item
    python -m phobos_modkit steam-workshop details <ID or URL> ...        update dates, version tags, subscribers
    python -m phobos_modkit steam-workshop comments 2023507013            one item's cached comments in full
    python -m phobos_modkit steam-workshop collection 3497770083 --grep "*hover*"   a collection's items
    python -m phobos_modkit steam-workshop sql "SELECT title, time_updated FROM item"

Details come in batches of 100 in one request, and a collection's members in one more. Comments take one request per item, about 8 s apart, because Steam
limits quick reads; anything fetched in the last 24 hours (--max-age) is reused. Never logs in or changes anything
on Steam. Options go after the report's name.
"""
from __future__ import annotations

import argparse
from contextlib import closing
import sqlite3
import sys
import time

from .. import cache as derived
from ..report import envelope_text, home_redactor, keep, render_markdown
from . import workshop
from . import workshop_reports as reports
from ..manifest import ONLINE, READS

EXIT_OK, EXIT_FAILED, EXIT_USAGE = 0, 1, 2


def common_options():
    common = argparse.ArgumentParser(add_help=False)
    c = common.add_argument_group("fetching")
    c.add_argument("--max-age", type=float, default=24, help="hours a fetched item stays fresh (default 24)")
    c.add_argument("--refresh", action="store_true", help="fetch again even when the cache is fresh")
    c.add_argument("--offline", action="store_true", help="use the cache only; never contact Steam")
    c.add_argument("--cache", help="where the cache is kept (else PHOBOS_MODKIT_CACHE, settings, the temp folder)")
    c.add_argument("--settings", help="a JSON settings file with modkitCachePath")
    o = common.add_argument_group("output")
    o.add_argument("--days", type=int, default=90, help="how far back 'recent' comments go (default 90)")
    o.add_argument("--game-version", help="also flag comments that mention this version, e.g. 1.7")
    o.add_argument("--top", type=int, default=30, help="rows per table (default 30)")
    o.add_argument("--json", action="store_true", help="print JSON instead of Markdown")
    o.add_argument("--no-redact", action="store_true", help="show the home folder instead of ~")
    return common


def build_parser(prog, description, epilog, target_help, extra=None):
    common = common_options()
    p = argparse.ArgumentParser(prog=prog, description=description, epilog=epilog,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="report", metavar="report")
    for name, text in (("report", "details and comment research per item"),
                       ("details", "update dates, version tags and subscribers; no comments fetched")):
        s = sub.add_parser(name, parents=[common], help=text)
        s.add_argument("targets", nargs="+", help=target_help)
    s = sub.add_parser("comments", parents=[common], help="one item's comments in full, newest first")
    s.add_argument("targets", nargs=1, help=target_help)
    c = sub.add_parser("collection", parents=[common],
                       help="a collection's items: versions and the opening of each description; no comments fetched")
    c.add_argument("targets", nargs="+", help="a collection's Workshop ID or URL")
    c.add_argument("--grep", help="keep the items whose title or description matches (* and ? are wildcards)")
    q = sub.add_parser("sql", parents=[common], help="any read-only SQL query over the cache")
    q.add_argument("query")
    if extra:
        extra(sub, common)
    return p


def run(args, ids, settings_file=None, environ=None, out=None, post=None, pacer=None, clock=None,
        prepare=None, tool="steam-workshop"):
    """Refresh the cache for ids as the report needs, then print the report. prepare(conn, args) may return a
    Report of its own for reports a game adapter adds."""
    out = out or sys.stdout
    redact = keep if args.no_redact else home_redactor()
    settings_file = args.settings or settings_file
    cache = derived.folder(workshop.CACHE_FOLDER, args.cache, environ, settings_file)
    clock = clock or time.time
    done, children = None, None
    if ids and args.report == "collection":
        if args.offline:
            with closing(workshop.connect(cache)) as conn:
                children = workshop.collection_children(conn, ids)
        else:
            done, children = workshop.refresh_collections(ids, cache, args.max_age, force=args.refresh,
                                                          post=post or workshop.http_post, clock=clock)
    elif ids and not args.offline and args.report in ("report", "details", "comments", "versions"):
        done = workshop.refresh(ids, cache, args.max_age, comments=args.report in ("report", "comments"),
                                force=args.refresh, post=post or workshop.http_post, pacer=pacer, clock=clock)
    with closing(workshop.connect(cache)) as conn:
        try:
            report = prepare(conn, args) if prepare else None
            if report is None:
                if args.report == "collection":
                    report = reports.collection(conn, children or {}, args.game_version, args.grep, args.top)
                elif args.report == "report":
                    report = reports.research(conn, ids, args.days, args.game_version, clock(), args.top)
                elif args.report == "details":
                    report = reports.details(conn, ids, args.game_version)
                elif args.report == "comments":
                    report = reports.comments(conn, ids[0], args.top)
                else:
                    report = reports.sql(conn, args.query, args.top)
        except sqlite3.Error as problem:
            print(f"The query failed: {problem}", file=sys.stderr)
            return EXIT_FAILED
    if done is not None:
        line = (f"Steam: {done.details_fetched} items' details and {done.comments_fetched} comment pages fetched now; "
                f"{done.reused} reused from the last {args.max_age:g} hours.")
        if done.rate_limited:
            line += (" Steam is limiting requests for now, so some items show older comments or none: run this "
                     "again in a few minutes.")
        report.lines.insert(0, line)
        report.lines[1:1] = [f"Problem: {p}" for p in done.problems if "limiting" not in p][:5]
    elif args.offline:
        report.lines.insert(0, "From the cache only (--offline); nothing was fetched.")
    if args.json:
        out.write(envelope_text(tool, report, redact) + "\n")
    else:
        out.write(render_markdown(report, redact) + "\n")
    return EXIT_OK


def normalise(argv):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and not argv[0].startswith("-") and argv[0] not in ("report", "details", "comments", "collection", "sql",
                                                               "versions"):
        argv.insert(0, "report")
    return argv


def _parser():
    return build_parser("steam-workshop", __doc__.split("\n\n")[0], __doc__.split("\n\n", 1)[1],
                        "a Workshop item ID or URL")


def main(argv=None, settings_file=None, environ=None, out=None, post=None, pacer=None, clock=None):
    argv = normalise(argv)
    parser = _parser()
    if not argv:
        parser.print_help()
        return EXIT_USAGE
    args = parser.parse_args(argv)
    ids = []
    for target in getattr(args, "targets", []):
        found = workshop.item_id(target)
        if found is None:
            print(f"Not a Workshop ID or URL: {target}", file=sys.stderr)
            return EXIT_USAGE
        ids.append(found)
    return run(args, list(dict.fromkeys(ids)), settings_file, environ, out, post, pacer, clock)


CACHE_POLICIES = [workshop.CACHE_POLICY]

MANIFEST = {"game": None, "parser": _parser, "effect": ONLINE,
            "reports": {"sql": {"effect": READS}}}
