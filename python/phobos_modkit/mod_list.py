"""What is wrong with a game's list of active mods, why, and the safe changes that put it right (1.72.0). Game-free.

The first step of D'thorga Companion's own mod manager (the owner, 22 Nov 2026: "We actually should have our own, third-party, mod
managing", after RimSort said only "1 missing mod" for a patch whose author had taken it off the Workshop). A game's adapter
(`games/<game>/mod_list.py`) knows where the game keeps its lists and how its mods describe themselves; this module holds the
checks, the memory of every mod a check has seen, and the backups behind every change.

The checks, each a problem, a warning or a note:

- **Missing**: the list names a mod that is not on this PC, with the likeliest reason (taken off the Workshop by its author, no
  longer subscribed, a download not finished, a local folder gone, or never seen here), what it was, who needs it, and any clue
  that another mod now does its job.
- **Needs**: a mod on the list needs another that is switched off (one press switches it on) or not on this PC.
- **Order and clashes**: a mod loads before one it must load after (or the reverse), two mods that refuse each other are both on,
  or one mod is listed twice.
- **Early warnings**: a mod on this PC that the Workshop no longer has, or that Steam no longer keeps up to date for you.
- **Game version**: a mod that does not say it works with this version of the game.

Changes are made only by `apply_fix` and `undo`, each after a backup of the list as it stood, and both refuse while the game or a
program that rewrites the list is running. Nothing here deletes a backup.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re

from .paths import companion_data, resolve

FOLDER = ("modListPath", "PHOBOS_MOD_LIST")
REMEMBERED_FORMAT = 1
PROBLEM, WARNING, NOTE = "problem", "warning", "note"
SEVERITIES = (PROBLEM, WARNING, NOTE)
REMOVE, REMOVE_EXTRA, ENABLE, MOVE = "remove", "remove-extra", "enable", "move"
ACTIONS = (REMOVE, REMOVE_EXTRA, ENABLE, MOVE)
BEFORE_GOING_BACK = "before going back"
# Steam's GetPublishedFileDetails result: 1 is a public item; 9 is "no such item" (removed, private, or never published).
STEAM_FOUND = 1
SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")
MIN_CLUE_WORD = 5        # letters a word of a mod's name or id needs before a clue may rest on it (agent default)
CLUE_STOP_WORDS = frozenset({"patch", "patches", "compat", "compatibility", "framework", "expanded", "vanilla", "addon",
                             "fixes", "tweaks", "retexture", "steam", "unofficial", "update", "continued", "rimworld"})


class FixError(RuntimeError):
    """A change that was refused, in words for the person who asked for it."""


# ---------------------------------------------------------------- what an adapter hands over

@dataclass(frozen=True)
class Need:
    """One mod another needs: its id, any ids that would do instead, and what the needing mod calls it."""
    ids: tuple
    name: str = ""
    workshop_id: str = ""


@dataclass
class Mod:
    """One mod on this PC, as its own files describe it."""
    id: str                      # as the mod declares it; the adapter's key() compares them
    name: str
    source: str                  # "game" (the game's own and its expansions), "local" or "workshop"
    folder: str = ""
    workshop_id: str = ""
    authors: str = ""
    needs: list = field(default_factory=list)          # Need
    load_after: list = field(default_factory=list)
    load_before: list = field(default_factory=list)
    incompatible: list = field(default_factory=list)
    versions: list = field(default_factory=list)       # the game versions it says it works with; empty when it says none
    version_min: str = ""
    version_max: str = ""
    preview: str = ""            # its own picture, as the game's mod menu or the Workshop shows it; "" when it has none (1.82.0)


@dataclass
class ModList:
    """One list of active mods the game reads, in load order."""
    key: str                     # "active", "default", "save:Sandbox/Phobos-1"
    label: str                   # in words
    path: Path
    ids: list
    writable: bool = True


@dataclass
class Fix:
    action: str
    list_key: str
    id: str
    label: str


@dataclass
class Problem:
    kind: str                    # missing, needs, order, clash, twice, removed, unsubscribed, version
    severity: str
    list_key: str
    id: str
    name: str
    title: str
    why: str = ""
    clue: str = ""
    needed_by: list = field(default_factory=list)
    fixes: list = field(default_factory=list)          # Fix
    workshop_id: str = ""


# ---------------------------------------------------------------- where its own files live

def folder(game, environ=None, settings=None):
    """This game's folder of the check's own files: the memory of mods seen, and the backups of lists."""
    base = resolve(*FOLDER, companion_data(environ) / "mod-list", None, environ, settings)
    return Path(base) / (SAFE_NAME.sub("-", game) or "game")


def now_stamp(now=None):
    return (now or datetime.now(timezone.utc)).astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def digest_text(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------- the memory of every mod a check has seen

def remembered_file(game, environ=None, settings=None):
    return folder(game, environ, settings) / "remembered.json"


def load_remembered(path):
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data.get("mods", {}) if isinstance(data, dict) and data.get("format") == REMEMBERED_FORMAT else {}


def remember(path, adapter, mods, now=None):
    """Adds or refreshes every mod on this PC in the memory, keyed as the adapter compares ids. Never forgets one: the point is
    to know a mod after its files have gone. Never raises; a memory that cannot be written costs only a later explanation."""
    known = load_remembered(path)
    stamp = (now or datetime.now(timezone.utc)).date().isoformat()
    for mod in mods:
        key = adapter.key(mod.id)
        entry = known.get(key, {"first_seen": stamp})
        entry.update({"id": mod.id, "name": mod.name, "source": mod.source, "workshop_id": mod.workshop_id or
                      entry.get("workshop_id", ""), "authors": mod.authors, "last_seen": stamp,
                      "needs": [{"ids": list(n.ids), "name": n.name, "workshop_id": n.workshop_id} for n in mod.needs],
                      "load_after": list(mod.load_after)})
        known[key] = entry
    try:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        temporary = Path(path).with_suffix(".tmp")
        temporary.write_text(json.dumps({"format": REMEMBERED_FORMAT, "mods": known}, indent=1, sort_keys=True),
                             encoding="utf-8")
        os.replace(temporary, path)
    except OSError:
        pass
    return known


# ---------------------------------------------------------------- reading a list against what is installed

class Installed:
    """The mods on this PC, looked up by the adapter's key."""

    def __init__(self, adapter, mods):
        self.adapter = adapter
        self.mods = list(mods)
        self.by_key = {}
        for mod in self.mods:
            self.by_key.setdefault(adapter.key(mod.id), []).append(mod)

    def find(self, listed):
        """The mod a list entry loads, or None."""
        return self.adapter.pick(self.by_key.get(self.adapter.key(listed), []), listed)

    def has(self, ids):
        return any(self.adapter.key(i) in self.by_key for i in ids)

    def first(self, ids):
        for i in ids:
            found = self.by_key.get(self.adapter.key(i))
            if found:
                return found[0]
        return None


