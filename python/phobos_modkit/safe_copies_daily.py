"""Safe copies of everything, every day (1.71.0; the owner's word of 22 Nov 2026). Game-free.

`run-all` runs every list in every repository on the owner's games list (D'thorga Companion's games.json): each repository's own
list (config/safe-copies.json) and every game's list it keeps (config/safe-copies/<game>.json), so a new game or repository joins
the daily run by being on the list, with nothing to add here. With `--settle`, files written in the last two minutes wait for the
next run, as a game may be saving; with `--verify`, every copy is hashed again afterwards. What it did is kept for the Companion
in its folder (safe-copies/last-run-all.json).

`schedule` sets the daily run as a Windows scheduled task of the owner's own (no administrator, no password): at the time they
choose, caught up at the next sign-in when the PC was off, never two at once, at low priority and with no window. It runs this
copy of the kit, with the Python that set it.
"""
from __future__ import annotations

from datetime import datetime, timedelta
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from xml.etree import ElementTree

from . import __version__, games_list, safe_copies as sc
from .games_list import GAMES, games_file  # noqa: F401  (kept here for the callers that import them from this module)
from .paths import companion_data
from .progress import silent

TASK = "D'thorga Safe Copies"
TIME = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")
LIMIT = "PT3H"                        # a run that has not ended in three hours is stopped; the next day's starts afresh
TASK_NS = "http://schemas.microsoft.com/windows/2004/02/mit/task"
NO_WINDOW = 0x08000000


class DailyError(sc.SafeCopiesError):
    """A request about the daily run this module refuses, with the reason in words."""


def repositories(path):
    """Every repository folder on a games list, each once, in the list's order (games_list, since 1.109.0)."""
    try:
        return games_list.repositories(path)
    except games_list.GamesListError as error:
        raise DailyError(str(error)) from None


def lists_in(repository):
    """(repository, game) for each list a repository keeps: None for its own, else the game's name."""
    found = [(repository, None)] if sc.list_path(repository).is_file() else []
    folder = Path(repository) / sc.LISTS
    if folder.is_dir():
        found += [(repository, path.stem) for path in sorted(folder.glob("*.json")) if sc.NAME.match(path.stem)]
    return found


def daily_record(environ=None):
    return companion_data(environ) / "safe-copies" / "last-run-all.json"


def run_all(environ=None, games=None, settle=False, verify=False, push=True, now=None, progress=None, runner=None):
    """Runs every list on the games list, one after another, then checks every copy if asked. A list that is refused, or a
    repository that is not there, is a row of its own; the others still run."""
    progress = progress or silent()
    path = games_file(games, environ)
    rows = []
    for repository in repositories(path):
        if not Path(repository).is_dir():
            rows.append({"repository": Path(repository).name, "game": None, "ok": False, "problem": "not on this PC"})
            continue
        for root, game in lists_in(repository):
            row = {"repository": Path(root).name, "game": game, "ok": True, "copied": 0, "bytes": 0, "failed": 0, "notes": []}
            try:
                collection, results = sc.run(root, environ, push=push, now=now, progress=progress, runner=runner, game=game,
                                             settle=settle)
            except sc.SafeCopiesError as refused:
                row.update(ok=False, problem=str(refused))
            else:
                row.update(game=collection.game, notes=collection.notes[:sc.SHOWN],
                           copied=sum(len(r["copied"]) for r in results),
                           bytes=sum(c["bytes"] for r in results for c in r["copied"]),
                           failed=sum(len(r["failed"]) + len(r["warnings"]) for r in results))
                row["ok"] = not row["failed"]
            rows.append(row)
    checked = sc.verify(environ, None, progress) if verify else None
    summary = {"time": sc._iso(now), "kit": __version__, "games": str(path), "lists": rows, "settled": settle,
               "checked": checked, "ok": all(r["ok"] for r in rows) and not any(c["problems"] for c in checked or [])}
    sc._write_json(daily_record(environ), summary)
    return summary


