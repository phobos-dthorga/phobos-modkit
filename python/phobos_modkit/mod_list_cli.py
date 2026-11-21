"""mod-list: what is wrong with a game's list of active mods, why, and safe changes that put it right (1.72.0).

    mod-list check --name GAME [--online] [--list KEY]     every problem, warning and note, with the changes offered
    mod-list mods --name GAME                                          every mod on this PC, and where each list has it (1.73.0)
    mod-list fix --name GAME --list KEY --remove ID [--apply]          take a mod off a list (also --remove-extra, --enable)
    mod-list fix --name GAME --list KEY --move ID --to PLACE [--apply] move a mod to a place, 1 first (1.73.0)
    mod-list undo --name GAME --list KEY [--backup FILE] [--apply]     go back on the last change; again, the one before
    mod-list backups --name GAME                                       every backup kept of the game's lists
    mod-list games                                                     the games whose lists the check can read

GAME is a game's name or id (RimWorld, project-zomboid), or give --app-id. `check` reads only, and with --online also asks Steam's
public Workshop API which items still exist (no account). `fix` and `undo` change nothing without --apply; with it, they keep a
backup of the list as it stood first, and refuse while the game or a program that rewrites the list (RimSort) is running.
Backups and the memory of every mod seen live in D'thorga Companion's folder (setting modListPath) and are never deleted here.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys

from . import history
from . import mod_list as core
from .games import MOD_LIST_GAMES, mod_list_adapter, mod_list_game
from .installs import game_running
from .manifest import ONLINE, READS, WRITES
from .progress import Progress
from .report import Bullets, Fact, Report, Table, envelope_text, home_redactor, keep, render_markdown

EXIT_OK, EXIT_REFUSED, EXIT_USAGE = 0, 1, 2
BACKUPS_LISTED = 10
HEADINGS = {core.PROBLEM: "Problems", core.WARNING: "Warnings", core.NOTE: "Notes"}


def _common(p, lists=True):
    p.add_argument("--name", help="the game, by name or id (RimWorld, project-zomboid)")
    p.add_argument("--app-id", type=int, help="the game's Steam app ID, instead of its name")
    p.add_argument("--data", help="the game's own data folder, where the tools would not find it")
    p.add_argument("--settings", help="a JSON settings file with the games' paths")
    if lists:
        p.add_argument("--list", dest="list_key", metavar="KEY", help="only this list, by the key a check names")
    p.add_argument("--json", action="store_true", help="print JSON instead of Markdown")
    p.add_argument("--no-redact", action="store_true", help="show the home folder instead of ~")


def _parser():
    p = argparse.ArgumentParser(prog="mod-list", description=__doc__.split("\n\n")[0],
                                formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__.split("\n\n", 1)[1])
    sub = p.add_subparsers(dest="report", required=True)
    check = sub.add_parser("check", help="every problem with the game's lists of active mods, why, and the changes offered")
    _common(check)
    check.add_argument("--online", action="store_true", help="ask Steam which Workshop items still exist")
    fix = sub.add_parser("fix", help="one change to a list, after a backup; only with --apply")
    _common(fix)
    change = fix.add_mutually_exclusive_group(required=True)
    change.add_argument("--remove", metavar="ID", help="take this mod off the list")
    change.add_argument("--remove-extra", metavar="ID", help="keep the first entry of this mod and take the others off")
    change.add_argument("--enable", metavar="ID", help="switch this mod on: at --to, else just before the first mod that needs it")
    change.add_argument("--move", metavar="ID", help="move this mod to the place --to names")
    fix.add_argument("--to", type=int, metavar="PLACE", help="the place a mod moved or switched on goes to, 1 first (1.73.0)")
    fix.add_argument("--apply", action="store_true", help="make the change; without it, only say what it would be")
    undo = sub.add_parser("undo", help="put a list back as it was before the last change made here; only with --apply")
    _common(undo)
    undo.add_argument("--backup", help="this backup (its file name), instead of the latest")
    undo.add_argument("--apply", action="store_true", help="go back; without it, only say what it would do")
    mods = sub.add_parser("mods", help="every mod on this PC, and where each of the game's lists has it")
    _common(mods, lists=False)
    backups = sub.add_parser("backups", help="every backup kept of the game's lists, newest first")
    _common(backups, lists=False)
    games = sub.add_parser("games", help="the games whose lists the check can read")
    games.add_argument("--json", action="store_true", help="print JSON instead of Markdown")
    games.add_argument("--no-redact", action="store_true", help="show the home folder instead of ~")
    return p


# ---------------------------------------------------------------- reading

def _steam_results(ids, post=None):
    from .steam.workshop import fetch_details, http_post
    items = fetch_details(sorted(ids), post or http_post)
    return {item.id: item.result for item in items}


def survey(adapter, environ=None, settings=None, online=False, list_key=None, post=None, progress=None, now=None):
    """Everything a check finds, as plain data."""
    progress = progress or (lambda *a, **k: None)
    progress("Reading your mods", 1, 4)
    mods = adapter.installed()
    installed = core.Installed(adapter, mods)
    memory = core.remember(core.remembered_file(adapter.game, environ, settings), adapter, mods, now)
    lists = [m for m in adapter.lists() if list_key is None or m.key == list_key]
    notes = list(adapter.notes())
    progress("Asking Steam what it keeps", 2, 4)
    subscribed = adapter.subscribed()
    steam = None
    if online:
        ids = {m.workshop_id for m in mods if m.source == "workshop" and m.workshop_id}
        for mod_list in lists:
            for listed in mod_list.ids:
                remembered = memory.get(adapter.key(listed))
                if installed.find(listed) is None and remembered and remembered.get("workshop_id"):
                    ids.add(remembered["workshop_id"])
        try:
            steam = _steam_results(ids, post) if ids else {}
        except Exception as error:   # the check still stands without Steam; it says why
            notes.append(f"Steam could not be asked which Workshop items still exist ({error}); read again later.")
    progress("Checking each list", 3, 4)
    problems = []
    for mod_list in lists:
        problems += core.check(adapter, mod_list, installed, memory, steam, subscribed)
    progress("Done", 4, 4)
    counts = {s: sum(1 for p in problems if p.severity == s) for s in core.SEVERITIES}
    return {"game": adapter.game, "name": adapter.name, "supported": True, "version": adapter.game_version(),
            "online": steam is not None, "notes": notes, "installed": len(mods),
            "running": game_running(list(adapter.processes) + list(adapter.managers)),
            "lists": [{"key": m.key, "label": m.label, "path": str(m.path), "count": len(m.ids), "writable": m.writable}
                      for m in lists],
            "problems": [core.problem_data(p) for p in problems], "counts": counts,
            "backups": [_backup_data(r, f) for r, f in core.backups(adapter.game, environ, settings)[:BACKUPS_LISTED]]}


def _backup_data(record, listed):
    return {"list": record.get("list", ""), "why": record.get("why", ""), "at": record.get("at", ""), "file": listed.name,
            "undone": bool(record.get("undone"))}


def mods_data(adapter, environ=None, settings=None, now=None, progress=None):
    """Every mod on this PC with what the list editor shows, and each list's entries in order, joined by key (1.73.0)."""
    progress = progress or (lambda *a, **k: None)
    progress("Reading your mods", 1, 2)
    mods = adapter.installed()
    memory = core.remember(core.remembered_file(adapter.game, environ, settings), adapter, mods, now)
    seen = set()
    rows = []
    for mod in mods:
        key = adapter.key(mod.id)
        if key in seen:
            continue
        seen.add(key)
        rows.append({"key": key, "id": mod.id, "name": mod.name, "source": mod.source, "workshop_id": mod.workshop_id,
                     "authors": mod.authors, "versions": list(mod.versions), "needs": [n.name or n.ids[0] for n in mod.needs]})
    lists = []
    for mod_list in adapter.lists():
        lists.append({"key": mod_list.key, "label": mod_list.label, "writable": mod_list.writable, "count": len(mod_list.ids),
                      "entries": [{"id": i, "key": adapter.key(i),
                                   "remembered": (memory.get(adapter.key(i)) or {}).get("name", "")} for i in mod_list.ids]})
    progress("Done", 2, 2)
    return {"game": adapter.game, "name": adapter.name, "supported": True, "version": adapter.game_version(), "mods": rows,
            "lists": lists, "running": game_running(list(adapter.processes) + list(adapter.managers)),
            "notes": list(adapter.notes()),
            "changes": {m["key"]: len(core.changes(adapter.game, m["key"], environ, settings)) for m in lists}}