def _words(text):
    return [w for w in re.split(r"[^a-z0-9]+", text.lower()) if len(w) >= MIN_CLUE_WORD and w not in CLUE_STOP_WORDS]


def _named(mod):
    return mod.name or mod.id


def _counts(text_list):
    return ", ".join(text_list[:-1]) + (" and " if len(text_list) > 1 else "") + text_list[-1] if text_list else ""


def _targets(adapter, gone_key, memory, active):
    """The active mods a missing one worked with: those it needed or loaded after, from memory; else those whose names its id
    carries (a patch named for two mods, as "x.rimmarket.hospitality.compatibility" is)."""
    found = []
    remembered = memory.get(gone_key)
    if remembered:
        for need in remembered.get("needs", []):
            for i in need.get("ids", []):
                mod = active.get(adapter.key(i))
                if mod and mod not in found and mod.source != "game":
                    found.append(mod)
        for i in remembered.get("load_after", []):
            mod = active.get(adapter.key(i))
            if mod and mod not in found and mod.source != "game":
                found.append(mod)
    if len(found) < 2:
        words = set(_words(gone_key))
        for mod in active.values():
            if mod.source == "game" or mod in found:
                continue
            tail = _words(adapter.key(mod.id).rsplit(".", 1)[-1])
            if tail and all(w in words for w in tail):
                found.append(mod)
    return found


