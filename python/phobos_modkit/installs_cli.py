"""installs: what each of a repository's mods has installed, in the repository and in its backups, and what moving between them
would gain or lose by their changelogs; and the three ways to move.

    installs status --root REPO                     every mod: installed, repository, backups, and what you would gain or lose
    installs status --root REPO --mod NAME          one mod
    installs backup --root REPO --mod NAME          copy the installed mod into the backups folder (safe while the game runs)
    installs restore --root REPO --mod NAME --backup BACKUP
                                                    put a backup back; the install it replaces becomes a backup first
    installs install --root REPO --mod NAME         run the repository's own install command (it builds, backs up, copies);
                                                    --mod again for more mods, installed in one run
    installs build --root REPO                      run the repository's own build command (writes only inside the repository)

The repository's config/installs.json names its game, its mods folder, its backups folder and its install command
(docs/installs.md). restore and install refuse while the game runs. Nothing here touches saves or a mod manager's lists.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import os
from pathlib import Path
import sys

from . import installs
from .manifest import READS, RUNS, WRITES
from .progress import Progress
from .report import Bullets, Report, Table, envelope_text, home_redactor, keep, render_markdown

EXIT_OK, EXIT_REFUSED, EXIT_USAGE = 0, 1, 2
MB = 1024 ** 2


def _parser():
    p = argparse.ArgumentParser(prog="installs", description=__doc__.split("\n\n")[0],
                                formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__.split("\n\n", 1)[1])
    sub = p.add_subparsers(dest="report", required=True)
    helps = {"status": "every mod's installed copy, repository copy and backups, and what moving between them gains or loses",
             "backup": "copy the installed mod into the backups folder",
             "restore": "put a backup back as the installed mod; the replaced install becomes a backup first",
             "install": "run the repository's own install command for one or more mods",
             "build": "run the repository's own build command; it writes only inside the repository"}
    for name, helptext in helps.items():
        s = sub.add_parser(name, help=helptext)
        s.add_argument("--root", help="the repository (default: the current folder)")
        if name == "install":
            s.add_argument("--mod", action="append", required=True, help="a mod's folder name (repeatable)")
        elif name != "build":
            s.add_argument("--mod", required=name != "status",
                           help="the mod's folder name" + (" (default: every mod)" if name == "status" else ""))
        if name == "restore":
            s.add_argument("--backup", required=True, help="the backup's folder name, as status lists it")
        s.add_argument("--settings", help="a JSON settings file naming the game's folder (default: the one installs.json names)")
        s.add_argument("--top", type=int, default=12, help="entries shown per list in the summary (default 12)")
        s.add_argument("--json", action="store_true", help="print JSON instead of Markdown")
        s.add_argument("--no-redact", action="store_true", help="show the home folder instead of ~")
    return p


# ---------------------------------------------------------------- data for programs

def _entry(entry):
    return {"version": entry.version, "section": entry.section, "text": entry.text, "lead": entry.lead,
            "aboutSaves": entry.about_saves}


def _delta(delta, *logs):
    summaries = {}
    for log in logs:
        if log is not None:
            for version, line in log.summaries.items():
                summaries.setdefault(version, line)
    used = {e.version for e in delta.gain + delta.lose} | {pair[1].version for pair in delta.reworded}
    return {"gain": [_entry(e) for e in delta.gain], "lose": [_entry(e) for e in delta.lose],
            "reworded": [{"now": _entry(a), "would": _entry(b)} for a, b in delta.reworded],
            "saveNotes": [_entry(e) for e in delta.save_notes],
            "summaries": {v: s for v, s in summaries.items() if v in used}}


def _copy(copy, against=None):
    return {"kind": copy.kind, "name": copy.name, "version": copy.version, "record": copy.record, "backup": copy.backup or None,
            "taken": copy.taken or None, "size": copy.size, "hasChangelog": copy.changelog is not None,
            "direction": installs.direction(against.version, copy.version) if against is not None else None}


def state_of(state, update):
    if state.installed is None:
        return "not-installed"
    if not (update.gain or update.lose or update.reworded):
        return "up-to-date"
    if update.gain and not update.lose:
        return "behind"
    if update.lose and not update.gain:
        return "ahead"
    return "differs"


def _build_data(state):
    return {"needsBuild": state.needs_build,
            "projects": [{**b, "built": _iso(b["built"]), "newest": _iso(b["newest"])} for b in state.builds]}


def _iso(stamp):
    return datetime.fromtimestamp(stamp, timezone.utc).isoformat(timespec="seconds") if stamp else None


def mod_data(state):
    installed = state.installed
    update = installs.compare(installed.changelog, state.repository.changelog) if installed else installs.Delta()
    backups = []
    for b in state.backups:
        moved = installs.compare(installed.changelog, b.changelog) if installed else installs.Delta()
        backups.append({**_copy(b, installed), "delta": _delta(moved, installed.changelog if installed else None, b.changelog)})
    return {"mod": state.mod, "name": state.repository.name or (installed.name if installed else "") or state.mod,
            "changelog": state.changelog,
            "state": state_of(state, update),
            "repository": _copy(state.repository, installed),
            "installed": _copy(installed) if installed else None,
            "update": _delta(update, installed.changelog if installed else None, state.repository.changelog),
            "uncommitted": state.uncommitted[:50], "uncommittedCount": len(state.uncommitted),
            "commitsSince": state.commits_since, "backups": backups,
            "installedCommit": {"commit": state.commit, "exact": state.commit_exact} if state.commit else None,
            "files": state.files, "build": _build_data(state), "settings": state.settings, "settingsNote": state.settings_note,
            "lookOut": state.look_out}


# ---------------------------------------------------------------- words for people

_STATE_WORDS = {"not-installed": "not installed", "up-to-date": "up to date", "behind": "repository has more",
                "ahead": "installed copy has entries the repository lacks", "differs": "both have entries the other lacks"}


def _size(size):
    return "" if size is None else f"{size / MB:,.0f} MB"


def status_report(where, states, running, top):
    datas = [mod_data(s) for s in states]
    behind = sum(d["state"] in ("behind", "differs") for d in datas)
    report = Report(f"Installs: {len(datas):,} mod{'' if len(datas) == 1 else 's'}, {behind:,} with changes in the repository "
                    "not yet installed")
    report.lines.append("What you would gain or lose is read from the changelogs the two copies carry: an entry one has and the "
                        "other lacks. A changelog says what changed, not that it works in game.")
    if running:
        report.lines.append(f"**The game is running ({', '.join(running)}): going back and installing wait until it closes.**")
    report.section("Mods", Table(
        ["Mod", "Installed", "Repository", "To gain", "To lose", "Files", "Build", "Backups", "State"],
        [[d["name"], (d["installed"] or {}).get("version") or "-", d["repository"]["version"] or "-", f"{len(d['update']['gain']):,}",
          f"{len(d['update']['lose']):,}", f"{(d['files'] or {}).get('total', 0):,}", "needed" if d["build"]["needsBuild"] else "",
          f"{len(d['backups']):,}", _STATE_WORDS[d["state"]]] for d in datas]))
    for d in datas:
        update = d["update"]
        if not (update["gain"] or update["lose"]):
            continue
        items = [f"**Saves:** {e['text']} ({e['version']})" for e in update["saveNotes"]]
        items += [f"**Setting:** {c.get('label') or c.get('key')} {c.get('what')}" for c in d["settings"] or []]
        items += [f"Look out for, in play: row {r['id']}, {r['title']}" for r in d["lookOut"]]
        items += [f"Gain ({e['version']}, {e['section'] or 'no section'}): {e['lead']}" for e in update["gain"][:top]]
        items += [f"Lose ({e['version']}, {e['section'] or 'no section'}): {e['lead']}" for e in update["lose"][:top]]
        report.section(f"{d['name']}: installing from the repository", Bullets(items))
    report.section("Space", Bullets([
        f"Backups: {sum(b['size'] or 0 for d in datas for b in d['backups']) / MB:,.0f} MB in {where.backups}.",
        f"Free on the backups' drive: {_size(installs.free_bytes(where.backups)) or 'unknown'}; "
        f"on the game's drive: {_size(installs.free_bytes(where.target)) or 'unknown'}.",
        "Old backups are listed by the cleanup tool; it deletes only when the owner runs it with --apply."]))
    data = {"repository": where.root.name, "target": str(where.target), "backupsFolder": str(where.backups),
            "gameRunning": running, "installCommand": " ".join(where.config.get("install") or []),
            "canBuild": bool((where.config.get("build") or {}).get("command")),
            "needsBuild": any(d["build"]["needsBuild"] for d in datas),
            "space": {"backups": sum(b["size"] or 0 for d in datas for b in d["backups"]),
                      "backupsFree": installs.free_bytes(where.backups), "targetFree": installs.free_bytes(where.target),
                      "spare": installs.SPARE_BYTES},
            "mods": datas}
    return report, data


def _done(title, lines, data):
    report = Report(title)
    report.lines.extend(lines)
    return report, data


def main(argv=None, environ=None, out=None, now=None, running=None, run=None):
    out = out or sys.stdout
    environ = os.environ if environ is None else environ
    try:
        args = _parser().parse_args(list(sys.argv[1:] if argv is None else argv))
    except SystemExit as stop:
        return EXIT_USAGE if stop.code else EXIT_OK
    redact = keep if args.no_redact else home_redactor()
    running = running or installs.game_running
    progress = Progress(environ)
    code = EXIT_OK

    def emit(report, data):
        out.write((envelope_text("installs", report, redact, data) if args.json else render_markdown(report, redact)) + "\n")

    try:
        where = installs.place(Path(args.root or "."), args.settings, environ)
        if args.report == "status":
            mods = [args.mod] if args.mod else None
            if args.mod and args.mod not in installs.mods_of(where.root, where.config):
                raise installs.InstallsError(f"{args.mod!r} is not one of this repository's mods.")
            states = installs.survey(where, mods, progress=progress)
            report, data = status_report(where, states, running(where.game.PROCESSES), args.top)
        elif args.report == "backup":
            progress(f"Copying the installed {args.mod} into the backups")
            name = installs.backup(where, args.mod, now)
            report, data = _done(f"Backed up {args.mod}", [f"The installed copy was copied to {where.backups / name}."],
                                 {"ok": True, "mod": args.mod, "backup": name})
        elif args.report == "restore":
            progress(f"Putting {args.backup} back; the install it replaces becomes a backup")
            replaced = installs.restore(where, args.mod, args.backup, now, running)
            lines = [f"{args.backup} is now the installed copy of {args.mod}; the backup itself is kept."]
            lines.append(f"The install it replaced was kept as the backup {replaced}." if replaced else "Nothing was installed before.")
            report, data = _done(f"Went back to {args.backup}", lines, {"ok": True, "mod": args.mod, "backup": args.backup,
                                                                         "replacedBy": replaced})
        elif args.report == "build":
            progress("Starting the build")
            exit_code, lines = installs.build(where, run, progress)
            ok = exit_code == 0
            code = EXIT_OK if ok else EXIT_REFUSED
            report, data = _done("Built every project" if ok else f"The build failed (exit {exit_code})",
                                 ["Its last lines of output follow."], {"ok": ok, "exitCode": exit_code, "output": lines})
            report.blocks.append(Bullets(lines or ["(no output)"]))
        else:
            progress("Starting the build and install")
            exit_code, lines = installs.install(where, args.mod, run, running=running, progress=progress)
            ok = exit_code == 0
            code = EXIT_OK if ok else EXIT_REFUSED
            names = ", ".join(args.mod)
            report, data = _done(f"Installed {names} from the repository" if ok else f"The install of {names} failed (exit {exit_code})",
                                 ["Its last lines of output follow."], {"ok": ok, "mods": args.mod, "exitCode": exit_code, "output": lines})
            report.blocks.append(Bullets(lines or ["(no output)"]))
    except installs.InstallsError as error:
        if not args.json:
            print(redact(str(error)), file=sys.stderr)
            return EXIT_REFUSED
        report, data = _done("Refused", [str(error)], {"ok": False, "refusal": str(error)})
        code = EXIT_REFUSED
    emit(report, data)
    return code


MANIFEST = {"game": None, "parser": _parser, "effect": READS,
            "reports": {"status": {"question": "What would updating or going back change in my installed mods?"},
                        "backup": {"effect": WRITES, "note": "copies an installed mod into the repository's backups folder"},
                        "restore": {"effect": WRITES,
                                    "note": "replaces an installed mod with a backup; the replaced install is kept as a backup"},
                        "install": {"effect": RUNS, "note": "runs the repository's own install command, which builds and copies"},
                        "build": {"effect": RUNS, "note": "runs the repository's own build command, which writes only inside it"}}}