def _bullet(problem):
    text = f"**{problem['title']}**"
    if problem["why"]:
        text += f" {problem['why']}"
    if problem["clue"]:
        text += f" Clue: {problem['clue']}"
    if problem["fixes"]:
        text += " Changes offered: " + "; ".join(f"{f['label']} (`--{f['action']} {f['id']}`)" for f in problem["fixes"]) + "."
    return text


def check_report(data):
    counts = data["counts"]
    report = Report(f"Mod list: {data['name']}: {counts['problem']} problems, {counts['warning']} warnings")
    report.facts += [Fact("Game", data["name"]), Fact("Version", data["version"] or "unknown"),
                     Fact("Mods on this PC", str(data["installed"])), Fact("Asked Steam", "yes" if data["online"] else "no")]
    for mod_list in data["lists"]:
        report.lines.append(f"{mod_list['label']}: {mod_list['count']} mods (list `{mod_list['key']}`).")
    if not data["lists"]:
        report.lines.append("No list of active mods was found.")
    if data["running"]:
        report.lines.append(f"Running now: {', '.join(data['running'])}. Changes wait until it is closed.")
    for severity in core.SEVERITIES:
        found = [p for p in data["problems"] if p["severity"] == severity and p["kind"] != "version"]
        lines = [_bullet(p) for p in found]
        versions = [p for p in data["problems"] if p["severity"] == severity and p["kind"] == "version"]
        if versions:
            lines.append(f"**{len(versions)} mods do not say they work with version {data['version']} of the game.** Many still "
                         "work; look at one if the game reports errors from it: " + ", ".join(p["name"] for p in versions) + ".")
        if lines:
            report.section(HEADINGS[severity], Bullets(lines))
    if not data["problems"]:
        report.lines.append("Nothing wrong was found.")
    if data["notes"]:
        report.section("What the check could not see", Bullets(data["notes"]))
    return report