def coverage_clue(adapter, gone_key, memory, active):
    """A clue, in words, that one of the mods a missing patch joined now does its job itself: its own files name the other."""
    targets = _targets(adapter, gone_key, memory, active)
    if len(targets) < 2:
        return ""
    for target in targets:
        for other in targets:
            if other is target:
                continue
            words = [w for w in _words(other.name) + _words(adapter.key(other.id).rsplit(".", 1)[-1])][:3]
            if words and adapter.mentions(target, words):
                return (f"{_named(target)}'s own files mention {_named(other)}, so {_named(target)} may now do this job itself. "
                        "A clue, not proof: check its page or settings.")
    return ""


def _gone_reason(adapter, remembered, workshop_id, subscribed, steam):
    if remembered and remembered.get("source") == "local":
        return "Its folder among your own mods is gone."
    if remembered and remembered.get("source") == "game":
        return "The game's own files for it are gone: an expansion not owned, or the game needs checking in Steam."
    if workshop_id:
        result = steam.get(workshop_id) if steam is not None else None
        if result is not None and result != STEAM_FOUND:
            return ("Steam no longer has it: its author took it off the Workshop or made it private, so Steam unsubscribed you "
                    "and deleted its files.")
        if subscribed is not None and workshop_id not in subscribed:
            return ("You are no longer subscribed to it, so Steam deleted its files." if result == STEAM_FOUND else
                    "Steam no longer lists it among your subscriptions. Ask Steam whether it still exists (read online).")
        if subscribed is not None:
            return "Steam lists it as subscribed, but its files are missing or broken: the download may not have finished."
    return "No check has seen it on this PC, so the tools cannot say what it was."


def check(adapter, mod_list, installed, memory, steam=None, subscribed=None):
    """Every problem with one list. `steam` is {workshop id: Steam's result} when read online, else None; `subscribed` the
    Workshop ids Steam keeps for this game, or None when unknown."""
    problems = []
    entries = [(position, listed, installed.find(listed)) for position, listed in enumerate(mod_list.ids)]
    active = {}
    position_of = {}
    for position, listed, mod in entries:
        key = adapter.key(listed)
        if mod is not None:
            active.setdefault(key, mod)
            active.setdefault(adapter.key(mod.id), mod)
        position_of.setdefault(key, position)
    needers = {}
    for _, _, mod in entries:
        for need in (mod.needs if mod else []):
            for i in need.ids:
                needers.setdefault(adapter.key(i), []).append(mod)
    seen = set()
    can_check = adapter.can_check_missing()
    unchecked = []
    for position, listed, mod in entries:
        key = adapter.key(listed)
        if key in seen:
            problems.append(Problem("twice", PROBLEM, mod_list.key, listed, _named(mod) if mod else listed,
                                    f"{_named(mod) if mod else listed} is on the list more than once.",
                                    "The game loads one copy and warns about the other.",
                                    fixes=[Fix(REMOVE_EXTRA, mod_list.key, listed, "Keep the first, take the others off")]))
            continue
        seen.add(key)
        if mod is not None:
            continue
        if not can_check and not adapter.is_local_id(listed):
            unchecked.append(listed)
            continue
        remembered = memory.get(key)
        workshop_id = (remembered or {}).get("workshop_id", "")
        name = (remembered or {}).get("name") or listed
        by = sorted({_named(m) for m in needers.get(key, [])})
        clue = coverage_clue(adapter, key, memory, active)
        why = _gone_reason(adapter, remembered, workshop_id, subscribed, steam)
        if by:
            why += f" {_counts(by)} {'needs' if len(by) == 1 else 'need'} it: take it off only if you take them off too."
        fixes = [Fix(REMOVE, mod_list.key, listed, "Take it off the list")]
        problems.append(Problem("missing", PROBLEM, mod_list.key, listed, name,
                                f"{name} is switched on, but it is not on this PC.", why, clue, by, fixes, workshop_id))
    if unchecked:
        problems.append(Problem("unchecked", NOTE, mod_list.key, "", "",
                                f"{len(unchecked)} mods on {mod_list.label} could not be looked for.",
                                adapter.why_unchecked()))
    problems += _needs(adapter, mod_list, entries, installed, active)
    problems += _order(adapter, mod_list, entries, active, position_of)
    problems += _warnings(adapter, mod_list, entries, steam, subscribed)
    problems += _versions(adapter, mod_list, entries)
    order = {s: i for i, s in enumerate(SEVERITIES)}
    return sorted(problems, key=lambda p: (order[p.severity], p.kind, p.name.lower()))


