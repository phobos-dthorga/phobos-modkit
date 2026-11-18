"""rimworld-sources: where the public source of each mod a project ties into lives, checked, not guessed.

    rimworld-sources --root .                       every active mod the project's mods tie into
    rimworld-sources --root . --mod some.packageid  this mod too (or only it, with --only-named)
    rimworld-sources --root . --write               record the answers in config/source-repos.json
    rimworld-sources --root . --recheck             look again at mods the register already confirmed

Candidates come from the cheapest place first: the mod's About.xml, then its Workshop page's description (the Workshop
tool's cache, refreshed when an hour old), then, only when neither gives one, a GitHub search by the mod's name. A
candidate counts only when the repository holds an About.xml naming the mod's own package ID, so a link to another
mod (Harmony's, most often) is ruled out by the check, not by a list. A repository that exists but holds no such
About.xml is listed as unconfirmed: it may hold the source alone.

Keyless and slow on purpose: GitHub allows 60 API calls an hour and 10 searches a minute without logging in, so calls
are paced and cached for a week, and a run that meets the limit says so and keeps what it found. Writes nothing
unless --write is given, and then only the register in the project.
"""
from __future__ import annotations

import argparse
from contextlib import closing
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sqlite3
import sys
import xml.etree.ElementTree as ET

from ... import cache as derived
from ...github import Client, GitHubError, RateLimited, http_get, links
from ...github import CACHE_FOLDER as GITHUB_CACHE
from ...manifest import ONLINE
from ...report import Bullets, Report, Table, envelope_text, home_redactor, keep, render_markdown
from ...steam import workshop
from . import loading, paths
from .archive_cli import tied_active
from .mods import ModIndex, _about_root, _text, default_roots

EXIT_OK, EXIT_FAILED, EXIT_USAGE = 0, 1, 2
REGISTER = Path("config") / "source-repos.json"
REGISTER_FORMAT = 1
TREE_ABOUT_LIMIT = 6
BRACKETED = re.compile(r"\[[^\]]*\]|\([^)]*\)")


def _parser():
    p = argparse.ArgumentParser(prog="rimworld-sources", description=__doc__.split("\n\n")[0],
                                formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__.split("\n\n", 1)[1])
    p.add_argument("--root", default=".", help="the project whose mods' tie-ins decide what to look up (default: here)")
    p.add_argument("--mod", action="append", default=[], metavar="PACKAGE_ID", help="look up this installed mod too; may repeat")
    p.add_argument("--only-named", action="store_true", help="look up only the mods named with --mod")
    p.add_argument("--write", action="store_true", help="record the answers in config/source-repos.json under the root")
    p.add_argument("--recheck", action="store_true", help="look again at mods the register already confirmed")
    p.add_argument("--refresh", action="store_true", help="ignore cached GitHub answers")
    p.add_argument("--no-search", action="store_true", help="never search GitHub by name; links only")
    p.add_argument("--game", help="the RimWorld folder (else RIMWORLD_PATH, the settings file, Steam's default)")
    p.add_argument("--workshop", help="the Workshop content folder (else RIMWORLD_WORKSHOP_PATH, settings, beside the game)")
    p.add_argument("--config", help="the folder holding ModsConfig.xml (else RIMWORLD_CONFIG_PATH, settings, default)")
    p.add_argument("--cache", help="the kit's cache folder (else PHOBOS_MODKIT_CACHE, settings, the system's temp folder)")
    p.add_argument("--settings", help="a JSON settings file with the paths above")
    p.add_argument("--top", type=int, default=80, help="rows per table (default %(default)s)")
    p.add_argument("--json", action="store_true", help="print JSON instead of Markdown")
    p.add_argument("--no-redact", action="store_true", help="show the home folder instead of ~")
    return p


# ---- One mod ----

def _package_of(about_text):
    try:
        root = ET.fromstring(about_text)
    except ET.ParseError:
        match = re.search(r"<packageId>\s*([^<]+?)\s*</packageId>", about_text or "", re.I)
        return loading.bare_id(match.group(1)) if match else ""
    return loading.bare_id(_text(root, "packageId"))


