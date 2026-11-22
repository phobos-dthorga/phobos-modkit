"""Saved lists of active mods: kept by name, kept at each game start, read from saves, a mod manager's history and files, compared
with the list the game reads, and loaded in its place (1.75.0). Game-free.

Step 4 of D'thorga Companion's own mod manager (the owner, 22 Nov 2026: "Start step 4, saved lists"). The owner's choices on
question cards: lists **from each save's own mods, RimSort's history and files** as well as lists saved by name; loading **shows the
difference, then a yes**; mods a list names that are not on this PC are **left out, named with why, and offered in Steam**; and a
copy **kept at each game start** whose list differs from the last copy kept.

Where lists come from (a list's `source`):

- **saved**: kept here by name (`lists/<name>.json` in the game's mod-list folder);
- **kept**: kept here at a game start (`kept/<time>.json`), noticed when the tools next read the list;
- **save**: a game save's own record of the mods it was played with (the adapter reads it; saves are never changed);
- **manager**: a mod manager's own history of lists (RimWorld: RimSort's), read where it keeps it;
- **file**: a file the person opens (RimWorld: the game's own `.rml`, an exported RimSort list, a save).

Loading writes the list as `apply`ing any change does: after a backup, refused while the game or a mod manager runs, undone by
`undo`. Nothing here deletes a kept copy; a saved list is taken away only on the person's word (`forget`).
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re

from .mod_list import FixError, _commit, _gone_reason, _refuse_while_running, folder, load_remembered, remembered_file
from .mod_sort import kept_run

LISTS_FORMAT = 1
SAVED, KEPT, SAVE, MANAGER, FILE = "saved", "kept", "save", "manager", "file"
SOURCES = (SAVED, KEPT, SAVE, MANAGER)
MAX_NAME = 80
NAME_FILE = re.compile(r"[^A-Za-z0-9 ._-]+")
# A list file may be changed after the game it was kept for started: the copy waits for a list unchanged since the start, allowing
# the game's own write of its list as it starts (agent default).
START_GRACE_SECONDS = 120


@dataclass
class SavedList:
    """A list of active mods kept somewhere, in load order, with what it knew of each mod."""
    source: str
    ref: str                      # how to ask for it again: a file name, or a path for a file
    label: str
    when: str = ""                # ISO time it was made (saved, kept, the save's or the file's time)
    ids: list = field(default_factory=list)
    names: dict = field(default_factory=dict)       # key: name, as the list knew them
    workshop: dict = field(default_factory=dict)    # key: Workshop number
    version: str = ""
    note: str = ""
    ran: dict = field(default_factory=dict)         # a kept copy's verdict from the run that started with it (1.85.0)


def lists_folder(game, environ=None, settings=None):
    return folder(game, environ, settings) / "lists"


def kept_folder(game, environ=None, settings=None):
    return folder(game, environ, settings) / "kept"


def _stamp(now=None):
    return (now or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat(timespec="seconds")


def _write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
    os.replace(temporary, path)


def _read_json_list(path, source):
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or data.get("format") != LISTS_FORMAT or not isinstance(data.get("ids"), list):
        return None
    return SavedList(source, Path(path).stem, str(data.get("label") or Path(path).stem), str(data.get("when", "")),
                     [str(i) for i in data["ids"]], dict(data.get("names") or {}), dict(data.get("workshop") or {}),
                     str(data.get("version", "")), str(data.get("note", "")), dict(data.get("ran") or {}))


def _data(saved):
    data = asdict(saved)
    data["format"] = LISTS_FORMAT
    return data


def snapshot(adapter, mod_list, installed, source, ref, label, now=None, note=""):
    """A list as it stands, with each mod's name and Workshop number as this PC knows them."""
    names, workshop = {}, {}
    for listed in mod_list.ids:
        mod = installed.find(listed) if installed is not None else None
        if mod is not None:
            names[adapter.key(listed)] = mod.name
            if mod.workshop_id:
                workshop[adapter.key(listed)] = mod.workshop_id
    return SavedList(source, ref, label, _stamp(now), list(mod_list.ids), names, workshop, adapter.game_version(), note)