def _needs(adapter, mod_list, entries, installed, active):
    """A mod on the list needs one that is not: switched off when it is on this PC, else not here. A needed mod that is listed but
    missing is the missing check's, not this one's."""
    listed = {adapter.key(e[1]) for e in entries}
    wanted = {}                  # the needed mod's first key: (the Need, the mods needing it)
    for _, _, mod in entries:
        for need in (mod.needs if mod else []):
            keys = [adapter.key(i) for i in need.ids]
            if any(k in active or k in listed for k in keys):
                continue
            found = wanted.setdefault(keys[0], (need, []))
            if _named(mod) not in found[1]:
                found[1].append(_named(mod))
    problems = []
    for need, by in wanted.values():
        there = installed.first(need.ids)
        label = there.name if there else (need.name or need.ids[0])
        who = f"{_counts(by)} {'needs' if len(by) == 1 else 'need'} {label}"
        if there is not None:
            problems.append(Problem("needs", PROBLEM, mod_list.key, there.id, label, f"{who}, which is switched off.",
                                    "It is on this PC; switching it on puts it just before the first mod that needs it.",
                                    needed_by=by, fixes=[Fix(ENABLE, mod_list.key, there.id, "Switch it on")],
                                    workshop_id=there.workshop_id))
        else:
            problems.append(Problem("needs", PROBLEM, mod_list.key, need.ids[0], label, f"{who}, which is not on this PC.",
                                    adapter.how_to_get(need), needed_by=by, workshop_id=need.workshop_id))
    return problems


def _order(adapter, mod_list, entries, active, position_of):
    problems, clashed = [], set()
    for position, listed, mod in entries:
        if mod is None:
            continue
        for wanted, after in [(i, True) for i in mod.load_after] + [(i, False) for i in mod.load_before]:
            key = adapter.key(wanted)
            other = active.get(key)
            if other is None or other is mod or key not in position_of:
                continue
            theirs = position_of[key]
            if (after and theirs > position) or (not after and theirs < position):
                word = "after" if after else "before"
                problems.append(Problem("order", WARNING, mod_list.key, listed, _named(mod),
                                        f"{_named(mod)} must load {word} {_named(other)}, but loads "
                                        f"{'before' if after else 'after'} it.",
                                        f"{_named(mod)} says so in its own files. Move it {word} {_named(other)}, or sort the list."))
        for refused in mod.incompatible:
            other = active.get(adapter.key(refused))
            pair = frozenset({adapter.key(mod.id), adapter.key(refused)})
            if other is None or other is mod or pair in clashed:
                continue
            clashed.add(pair)
            problems.append(Problem("clash", PROBLEM, mod_list.key, listed, _named(mod),
                                    f"{_named(mod)} and {_named(other)} are both on, but {_named(mod)} says they do not work "
                                    "together.", "Switch one of them off.",
                                    fixes=[Fix(REMOVE, mod_list.key, listed, f"Switch {_named(mod)} off"),
                                           Fix(REMOVE, mod_list.key, other.id, f"Switch {_named(other)} off")]))
    return problems