def verify(client, name, package_id):
    """(confirmed path or None, repository facts or None, note). Confirmed when an About.xml in the repository names
    the package ID."""
    text = client.raw(name, "HEAD", "About/About.xml")
    if text is not None:
        named = _package_of(text)
        if named == package_id:
            return "About/About.xml", client.repository(name), ""
        # A repository whose own About.xml is another mod's is that mod (Harmony's, most often): no need to look further.
        return None, {"full_name": name}, f"it is {named or 'another mod'}'s repository"
    facts = client.repository(name)
    if facts is None:
        return None, None, "no such repository"
    full = facts.get("full_name") or name
    abouts = [p for p in client.tree(full, facts.get("default_branch") or "HEAD") if p.lower().endswith("about/about.xml")]
    for path in abouts[:TREE_ABOUT_LIMIT]:
        text = client.raw(full, facts.get("default_branch") or "HEAD", path)
        if text is not None and _package_of(text) == package_id:
            return path, facts, ""
    seen = ", ".join(sorted({_package_of(client.raw(full, facts.get("default_branch") or "HEAD", p) or "") or "?" for p in abouts[:2]}))
    return None, facts, (f"its About.xml names {seen}" if abouts else "no About.xml in it; it may hold the source alone")


def search_terms(mod):
    """A GitHub search for a mod: its name without bracketed tags, with RimWorld."""
    name = " ".join(BRACKETED.sub(" ", mod.name).split()) or mod.package_id
    return f"{name} rimworld"


def look_up(client, mod, description, search=True):
    """A finding for one mod: its candidates in order, stopping at the first confirmed."""
    about = _about_root(mod.folder)
    about_text = ET.tostring(about, encoding="unicode") if about is not None else ""
    places = [("About.xml", links(about_text)), ("Workshop page", links(description))]
    finding = {"name": mod.name, "package_id": loading.bare_id(mod.package_id), "workshop_id": mod.workshop_id,
               "repository": "", "found": "", "confirmed": "", "pushed": "", "licence": "", "archived": False,
               "candidates": []}
    tried = set()

    def attempt(where, candidates):
        for name in candidates:
            if name.lower() in tried:
                continue
            tried.add(name.lower())
            confirmed, facts, note = verify(client, name, finding["package_id"])
            label = (facts or {}).get("full_name") or name
            if confirmed:
                finding.update(repository=(facts or {}).get("html_url") or f"https://github.com/{label}", found=where,
                               confirmed=confirmed, pushed=((facts or {}).get("pushed_at") or "")[:10],
                               licence=(((facts or {}).get("license") or {}).get("spdx_id") or ""),
                               archived=bool((facts or {}).get("archived")))
                return True
            finding["candidates"].append({"repository": label, "found": where, "note": note})
        return False

    for where, candidates in places:
        if attempt(where, candidates):
            return finding
    if search and attempt("GitHub search", client.search(search_terms(mod))):
        return finding
    return finding


# ---- The register ----

def read_register(path):
    if not path.is_file():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return data.get("mods", {})


def write_register(path, mods, now):
    data = {"format": REGISTER_FORMAT,
            "description": "Where the public source of each mod this project ties into lives, from phobos-modkit's "
                           "rimworld-sources. A repository counts as confirmed only when an About.xml in it names the mod's "
                           "package ID. Read a mod's source here before decompiling it (AGENTS.md).",
            "updated": now, "mods": dict(sorted(mods.items()))}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")


# ---- Report ----

def build_report(findings, kept, client, problems, top, written):
    every = sorted(list(findings.values()) + list(kept.values()), key=lambda f: f["name"].lower())
    confirmed = [f for f in every if f["confirmed"]]
    unconfirmed = [f for f in every if not f["confirmed"] and f["candidates"]]
    none = [f for f in every if not f["confirmed"] and not f["candidates"]]
    report = Report("rimworld-sources")
    report.lines.append(f"{len(every)} mods: {len(confirmed)} with a confirmed public repository, {len(unconfirmed)} with only "
                        f"unconfirmed candidates, {len(none)} with none found. {len(kept)} taken from the register without "
                        f"looking again.")
    report.lines.append(f"GitHub: {client.fetched} fetched now, {client.reused} from the cache. Keyless; nothing logged in.")
    if written:
        report.lines.append(f"Recorded in {written}.")
    if problems:
        report.blocks.append(Bullets(problems))
    if confirmed:
        rows = [[f["name"], f["repository"], f["found"], f["pushed"] or "-", f["licence"] or "-",
                 "archived" if f["archived"] else ""] for f in confirmed]
        report.section("Confirmed: read these before decompiling",
                       Table(["Mod", "Repository", "Found in", "Last push", "Licence", ""], rows[:top], total=len(rows)))
    if unconfirmed:
        rows = [[f["name"], c["repository"], c["found"], c["note"]] for f in unconfirmed for c in f["candidates"]]
        report.section("Not confirmed: a repository exists, but no About.xml in it names the mod",
                       Table(["Mod", "Candidate", "Found in", "Why not"], rows[:top], total=len(rows)))
    if none:
        report.section("No public source found", Bullets([f"{f['name']} ({f['package_id']})" for f in none][:top]))
    return report


