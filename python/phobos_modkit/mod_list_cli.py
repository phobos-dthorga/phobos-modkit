"""mod-list: what is wrong with a game's list of active mods, why, and safe changes that put it right (1.72.0).

    mod-list check --name GAME [--online] [--list KEY]     every problem, warning and note, with the changes offered
    mod-list mods --name GAME                                          every mod on this PC, and where each list has it (1.73.0)
    mod-list fix --name GAME --list KEY --remove ID [--apply]          take a mod off a list (also --remove-extra, --enable)
    mod-list fix --name GAME --list KEY --move ID --to PLACE [--apply] move a mod to a place, 1 first (1.73.0)
    mod-list sort --name GAME --list KEY [--full] [--apply]           sort the list from every rule, each move explained (1.74.0)
    mod-list rules --name GAME                                         your own rules, and every rule set the sorter reads
    mod-list rules --name GAME --mod ID --after OTHER [--apply]        keep a rule of your own (also --before, --top, --bottom)
    mod-list rules --name GAME --drop N [--apply]                      take your rule N away
    mod-list lists --name GAME                                         every saved list: by name, at game starts, saves, RimSort
    mod-list compare --name GAME --list KEY --from SOURCE:REF          what loading a list would change (or --file PATH)
    mod-list load --name GAME --list KEY --from SOURCE:REF [--apply]   load it, leaving out mods not on this PC (1.75.0)
    mod-list save --name GAME --list KEY --as NAME [--replace] [--apply]   keep the list as it stands, by name
    mod-list forget --name GAME --saved NAME [--apply]                 take away a list saved by name
    mod-list export --name GAME (--list KEY | --from SOURCE:REF) --to PATH [--apply]   write a list as the game's own file
    mod-list subscribe --name GAME --item N [--item N ...] [--wait SECONDS] [--apply]   subscribe through Steam (1.77.0)
    mod-list unsubscribe --name GAME --list KEY --item N [...] [--apply]   switch them off, then unsubscribe through Steam
    mod-list undo --name GAME --list KEY [--backup FILE] [--apply]     go back on the last change; again, the one before
    mod-list backups --name GAME                                       every backup kept of the game's lists
    mod-list games                                                     the games whose lists the check can read

Several mods may be moved, switched on or switched off at once: name each with its own --move, --enable or --remove (1.74.0).
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
from . import mod_lists
from .steam import client as steam_client
from . import mod_sort
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
    change.add_argument("--remove", metavar="ID", action="append", help="take this mod off the list (again for several)")
    change.add_argument("--remove-extra", metavar="ID", help="keep the first entry of this mod and take the others off")
    change.add_argument("--enable", metavar="ID", action="append",
                        help="switch this mod on: at --to, else just before the first mod that needs it (again for several)")
    change.add_argument("--move", metavar="ID", action="append",
                        help="move this mod to the place --to names (again for several, moved as one block)")
    fix.add_argument("--to", type=int, metavar="PLACE", help="the place a mod moved or switched on goes to, 1 first (1.73.0)")
    fix.add_argument("--apply", action="store_true", help="make the change; without it, only say what it would be")
    undo = sub.add_parser("undo", help="put a list back as it was before the last change made here; only with --apply")
    _common(undo)
    undo.add_argument("--backup", help="this backup (its file name), instead of the latest")
    undo.add_argument("--apply", action="store_true", help="go back; without it, only say what it would do")
    sort = sub.add_parser("sort", help="the list sorted from every rule, each move explained; written only with --apply")
    _common(sort)
    sort.add_argument("--full", action="store_true", help="rebuild the whole order (else move only what a rule says is out of place)")
    sort.add_argument("--apply", action="store_true", help="write the sorted list, after a backup")
    rules = sub.add_parser("rules", help="your own load-order rules, and every rule set the sorter reads")
    _common(rules, lists=False)
    rules.add_argument("--mod", metavar="ID", help="the mod a new rule is about")
    where = rules.add_mutually_exclusive_group()
    where.add_argument("--after", metavar="OTHER", help="it loads after this mod")
    where.add_argument("--before", metavar="OTHER", help="it loads before this mod")
    where.add_argument("--top", action="store_true", help="it loads as near the top as its rules allow")
    where.add_argument("--bottom", action="store_true", help="it loads as near the bottom as its rules allow")
    where.add_argument("--drop", type=int, metavar="N", help="take your rule N away (as `rules` numbers them)")
    rules.add_argument("--apply", action="store_true", help="keep the change; without it, only say what it would be")
    lists = sub.add_parser("lists", help="every saved list: by name, kept at game starts, each save's, and RimSort's history")
    _common(lists, lists=False)
    for name, words in (("compare", "what loading a list would change; only reads"),
                        ("load", "load a list in place of the one the game reads, after a backup; only with --apply")):
        each = sub.add_parser(name, help=words)
        _common(each)
        source = each.add_mutually_exclusive_group(required=True)
        source.add_argument("--from", dest="from_list", metavar="SOURCE:REF",
                            help="a list as `lists` names it: saved:NAME, kept:TIME, save:FILE, manager:FILE")
        source.add_argument("--file", metavar="PATH", help="a list file (the game's .rml, a save, an exported RimSort list)")
        if name == "load":
            each.add_argument("--apply", action="store_true", help="write it; without it, only say what it would do")
    save = sub.add_parser("save", help="keep the list as it stands, by name; only with --apply")
    _common(save)
    save.add_argument("--as", dest="as_name", required=True, metavar="NAME", help="the name to keep it by")
    save.add_argument("--replace", action="store_true", help="replace a list kept by that name")
    save.add_argument("--apply", action="store_true", help="keep it; without it, only say what it would do")
    forget = sub.add_parser("forget", help="take away a list saved by name; only with --apply")
    _common(forget, lists=False)
    forget.add_argument("--saved", required=True, metavar="NAME", help="the saved list's name, as `lists` gives its ref")
    forget.add_argument("--apply", action="store_true", help="take it away; without it, only say what it would do")
    export = sub.add_parser("export", help="write a list as the game's own list file; only with --apply")
    _common(export)
    export.add_argument("--from", dest="from_list", metavar="SOURCE:REF", help="a saved list, instead of the game's list")
    export.add_argument("--to", dest="to_file", required=True, metavar="PATH", help="the file to write")
    export.add_argument("--apply", action="store_true", help="write it; without it, only say what it would do")
    subscribe = sub.add_parser("subscribe", help="subscribe to Workshop items through the running Steam client; only with --apply")
    _common(subscribe, lists=False)
    subscribe.add_argument("--item", action="append", required=True, metavar="N", help="a Workshop number (again for several)")
    subscribe.add_argument("--wait", type=int, default=0, metavar="SECONDS",
                           help="wait this long for Steam to download them, saying how far it is")
    subscribe.add_argument("--apply", action="store_true", help="subscribe; without it, only say what it would do")
    unsubscribe = sub.add_parser("unsubscribe", help="switch Workshop mods off, then unsubscribe through Steam; only with --apply")
    _common(unsubscribe)
    unsubscribe.add_argument("--item", action="append", required=True, metavar="N", help="a Workshop number (again for several)")
    unsubscribe.add_argument("--apply", action="store_true", help="do it; without it, only say what it would do")
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
    _keep_at_start(adapter, installed, environ, settings)
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
    _keep_at_start(adapter, core.Installed(adapter, mods), environ, settings)
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


def _keep_at_start(adapter, installed, environ, settings):
    """A copy of the list the game last started with, kept when it differs from the last copy (1.75.0): every read notices."""
    found = adapter.lists()
    if found and found[0].writable:
        mod_lists.keep_at_start(adapter, found[0], installed, environ, settings)


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
            return action, (value[0] if isinstance(value, list) and len(value) == 1 else value)
    raise core.FixError("Name one change: --remove, --remove-extra, --enable or --move.")


def fix(adapter, args, environ=None, running=game_running, now=None):
    mod_list = _the_list(adapter, args.list_key)
    action, mod_id = _change(args)
    # Only switching on needs to know what is on this PC; reading 400 mods' files would slow every move (1.73.0).
    installed = core.Installed(adapter, adapter.installed()) if action == core.ENABLE else None
    ids, words = core.plan(adapter, mod_list, installed, action, mod_id, args.to)
    before = {adapter.key(i) for i in mod_list.ids}
    after = {adapter.key(i) for i in ids}
    data = {"list": mod_list.key, "label": mod_list.label, "action": action,
            "id": mod_id if isinstance(mod_id, str) else ", ".join(mod_id), "change": words,
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


SORT_SHOWN = 60          # moves listed in the Markdown report (the JSON has them all)


def sort(adapter, args, environ=None, running=game_running, now=None, progress=None):
    progress = progress or (lambda *a, **k: None)
    mod_list = _the_list(adapter, args.list_key)
    how = mod_sort.FULL if args.full else mod_sort.FEWEST
    progress("Reading your mods and every rule", 1, 3)
    data = mod_sort.sort_list(adapter, mod_list, how, environ, args.settings)
    progress("Sorting", 2, 3)
    words = ("re-sort the whole list" if args.full else "sort the list") + f": {len(data['moves'])} moved"
    data.update(list=mod_list.key, label=mod_list.label, change=words, applied=False, backup="",
                sets=[mod_sort.rule_data(s) for s in mod_sort.every_rule_set(adapter, environ, args.settings)])
    if args.apply:
        backup = core.apply_order(adapter, mod_list, data["ids"], words, running, environ, args.settings, now)
        data.update(applied=True, backup=backup.name)
        history.record(adapter.game, "mod-list-change", environ, args.settings, now, list=mod_list.key, change=words,
                       backup=backup.name)
    progress("Done", 3, 3)
    report = Report(f"Mod list: {words}" + ("" if args.apply else " (preview)"))
    used = data["rules"]
    report.lines.append(f"Rules read: {used['own']} from mods' own files, {used['needs']} from what mods need, "
                        f"{used['workshop']} from Workshop pages, {used['community']} community, {used['yours']} yours.")
    if data["moves"]:
        rows = [[str(m["from"]), str(m["to"]), m["name"], " ".join(m["why"])] for m in data["moves"][:SORT_SHOWN]]
        report.section("Moves", Table(["From", "To", "Mod", "Why"], rows))
    else:
        report.lines.append("Nothing needs to move.")
    if data["set_aside"]:
        report.section("Rules set aside", Bullets([f"{g['rule']} (a loop: {g['loop']})" for g in data["set_aside"]]))
    report.lines.append(f"Kept a backup first: {data['backup']}." if args.apply else "**Preview only. Add --apply to write it.**")
    return report, data


def _rule_kind(args):
    for kind in ("after", "before"):
        if getattr(args, kind):
            return kind, getattr(args, kind)
    for kind in ("top", "bottom"):
        if getattr(args, kind):
            return kind, ""
    return None, ""


def rules(adapter, args, environ=None, now=None):
    path = mod_sort.rules_file(adapter.game, environ, args.settings)
    kind, other = _rule_kind(args)
    data = {"changed": "", "applied": False}
    if args.drop is not None:
        listed = mod_sort.load_own_rules(path)
        if not 1 <= args.drop <= len(listed):
            raise core.FixError(f"There is no rule {args.drop}; there are {len(listed)}.")
        data["changed"] = "take away: " + mod_sort.rule_words(listed[args.drop - 1])
        if args.apply:
            mod_sort.drop_rule(path, args.drop)
            data["applied"] = True
    elif kind:
        if not args.mod:
            raise core.FixError("Name the mod the rule is about with --mod.")
        data["changed"] = "keep: " + mod_sort.rule_words({"mod": args.mod, "kind": kind, "other": other})
        if args.apply:
            mod_sort.add_rule(adapter, path, args.mod, kind, other, now)
            data["applied"] = True
    elif args.mod:
        raise core.FixError("Say where it loads: --after, --before, --top or --bottom.")
    own = mod_sort.load_own_rules(path)
    data.update(rules=[dict(r, number=n, words=mod_sort.rule_words(r)) for n, r in enumerate(own, 1)],
                sets=[mod_sort.rule_data(s) for s in mod_sort.every_rule_set(adapter, environ, args.settings)],
                theirs=_manager_rules(adapter))
    report = Report(f"Mod list: {len(own)} rules of your own for {adapter.name}")
    if data["changed"]:
        report.lines.append(("Done: " if data["applied"] else "Preview: ") + data["changed"] + "."
                            + ("" if data["applied"] else " **Add --apply to keep it.**"))
    if own:
        report.section("Your rules here", Bullets([f"{r['number']}. {r['words']}" for r in data["rules"]]))
    if data["theirs"]:
        report.section("Your rules in RimSort (read only)", Bullets([r["words"] for r in data["theirs"]]))
    report.section("What the sorter reads", Table(["Rules", "Mods with rules", "Where"],
                                                  [[s["label"], str(s["count"]), s["where"]] for s in data["sets"]]))
    return report, data


def _manager_rules(adapter):
    """The owner's rules a mod manager keeps (RimSort's user rules), in words, read only."""
    found = []
    for rule_set in (adapter.rule_sets() if hasattr(adapter, "rule_sets") else []):
        if rule_set.source != mod_sort.YOURS:
            continue
        for mod, entry in sorted(rule_set.rules.items()):
            for kind in ("after", "before"):
                for other, note in entry.get(kind, []):
                    found.append({"mod": mod, "kind": kind, "other": other, "note": note,
                                  "words": mod_sort.rule_words({"mod": mod, "kind": kind, "other": other})})
            for kind in ("top", "bottom"):
                if entry.get(kind) is not None:
                    found.append({"mod": mod, "kind": kind, "other": "", "note": entry[kind],
                                  "words": mod_sort.rule_words({"mod": mod, "kind": kind, "other": ""})})
    return found


SOURCE_WORDS = {mod_lists.SAVED: "Saved by name", mod_lists.KEPT: "Kept at a game start", mod_lists.SAVE: "From a save",
                mod_lists.MANAGER: "RimSort's history"}


def lists_report(adapter, args, environ=None):
    found = mod_lists.every_list(adapter, environ, args.settings)
    data = {"sources": {source: [mod_lists.list_data(s) for s in items] for source, items in found.items()},
            "files": bool(hasattr(adapter, "read_list_file")), "suffix": getattr(adapter, "list_suffix", "")}
    report = Report(f"Mod list: {sum(len(v) for v in found.values())} saved lists for {adapter.name}")
    for source, items in found.items():
        if items:
            report.section(SOURCE_WORDS[source], Table(["Name", "When", "Mods", "Ref"],
                                                       [[s.label, s.when, str(len(s.ids)), f"{source}:{s.ref}"] for s in items]))
    return report, data


def _chosen(adapter, args, environ):
    if getattr(args, "file", None):
        return mod_lists.find_list(adapter, mod_lists.FILE, args.file, environ, args.settings)
    source, sep, ref = (args.from_list or "").partition(":")
    if not sep or not ref:
        raise core.FixError("Name a list as SOURCE:REF, as `mod-list lists` gives it.")
    return mod_lists.find_list(adapter, source, ref, environ, args.settings)


def compare_report(adapter, args, environ=None, running=game_running, now=None):
    mod_list = _the_list(adapter, args.list_key)
    chosen = _chosen(adapter, args, environ)
    installed = core.Installed(adapter, adapter.installed())
    subscribed = adapter.subscribed()
    applied = getattr(args, "apply", False)
    if applied:
        found, backup = mod_lists.load(adapter, mod_list, chosen, installed, running, environ, args.settings, now, subscribed)
        history.record(adapter.game, "mod-list-change", environ, args.settings, now, list=mod_list.key,
                       change=f"load {chosen.label}", backup=backup.name)
        found.update(applied=True, backup=backup.name, change=f"load {chosen.label}")
    else:
        found = mod_lists.compare(adapter, mod_list, chosen, installed, subscribed, environ, args.settings)
        found.update(applied=False, backup="", change=f"load {chosen.label}")
    found.update(list=mod_list.key)
    title = f"Mod list: {'loaded' if applied else 'loading'} {chosen.label}"
    report = Report(title + ("" if applied else " (preview)"))
    report.lines.append(f"Switched on: {len(found['on'])}. Switched off: {len(found['off'])}. Moved: {found['moved']}. "
                        f"Not on this PC, left out: {len(found['missing'])}.")
    if found["missing"]:
        report.section("Not on this PC", Bullets([f"**{m['name']}** ({m['id']}). {m['why']}" for m in found["missing"]]))
    report.lines.append(f"Kept a backup first: {found['backup']}." if applied else "**Preview only.**")
    return report, found


def save_report(adapter, args, environ=None, now=None):
    mod_list = _the_list(adapter, args.list_key)
    data = {"name": args.as_name.strip(), "applied": False, "ref": mod_lists.file_name_for(args.as_name)}
    if args.apply:
        installed = core.Installed(adapter, adapter.installed())
        saved = mod_lists.save_named(adapter, mod_list, installed, args.as_name, args.replace, environ, args.settings, now)
        data.update(applied=True, ref=saved.ref, count=len(saved.ids))
    report = Report(f"Mod list: {'kept' if args.apply else 'keep'} {mod_list.label} as {data['name']!r}"
                    + ("" if args.apply else " (preview)"))
    return report, data


def forget_report(adapter, args, environ=None):
    data = {"ref": args.saved, "applied": False}
    if args.apply:
        mod_lists.forget_named(adapter.game, args.saved, environ, args.settings)
        data["applied"] = True
    return Report(f"Mod list: {'took away' if args.apply else 'take away'} the saved list {args.saved!r}"), data


def export_report(adapter, args, environ=None):
    if not hasattr(adapter, "render_list_file"):
        raise core.FixError(f"The tools cannot write {adapter.name}'s list files yet.")
    if args.from_list:
        chosen = _chosen(adapter, args, environ)
    else:
        mod_list = _the_list(adapter, args.list_key)
        chosen = mod_lists.snapshot(adapter, mod_list, core.Installed(adapter, adapter.installed()), mod_lists.FILE, "",
                                    mod_list.label)
    target = Path(args.to_file)
    if target.suffix.lower() != adapter.list_suffix:
        target = target.with_name(target.name + adapter.list_suffix)
    data = {"file": str(target), "count": len(chosen.ids), "applied": False}
    if args.apply:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(adapter.render_list_file(chosen).encode("utf-8"))
        data["applied"] = True
    return Report(f"Mod list: {'wrote' if args.apply else 'write'} {chosen.label} to {target.name}"), data


MAX_ITEMS = 500                 # Workshop items one press subscribes to (agent default)
WAIT_LIMIT = 3600               # the longest wait for downloads asked for (agent default)


def _items(args):
    found = []
    for item in args.item:
        number = str(item).strip()
        if not number.isdigit() or not 6 <= len(number) <= 20:
            raise core.FixError(f"{item!r} is not a Workshop number.")
        if number not in found:
            found.append(number)
    if len(found) > MAX_ITEMS:
        raise core.FixError(f"At most {MAX_ITEMS} items at once.")
    return found


def _session(adapter, environ, library):
    path = adapter.steam_library() if hasattr(adapter, "steam_library") else None
    if path is None and library is None:
        raise core.FixError(f"{adapter.name}'s own Steam library was not found, so the tools cannot ask Steam: is the game "
                            "installed through Steam?")
    return steam_client.Session((library or steam_client.Library)(path), adapter.app_id, environ)


def _by_number(adapter):
    found = {}
    for mod in adapter.installed():
        if mod.source == "workshop" and mod.workshop_id:
            found.setdefault(mod.workshop_id, mod)
    return found


def subscribe_report(adapter, args, environ=None, library=None, progress=None, clock=None, sleep=None):
    items = _items(args)
    wait = max(0, min(int(args.wait or 0), WAIT_LIMIT))
    data = {"items": items, "applied": False, "results": []}
    if args.apply:
        progress = progress or (lambda *a, **k: None)
        session = _session(adapter, environ, library)
        if clock is not None:
            session.clock, session.sleep = clock, sleep
        with session:
            progress("Asking Steam to subscribe", 0, len(items))
            subscribed = []
            for n, item in enumerate(items, 1):
                if session.subscribe(item):
                    subscribed.append(item)
                progress("Asking Steam to subscribe", n, len(items))
            ends = session.clock() + wait
            installed = 0
            while wait and subscribed and session.clock() < ends:
                done, total, installed = session.progress(subscribed)
                if installed == len(subscribed):
                    break
                progress(f"Steam is downloading: {installed} of {len(subscribed)} done", done // 1024, max(total // 1024, 1))
                session.sleep(1.0)
            states = {item: session.state(item) for item in items}
        here = _by_number(adapter)
        data.update(applied=True, results=[
            {"workshop_id": item, "subscribed": bool(states[item] & steam_client.SUBSCRIBED),
             "installed": item in here, "state": steam_client.state_words(states[item]),
             "id": here[item].id if item in here else "", "name": here[item].name if item in here else ""}
            for item in items])
        history.record(adapter.game, "mod-list-subscribe", environ, args.settings, None, items=items)
    done = [r for r in data["results"] if r["subscribed"]]
    title = (f"Mod list: subscribed to {len(done)} of {len(items)}" if args.apply
             else f"Mod list: subscribe to {len(items)} (preview)")
    report = Report(title)
    for result in data["results"]:
        report.lines.append(f"{result['workshop_id']}: {result['state']}" + (f" ({result['name']})" if result["name"] else ""))
    return report, data


def unsubscribe_report(adapter, args, environ=None, running=game_running, library=None, now=None):
    mod_list = _the_list(adapter, args.list_key)
    items = _items(args)
    here = _by_number(adapter)
    on = [here[i].id for i in items if i in here and any(adapter.key(x) == adapter.key(here[i].id) for x in mod_list.ids)]
    data = {"items": items, "applied": False, "switched_off": on, "backup": "", "results": []}
    if args.apply:
        core._refuse_while_running(adapter, running)
        if on:
            words, backup, ids = core.apply_fix(adapter, mod_list, None, core.REMOVE, on, running, environ, args.settings,
                                                now)
            data.update(backup=backup.name, ids=ids, keys=[adapter.key(i) for i in ids], change=words)
        with _session(adapter, environ, library) as session:
            data["results"] = [{"workshop_id": item, "unsubscribed": session.unsubscribe(item),
                                "name": here[item].name if item in here else ""} for item in items]
        data["applied"] = True
        history.record(adapter.game, "mod-list-unsubscribe", environ, args.settings, now, items=items,
                       backup=data["backup"])
    gone = [r for r in data["results"] if r["unsubscribed"]]
    report = Report(f"Mod list: unsubscribed from {len(gone)} of {len(items)}" if args.apply
                    else f"Mod list: unsubscribe from {len(items)} (preview)")
    if on:
        report.lines.append(f"Switched off first: {', '.join(on)}" + (f" (backup {data['backup']})." if data["backup"] else "."))
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


def main(argv=None, environ=None, out=None, post=None, running=None, now=None, steam=None):
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
        elif args.report == "sort":
            report, data = sort(adapter, args, environ, running or game_running, now, Progress(environ))
        elif args.report == "rules":
            report, data = rules(adapter, args, environ, now)
        elif args.report == "lists":
            report, data = lists_report(adapter, args, environ)
        elif args.report in ("compare", "load"):
            report, data = compare_report(adapter, args, environ, running or game_running, now)
        elif args.report == "save":
            report, data = save_report(adapter, args, environ, now)
        elif args.report == "forget":
            report, data = forget_report(adapter, args, environ)
        elif args.report == "export":
            report, data = export_report(adapter, args, environ)
        elif args.report == "subscribe":
            report, data = subscribe_report(adapter, args, environ, steam, Progress(environ))
        elif args.report == "unsubscribe":
            report, data = unsubscribe_report(adapter, args, environ, running or game_running, steam, now)
        elif args.report == "fix":
            report, data = fix(adapter, args, environ, running or game_running, now)
        else:
            report, data = undo(adapter, args, environ, running or game_running, now)
    except (core.FixError, steam_client.SteamError, ValueError, OSError) as error:
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
                        "sort": {"effect": WRITES, "when": "--apply",
                                 "question": "How would my mods be sorted from their rules, and why?"},
                        "rules": {"effect": WRITES, "when": "--apply", "question": "Which load-order rules does the sorter read?"},
                        "lists": {"question": "Which saved mod lists can I load?"},
                        "compare": {"question": "What would loading a saved mod list change?"},
                        "load": {"effect": WRITES, "when": "--apply", "question": None},
                        "save": {"effect": WRITES, "when": "--apply", "question": None},
                        "forget": {"effect": WRITES, "when": "--apply", "question": None},
                        "export": {"effect": WRITES, "when": "--apply", "question": None},
                        "subscribe": {"effect": WRITES, "when": "--apply", "question": None},
                        "unsubscribe": {"effect": WRITES, "when": "--apply", "question": None},
                        "backups": {"question": "Which backups of my mod lists are kept?"},
                        "mods": {"question": "Which mods are on this PC, and which are switched on?"},
                        "games": {"question": "Which games' mod lists can the tools read?"}}}


if __name__ == "__main__":
    sys.exit(main())
