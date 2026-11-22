"""issue-links: where a fault in a mod is reported, and GitHub's new-issue form filled in for a person to send (1.94.0).

    issue-links where --name GAME [--app-id N] [--data DIR] --root REPO [...] --mod NAME [...]
        each mod: ours (a repository named, on GitHub), theirs (its public source confirmed in a source register), or unknown
    issue-links new --repository OWNER/REPO --title TEXT [--body-file FILE] [--label NAME]
        the address of GitHub's new-issue form, filled in; a body too long for an address goes to `clipboard` instead
    issue-links issues --repository OWNER/REPO [--words TEXT]
        the repository's issues, open and closed, newest first, those naming every word first (keyless)

D'thorga Companion's report links (phobos-companion docs/online.md, O4; the owner's choice of 23 Nov 2026: pre-filled reports to
our own repositories, and for other authors their existing issues and their blank form, on the Logs page). **Nothing here posts
anything**: `new` only builds an address, which a person opens in their browser, reads and sends themselves. Drafts to other
authors still go through the owner's private tracker (phobos-modkit rules/reports.md).

`where` is game-free: a game's mod-list adapter says which folder each installed mod is in; a repository's `config/installs.json`
names the folder its own mods are built in, and a mod installed from a folder of that name is ours; a repository's
`config/source-repos.json` names other authors' confirmed public source by package ID. `issues` reads keyless through the kit's
GitHub reader (one hourly allowance for every tool): one call for each 100 issues, up to three, cached for an hour.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys
import time
import urllib.parse

from . import cache as derived
from . import github, installs, repos
from .games import mod_list_adapter, mod_list_game
from .manifest import ONLINE, READS
from .report import Bullets, Report, Table, envelope_text, home_redactor, keep, render_markdown

EXIT_OK, EXIT_REFUSED, EXIT_USAGE = 0, 1, 2
MAX_ADDRESS = 6000          # GitHub refuses an address that is too long and names no figure (agent default, docs/online.md)
MAX_TITLE = 200
ISSUE_PAGES = 3
ISSUES_FRESH_HOURS = 1
REGISTER = Path("config") / "source-repos.json"
REPOSITORY = re.compile(r"^[A-Za-z0-9-]{1,39}/[A-Za-z0-9._-]{1,100}$")


class LinkError(ValueError):
    """A request this command refuses, with the reason in words."""


# ---- where ----

def _ours(roots):
    """{mod folder name: owner/repo} for every repository on GitHub that says where its own mods are built."""
    found = {}
    for root in roots:
        name = repos.github_name(root)
        if not name:
            continue
        try:
            config = installs.load_config(root)
        except installs.InstallsError:
            continue
        for folder in installs.mods_of(root, config):
            found.setdefault(folder.lower(), name)
    return found


def _theirs(roots):
    """{package id, lowered: owner/repo} from every source register's confirmed repositories on GitHub."""
    found = {}
    for root in roots:
        try:
            mods = json.loads((Path(root) / REGISTER).read_text(encoding="utf-8")).get("mods", {})
        except (OSError, ValueError):
            continue
        for mod in (mods.values() if isinstance(mods, dict) else mods):
            names = github.links(mod.get("repository") or "")
            if mod.get("confirmed") and names and mod.get("package_id"):
                found.setdefault(mod["package_id"].lower(), names[0])
    return found


def where(adapter, roots, names):
    """[{mod, id, whose: ours|theirs|unknown, repository}] for each mod name given, as installed on this PC."""
    installed = {m.name.lower(): m for m in adapter.installed()}
    ours, theirs = _ours(roots), _theirs(roots)
    found = []
    for name in names:
        mod = installed.get(name.lower())
        entry = {"mod": name, "id": mod.id if mod else "", "whose": "unknown", "repository": None}
        if mod is not None:
            folder = Path(mod.folder).name.lower() if mod.folder else ""
            if folder in ours:
                entry.update(whose="ours", repository=ours[folder])
            elif mod.id.lower() in theirs:
                entry.update(whose="theirs", repository=theirs[mod.id.lower()])
        found.append(entry)
    return found


# ---- new ----

def new_issue(repository, title, body="", label=None, limit=MAX_ADDRESS):
    """{url, clipboard}: the form's address with the title (and label) and, when it fits, the body; else the body to paste."""
    if not REPOSITORY.match(repository or ""):
        raise LinkError(f"\"{repository}\" is not a repository's name (OWNER/REPO)")
    title = " ".join((title or "").split())[:MAX_TITLE]
    if not title:
        raise LinkError("a report needs a title")
    base = f"https://github.com/{repository}/issues/new?"
    fields = {"title": title}
    if label:
        fields["labels"] = label
    with_body = base + urllib.parse.urlencode({**fields, "body": body}) if body else None
    if with_body and len(with_body) <= limit:
        return {"url": with_body, "clipboard": None}
    paste = {"body": "Paste the report from your clipboard here."} if body else {}
    return {"url": base + urllib.parse.urlencode({**fields, **paste}), "clipboard": body or None}


# ---- issues ----