# ---------------------------------------------------------------- lists saved by name

def file_name_for(name):
    """The file a saved list is kept in: its name, kept to letters, digits, spaces, dots, dashes and underscores."""
    cleaned = NAME_FILE.sub("-", name.strip()).strip(" .-")
    return cleaned[:MAX_NAME]


def save_named(adapter, mod_list, installed, name, replace=False, environ=None, settings=None, now=None):
    """Keeps the list as it stands under a name; refuses an empty name, or one in use unless `replace`."""
    if not name.strip() or len(name.strip()) > MAX_NAME:
        raise FixError(f"Give the list a name of 1 to {MAX_NAME} letters.")
    stem = file_name_for(name)
    if not stem:
        raise FixError("Give the list a name with letters or digits in it.")
    path = lists_folder(adapter.game, environ, settings) / f"{stem}.json"
    if path.exists() and not replace:
        raise FixError(f"A list named {name.strip()!r} is kept already: choose another name, or replace it.")
    saved = snapshot(adapter, mod_list, installed, SAVED, stem, name.strip(), now)
    _write_json(path, _data(saved))
    return saved


def forget_named(game, ref, environ=None, settings=None):
    """Takes away a list saved by name (the person's word)."""
    path = lists_folder(game, environ, settings) / f"{file_name_for(ref)}.json"
    if not path.is_file():
        raise FixError(f"There is no saved list {ref!r}.")
    path.unlink()
    return ref


def _kept_here(target, source):
    found = []
    for path in sorted(Path(target).glob("*.json"), reverse=True) if Path(target).is_dir() else []:
        saved = _read_json_list(path, source)
        if saved is not None:
            found.append(saved)
    return found


def named_lists(game, environ=None, settings=None):
    return sorted(_kept_here(lists_folder(game, environ, settings), SAVED), key=lambda s: s.label.lower())


def kept_lists(game, environ=None, settings=None):
    return _kept_here(kept_folder(game, environ, settings), KEPT)


# ---------------------------------------------------------------- a copy kept at each game start

def keep_at_start(adapter, mod_list, installed, environ=None, settings=None, now=None):
    """Keeps a copy of the list the game last started with, when it differs from the last copy kept. The adapter says when the
    game last started and whether it runs (`last_start()`); a list changed after that start (and not by the game as it started) is
    not what it started with, so nothing is kept. Returns the copy kept, or None. Never raises: a copy not kept costs only a list."""
    try:
        start = adapter.last_start() if hasattr(adapter, "last_start") else None
        if not start:
            return None
        started, running = start["started"], start.get("running", False)
        changed = datetime.fromtimestamp(Path(mod_list.path).stat().st_mtime, timezone.utc)
        ended = start.get("ended") or started
        if not running and (changed - ended).total_seconds() > START_GRACE_SECONDS:
            return None
        kept = kept_lists(adapter.game, environ, settings)
        if kept and kept[0].when >= _stamp(started):
            return None
        if kept and [adapter.key(i) for i in kept[0].ids] == [adapter.key(i) for i in mod_list.ids]:
            return None
        ref = started.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        label = f"Game start, {started.astimezone().strftime('%d %b %Y %H:%M')}"
        saved = snapshot(adapter, mod_list, installed, KEPT, ref, label, started)
        _write_json(kept_folder(adapter.game, environ, settings) / f"{ref}.json", _data(saved))
        return saved
    except (OSError, ValueError, KeyError, TypeError):
        return None


# ---------------------------------------------------------------- every list on offer

def every_list(adapter, environ=None, settings=None):
    """Every list on offer, by source: saved by name, kept at starts, each save's, and a mod manager's history."""
    found = {SAVED: named_lists(adapter.game, environ, settings), KEPT: kept_lists(adapter.game, environ, settings),
             SAVE: [], MANAGER: []}
    if hasattr(adapter, "save_lists"):
        found[SAVE] = list(adapter.save_lists())
    if hasattr(adapter, "manager_lists"):
        found[MANAGER] = list(adapter.manager_lists())
    return found