def _warnings(adapter, mod_list, entries, steam, subscribed):
    problems, done = [], set()
    for _, listed, mod in entries:
        if mod is None or mod.source != "workshop" or not mod.workshop_id or mod.workshop_id in done:
            continue
        done.add(mod.workshop_id)
        result = steam.get(mod.workshop_id) if steam is not None else None
        if result is not None and result != STEAM_FOUND:
            problems.append(Problem("removed", WARNING, mod_list.key, listed, _named(mod),
                                    f"The Workshop no longer has {_named(mod)}.",
                                    "Its author took it off the Workshop or made it private. Its files are still here, but "
                                    "Steam will not update it and may delete it: a safe copy of its folder keeps it.",
                                    workshop_id=mod.workshop_id))
        elif subscribed is not None and mod.workshop_id not in subscribed:
            problems.append(Problem("unsubscribed", WARNING, mod_list.key, listed, _named(mod),
                                    f"Steam no longer keeps {_named(mod)} up to date for you.",
                                    "Its files are here, but you are not subscribed to it: it will not be updated, and Steam may "
                                    "delete it. Subscribe again to keep it current.", workshop_id=mod.workshop_id))
    return problems


def _versions(adapter, mod_list, entries):
    problems = []
    version = adapter.game_version()
    if not version:
        return problems
    for _, listed, mod in entries:
        if mod is None or mod.source == "game":
            continue
        reason = adapter.version_misfit(mod, version)
        if reason:
            problems.append(Problem("version", NOTE, mod_list.key, listed, _named(mod), reason,
                                    "Many such mods still work; it is worth a look if the game reports errors from it.",
                                    workshop_id=mod.workshop_id))
    return problems


# ---------------------------------------------------------------- changing a list, with a backup every time

def backups_folder(game, environ=None, settings=None):
    return folder(game, environ, settings) / "backups"


def _index(place, length):
    """A place as people count (1 is first) as an index into a list of this length, kept inside it."""
    return max(0, min(int(place) - 1, length))


def _several(mod_ids):
    return [mod_ids] if isinstance(mod_ids, str) else list(mod_ids)


def plan(adapter, mod_list, installed, action, mod_id, place=None):
    """The list's ids after one change, and the change in words. Raises FixError when the change makes no sense. `installed` is
    needed only to switch a mod on; `place` (1 is first) says where a mod switched on or moved goes. Moving, switching on and
    switching off take several mods at once (1.74.0): moved or switched on together, they go to the place as one block, in the
    order they had on the list (or were named in)."""
    wanted = _several(mod_id)
    if not wanted:
        raise FixError("Name a mod to change.")
    if len(wanted) > 1 and action == REMOVE_EXTRA:
        raise FixError("Keep the first of one mod at a time.")
    if len(wanted) > 1:
        return _plan_several(adapter, mod_list, installed, action, wanted, place)
    return _plan_one(adapter, mod_list, installed, action, wanted[0], place)


def _plan_several(adapter, mod_list, installed, action, wanted, place):
    keys = {adapter.key(i) for i in wanted}
    ids = list(mod_list.ids)
    count = len(keys)
    if action in (MOVE, REMOVE):
        missing = [i for i in wanted if not any(adapter.key(x) == adapter.key(i) for x in ids)]
        if missing:
            raise FixError(f"{', '.join(missing)} {'is' if len(missing) == 1 else 'are'} not on the list.")
        if action == REMOVE:
            return [i for i in ids if adapter.key(i) not in keys], f"switch {count} mods off"
        if place is None or int(place) < 1:
            raise FixError("Say where to move them: a place from 1 (first).")
        moving = [i for i in ids if adapter.key(i) in keys]
        rest = [i for i in ids if adapter.key(i) not in keys]
        to = _index(place, len(rest))
        after = rest[:to] + moving + rest[to:]
        if after == ids:
            raise FixError("They are there already.")
        return after, f"move {count} mods to place {to + 1}"
    if action == ENABLE:
        already = [i for i in wanted if any(adapter.key(x) == adapter.key(i) for x in ids)]
        if already:
            raise FixError(f"{', '.join(already)} {'is' if len(already) == 1 else 'are'} on the list already.")
        mods = []
        for i in wanted:
            mod = installed.first([i]) if installed is not None else None
            if mod is None:
                raise FixError(f"{i} is not on this PC, so it cannot be switched on.")
            mods.append(mod)
        if place is not None:
            at = _index(place, len(ids))
            return ids[:at] + [adapter.listed_id(m) for m in mods] + ids[at:], f"switch {count} mods on, at place {at + 1}"
        for mod in mods:
            ids, _ = _plan_one(adapter, ModList(mod_list.key, mod_list.label, mod_list.path, ids), installed, ENABLE, mod.id, None)
        return ids, f"switch {count} mods on"
    raise FixError(f"{action} is not a change this tool makes; it makes {', '.join(ACTIONS)}.")


