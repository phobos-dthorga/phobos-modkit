"""records: a copy of D'thorga Companion's own records in a folder of the owner's choosing, and how old the newest copy is (1.43.0).

    records status [--every-hours N]              what would be copied, where to, the copies made, and whether one is due
    records backup [--to FOLDER] [--automatic]   keeps the records in the store there, as a new dated copy
    records restore --copy NAME --into FOLDER     writes one copy out, plain, into an empty folder of the owner's naming
    records pack [--apply]                        turns copies made as plain folders into store copies, each checked first
    records tidy [--apply]                        lets go of kept files that no copy names any more

The records are what the owner's own clicks and the tools' history wrote, and nothing else can rebuild: test verdicts and their
word on notes, the history log, the "looked at" marks, screen notes, keyboard shortcuts and the central settings file. They live in
the Companion's folder in the local application data, which the owner's NAS does not back up (owner's go-ahead, 19 Nov 2026,
D'thorga Companion's docs/later.md item 2). Everything in that folder is copied except the window's browser cache; a record kept
elsewhere by a setting (historyPath, the verdict files, PHOBOS_SETTINGS) is copied too.

The folder is the setting recordsBackupPath (PHOBOS_RECORDS_BACKUP), set on the Companion's Settings page. **Each file is kept
once** (1.149.0; the owner's choice by card, 28 Nov 2026, "Store-once"): its bytes go into the folder's `store/` under their SHA-256,
compressed (`packed.Store`), and each copy is one small `<local time>.json` listing its files. 24 copies as plain folders measured
155 MB on 28 Nov 2026, of which 23 MB was distinct; kept once and compressed, about 10.5 MB. `restore` writes a copy out plain to
browse or put back. **No copy is ever deleted by the kit**: the owner prunes by deleting a copy's `.json`, and `tidy --apply` then
lets go of the kept files no copy names. Copies made before 1.149.0 are plain folders with a backup.json; `pack --apply` turns them
into store copies (the owner's choice by card, the same day: "Convert, checked first"), removing each folder only once every one of
its files reads back the same from the store.

**The Companion copies by itself** (1.55.0; owner, 20 Nov 2026: "every few hours when it's open, and if the schedule is missed, the
soonest next opportunity"): it asks `status --every-hours N` whether a copy is due (none yet, or the newest is N hours old or more)
and runs `backup --automatic`, whose backup.json says so. A folder that cannot be reached (a drive not there, a NAS asleep) is
refused in words, so the next attempt simply tries again.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shutil
import sys
import time

from . import __version__
from .packed import PackError, Store
from .history import LOG as HISTORY
from .manifest import READS, WRITES
from .paths import CENTRAL_VARIABLE, central_settings_file, companion_data, resolve, where
from .report import Bullets, Report, Table, envelope_text, home_redactor, keep, render_markdown
from .testpass_cli import DECISIONS, VERDICTS

EXIT_OK, EXIT_USAGE, EXIT_REFUSED = 0, 2, 3
BACKUP = ("recordsBackupPath", "PHOBOS_RECORDS_BACKUP")
# The window's browser cache (WebView2 on Windows): rebuilt by the window, and most of the folder's size. And the Companion's
# kept answers (0.116.0): the last reading of each slow page, shown while it reads again, so read afresh in seconds (1.147.2).
LEFT_OUT = frozenset({"EBWebView", "answers"})
PARTIAL = ".partial"
MANIFEST_FILE = "backup.json"
FOLDER_FORMAT = 1                 # a copy as a plain folder, before 1.149.0
STORE_FORMAT = 2                  # a copy as a list of files kept in the store
STORE = "store"
COPY_SUFFIX = ".json"
FOLDER_FORM, STORE_FORM = "folder", "store"
# A kept file younger than this is never let go by tidy: a backup running at that moment has kept it but not yet written its list.
TIDY_GRACE_SECONDS = 24 * 3600
COPY_NAME = re.compile(r"^[0-9]{8}-[0-9]{6}(-[0-9]{1,3})?$")
# After this many days without a copy, the Companion's Home says the records want backing up (an agent choice).
STALE_DAYS = 7


class RecordsError(ValueError):
    """A request this command refuses, with the reason in words."""


def _inside(path, folder):
    try:
        Path(path).resolve().relative_to(Path(folder).resolve())
        return True
    except ValueError:
        return False


def _size(path):
    """(files, bytes) under a path; a file counts as one."""
    path = Path(path)
    if path.is_file():
        return 1, path.stat().st_size
    files = size = 0
    for found in path.rglob("*"):
        if found.is_file():
            files += 1
            size += found.stat().st_size
    return files, size


def sources(environ=None):
    """[(name in the copy, path)] of every record: the Companion's folder (less the browser cache, entry by entry), then any record
    a setting keeps outside it."""
    environ = os.environ if environ is None else environ
    data = companion_data(environ)
    found = []
    if data.is_dir():
        for child in sorted(data.iterdir(), key=lambda p: p.name.lower()):
            if child.name not in LEFT_OUT and not child.name.endswith(PARTIAL):
                found.append((child.name, child))
    elsewhere = [("history", where(*HISTORY, environ=environ)), ("test-verdicts", where(*VERDICTS, environ=environ)),
                 ("test-key-decisions", where(*DECISIONS, environ=environ))]
    if environ.get(CENTRAL_VARIABLE):
        elsewhere.append(("settings.json", ("environment", str(central_settings_file(environ)))))
    for name, layer in elsewhere:
        if layer is None:
            continue
        path = Path(layer[1])
        if path.exists() and not _inside(path, data):
            found.append((f"elsewhere-{name}", path))
    return found


def backup_folder(explicit=None, environ=None):
    """Where the copies go, or None when the owner has not chosen yet."""
    return resolve(*BACKUP, None, explicit, environ)


def _read_copy(child):
    """(name, form, its list) of one copy in the backup folder, or None when the entry is not a copy."""
    if child.is_dir() and COPY_NAME.match(child.name):
        listing, form, name = child / MANIFEST_FILE, FOLDER_FORM, child.name
    elif child.is_file() and child.name.endswith(COPY_SUFFIX) and COPY_NAME.match(child.name[: -len(COPY_SUFFIX)]):
        listing, form, name = child, STORE_FORM, child.name[: -len(COPY_SUFFIX)]
    else:
        return None
    try:
        return name, form, json.loads(listing.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def copies(folder):
    """The copies already in the folder, newest first: name, time (UTC, from its list), files, bytes (as the records were), and its
    form: `store` (1.149.0) or a plain `folder`."""
    if folder is None or not Path(folder).is_dir():
        return []
    found = []
    for child in Path(folder).iterdir():
        read = _read_copy(child)
        if read is None:
            continue
        name, form, made = read
        found.append({"name": name, "time": made.get("time", ""), "files": made.get("files", 0),
                      "bytes": made.get("bytes", 0), "automatic": bool(made.get("automatic")), "form": form})
    return sorted(found, key=lambda c: (c["time"], c["name"]), reverse=True)


def store_size(folder):
    """(files, bytes on disk) of the folder's store."""
    if folder is None:
        return 0, 0
    kept = Store(Path(folder) / STORE).kept()
    return len(kept), sum(kept.values())


