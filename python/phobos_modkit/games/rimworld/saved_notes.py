"""Saved histories as seen-in-play notes (1.121.0): lists a mod keeps in its saves, read as evidence for a test list.

A mod's saved lists of what happened (phobos-rimworld's vehicle event logs and logbooks) say every time a stage was entered, a part
failed or a service was done, with the tick it happened at. Read from saves, each item becomes a note in the seen-in-play format, so
test-pass judges it beside the game's own notes, by the same evidence map: expectations, parts and order rules.

**Which version wrote it.** A save does not record mods' versions, and a note older than the row it stands for must count as stale.
The mod's own version ledger answers it: a saved list of lines "tick|mod name|version", one each time a version began running. An
item's tick then names its version exactly. **An item older than the ledger's first line has no known version and is given "0"**, so
it is stale for any row naming a version.

**The same item in several saves is one note**, kept from the oldest save holding it (its time is that save's), with its tick, so
order rules sort by tick within one save's time. The mapping lives in the repository's evidence map, under `saved`
(`docs/test-pass.md`).
"""
from __future__ import annotations

from contextlib import closing
from datetime import datetime, timezone
import re

from ... import cache as derived
from . import paths
from . import save as saves
from . import save_checks
from . import save_thing

DEFAULT_SAVES = 4
FORMAT = 1
_TEMPLATE = re.compile(r"\{(\w+)\}")


class SavedError(ValueError):
    """The evidence map's saved section cannot be used; the message says why."""


def _fill(template, fields):
    text = _TEMPLATE.sub(lambda m: str(fields.get(m.group(1), "")), template)
    return re.sub(r"\.{2,}", ".", text).strip(". ")


def check_config(saved):
    """The saved section, checked: (sources, ledger key, how many saves). SavedError says what is wrong."""
    if not isinstance(saved, dict):
        raise SavedError("\"saved\" is an object, with its \"sources\"")
    sources = saved.get("sources")
    if not isinstance(sources, list) or not sources:
        raise SavedError("\"saved\" needs \"sources\", a list of the saved lists to read")
    for n, source in enumerate(sources, 1):
        where = f"saved source {n}"
        if not isinstance(source, dict):
            raise SavedError(f"{where} is an object")
        for name in ("name", "mod", "list", "tick"):
            if not isinstance(source.get(name), str) or not source[name]:
                raise SavedError(f"{where} needs \"{name}\"")
        if not isinstance(source.get("select"), dict) or not source["select"]:
            raise SavedError(f"{where} needs \"select\", saying which things keep the list")
        if not (isinstance(source.get("key"), str) or isinstance(source.get("keys"), dict)):
            raise SavedError(f"{where} needs \"key\", or \"keyBy\" and \"keys\"")
        if isinstance(source.get("keys"), dict) and not isinstance(source.get("keyBy"), str):
            raise SavedError(f"{where}: \"keys\" needs \"keyBy\", the field that chooses among them")
    count = saved.get("saves", DEFAULT_SAVES)
    if not isinstance(count, int) or count < 1:
        raise SavedError("\"saves\" is how many of the newest saves to read, at least 1")
    ledger = saved.get("ledger", "")
    if not isinstance(ledger, str):
        raise SavedError("\"ledger\" is the saved list's name, as the save writes it")
    return sources, ledger, count


def items_of(rows, list_name):
    """Each item of a saved list as {field: value}, in save order: rows under list_name/li[N]/field."""
    pattern = re.compile(re.escape(list_name) + r"/li\[(\d+)\]/(.+)", re.IGNORECASE)
    items = {}
    for path, value in rows:
        found = pattern.fullmatch(path)
        if found:
            items.setdefault(int(found.group(1)), {})[found.group(2)] = value
    return [items[n] for n in sorted(items)]


def read_ledger(conn, key):
    """{mod name: [(tick, version), ...]} from the version ledger's saved lines, oldest first; empty without one."""
    if not key:
        return {}
    ledger = {}
    rows = conn.execute("SELECT value FROM component_view WHERE path = ? ORDER BY position", (f"{key}/li",)).fetchall()
    for (line,) in rows:
        parts = str(line).split("|")
        if len(parts) == 3 and parts[0].strip().lstrip("-").isdigit():
            ledger.setdefault(parts[1].strip(), []).append((int(parts[0]), parts[2].strip()))
    for entries in ledger.values():
        entries.sort()
    return ledger