def unsupported(name, app_id):
    label = name or (f"app {app_id}" if app_id else "That game")
    return {"game": name or "", "name": label, "supported": False, "version": "", "online": False, "installed": 0,
            "notes": [f"The tools cannot read {label}'s list of active mods yet. The games they can read: "
                      + ", ".join(row[1] for row in MOD_LIST_GAMES) + "."],
            "running": [], "lists": [], "problems": [], "counts": {s: 0 for s in core.SEVERITIES}, "backups": []}


# ---------------------------------------------------------------- changing

def _the_list(adapter, key):
    if not key:
        raise core.FixError("Name the list to change with --list (a check names each list's key).")
    found = next((m for m in adapter.lists() if m.key == key), None)
    if found is None:
        raise core.FixError(f"{adapter.name} has no list {key!r}.")
    return found


def _change(args):
    for action, value in ((core.REMOVE, args.remove), (core.REMOVE_EXTRA, args.remove_extra), (core.ENABLE, args.enable),
                          (core.MOVE, args.move)):
        if value:
            return action, value
    raise core.FixError("Name one change: --remove, --remove-extra or --enable.")


def fix(adapter, args, environ=None, running=game_running, now=None):
    mod_list = _the_list(adapter, args.list_key)
    action, mod_id = _change(args)
    # Only switching on needs to know what is on this PC; reading 400 mods' files would slow every move (1.73.0).
    installed = core.Installed(adapter, adapter.installed()) if action == core.ENABLE else None
    ids, words = core.plan(adapter, mod_list, installed, action, mod_id, args.to)
    before = {adapter.key(i) for i in mod_list.ids}
    after = {adapter.key(i) for i in ids}
    data = {"list": mod_list.key, "label": mod_list.label, "action": action, "id": mod_id, "change": words,
            "removed": sorted(before - after), "added": sorted(after - before), "applied": False, "backup": "",
            "ids": ids, "keys": [adapter.key(i) for i in ids]}
    if args.apply:
        words, backup, ids = core.apply_fix(adapter, mod_list, installed, action, mod_id, running, environ, args.settings, now,
                                            args.to)
        data.update(applied=True, backup=backup.name)
        history.record(adapter.game, "mod-list-change", environ, args.settings, now, list=mod_list.key, change=words,
                       backup=backup.name)
    report = Report(f"Mod list: {words}" + ("" if args.apply else " (preview)"))
    report.lines.append(f"{mod_list.label}: {len(mod_list.ids)} mods now, {len(ids)} after.")
    report.lines.append(f"Kept a backup first: {data['backup']}." if args.apply else "**Preview only. Add --apply to make it.**")
    return report, data