def age_days(time_text, now=None):
    """Whole days since an ISO time; None when it cannot be read."""
    try:
        then = datetime.fromisoformat(time_text)
    except (TypeError, ValueError):
        return None
    if then.tzinfo is None:
        then = then.replace(tzinfo=timezone.utc)
    return max(0, ((now or datetime.now(timezone.utc)) - then).days)


def age_hours(time_text, now=None):
    """Hours since an ISO time, to a tenth; None when it cannot be read."""
    try:
        then = datetime.fromisoformat(time_text)
    except (TypeError, ValueError):
        return None
    if then.tzinfo is None:
        then = then.replace(tzinfo=timezone.utc)
    return round(max(0.0, ((now or datetime.now(timezone.utc)) - then).total_seconds() / 3600), 1)


def status(explicit=None, environ=None, now=None, every_hours=None):
    """What would be copied and the copies made. With every_hours, `due` says whether a copy should be made now: a folder is chosen,
    and there is no copy yet or the newest is that many hours old or more."""
    folder = backup_folder(explicit, environ)
    items = []
    for name, path in sources(environ):
        files, size = _size(path)
        items.append({"name": name, "path": str(path), "files": files, "bytes": size})
    made = copies(folder)
    newest = made[0] if made else None
    age = age_days(newest["time"], now) if newest else None
    hours = age_hours(newest["time"], now) if newest else None
    kept_files, kept_bytes = store_size(folder)
    found = {"folder": str(folder) if folder else None, "folderExists": bool(folder and Path(folder).is_dir()),
             "records": items, "copies": made, "newest": newest, "ageDays": age, "ageHours": hours, "staleDays": STALE_DAYS,
             "stale": age is None or age >= STALE_DAYS, "store": {"files": kept_files, "bytes": kept_bytes},
             "folderCopies": sum(1 for c in made if c["form"] == FOLDER_FORM)}
    if every_hours is not None:
        found["everyHours"] = every_hours
        found["due"] = bool(folder) and (hours is None or hours >= every_hours)
    return found