def last_run_all(environ=None):
    """What the last run-all did, or None."""
    try:
        return json.loads(daily_record(environ).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


# ---------------------------------------------------------------- the scheduled task (Windows)

def _windows():
    if sys.platform != "win32":
        raise DailyError("the daily run is a Windows scheduled task; elsewhere, run safe-copies run-all from cron")


def program(python=None):
    """The Python the task runs: the windowless pythonw.exe beside this one when there is one."""
    python = Path(python or sys.executable)
    quiet = python.with_name("pythonw.exe")
    return quiet if quiet.is_file() else python


def task_xml(at, games, python=None, folder=None, user=None, today=None):
    """The task's definition, as Task Scheduler reads it."""
    match = TIME.match(at or "")
    if not match:
        raise DailyError(f"{at!r} is not a time of day as HH:MM, such as 04:00")
    folder = Path(folder or Path(__file__).resolve().parents[1])
    start = datetime.combine(today or datetime.now().date(), datetime.min.time()).replace(hour=int(match[1]),
                                                                                            minute=int(match[2]))
    arguments = f'-m phobos_modkit safe-copies run-all --settle --verify --games "{games}"'
    user = user or os.environ.get("USERNAME", "")

    def text(value):
        return str(value).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")

    return f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.4" xmlns="{TASK_NS}">
  <RegistrationInfo>
    <Author>{text(user)}</Author>
    <Description>Safe copies of what cannot be made again, every day (phobos-modkit {__version__}, safe-copies schedule).</Description>
  </RegistrationInfo>
  <Triggers>
    <CalendarTrigger>
      <StartBoundary>{start.isoformat(timespec="seconds")}</StartBoundary>
      <Enabled>true</Enabled>
      <ScheduleByDay><DaysInterval>1</DaysInterval></ScheduleByDay>
    </CalendarTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author">
      <UserId>{text(user)}</UserId>
      <LogonType>InteractiveToken</LogonType>
      <RunLevel>LeastPrivilege</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <StartWhenAvailable>true</StartWhenAvailable>
    <RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable>
    <IdleSettings><StopOnIdleEnd>false</StopOnIdleEnd><RestartOnIdle>false</RestartOnIdle></IdleSettings>
    <Enabled>true</Enabled>
    <Hidden>false</Hidden>
    <ExecutionTimeLimit>{LIMIT}</ExecutionTimeLimit>
    <Priority>7</Priority>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>{text(program(python))}</Command>
      <Arguments>{text(arguments)}</Arguments>
      <WorkingDirectory>{text(folder)}</WorkingDirectory>
    </Exec>
  </Actions>
</Task>
"""


def _schtasks(*arguments, run=subprocess.run):
    return run(["schtasks", *arguments], capture_output=True, text=True, check=False,
               creationflags=NO_WINDOW if sys.platform == "win32" else 0)


def schedule_set(at, games, run=subprocess.run, python=None, folder=None):
    """Sets (or moves) the daily run to `at`, HH:MM local time."""
    _windows()
    definition = task_xml(at, games, python, folder)
    with tempfile.TemporaryDirectory() as work:
        path = Path(work) / "task.xml"
        path.write_text(definition, encoding="utf-16")
        done = _schtasks("/Create", "/TN", TASK, "/XML", str(path), "/F", run=run)
    if done.returncode != 0:
        raise DailyError(f"Task Scheduler refused the daily run: {(done.stderr or done.stdout).strip()}")
    return schedule_read(run)


def schedule_off(run=subprocess.run):
    """Removes the daily run; nothing else. Copies already made stay."""
    _windows()
    if schedule_read(run)["set"]:
        done = _schtasks("/Delete", "/TN", TASK, "/F", run=run)
        if done.returncode != 0:
            raise DailyError(f"Task Scheduler would not remove the daily run: {(done.stderr or done.stdout).strip()}")
    return schedule_read(run)


def schedule_read(run=subprocess.run):
    """Whether the daily run is set, at what time, and what it runs."""
    if sys.platform != "win32":
        return {"set": False, "supported": False}
    done = _schtasks("/Query", "/TN", TASK, "/XML", run=run)
    if done.returncode != 0:
        return {"set": False, "supported": True}
    try:
        # schtasks prints the definition as text that still declares UTF-16: read it without the declaration.
        tree = ElementTree.fromstring(re.sub(r"^\s*<\?xml[^>]*\?>", "", done.stdout or ""))
    except ElementTree.ParseError:
        return {"set": True, "supported": True, "at": None}
    ns = {"t": TASK_NS}
    start = tree.findtext(".//t:CalendarTrigger/t:StartBoundary", default="", namespaces=ns)
    enabled = tree.findtext(".//t:Settings/t:Enabled", default="true", namespaces=ns) == "true"
    return {"set": True, "supported": True, "enabled": enabled, "at": start[11:16] or None,
            "command": tree.findtext(".//t:Exec/t:Command", default="", namespaces=ns),
            "arguments": tree.findtext(".//t:Exec/t:Arguments", default="", namespaces=ns),
            "folder": tree.findtext(".//t:Exec/t:WorkingDirectory", default="", namespaces=ns)}


def next_run(at, now=None):
    """When a daily run at HH:MM next starts, as local time."""
    now = now or datetime.now()
    hour, minute = (int(part) for part in at.split(":"))
    moment = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    return moment if moment > now else moment + timedelta(days=1)
