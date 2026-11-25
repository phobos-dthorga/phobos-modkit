"""makeup: what a repository is made of, how it grew, where the work goes, and what each product holds for players (1.39.0).

    makeup now --root REPO              every committed file by product, kind, language, lines and size; and since 1.127.0,
                                        each mod's size as installed, where the repository's installs.json says where
    makeup growth --root REPO           the same, totalled by kind and by product, one point a day since the first commit
    makeup churn --root REPO [--days N] the files commits changed lately: how often, lines added and removed, last change
    makeup census --root REPO           each product's Defs by type, pictures, sounds and text keys

Products, kinds and what counts are in docs/makeup.md. Reads only.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
import os
from pathlib import Path
import sys

from . import connections, makeup
from .manifest import READS
from .progress import Progress
from .report import Report, Table, envelope_text, home_redactor, keep, render_markdown

EXIT_OK, EXIT_REFUSED, EXIT_USAGE = 0, 1, 2
DEFAULT_DAYS = 30


def _parser():
    p = argparse.ArgumentParser(prog="makeup", description=__doc__.split("\n\n")[0],
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="report", required=True)
    for name, helptext in (("now", "every committed file by product, kind, language, lines and size"),
                           ("growth", "totals by kind and product, one point a day since the first commit"),
                           ("churn", "the files commits changed lately"),
                           ("census", "each product's Defs by type, pictures, sounds and text keys")):
        s = sub.add_parser(name, help=helptext)
        s.add_argument("--root", default=".", help="the repository (default: here)")
        if name == "churn":
            s.add_argument("--days", type=int, default=DEFAULT_DAYS, help=f"how far back (default {DEFAULT_DAYS}; 0 for every commit)")
        s.add_argument("--top", type=int, default=25, help="rows per table (default 25)")
        s.add_argument("--json", action="store_true", help="print JSON instead of Markdown")
        s.add_argument("--no-redact", action="store_true", help="show the home folder instead of ~")
    return p


def _owner(entry):
    return entry["product"] or (f"outside any product: {entry['group']}" if entry["group"] else "outside any product")


def now_report(root, environ, progress, top):
    data = makeup.now(root, environ, progress)
    totals = defaultdict(lambda: defaultdict(lambda: [0, 0, 0]))
    for f in data["files"]:
        cell = totals[_owner(f)][f["kind"]]
        cell[0] += 1
        cell[1] += f["lines"]
        cell[2] += f["bytes"]
    rows = []
    for owner, kinds in sorted(totals.items(), key=lambda kv: -sum(c[1] for c in kv[1].values())):
        rows.append([owner, f"{sum(c[0] for c in kinds.values()):,}", f"{sum(c[1] for c in kinds.values()):,}",
                     f"{sum(c[2] for c in kinds.values()) / 1e6:.1f} MB",
                     ", ".join(f"{k} {kinds[k][1]:,}" for k in makeup.KINDS if kinds.get(k) and kinds[k][1])])
    report = Report(f"Make-up of {data['repository']}: {len(data['files']):,} committed files")
    report.section("By product", Table(["Product", "Files", "Lines", "Size", "Lines by kind"], rows[:top], total=len(rows)))
    installed = makeup.installed_sizes(root, environ)
    data["installed"] = installed
    if installed is not None:
        if installed["problem"]:
            report.section("Size as installed", [f"Not measured: {installed['problem']}"])
        else:
            mods = installed["mods"]
            report.section("Size as installed", Table(
                ["Mod", "Installed", "Files", "In the repository"],
                [[m["mod"], f"{m['bytes'] / 1e6:.1f} MB" if m["found"] else "not installed", f"{m['files']:,}",
                  f"{m['repositoryBytes'] / 1e6:.1f} MB"] for m in mods][:top], total=len(mods)))
    return report, data


def growth_report(root, environ, progress, top):
    data = makeup.growth(root, environ, progress)
    report = Report(f"Growth of {data['repository']}: {len(data['points'])} days with commits")
    report.section("Lines by kind, day by day", Table(
        ["Day", *makeup.KINDS],
        [[p["day"], *[f"{p['kinds'].get(k, [0, 0])[0]:,}" for k in makeup.KINDS]] for p in data["points"][-top:]],
        total=len(data["points"])))
    return report, data


def churn_report(root, days, top):
    found = makeup.churn(root, days)
    files = [{"path": path, **values, "kind": makeup.classify(path)[0]} for path, values in found.items()]
    files.sort(key=lambda f: (-f["commits"], -(f["added"] + f["removed"])))
    window = f"the last {days} days" if days else "every commit"
    report = Report(f"Churn in {Path(root).resolve().name}: {len(files):,} files changed in {window}")
    report.section("Most often changed", Table(["File", "Kind", "Commits", "Added", "Removed", "Last"],
                                               [[f["path"], f["kind"], f["commits"], f"{f['added']:,}", f"{f['removed']:,}",
                                                 f["last"]] for f in files[:top]], total=len(files)))
    return report, {"repository": Path(root).resolve().name, "days": days, "files": files}


def census_report(root, environ, progress, top):
    files = makeup.now(root, environ, progress)["files"]
    conn = connections.open_graph(Path(root).resolve(), environ, None, progress)
    try:
        found = makeup.census(root, conn, files)
    finally:
        conn.close()
    rows = [[name, f"{sum(v['defs'].values()):,}", ", ".join(f"{t} {n}" for t, n in list(v["defs"].items())[:5]),
             v["pictures"], v["sounds"], f"{v['keys']:,}"]
            for name, v in sorted(found.items(), key=lambda kv: -sum(kv[1]["defs"].values()))]
    report = Report(f"Census of {Path(root).resolve().name}: what each product holds")
    report.section("Products", Table(["Product", "Defs", "Most common", "Pictures", "Sounds", "Text keys"], rows[:top],
                                     total=len(rows)))
    return report, {"repository": Path(root).resolve().name, "products": found}


def main(argv=None, environ=None, out=None):
    out = out or sys.stdout
    environ = os.environ if environ is None else environ
    try:
        args = _parser().parse_args(list(sys.argv[1:] if argv is None else argv))
    except SystemExit as stop:
        return EXIT_USAGE if stop.code else EXIT_OK
    redact = keep if args.no_redact else home_redactor()
    progress = Progress(environ)
    root = Path(args.root).resolve()
    code = EXIT_OK
    try:
        if not (root / ".git").exists():
            raise makeup.MakeupError(f"{root} is not a git repository.")
        if args.report == "now":
            report, data = now_report(root, environ, progress, args.top)
        elif args.report == "growth":
            report, data = growth_report(root, environ, progress, args.top)
        elif args.report == "churn":
            report, data = churn_report(root, args.days, args.top)
        else:
            report, data = census_report(root, environ, progress, args.top)
    except (makeup.MakeupError, connections.ConnectionsError, OSError) as error:
        if not args.json:
            print(redact(str(error)), file=sys.stderr)
            return EXIT_REFUSED
        report, data, code = Report("Refused", [str(error)]), {"ok": False, "refusal": str(error)}, EXIT_REFUSED
    out.write((envelope_text("makeup", report, redact, data) if args.json else render_markdown(report, redact)) + "\n")
    return code


MANIFEST = {"game": None, "parser": _parser, "effect": READS,
            "reports": {"now": {"note": "every committed file by product and kind; needs the repository"},
                        "growth": {"note": "totals one point a day; needs the repository"},
                        "churn": {"note": "the files commits changed lately; needs the repository"},
                        "census": {"note": "what each product holds for players; needs the repository"}}}


if __name__ == "__main__":
    sys.exit(main())