def issues(client, repository, words=""):
    """The repository's issues, open and closed, newest first; those whose title or text names every word come first, marked."""
    if not REPOSITORY.match(repository or ""):
        raise LinkError(f"\"{repository}\" is not a repository's name (OWNER/REPO)")
    wanted = [w.lower() for w in re.findall(r"[A-Za-z0-9_.]{3,}", words or "")][:8]
    found = []
    for page in range(1, ISSUE_PAGES + 1):
        url = f"{github.API}/repos/{repository}/issues?state=all&per_page=100&page={page}"
        status, body = client.fetch(url, "api", ISSUES_FRESH_HOURS * 3600)
        if status != 200:
            break
        batch = json.loads(body.decode("utf-8", "replace"))
        for item in batch:
            if "pull_request" in item:
                continue
            text = f"{item.get('title', '')} {item.get('body') or ''}".lower()
            found.append({"number": item.get("number"), "title": item.get("title", ""), "state": item.get("state"),
                          "updated": item.get("updated_at"), "url": item.get("html_url"),
                          "matches": bool(wanted) and all(w in text for w in wanted)})
        if len(batch) < 100:
            break
    return sorted(found, key=lambda i: (not i["matches"], -(i["number"] or 0)))


# ---- the command ----

def _parser():
    p = argparse.ArgumentParser(prog="issue-links", description=__doc__.split("\n\n")[0],
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="report", required=True)
    w = sub.add_parser("where", help="each mod: ours, theirs or unknown, with its repository on GitHub")
    w.add_argument("--name", help="the game's name or id")
    w.add_argument("--app-id", help="the game's Steam app id")
    w.add_argument("--data", help="the game's data folder, when not where it usually is")
    w.add_argument("--root", action="append", default=[], help="a repository on this PC (repeatable)")
    w.add_argument("--mod", action="append", default=[], help="a mod's name as the log names it (repeatable)")
    w.add_argument("--settings", help="a JSON settings file")
    n = sub.add_parser("new", help="the address of GitHub's new-issue form, filled in")
    n.add_argument("--repository", required=True, help="OWNER/REPO")
    n.add_argument("--title", required=True, help="the report's title")
    n.add_argument("--body-file", help="a file holding the report's text")
    n.add_argument("--label", help="a label to choose, where the repository has it")
    i = sub.add_parser("issues", help="the repository's issues, those naming every word first (keyless)")
    i.add_argument("--repository", required=True, help="OWNER/REPO")
    i.add_argument("--words", default="", help="words from the fault, to find an existing report of it")
    i.add_argument("--cache", help="the kit's cache folder")
    for sub_parser in (w, n, i):
        sub_parser.add_argument("--json", action="store_true", help="print JSON instead of Markdown")
        sub_parser.add_argument("--no-redact", action="store_true", help="show the home folder instead of ~")
    return p


def main(argv=None, out=None, environ=None, get=None, clock=time.time, settings_file=None):
    out = out or sys.stdout
    try:
        args = _parser().parse_args(list(sys.argv[1:] if argv is None else argv))
    except SystemExit as stop:
        return EXIT_USAGE if stop.code else EXIT_OK
    redact = keep if args.no_redact else home_redactor()

    def emit(report, data):
        out.write((envelope_text("issue-links", report, redact, data) if args.json else render_markdown(report, redact)) + "\n")

    try:
        if args.report == "where":
            row = mod_list_game(args.name, args.app_id)
            if row is None:
                raise LinkError(f"The tools cannot read {args.name or args.app_id}'s mods yet.")
            found = where(mod_list_adapter(row, environ, args.settings, args.data), args.root, args.mod)
            report = Report(f"Where {len(found)} mods are reported")
            report.section("Mods", Table(["Mod", "Whose", "Repository"],
                                         [[f["mod"], f["whose"], f["repository"] or ""] for f in found]))
            emit(report, {"mods": found})
        elif args.report == "new":
            body = Path(args.body_file).read_text(encoding="utf-8") if args.body_file else ""
            link = new_issue(args.repository, args.title, body, args.label)
            report = Report("A new report, filled in", ["Open it in a browser, read it, and send it yourself."])
            report.section("Address", Bullets([link["url"]] + (["The text is too long for an address: paste it from the "
                                                                  "clipboard."] if link["clipboard"] else [])))
            emit(report, link)
        else:
            folder = derived.folder(github.CACHE_FOLDER, args.cache, environ, settings_file)
            client = github.Client(folder, get=get or github.http_get, clock=clock, keep_last=True)
            found = issues(client, args.repository, args.words)
            report = Report(f"{args.repository}: {len(found)} issues, {sum(i['matches'] for i in found)} naming every word")
            report.section("Issues", Table(["#", "State", "Title", "Matches"],
                                           [[str(i["number"]), i["state"] or "", i["title"], "yes" if i["matches"] else ""]
                                            for i in found[:25]]))
            if client.limited:
                report.section("Limits", Bullets([client.limited]))
            emit(report, {"issues": found, "limited": client.limited, "stale": bool(client.stale)})
    except (LinkError, OSError, github.GitHubError) as error:
        emit(Report("issue-links: refused", [str(error)]), {"refused": str(error)})
        return EXIT_REFUSED
    return EXIT_OK


MANIFEST = {"game": None, "parser": _parser, "effect": READS, "surface": "issue-links",
            "reports": {"issues": {"effect": ONLINE, "note": "GitHub's issues, keyless; one call for each 100, cached an hour"}}}