def version_at(ledger, mod, tick):
    """The version of the mod that ran at the tick, by the ledger; "0" when the ledger does not reach back that far."""
    found = "0"
    for start, version in ledger.get(mod, []):
        if start <= tick:
            found = version
        else:
            break
    return found


def _iso(path):
    return datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def notes_from_save(conn, save, meta, sources, ledger_key):
    """Every note the sources' lists give in one save, each a dict in the seen-in-play format, with its tick."""
    ledger = read_ledger(conn, ledger_key)
    reader = save_checks.SaveReader(conn, save, meta)
    time = _iso(save)
    found = []
    for source in sources:
        defaults = {str(k): str(v) for k, v in (source.get("defaults") or {}).items()}
        for thing in save_checks.select_things(conn, source["select"]):
            for item in items_of(reader.values(thing), source["list"]):
                fields = dict(defaults)
                fields.update(item)
                fields.setdefault("thing", thing[1])
                fields.setdefault("thingDef", thing[2])
                tick_text = str(fields.get(source["tick"], "")).strip()
                if not tick_text.lstrip("-").isdigit():
                    continue
                tick = int(tick_text)
                if source.get("keys"):
                    template = source["keys"].get(fields.get(source["keyBy"], ""))
                    if not template:
                        continue
                else:
                    template = source["key"]
                note = {"format": FORMAT, "time": time, "tick": tick, "key": _fill(template, fields), "mod": source["mod"],
                        "version": version_at(ledger, source["mod"], tick), "on": thing[1], "kind": thing[2],
                        "source": "save", "save": save.name}
                said = (_fill(source["detail"], fields) if source.get("detail")
                        else ", ".join(f"{k} {v}" for k, v in item.items() if k != source["tick"] and v))
                note["detail"] = f"{thing[2]}: {said}"
                if source.get("variant"):
                    note["variant"] = _fill(source["variant"], fields)
                values = {}
                for name, field in (source.get("values") or {}).items():
                    try:
                        values[name] = float(fields.get(field, ""))
                    except ValueError:
                        pass
                if values:
                    note["values"] = values
                found.append(note)
    return found, bool(ledger)


def gather(saved, folder, cache, indexer=None, environ=None, progress=None):
    """(notes, sources read): the notes from the newest saves the saved section names, each item once, from the oldest save
    holding it. sources read is one row per save: (name, notes, whether it held a ledger)."""
    sources, ledger_key, count = check_config(saved)
    chosen = list(reversed(saves.saves_in(folder)[:count]))     # oldest first, so an item keeps its first save
    seen, notes, read = set(), [], []
    for n, save in enumerate(chosen, 1):
        if progress:
            progress(f"Reading {save.name} for its saved histories", n, len(chosen))
        index, _ = saves.ensure(save, cache, indexer, environ)
        with closing(saves.open_read_only(index)) as conn:
            try:
                found, has_ledger = notes_from_save(conn, save, saves.read_meta(index), sources, ledger_key)
            except save_thing.ThingError:
                index, _ = saves.ensure(save, cache, indexer, environ, True)     # saved again while it was being read: once more
                with closing(saves.open_read_only(index)) as again:
                    found, has_ledger = notes_from_save(again, save, saves.read_meta(index), sources, ledger_key)
        fresh = 0
        for note in found:
            identity = (note["on"], note["key"], note.get("variant", ""), note["tick"])
            if identity not in seen:
                seen.add(identity)
                notes.append(note)
                fresh += 1
        read.append((save.name, fresh, has_ledger))
    return notes, read


def for_test_pass(saved, environ=None, settings_file=None, progress=None):
    """What test-pass calls (testpass_cli): the notes from the player's own Saves folder and the kit's index cache, found as every
    save tool finds them. Raises SavedError for a section that cannot be used, saves.SaveError when there is no Saves folder."""
    folder = paths.saves_path(None, environ, settings_file)
    cache = derived.folder(saves.CACHE_FOLDER, None, environ, settings_file)
    return gather(saved, folder, cache, None, environ, progress)