def find_list(adapter, source, ref, environ=None, settings=None):
    """One list by its source and ref, as `every_list` names it, or from a file."""
    if source == FILE:
        if not hasattr(adapter, "read_list_file"):
            raise FixError(f"The tools cannot read {adapter.name}'s list files yet.")
        saved = adapter.read_list_file(Path(ref))
        if saved is None:
            raise FixError(f"{ref} is not a list of mods the tools can read.")
        return saved
    if source not in SOURCES:
        raise FixError(f"A list comes from {', '.join(SOURCES + (FILE,))}; not {source!r}.")
    for saved in every_list(adapter, environ, settings)[source]:
        if saved.ref == ref:
            return saved
    raise FixError(f"There is no {source} list {ref!r}: read the lists again.")


# ---------------------------------------------------------------- comparing and loading

def compare(adapter, mod_list, chosen, installed, subscribed=None, environ=None, settings=None):
    """What loading a list would do to the list the game reads: switched on, switched off, moved, and the mods it names that are
    not on this PC (left out, each with why it is gone). `ids` is what would be written."""
    memory = load_remembered(remembered_file(adapter.game, environ, settings))
    keep, missing, seen = [], [], set()
    for listed in chosen.ids:
        key = adapter.key(listed)
        if key in seen:
            continue
        seen.add(key)
        if installed.find(listed) is None:
            remembered = memory.get(key) or {}
            workshop_id = chosen.workshop.get(key) or remembered.get("workshop_id", "")
            why = _gone_reason(adapter, remembered or None, workshop_id, subscribed, None)
            if not remembered and not workshop_id:
                why = ("It is not on this PC, and this list did not record where it came from: look for it on the Workshop by "
                       "its name.")
            missing.append({"id": listed, "key": key, "name": chosen.names.get(key) or remembered.get("name") or listed,
                            "workshop_id": workshop_id, "why": why})
        else:
            keep.append(listed)
    now_keys = [adapter.key(i) for i in mod_list.ids]
    new_keys = [adapter.key(i) for i in keep]
    on = [k for k in new_keys if k not in set(now_keys)]
    off = [k for k in now_keys if k not in set(new_keys)]
    both = [k for k in new_keys if k in set(now_keys)]
    old_place = {k: n for n, k in enumerate(k for k in now_keys if k in set(both))}
    moved = len(both) - len(kept_run(old_place, both)) if both else 0

    def named(key):
        mod = installed.first([key])
        return mod.name if mod is not None else (chosen.names.get(key) or (memory.get(key) or {}).get("name") or key)

    return {"source": chosen.source, "ref": chosen.ref, "label": chosen.label, "when": chosen.when, "version": chosen.version,
            "ids": keep, "keys": new_keys, "same": new_keys == now_keys,
            "on": [{"key": k, "name": named(k)} for k in on], "off": [{"key": k, "name": named(k)} for k in off],
            "moved": moved, "missing": missing, "count": len(keep), "now": len(now_keys)}


def load(adapter, mod_list, chosen, installed, running, environ=None, settings=None, now=None, subscribed=None):
    """Writes a list in place of the one the game reads, leaving out mods not on this PC, after a backup. Returns (what it did,
    the backup)."""
    if not mod_list.writable:
        raise FixError(f"{mod_list.label} is not a list this tool changes.")
    _refuse_while_running(adapter, running)
    found = compare(adapter, mod_list, chosen, installed, subscribed, environ, settings)
    if found["same"]:
        raise FixError(f"{mod_list.label} is that list already.")
    if not found["ids"]:
        raise FixError(f"None of the mods {chosen.label} names is on this PC.")
    words = f"load {chosen.label}"
    return found, _commit(adapter, mod_list, found["ids"], words, environ, settings, now)


def list_data(saved, with_ids=False):
    data = {"source": saved.source, "ref": saved.ref, "label": saved.label, "when": saved.when, "count": len(saved.ids),
            "version": saved.version, "note": saved.note, "ran": dict(saved.ran)}
    if with_ids:
        data["ids"] = list(saved.ids)
    return data
