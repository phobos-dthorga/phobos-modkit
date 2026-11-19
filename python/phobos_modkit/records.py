"""records: a copy of D'thorga Companion's own records in a folder of the owner's choosing, and how old the newest copy is (1.43.0).

    records status                 what would be copied, where to, and the copies already there
    records backup [--to FOLDER]   copies the records into a new dated folder there

The records are what the owner's own clicks and the tools' history wrote, and nothing else can rebuild: test verdicts and their
word on notes, the history log, the "looked at" marks, screen notes, keyboard shortcuts and the central settings file. They live in
the Companion's folder in the local application data, which the owner's NAS does not back up (owner's go-ahead, 19 Nov 2026,
D'thorga Companion's docs/later.md item 2). Everything in that folder is copied except the window's browser cache; a record kept
elsewhere by a setting (historyPath, the verdict files, PHOBOS_SETTINGS) is copied too.

The folder is the setting recordsBackupPath (PHOBOS_RECORDS_BACKUP), set on the Companion's Settings page. Each copy is a folder
named for the owner's local time, written beside its place and then renamed, with a backup.json saying what it holds. **Nothing is
ever deleted**: the owner prunes old copies by hand.
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

from . import __version__
from .history import LOG as HISTORY
from .manifest import READS, WRITES
from .paths import CENTRAL_VARIABLE, central_settings_file, companion_data, resolve, where
from .report import Bullets, Report, Table, envelope_text, home_redactor, keep, render_markdown
from .testpass_cli import DECISIONS, VERDICTS

EXIT_OK, EXIT_USAGE, EXIT_REFUSED = 0, 2, 3
BACKUP = ("recordsBackupPath", "PHOBOS_RECORDS_BACKUP")
# The window's browser cache (WebView2 on Windows): rebuilt by the window, and most of the folder's size.
LEFT_OUT = frozenset({"EBWebView"})
PARTIAL = ".partial"
MANIFEST_FILE = "backup.json"
BACKUP_FORMAT = 1
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


def copies(folder):
    """The copies already in the folder, newest first: name, time (UTC, from its backup.json), files and bytes."""
    if folder is None or not Path(folder).is_dir():
        return []
    found = []
    for child in Path(folder).iterdir():
        if child.is_dir() and COPY_NAME.match(child.name):
            try:
                made = json.loads((child / MANIFEST_FILE).read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            found.append({"name": child.name, "time": made.get("time", ""), "files": made.get("files", 0),
                          "bytes": made.get("bytes", 0)})
    return sorted(found, key=lambda c: (c["time"], c["name"]), reverse=True)


def age_days(time_text, now=None):
    """Whole days since an ISO time; None when it cannot be read."""
    try:
        then = datetime.fromisoformat(time_text)
    except (TypeError, ValueError):
        return None
    if then.tzinfo is None:
        then = then.replace(tzinfo=timezone.utc)
    return max(0, ((now or datetime.now(timezone.utc)) - then).days)


def status(explicit=None, environ=None, now=None):
    folder = backup_folder(explicit, environ)
    items = []
    for name, path in sources(environ):
        files, size = _size(path)
        items.append({"name": name, "path": str(path), "files": files, "bytes": size})
    made = copies(folder)
    newest = made[0] if made else None
    age = age_days(newest["time"], now) if newest else None
    return {"folder": str(folder) if folder else None, "folderExists": bool(folder and Path(folder).is_dir()),
            "records": items, "copies": made, "newest": newest, "ageDays": age, "staleDays": STALE_DAYS,
            "stale": age is None or age >= STALE_DAYS}


def _local_stamp(now=None):
    return (now or datetime.now(timezone.utc)).astimezone().strftime("%Y%m%d-%H%M%S")


def backup(explicit=None, environ=None, now=None):
    """Copies every record into a new dated folder; returns what it wrote. Refuses with no folder chosen, or one inside the
    records themselves."""
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
    folder.mkdir(parents=True, exist_ok=True)
    stamp = _local_stamp(now)
    name = next(n for n in [stamp, *(f"{stamp}-{i}" for i in range(2, 1000))]
                if not (folder / n).exists() and not (folder / (n + PARTIAL)).exists())
    partial = folder / (name + PARTIAL)
    partial.mkdir()
    try:
        files = size = 0
        for item_name, path in found:
            target = partial / item_name
            if path.is_dir():
                shutil.copytree(path, target, ignore=shutil.ignore_patterns("*" + PARTIAL))
            else:
                shutil.copy2(path, target)
            counted = _size(target)
            files += counted[0]
            size += counted[1]
        when = (now or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat(timespec="seconds")
        (partial / MANIFEST_FILE).write_text(json.dumps({
            "format": BACKUP_FORMAT, "time": when, "kit": __version__, "files": files, "bytes": size,
            "records": [{"name": n, "from": str(p)} for n, p in found]}, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8", newline="\n")
        os.replace(partial, folder / name)
    except OSError:
        shutil.rmtree(partial, ignore_errors=True)
        raise
    return {"folder": str(folder), "name": name, "path": str(folder / name), "files": files, "bytes": size, "time": when}


def _parser():
    p = argparse.ArgumentParser(prog="records", description=__doc__.split("\n\n")[0],
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="report", required=True)
    for name, helptext in (("status", "what would be copied, where to, and the copies already there"),
                           ("backup", "copies the records into a new dated folder")):
        s = sub.add_parser(name, help=helptext)
        s.add_argument("--to", help="the backup folder (default: recordsBackupPath)")
        s.add_argument("--json", action="store_true", help="print JSON instead of Markdown")
        s.add_argument("--no-redact", action="store_true", help="show the home folder instead of ~")
    return p


def _kb(size):
    return f"{size / 1024:,.1f} KB" if size < 1024 * 1024 else f"{size / (1024 * 1024):,.1f} MB"


def main(argv=None, out=None, environ=None):
    out = out or sys.stdout
    try:
        args = _parser().parse_args(list(sys.argv[1:] if argv is None else argv))
    except SystemExit as stop:
        return EXIT_USAGE if stop.code else EXIT_OK
    redact = keep if args.no_redact else home_redactor()
    if args.report == "backup":
        try:
            made = backup(args.to, environ)
        except RecordsError as refused:
            out.write(f"Refused: {refused}\n")
            return EXIT_REFUSED
        report = Report(f"Records copied: {made['files']} files, {_kb(made['bytes'])}")
        report.section("Where", Bullets([made["path"]]))
        out.write((envelope_text("records", report, redact, {"copy": made}) if args.json
                   else render_markdown(report, redact)) + "\n")
        return EXIT_OK
    found = status(args.to, environ)
    if found["newest"] is None:
        title = "Records: never copied"
    else:
        title = f"Records: last copied {found['ageDays']} days ago" if found["ageDays"] else "Records: copied today"
    report = Report(title)
    report.section("What is copied", Table(["Record", "Files", "Size", "From"],
                                           [[r["name"], r["files"], _kb(r["bytes"]), r["path"]] for r in found["records"]]))
    report.section("Where the copies go", Bullets([found["folder"] or "No folder chosen yet: set recordsBackupPath (the "
                                                   "Companion's Settings page), then records backup."]))
    if found["copies"]:
        report.section("Copies", Table(["Copy", "When", "Files", "Size"],
                                       [[c["name"], c["time"], c["files"], _kb(c["bytes"])] for c in found["copies"][:10]]))
    out.write((envelope_text("records", report, redact, found) if args.json else render_markdown(report, redact)) + "\n")
    return EXIT_OK


MANIFEST = {"game": None, "parser": _parser, "effect": READS,
            "reports": {"status": {"note": "what would be copied, where to, and how old the newest copy is"},
                        "backup": {"effect": WRITES, "note": "copies the Companion's records into a new dated folder; deletes nothing"}}}