def _local_stamp(now=None):
    return (now or datetime.now(timezone.utc)).astimezone().strftime("%Y%m%d-%H%M%S")


def _unreachable(folder, error):
    return RecordsError(f"the backup folder {folder} cannot be reached or written to ({error.strerror or error}): check the drive "
                        "or the NAS is connected and awake; nothing was copied")


def _files_of(found):
    """[(path in the copy, file)] of every file of the records, in a stable order; partial files left out."""
    files = []
    for item_name, path in found:
        if path.is_dir():
            for child in sorted(path.rglob("*"), key=lambda p: p.as_posix().lower()):
                if child.is_file() and not any(part.endswith(PARTIAL) for part in child.relative_to(path).parts):
                    files.append((f"{item_name}/{child.relative_to(path).as_posix()}", child))
        elif path.is_file():
            files.append((item_name, path))
    return files


def _free_name(folder, stamp):
    def taken(name):
        return any((folder / n).exists() for n in (name, name + PARTIAL, name + COPY_SUFFIX, name + COPY_SUFFIX + PARTIAL))
    return next(n for n in [stamp, *(f"{stamp}-{i}" for i in range(2, 1000))] if not taken(n))


def _write_list(folder, name, listing):
    """Writes a copy's list through a partial file; the copy counts only once it is renamed into place."""
    target = folder / (name + COPY_SUFFIX)
    partial = folder / (name + COPY_SUFFIX + PARTIAL)
    partial.write_text(json.dumps(listing, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    os.replace(partial, target)
    return target


def _keep(store, files):
    """Keeps each file in the store; returns its entries for the copy's list."""
    entries = []
    for relative, path in files:
        modified = path.stat().st_mtime_ns
        sha, size = store.put(path)
        entries.append({"path": relative, "sha256": sha, "bytes": size, "mtimeNs": modified})
    return entries


def backup(explicit=None, environ=None, now=None, automatic=False):
    """Keeps every record in the folder's store and writes a new dated copy listing them; returns what it wrote. Refuses with no
    folder chosen, one inside the records themselves, or one that cannot be reached or written to."""
    environ = os.environ if environ is None else environ
    folder = backup_folder(explicit, environ)
    if folder is None:
        raise RecordsError("choose a folder for the copies first (recordsBackupPath, on the Companion's Settings page)")
    if not folder.is_absolute():
        raise RecordsError("the backup folder must be a full path")
    found = sources(environ)
    if not found:
        raise RecordsError("there are no records to copy yet")
    for _, path in found:
        if _inside(folder, path) or _inside(folder, companion_data(environ)):
            raise RecordsError("the backup folder cannot be inside the records it copies")
    try:
        folder.mkdir(parents=True, exist_ok=True)
        name = _free_name(folder, _local_stamp(now))
        entries = _keep(Store(folder / STORE), _files_of(found))
        when = (now or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat(timespec="seconds")
        size = sum(e["bytes"] for e in entries)
        target = _write_list(folder, name, {
            "format": STORE_FORMAT, "time": when, "kit": __version__, "files": len(entries), "bytes": size,
            "automatic": automatic, "records": [{"name": n, "from": str(p)} for n, p in found], "entries": entries})
    except OSError as error:
        raise _unreachable(folder, error) from None
    except PackError as error:
        raise RecordsError(f"{error}; no copy was written") from None
    return {"folder": str(folder), "name": name, "path": str(target), "files": len(entries), "bytes": size, "time": when,
            "automatic": automatic, "form": STORE_FORM}


def _find_copy(folder, name):
    for child in (folder / name, folder / (name + COPY_SUFFIX)):
        read = _read_copy(child) if child.exists() else None
        if read is not None:
            return child, read[1], read[2]
    raise RecordsError(f"there is no copy named {name} in {folder}")


def restore(name, into, explicit=None, environ=None):
    """Writes one copy out, plain, into a folder that is empty or not there yet: never into the Companion's own folder or the backup
    folder, so the live records and the copies are never written over. Returns what it wrote."""
    environ = os.environ if environ is None else environ
    folder = backup_folder(explicit, environ)
    if folder is None or not folder.is_dir():
        raise RecordsError("there is no backup folder to restore from (recordsBackupPath)")
    into = Path(into)
    if not into.is_absolute():
        raise RecordsError("the folder to restore into must be a full path")
    if _inside(into, companion_data(environ)) or _inside(into, folder):
        raise RecordsError("restore into a folder of its own, not into the Companion's folder or the backup folder; put records "
                           "back by hand, with the Companion closed")
    if into.exists() and (not into.is_dir() or any(into.iterdir())):
        raise RecordsError(f"{into} is not empty; nothing was written")
    path, form, listing = _find_copy(folder, name)
    files = size = 0
    try:
        if form == FOLDER_FORM:
            shutil.copytree(path, into, dirs_exist_ok=True)
            files, size = _size(into)
        else:
            store = Store(folder / STORE)
            for entry in listing.get("entries", []):
                target = into.joinpath(*entry["path"].split("/"))
                if not _inside(target, into):
                    raise RecordsError(f"the copy names a file outside its folder ({entry['path']}); stopped")
                store.get(entry["sha256"], target)
                if entry.get("mtimeNs"):
                    os.utime(target, ns=(entry["mtimeNs"], entry["mtimeNs"]))
                files += 1
                size += entry["bytes"]
    except PackError as error:
        raise RecordsError(f"{error}; the restore stopped part-way in {into}") from None
    except OSError as error:
        raise RecordsError(f"could not write into {into} ({error.strerror or error})") from None
    return {"name": name, "into": str(into), "files": files, "bytes": size, "form": form}


def pack(explicit=None, environ=None, apply=False):
    """Turns each copy made as a plain folder into a store copy. Each folder's files are kept, every kept file read back and checked
    against its hash, its list written, and only then is the folder removed. Without apply, says what it would do."""
    folder = backup_folder(explicit, environ)
    if folder is None or not folder.is_dir():
        raise RecordsError("there is no backup folder (recordsBackupPath)")
    store = Store(folder / STORE)
    results = []
    for made in sorted((c for c in copies(folder) if c["form"] == FOLDER_FORM), key=lambda c: c["name"]):
        source = folder / made["name"]
        files, size = _size(source)
        result = {"name": made["name"], "files": files, "bytes": size, "packed": False}
        results.append(result)
        if not apply:
            continue
        if (folder / (made["name"] + COPY_SUFFIX)).exists():
            result["refusal"] = "a store copy of this name is already there; the folder is left as it is"
            continue
        try:
            listing = json.loads((source / MANIFEST_FILE).read_text(encoding="utf-8"))
            inside = [(p.relative_to(source).as_posix(), p) for p in sorted(source.rglob("*"), key=lambda p: p.as_posix().lower())
                      if p.is_file() and p.relative_to(source).as_posix() != MANIFEST_FILE]
            entries = _keep(store, inside)
            bad = sorted({e["sha256"] for e in entries if not store.check(e["sha256"])})
            if bad:
                result["refusal"] = f"{len(bad)} kept files did not read back the same; the folder is left as it is"
                continue
            listing.update({"format": STORE_FORMAT, "files": len(entries), "bytes": sum(e["bytes"] for e in entries),
                            "entries": entries, "packedFrom": FOLDER_FORM, "packedBy": __version__})
            _write_list(folder, made["name"], listing)
            shutil.rmtree(source)
            result["packed"] = True
        except (OSError, ValueError, PackError) as error:
            result["refusal"] = f"{error}; the folder is left as it is"
    kept_files, kept_bytes = store_size(folder)
    return {"folder": str(folder), "apply": apply, "copies": results, "store": {"files": kept_files, "bytes": kept_bytes}}


def tidy(explicit=None, environ=None, apply=False, now=None):
    """The kept files no copy names any more (after the owner deleted a copy's list), less any kept in the last day. Without apply,
    only says; with it, lets them go."""
    folder = backup_folder(explicit, environ)
    if folder is None or not folder.is_dir():
        raise RecordsError("there is no backup folder (recordsBackupPath)")
    store = Store(folder / STORE)
    named = set()
    for child in folder.iterdir():
        read = _read_copy(child)
        if read is not None and read[1] == STORE_FORM:
            named.update(e["sha256"] for e in read[2].get("entries", []))
    cutoff = (now if now is not None else time.time()) - TIDY_GRACE_SECONDS
    loose = {sha: size for sha, size in store.kept().items()
             if sha not in named and store.path_of(sha).stat().st_mtime < cutoff}
    removed = store.let_go(loose) if apply else (0, 0)
    return {"folder": str(folder), "apply": apply, "loose": len(loose), "looseBytes": sum(loose.values()),
            "removed": removed[0], "removedBytes": removed[1]}


def _parser():
    p = argparse.ArgumentParser(prog="records", description=__doc__.split("\n\n")[0],
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="report", required=True)
    for name, helptext in (("status", "what would be copied, where to, and the copies already there"),
                           ("backup", "keeps the records in the store as a new dated copy"),
                           ("restore", "writes one copy out, plain, into an empty folder"),
                           ("pack", "turns copies made as plain folders into store copies, each checked before its folder goes"),
                           ("tidy", "lets go of kept files no copy names any more")):
        s = sub.add_parser(name, help=helptext)
        s.add_argument("--to", help="the backup folder (default: recordsBackupPath)")
        if name == "status":
            s.add_argument("--every-hours", type=float, help="also say whether a copy is due: none yet, or the newest this old")
        elif name == "backup":
            s.add_argument("--automatic", action="store_true", help="mark the copy as made by the Companion's own timer")
        elif name == "restore":
            s.add_argument("--copy", required=True, help="the copy's name, as status lists it")
            s.add_argument("--into", required=True, help="an empty folder, or one not there yet, to write it into")
        else:
            s.add_argument("--apply", action="store_true", help="do it; without this, only say what would be done")
        s.add_argument("--json", action="store_true", help="print JSON instead of Markdown")
        s.add_argument("--no-redact", action="store_true", help="show the home folder instead of ~")
    return p


def _kb(size):
    return f"{size / 1024:,.1f} KB" if size < 1024 * 1024 else f"{size / (1024 * 1024):,.1f} MB"


def _backup_action(args, environ):
    made = backup(args.to, environ, automatic=args.automatic)
    report = Report(f"Records copied: {made['files']} files, {_kb(made['bytes'])}")
    report.section("Where", Bullets([made["path"]]))
    return report, {"copy": made}


def _restore_action(args, environ):
    made = restore(args.copy, args.into, args.to, environ)
    report = Report(f"Copy {made['name']} written out: {made['files']} files, {_kb(made['bytes'])}")
    report.section("Where", Bullets([made["into"]]))
    return report, {"restore": made}


def _pack_action(args, environ):
    done = pack(args.to, environ, apply=args.apply)
    plain = done["copies"]
    if not plain:
        report = Report("Records: every copy is already in the store")
    elif not done["apply"]:
        report = Report(f"Records: {len(plain)} copies are plain folders ({_kb(sum(c['bytes'] for c in plain))}); "
                        "pack --apply would keep them in the store")
    else:
        packed = sum(1 for c in plain if c["packed"])
        report = Report(f"Records: {packed} of {len(plain)} folder copies packed into the store")
    if plain:
        report.section("Copies", Table(["Copy", "Files", "Size", "Packed", "Why not"],
                                       [[c["name"], c["files"], _kb(c["bytes"]), "yes" if c["packed"] else "no",
                                         c.get("refusal", "")] for c in plain]))
    report.lines.append(f"The store holds {done['store']['files']} files in {_kb(done['store']['bytes'])}.")
    return report, {"pack": done}


def _tidy_action(args, environ):
    done = tidy(args.to, environ, apply=args.apply)
    if not done["loose"]:
        report = Report("Records: every kept file is named by a copy")
    elif done["apply"]:
        report = Report(f"Records: let go of {done['removed']} kept files no copy names ({_kb(done['removedBytes'])})")
    else:
        report = Report(f"Records: {done['loose']} kept files no copy names ({_kb(done['looseBytes'])}); tidy --apply lets them go")
    report.lines.append("Files kept in the last day are never let go, in case a backup is still writing its list.")
    return report, {"tidy": done}


_ACTIONS = {"backup": _backup_action, "restore": _restore_action, "pack": _pack_action, "tidy": _tidy_action}


def main(argv=None, out=None, environ=None):
    out = out or sys.stdout
    try:
        args = _parser().parse_args(list(sys.argv[1:] if argv is None else argv))
    except SystemExit as stop:
        return EXIT_USAGE if stop.code else EXIT_OK
    redact = keep if args.no_redact else home_redactor()
    if args.report in _ACTIONS:
        try:
            report, data = _ACTIONS[args.report](args, environ)
        except RecordsError as refused:
            out.write((envelope_text("records", Report("Refused"), redact, {"ok": False, "refusal": str(refused)})
                       if args.json else f"Refused: {refused}") + "\n")
            return EXIT_REFUSED
        out.write((envelope_text("records", report, redact, data) if args.json else render_markdown(report, redact)) + "\n")
        return EXIT_OK
    if args.every_hours is not None and args.every_hours <= 0:
        out.write("Refused: --every-hours must be more than 0\n")
        return EXIT_USAGE
    found = status(args.to, environ, every_hours=args.every_hours)
    if found["newest"] is None:
        title = "Records: never copied"
    else:
        title = f"Records: last copied {found['ageDays']} days ago" if found["ageDays"] else "Records: copied today"
    report = Report(title)
    report.section("What is copied", Table(["Record", "Files", "Size", "From"],
                                           [[r["name"], r["files"], _kb(r["bytes"]), r["path"]] for r in found["records"]]))
    report.section("Where the copies go", Bullets([found["folder"] or "No folder chosen yet: set recordsBackupPath (the "
                                                   "Companion's Settings page), then records backup."]))
    if "due" in found:
        report.lines.append(f"A copy is {'due now' if found['due'] else 'not due yet'} (every {found['everyHours']:g} hours).")
    if found["copies"]:
        report.section("Copies", Table(["Copy", "When", "Files", "Size", "Kept as"],
                                       [[c["name"], c["time"], c["files"], _kb(c["bytes"]), c["form"]]
                                        for c in found["copies"][:10]]))
        report.lines.append(f"The store holds {found['store']['files']} files in {_kb(found['store']['bytes'])}.")
        if found["folderCopies"]:
            report.lines.append(f"{found['folderCopies']} copies are still plain folders: records pack --apply keeps them in "
                                "the store, each checked before its folder goes.")
    out.write((envelope_text("records", report, redact, found) if args.json else render_markdown(report, redact)) + "\n")
    return EXIT_OK


MANIFEST = {"game": None, "parser": _parser, "effect": READS,
            "reports": {"status": {"note": "what would be copied, where to, and how old the newest copy is"},
                        "backup": {"effect": WRITES, "note": "keeps the Companion's records in the store as a new dated copy; "
                                   "deletes nothing"},
                        "restore": {"effect": WRITES, "note": "writes one copy out into an empty folder the owner names; never into "
                                    "the Companion's folder or the backup folder"},
                        "pack": {"effect": WRITES, "note": "with --apply, keeps each folder copy in the store and removes the folder "
                                 "only once every file reads back the same; without, only says"},
                        "tidy": {"effect": WRITES, "note": "with --apply, lets go of kept files no copy names, never one kept in "
                                 "the last day; without, only says"}}}