def _plan_one(adapter, mod_list, installed, action, mod_id, place=None):
    key = adapter.key(mod_id)
    ids = list(mod_list.ids)
    if action == MOVE:
        at = next((n for n, i in enumerate(ids) if adapter.key(i) == key), None)
        if at is None:
            raise FixError(f"{mod_id} is not on the list.")
        if place is None or int(place) < 1:
            raise FixError("Say where to move it: a place from 1 (first).")
        moving = ids.pop(at)
        to = _index(place, len(ids))
        if to == at:
            raise FixError(f"{mod_id} is in place {at + 1} already.")
        return ids[:to] + [moving] + ids[to:], f"move {mod_id} to place {to + 1}"
    if action == REMOVE:
        kept = [i for i in ids if adapter.key(i) != key]
        if len(kept) == len(ids):
            raise FixError(f"{mod_id} is not on the list.")
        return kept, f"take {mod_id} off the list"
    if action == REMOVE_EXTRA:
        first = next((n for n, i in enumerate(ids) if adapter.key(i) == key), None)
        if first is None:
            raise FixError(f"{mod_id} is not on the list.")
        kept = [i for n, i in enumerate(ids) if n == first or adapter.key(i) != key]
        if len(kept) == len(ids):
            raise FixError(f"{mod_id} is on the list once already.")
        return kept, f"keep the first {mod_id} and take the others off"
    if action == ENABLE:
        if any(adapter.key(i) == key for i in ids):
            raise FixError(f"{mod_id} is on the list already.")
        mod = installed.first([mod_id]) if installed is not None else None
        if mod is None:
            raise FixError(f"{mod_id} is not on this PC, so it cannot be switched on.")
        if place is not None:
            at = _index(place, len(ids))
            return ids[:at] + [adapter.listed_id(mod)] + ids[at:], f"switch {mod.name} on, at place {at + 1}"
        at = len(ids)
        for n, listed in enumerate(ids):
            there = installed.find(listed)
            if there and any(key in [adapter.key(i) for i in need.ids] for need in there.needs):
                at = n
                break
        return ids[:at] + [adapter.listed_id(mod)] + ids[at:], f"switch {mod.name} on"
    raise FixError(f"{action} is not a change this tool makes; it makes {', '.join(ACTIONS)}.")


def _refuse_while_running(adapter, running):
    found = running(list(adapter.processes) + list(adapter.managers))
    if found:
        raise FixError(f"{_counts(found)} {'is' if len(found) == 1 else 'are'} running and would write over the change. "
                       "Close it, then try again.")


def _backup(adapter, mod_list, text, why, environ=None, settings=None, now=None, written=""):
    target = backups_folder(adapter.game, environ, settings)
    target.mkdir(parents=True, exist_ok=True)
    stamp = now_stamp(now)
    base = f"{stamp}--{SAFE_NAME.sub('-', mod_list.key)}"
    n = 1
    while (target / f"{base}.list").exists():
        n += 1
        base = f"{stamp}-{n}--{SAFE_NAME.sub('-', mod_list.key)}"
    (target / f"{base}.list").write_bytes(text.encode("utf-8"))
    record = {"list": mod_list.key, "path": str(mod_list.path), "why": why, "at": stamp, "written": written}
    (target / f"{base}.json").write_text(json.dumps(record, indent=1), encoding="utf-8")
    return target / f"{base}.list"


def _write(path, text):
    path = Path(path)
    temporary = path.with_name(path.name + ".phobos-tmp")
    temporary.write_bytes(text.encode("utf-8"))
    os.replace(temporary, path)


