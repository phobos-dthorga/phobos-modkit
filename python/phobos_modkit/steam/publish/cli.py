"""steam-publish: release notes, staging, the owner-run uploader and records for a repository's Workshop items.

    python -m phobos_modkit steam-publish notes --check           release notes current? pages valid?
    python -m phobos_modkit steam-publish notes --write           write the per-version change notes
    python -m phobos_modkit steam-publish status                  every mod: package ready? blockers, sizes, order
    python -m phobos_modkit steam-publish pending                 which items have a newer version than uploaded
    python -m phobos_modkit steam-publish prepare Framework       stage a checked candidate, offline
    python -m phobos_modkit steam-publish upload Framework --create          OWNER ONLY: SteamCMD asks for login
    python -m phobos_modkit steam-publish update --what-if        OWNER ONLY without --what-if: every due update
    python -m phobos_modkit steam-publish pull --visibility --changelog      bring Steam's live state back
    python -m phobos_modkit steam-publish change-notes            worksheets for tidying Change Notes tabs

Run from the repository (or pass --root); the catalogue is config/workshop-publishing.json unless --catalogue says
otherwise. Mods are named in full or by a unique ending (Framework for PhobosFramework). Only upload, update and
reconcile can reach Steam with a login, and only upload and update start SteamCMD: those are for the owner alone,
never for an agent, a test or CI. pull reads Steam's public API without a key.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
import sys

from ... import cache as derived
from ...report import Bullets, Code, Report, Table, envelope_text, home_redactor, keep, render_markdown
from .. import workshop
from . import notes, pull, stage, upload, worksheets
from .project import STAGING_CACHE, Project, PublishError
from ...manifest import OWNER_ONLY, READS, RUNS, WRITES

EXIT_OK, EXIT_FAILED, EXIT_USAGE = 0, 1, 2


def build_parser():
    common = argparse.ArgumentParser(add_help=False)
    g = common.add_argument_group("project")
    g.add_argument("--root", help="the repository (default: the current folder)")
    g.add_argument("--catalogue", help="the Workshop catalogue, relative to the root (default config/workshop-publishing.json)")
    g.add_argument("--cache", help="the kit's cache folder, where candidates are staged (else PHOBOS_MODKIT_CACHE, settings, temp)")
    g.add_argument("--settings", help="a JSON settings file with modkitCachePath")
    o = common.add_argument_group("output")
    o.add_argument("--json", action="store_true", help="print JSON instead of Markdown")
    o.add_argument("--no-redact", action="store_true", help="show the home folder instead of ~")

    p = argparse.ArgumentParser(prog="steam-publish", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="command", metavar="command")
    s = sub.add_parser("notes", parents=[common], help="check or write per-version change notes from changelogs")
    s.add_argument("mods", nargs="*")
    s.add_argument("--version", help="one version only (needs one mod)")
    s.add_argument("--base", help="also require changelog and page edits for content changed since this commit")
    mode = s.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="fail when generated files are missing or stale")
    mode.add_argument("--write", action="store_true", help="write missing or stale files")
    sub.add_parser("status", parents=[common], help="every mod's package, blockers, sizes and publication order")
    sub.add_parser("pending", parents=[common], help="which items have a newer version than the one uploaded")
    s = sub.add_parser("prepare", parents=[common], help="stage a checked candidate for one mod, offline")
    s.add_argument("mod")
    s.add_argument("--build", action="store_true", help="run the catalogue's build command first")
    s = sub.add_parser("verify", parents=[common], help="re-check a staged candidate's files")
    s.add_argument("candidate")
    s = sub.add_parser("upload", parents=[common], help="OWNER ONLY: send one candidate through SteamCMD")
    s.add_argument("mod")
    op = s.add_mutually_exclusive_group(required=True)
    op.add_argument("--create", action="store_const", const="create", dest="operation", help="a new item (always private)")
    op.add_argument("--update", action="store_const", const="update", dest="operation", help="the mod's existing item")
    s.add_argument("--visibility", choices=sorted(upload.VISIBILITY_ALIASES), help="default: private, or the recorded one")
    s.add_argument("--candidate", help="a staged candidate folder (default: the newest)")
    s.add_argument("--confirm-public", action="store_true", help="needed the first time an item goes public")
    s.add_argument("--force", action="store_true", help="send a version already on Steam again")
    upload_options(s)
    s = sub.add_parser("update", parents=[common], help="OWNER ONLY: build, prepare and update every due item")
    s.add_argument("mods", nargs="*")
    s.add_argument("--no-build", action="store_true", help="stage what is already built")
    upload_options(s)
    s = sub.add_parser("reconcile", parents=[common], help="settle an uncertain upload's receipt")
    s.add_argument("receipt")
    who = s.add_mutually_exclusive_group(required=True)
    who.add_argument("--item-id", help="the item Steam shows")
    who.add_argument("--not-created", action="store_true", help="Steam shows no such item")
    s = sub.add_parser("pull", parents=[common], help="bring Steam's live visibility, page and release dates back")
    s.add_argument("mods", nargs="*")
    for area in pull.AREAS:
        s.add_argument(f"--{area}", action="store_true")
    s.add_argument("--write", action="store_true", help="apply; default only reports")
    s = sub.add_parser("change-notes", parents=[common], help="worksheets for tidying each item's Change Notes tab")
    s.add_argument("mods", nargs="*")
    s.add_argument("--no-write", action="store_true", help="only count entries")
    return p


def upload_options(s):
    s.add_argument("--steam-user", help="the Steam account name, remembered locally; never a password")
    s.add_argument("--steamcmd", help="SteamCMD's program, remembered locally")
    s.add_argument("--acknowledge-hold", action="store_true", help="private only: pass holds and unpublished dependencies")
    s.add_argument("--what-if", action="store_true", help="show the plan; write nothing and never start SteamCMD")


# ---- reports ----

def notes_report(project, args):
    state, checked, rows = notes.run(project, args.mods, args.version, args.write, args.base)
    if state == "stale" and not args.check:
        state = "preview"
    report = Report(f"Release notes: {state}")
    report.lines.append(f"{checked} release entries checked; " + (
        f"{len(rows)} generated files written." if state == "written" else
        f"{len(rows)} generated files missing or stale." if rows else "every generated file is current."))
    if rows:
        report.section("Files", Table(["File", "SHA-256"], [r[:2] for r in rows]))
    if state == "preview":
        for path, _, text in rows:
            report.section(path, Code(text.splitlines(), "bbcode"), level=3)
        report.lines.append("Nothing written. Add --write to save them.")
    return report, EXIT_FAILED if state == "stale" else EXIT_OK


def status_report(project):
    rows = stage.status(project)
    report = Report("Workshop status")
    report.lines.append("Publication order, dependencies first: " + ", ".join(r["mod"] for r in rows) + ".")
    report.section("Mods", Table(["Mod", "Version", "Item", "Next", "Package", "Description bytes", "Change note bytes"],
                                 [[r["mod"], r.get("version", ""), r["itemId"] or "none", r.get("operation", ""),
                                   r["package"], r.get("sizes", {}).get("descriptionBytes", ""),
                                   r.get("sizes", {}).get("changeNoteBytes", "")] for r in rows]))
    problems = [f"{r['mod']}: {b}" for r in rows for b in r["blockers"]] + \
               [f"{r['mod']}: {r['error']}" for r in rows if r.get("error")]
    report.section("Blockers and errors", Bullets(problems) if problems else "None.")
    return report, EXIT_OK


def pending_report(project):
    rows = stage.pending(project)
    report = Report("Workshop updates due")
    due = [r["mod"] for r in rows if r["needsUpload"]]
    report.lines.append(f"{len(due)} of {len(rows)} items need an upload" + (f": {', '.join(due)}." if due else "."))
    report.section("Mods", Table(["Mod", "Version", "Item", "Uploaded", "Visibility", "Due"],
                                 [[r["mod"], r["version"], r["itemId"] or "none", r["uploadedVersion"] or "",
                                   r["uploadedVisibility"] or "", "yes" if r["needsUpload"] else ""] for r in rows]))
    return report, EXIT_OK


def manifest_report(title, folder, manifest):
    report = Report(title)
    report.lines += [f"{manifest['mod']} {manifest['version']}: {manifest['operation']}"
                     + (f" of item {manifest['itemId']}" if manifest["itemId"] else " of a new item") + ".",
                     f"Candidate: {folder}",
                     f"{len(manifest['files'])} files; change note covers {', '.join(manifest['changeNoteVersions'])}."]
    if manifest.get("workingTreeDirty"):
        report.lines.append("Prepared from uncommitted changes: good for a private test only.")
    report.section("Blockers", Bullets(manifest["blockers"]) if manifest["blockers"] else "None.")
    required = [f"{r['name']} ({r['itemId'] or 'not published yet'})" for r in manifest["requiredItemDetails"]]
    report.section("Required items to set on Steam", Bullets(required) if required else "None.")
    return report


def pull_report(project, args, post):
    areas = {a for a in pull.AREAS if getattr(args, a)}
    rows, changes = pull.plan(project, args.mods, areas, post)
    if args.write and changes:
        pull.apply(project, changes)
    state = "written" if args.write and changes else "preview" if changes else "unchanged"
    report = Report(f"Pull from Steam: {state}")
    for row in rows:
        live = f"{row['visibility']} on Steam, last updated {row['updated']}" if row.get("visibility") else ""
        report.section(row["mod"], *( [live] if live else []), Bullets(row["changes"] + row["notes"]) if
                       row["changes"] or row["notes"] else "Nothing to change.")
    if not areas:
        report.lines.append("Report only: add --visibility, --description and/or --changelog to choose what to pull.")
    elif state == "preview":
        report.lines.append("Nothing written. Add --write to apply, then review and commit.")
    elif state == "written":
        report.lines.append("Written: " + ", ".join(sorted(project.rel(p) for p in changes)) + ". Review and commit.")
    return report, EXIT_OK


def worksheets_report(project, args):
    rows = worksheets.run(project, args.mods, not args.no_write)
    report = Report("Change-note worksheets")
    report.section("Items", Table(["Mod", "Change notes", "To replace", "Worksheet"],
                                  [[m, n, r, "" if args.no_write else w] for m, n, r, w in rows]))
    return report, EXIT_OK


# ---- running ----

def main(argv=None, root=None, payload=None, settings_file=None, environ=None, out=None, post=None, run=None,
         build_run=None, adapters=None):
    """Run the command. A game repository's wrapper passes root, settings_file and, if it has one, a payload hook
    (project, mod) -> {relative path: bytes}. Tests pass stand-ins for Steam (post, run and build_run)."""
    out = out or sys.stdout
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.command:
        parser.print_help(out)
        return EXIT_USAGE
    redact = keep if args.no_redact else home_redactor()
    say = lambda line: print(redact(str(line)), file=out, flush=True)
    if adapters is None:
        from ...games import publish_adapters
        adapters = publish_adapters()
    try:
        cache = derived.folder(STAGING_CACHE, args.cache, environ, args.settings or settings_file)
        project = Project.load(args.root or root or Path.cwd(), adapters, args.catalogue, payload, cache)
        report, code = dispatch(project, args, say, post or workshop.http_post, run or upload.run_steamcmd,
                                build_run or subprocess.run, environ)
    except (PublishError, ValueError, OSError, KeyError, subprocess.SubprocessError, workshop.WorkshopError) as error:
        report, code = Report("steam-publish: error", [str(error)]), EXIT_FAILED
    if report is not None:
        print(envelope_text("steam-publish", report, redact) if args.json
              else render_markdown(report, redact), file=out)
    return code


def dispatch(project, args, say, post, run, build_run, environ):
    command = args.command
    if command == "notes":
        return notes_report(project, args)
    if command == "status":
        return status_report(project)
    if command == "pending":
        return pending_report(project)
    if command == "prepare":
        mod = project.resolve(args.mod)
        if args.build and not upload.build(project, mod, build_run):
            raise PublishError("--build needs a build command in the catalogue")
        folder, manifest = stage.prepare(project, mod)
        return manifest_report("Candidate prepared (offline)", folder, manifest), EXIT_OK
    if command == "verify":
        manifest = stage.verify(Path(args.candidate))
        return manifest_report("Candidate verified (offline)", args.candidate, manifest), EXIT_OK
    if command == "upload":
        request = upload.Request(args.mod, args.operation, args.visibility, args.candidate, args.steam_user,
                                 args.steamcmd, args.acknowledge_hold, args.confirm_public, args.what_if, args.force)
        upload.upload(project, request, say, run, environ=environ)
        return None, EXIT_OK
    if command == "update":
        upload.update_all(project, args.mods, say, args.no_build, args.what_if, args.acknowledge_hold,
                          args.steam_user, args.steamcmd, run, build_run, environ)
        return None, EXIT_OK
    if command == "reconcile":
        state = upload.reconcile(project, args.receipt, args.item_id, args.not_created)
        return Report("Receipt reconciled", [f"Marked {state}."]), EXIT_OK
    if command == "pull":
        return pull_report(project, args, post)
    if command == "change-notes":
        return worksheets_report(project, args)
    raise PublishError(f"Unknown command {command}")


MANIFEST = {"game": None, "parser": build_parser, "effect": READS, "reports": {
    "notes": {"effect": WRITES, "when": "--write"},
    "prepare": {"effect": RUNS, "when": "--build", "note": "stages a candidate in the kit's cache"},
    "upload": {"effect": OWNER_ONLY, "note": "only the owner runs it, in their own console"},
    "update": {"effect": OWNER_ONLY, "note": "only the owner runs it, in their own console"},
    "reconcile": {"effect": WRITES, "note": "settles an upload's receipt"},
    "pull": {"effect": WRITES, "when": "--write", "note": "reads Steam"},
    "change-notes": {"effect": WRITES, "note": "--no-write only counts"},
}}