def undo(adapter, args, environ=None, running=game_running, now=None):
    mod_list = _the_list(adapter, args.list_key)
    if not args.apply:
        choices = core.changes(adapter.game, mod_list.key, environ, args.settings)
        if args.backup:
            choices = [(r, f) for r, f in choices if f.name == args.backup]
        if not choices:
            raise core.FixError(f"There is no change of {mod_list.label} to go back on.")
        record, listed = choices[0]
        report = Report(f"Mod list: go back on \"{record.get('why')}\" (preview)")
        report.lines.append("**Preview only. Add --apply to go back.**")
        return report, {"list": mod_list.key, "undoes": record.get("why", ""), "file": listed.name, "applied": False}
    record = core.undo(adapter, mod_list, running, environ, args.settings, now, args.backup)
    history.record(adapter.game, "mod-list-undo", environ, args.settings, now, list=mod_list.key, undid=record.get("why", ""))
    report = Report(f"Mod list: went back on \"{record.get('why')}\"")
    report.lines.append("The list as it was just now is kept as a backup too.")
    ids = next((m.ids for m in adapter.lists() if m.key == mod_list.key), [])
    return report, {"list": mod_list.key, "undoes": record.get("why", ""), "applied": True, "ids": ids,
                    "keys": [adapter.key(i) for i in ids]}


def main(argv=None, environ=None, out=None, post=None, running=None, now=None):
    out = out or sys.stdout
    environ = os.environ if environ is None else environ
    try:
        args = _parser().parse_args(list(sys.argv[1:] if argv is None else argv))
    except SystemExit as stop:
        return EXIT_USAGE if stop.code else EXIT_OK
    redact = keep if args.no_redact else home_redactor()
    if args.report == "games":
        rows = [{"id": r[0], "name": r[1], "appId": r[2]} for r in MOD_LIST_GAMES]
        report = Report("Mod list: the games it can read")
        report.section("Games", Table(["Id", "Name", "Steam app"], [[r["id"], r["name"], r["appId"]] for r in rows]))
        out.write((envelope_text("mod-list", report, redact, {"games": rows}) if args.json else render_markdown(report, redact)) + "\n")
        return EXIT_OK
    row = mod_list_game(args.name, args.app_id)
    if row is None:
        if args.report not in ("check", "mods"):
            print(f"The tools cannot change {args.name or args.app_id}'s mod list yet.", file=sys.stderr)
            return EXIT_REFUSED
        data = unsupported(args.name, args.app_id)
        data.update(mods=[], changes={})
        report = check_report(data)
        out.write((envelope_text("mod-list", report, redact, data) if args.json else render_markdown(report, redact)) + "\n")
        return EXIT_OK
    adapter = mod_list_adapter(row, environ, args.settings, args.data)
    try:
        if args.report == "check":
            data = survey(adapter, environ, args.settings, args.online, args.list_key, post, Progress(environ), now)
            report = check_report(data)
        elif args.report == "mods":
            data = mods_data(adapter, environ, args.settings, now, Progress(environ))
            report = Report(f"Mod list: {len(data['mods'])} mods on this PC for {adapter.name}")
            for mod_list in data["lists"]:
                report.lines.append(f"{mod_list['label']}: {mod_list['count']} on.")
            report.section("Mods", Table(["Name", "Id", "From", "Workshop"],
                                         [[m["name"], m["id"], m["source"], m["workshop_id"]] for m in data["mods"]]))
        elif args.report == "backups":
            found = core.backups(adapter.game, environ, args.settings)
            data = {"backups": [_backup_data(r, f) for r, f in found]}
            report = Report(f"Mod list: {len(found)} backups of {adapter.name}'s lists")
            report.section("Backups", Table(["When", "List", "Kept before", "File"],
                                            [[b["at"], b["list"], b["why"], b["file"]] for b in data["backups"]]))
        elif args.report == "fix":
            report, data = fix(adapter, args, environ, running or game_running, now)
        else:
            report, data = undo(adapter, args, environ, running or game_running, now)
    except (core.FixError, ValueError, OSError) as error:
        # A refusal is an answer, as the kit's other writers give it: {"ok": false, "refusal": words} under --json.
        said = str(error)
        report = Report("Mod list: nothing was changed")
        report.lines.append(said)
        out.write((envelope_text("mod-list", report, redact, {"ok": False, "refusal": said}) if args.json
                   else render_markdown(report, redact)) + "\n")
        return EXIT_REFUSED
    out.write((envelope_text("mod-list", report, redact, data) if args.json else render_markdown(report, redact)) + "\n")
    return EXIT_OK


MANIFEST = {"game": None, "parser": _parser, "effect": READS, "surface": "mod-list",
            "question": "Is anything wrong with my list of active mods, and why?",
            "reports": {"check": {"effect": ONLINE, "when": "--online"},
                        "fix": {"effect": WRITES, "when": "--apply", "question": None},
                        "undo": {"effect": WRITES, "when": "--apply", "question": None},
                        "backups": {"question": "Which backups of my mod lists are kept?"},
                        "mods": {"question": "Which mods are on this PC, and which are switched on?"},
                        "games": {"question": "Which games' mod lists can the tools read?"}}}


if __name__ == "__main__":
    sys.exit(main())