def read_text(path):
    return Path(path).read_bytes().decode("utf-8-sig")


def apply_fix(adapter, mod_list, installed, action, mod_id, running, environ=None, settings=None, now=None, place=None):
    """Makes one change, after a backup of the list as it stood. Returns (the change in words, the backup, the list's ids now)."""
    if not mod_list.writable:
        raise FixError(f"{mod_list.label} is not a list this tool changes.")
    _refuse_while_running(adapter, running)
    ids, words = plan(adapter, mod_list, installed, action, mod_id, place)
    return words, _commit(adapter, mod_list, ids, words, environ, settings, now), ids


def _commit(adapter, mod_list, ids, words, environ=None, settings=None, now=None):
    before = read_text(mod_list.path)
    after = adapter.render(before, ids)
    backup = _backup(adapter, mod_list, before, words, environ, settings, now, written=digest_text(after))
    _write(mod_list.path, after)
    return backup


def apply_order(adapter, mod_list, ids, words, running, environ=None, settings=None, now=None):
    """Writes the list in a new order (a sort's), after a backup. Refuses an order that adds or drops a mod, or a list changed
    since the order was worked out (1.74.0)."""
    if not mod_list.writable:
        raise FixError(f"{mod_list.label} is not a list this tool changes.")
    _refuse_while_running(adapter, running)
    if sorted(adapter.key(i) for i in ids) != sorted(adapter.key(i) for i in mod_list.ids):
        raise FixError(f"{mod_list.label} has changed since it was sorted: sort it again.")
    if list(ids) == list(mod_list.ids):
        raise FixError(f"{mod_list.label} is in that order already.")
    return _commit(adapter, mod_list, list(ids), words, environ, settings, now)


def backups(game, environ=None, settings=None):
    """Every backup of a list, newest first: (record, the backup file)."""
    found = []
    target = backups_folder(game, environ, settings)
    for record_file in sorted(target.glob("*.json"), reverse=True) if target.is_dir() else []:
        try:
            record = json.loads(record_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        listed = record_file.with_suffix(".list")
        if listed.exists():
            found.append((record, listed))
    return found


def changes(game, list_key, environ=None, settings=None):
    """The changes made to a list that can still be gone back on, newest first: (record, backup file). Each undo marks the change
    it went back on, so the next goes back on the one before (1.73.0)."""
    return [(r, f) for r, f in backups(game, environ, settings)
            if r.get("list") == list_key and r.get("why") != BEFORE_GOING_BACK and not r.get("undone")]


def undo(adapter, mod_list, running, environ=None, settings=None, now=None, backup_file=None):
    """Puts the list back as it was before the latest change this tool made to it and not yet gone back on (or the backup named),
    after a backup of the list as it is now. Refuses when the list was changed since by something else, which going back would
    throw away. Pressed again, it goes back on the change before."""
    if not mod_list.writable:
        raise FixError(f"{mod_list.label} is not a list this tool changes.")
    _refuse_while_running(adapter, running)
    choices = changes(adapter.game, mod_list.key, environ, settings)
    if backup_file:
        choices = [(r, f) for r, f in choices if f.name == Path(backup_file).name]
    if not choices:
        raise FixError(f"There is no change of {mod_list.label} to go back on.")
    record, listed = choices[0]
    now_text = read_text(mod_list.path)
    if not backup_file and record.get("written") and record["written"] != digest_text(now_text):
        raise FixError(f"{mod_list.label} has changed since that change (a game or a mod manager saved it), so going back would "
                       "throw those changes away. Choose the backup by name to go back anyway.")
    _backup(adapter, mod_list, now_text, BEFORE_GOING_BACK, environ, settings, now)
    _write(mod_list.path, listed.read_bytes().decode("utf-8"))
    record["undone"] = True
    listed.with_suffix(".json").write_text(json.dumps(record, indent=1), encoding="utf-8")
    return record


def problem_data(problem):
    data = asdict(problem)
    data["fixes"] = [asdict(f) for f in problem.fixes]
    return data
