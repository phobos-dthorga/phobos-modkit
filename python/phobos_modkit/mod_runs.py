"""What the game's runs say about the list it ran with (1.85.0). Game-free.

The owner's choices of 23 Nov 2026, after a full re-sort broke a mod and nothing said so until the log was read by hand:

- **Did my change break it?** After the tools change a list, the first game run that starts after the change is compared with
  the run before it, which must have ended before the change: error signatures the later run has and the earlier one does not
  are new since the change. New since is not the same as caused by: a save, a mod update or chance can bring errors too, and the
  words say so.
- **Ran clean**: each run is judged once, when the game has closed: clean when it has no error signature the run before it did
  not have. **Only like with like is compared**: a run that loaded a save against another that did, a run that did not against
  another that did not, since loading a save brings errors of its own (seen 23 Nov 2026: a two-minute run that loaded nothing made
  76 errors from loading a save look new). The copy of the list kept at that run's start (mod_lists.keep_at_start) is marked with the verdict, so the newest copy
  that ran clean can be loaded in one press.
- **No errors from it**: the mods the run's errors name (by the clues a log carries) are kept with the verdict, so a mod that does
  not say it works with the game's version but ran without one error can be told apart from one that did not.

A game's adapter gives `runs()` (its logs, newest first, each with when it started and ended) and `run_report(path, previous)`
(the run's errors, the mods they name, and the error signatures new since the previous run). Kept in `runs.json` in the game's
mod-list folder.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path

from . import mod_list as core
from . import mod_lists

RUNS_FORMAT = 1
NEW_SHOWN = 20          # new error signatures kept per run (agent default)
CLEAN, NEW_ERRORS, NOT_RUN, TOO_LATE, RUNNING, NO_CHANGE, UNKNOWN, CHANGED = (
    "clean", "new-errors", "not-run-since", "too-late", "running", "no-change", "unknown", "changed-since")


def runs_file(game, environ=None, settings=None):
    return core.folder(game, environ, settings) / "runs.json"


def load_runs(path):
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data.get("runs", {}) if isinstance(data, dict) and data.get("format") == RUNS_FORMAT else {}


def _save_runs(path, runs):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_name(path.name + ".partial")
    partial.write_text(json.dumps({"format": RUNS_FORMAT, "runs": runs}, indent=1), encoding="utf-8")
    os.replace(partial, path)


def _iso(moment):
    return moment.astimezone(timezone.utc).isoformat(timespec="seconds") if moment else ""


def _stamp_of(moment):
    return moment.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _list_it_ran_with(adapter, started, environ, settings):
    """The kept copy of the list a run started with: the one kept at its start, else the newest kept before it."""
    kept = mod_lists.kept_lists(adapter.game, environ, settings)
    exact = [k for k in kept if k.ref == _stamp_of(started)]
    if exact:
        return exact[0]
    earlier = [k for k in kept if k.when and k.when <= _iso(started)]
    return earlier[0] if earlier else None


def _mark_kept(adapter, saved, verdict, environ, settings):
    path = mod_lists.kept_folder(adapter.game, environ, settings) / f"{saved.ref}.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    data["ran"] = verdict
    mod_lists._write_json(path, data)


def judge_latest(adapter, installed, environ=None, settings=None, running=False, now=None):
    """The newest run's verdict, judged once and kept (None while the game runs, or when the adapter cannot say). Never raises:
    a run not judged costs only a verdict."""
    if running or not hasattr(adapter, "runs"):
        return None
    try:
        runs = adapter.runs()
        if not runs or runs[0].get("started") is None:
            return None
        latest = runs[0]
        key = _iso(latest["started"])
        path = runs_file(adapter.game, environ, settings)
        known = load_runs(path)
        if key in known:
            return known[key]
        previous = runs[1] if len(runs) > 1 else None
        report = adapter.run_report(latest["path"], previous["path"] if previous else None)
        by_name = {}
        for mod in installed.mods:
            by_name.setdefault(mod.name, adapter.key(mod.id))
        saved = _list_it_ran_with(adapter, latest["started"], environ, settings)
        compared = previous is not None and bool(report.get("loaded")) == bool(report.get("previous_loaded"))
        new = report.get("new", []) if compared else []
        record = {"started": key, "ended": _iso(latest.get("ended")),
                  "previous_started": _iso(previous.get("started")) if previous else "",
                  "previous_ended": _iso(previous.get("ended")) if previous else "",
                  "loaded": report.get("loaded", ""), "previous_loaded": report.get("previous_loaded", ""),
                  "compared": compared, "clean": (not new) if compared else None, "new_errors": len(new),
                  "new": new[:NEW_SHOWN], "errors": report.get("errors", 0),
                  "error_mods": sorted({by_name.get(name, name) for name in report.get("error_mods", [])}),
                  "list": saved.ref if saved else "",
                  "active": [adapter.key(i) for i in saved.ids] if saved else [],
                  "judged": _iso(now or datetime.now(timezone.utc))}
        known[key] = record
        _save_runs(path, known)
        if saved is not None:
            _mark_kept(adapter, saved, {"started": key, "clean": record["clean"], "new_errors": len(new)}, environ, settings)
        return record
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return None


def _moment(text):
    try:
        return datetime.strptime(text, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def since_change(adapter, list_key, latest, environ=None, settings=None, running=False):
    """What the first run after the latest change the tools made to a list says: a verdict, the change, and the new errors."""
    changes = core.changes(adapter.game, list_key, environ, settings)
    if not changes:
        return {"verdict": NO_CHANGE}
    record, backup = changes[0]
    change = {"why": record.get("why", ""), "at": record.get("at", ""), "file": backup.name}
    answer = {"change": change, "verdict": UNKNOWN, "new": [], "new_errors": 0, "run": ""}
    the_list = next((m for m in adapter.lists() if m.key == list_key), None)
    if the_list is not None and record.get("written"):
        try:
            if core.digest_text(core.read_text(the_list.path)) != record["written"]:
                answer["verdict"] = CHANGED
                return answer
        except OSError:
            pass
    if running:
        answer["verdict"] = RUNNING
        return answer
    at = _moment(change["at"])
    runs = adapter.runs() if hasattr(adapter, "runs") else []
    if at is None or not runs or runs[0].get("started") is None:
        return answer
    started = runs[0]["started"]
    answer["run"] = _iso(started)
    if started < at:
        answer["verdict"] = NOT_RUN
        return answer
    previous_end = runs[1].get("ended") if len(runs) > 1 else None
    if previous_end is None or previous_end > at:
        answer["verdict"] = TOO_LATE
        return answer
    if latest is None or latest.get("started") != _iso(started) or latest.get("clean") is None:
        return answer
    answer.update(verdict=CLEAN if latest["clean"] else NEW_ERRORS, new=latest.get("new", [])[:10],
                  new_errors=latest.get("new_errors", 0))
    return answer


def last_clean(adapter, environ=None, settings=None):
    """The newest copy of the list kept at a game start that then ran clean, or None."""
    for saved in mod_lists.kept_lists(adapter.game, environ, settings):
        if (saved.ran or {}).get("clean") is True:
            return saved
    return None