def main(argv=None, settings_file=None, environ=None, out=None, get=None, post=None, sleep=None, clock=None):
    out = out or sys.stdout
    try:
        args = _parser().parse_args(list(sys.argv[1:] if argv is None else argv))
    except SystemExit as stop:
        return EXIT_USAGE if stop.code else EXIT_OK
    settings_file = args.settings or settings_file
    redact = keep if args.no_redact else home_redactor()
    code = EXIT_OK
    try:
        game = paths.game_path(args.game, environ, settings_file)
        workshop_folder = paths.workshop_path(game, args.workshop, environ, settings_file)
        mods_config = Path(paths.config_path(args.config, environ, settings_file)) / "ModsConfig.xml"
        if not mods_config.is_file():
            raise GitHubError(f"No ModsConfig.xml at {mods_config}. Name the folder with --config.")
        named = {loading.bare_id(m) for m in args.mod}
        if args.only_named:
            installed = {loading.bare_id(m.package_id): m for m in ModIndex.scan(default_roots(game, workshop_folder)).mods}
            mods = [installed[m] for m in sorted(named) if m in installed]
        else:
            mods, _, _, _ = tied_active(args.root, game, workshop_folder, mods_config, args.mod)
        register_path = Path(args.root) / REGISTER
        register = read_register(register_path)
        kept = {m.package_id: register[loading.bare_id(m.package_id)] for m in mods
                if not args.recheck and register.get(loading.bare_id(m.package_id), {}).get("confirmed")}
        wanted = [m for m in mods if m.package_id not in kept]

        options = {k: v for k, v in (("sleep", sleep), ("clock", clock)) if v is not None}
        client = Client(derived.folder(GITHUB_CACHE, args.cache, environ, settings_file), get=get or http_get,
                        refresh=args.refresh, **options)
        ids = [m.workshop_id for m in wanted if m.workshop_id]
        descriptions, problems = {}, []
        if ids:
            wcache = derived.folder(workshop.CACHE_FOLDER, args.cache, environ, settings_file)
            done = workshop.refresh(ids, wcache, comments=False, **({"post": post} if post else {}))
            problems += done.problems
            with closing(sqlite3.connect(workshop.index_path(wcache))) as conn:
                descriptions = dict(conn.execute("SELECT id, description FROM item"))
        findings = {}
        for mod in wanted:
            try:
                findings[mod.package_id] = look_up(client, mod, descriptions.get(mod.workshop_id) or "", not args.no_search)
            except RateLimited as limited:
                problems.append(f"{limited} Not looked up yet: {len(wanted) - len(findings)} mods.")
                break
            except GitHubError as error:
                problems.append(f"{mod.name}: {error}")
        written = None
        if args.write:
            merged = dict(register)
            stamp = (clock() if clock else None)
            now = (datetime.fromtimestamp(stamp, timezone.utc) if stamp else datetime.now(timezone.utc)).strftime("%Y-%m-%d")
            for finding in findings.values():
                merged[finding["package_id"]] = dict(finding, checked=now)
            write_register(register_path, merged, now)
            written = str(REGISTER)
        report = build_report(findings, kept, client, problems, args.top, written)
    except (GitHubError, OSError, ET.ParseError) as error:
        report, code = Report("rimworld-sources: error", [str(error)]), EXIT_FAILED
    print(envelope_text("rimworld-sources", report, redact) if args.json else render_markdown(report, redact), file=out)
    return code


MANIFEST = {"game": "rimworld", "parser": _parser, "effect": ONLINE,
            "note": "reads GitHub and Steam keyless, paced and cached; with --write, writes config/source-repos.json in the project"}
