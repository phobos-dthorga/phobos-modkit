"""rimworld-perf's look: inside the running game, from a snapshot (the kit's heap reader, `heap_reader`).

RimWorld 1.7 ships its own build of .NET (Waylith, Ludeon's engine) in its install folder, memory-reading library included; that
library is not signed by Microsoft, so the reader trusts it only because it sits beside the game's own coreclr.dll in the install
this adapter names. The overview is kept beside the gcdump heaps (`rimworld-heaps/`), so heap-report and heap-compare read both.

How an object is described: the first two of a pawn's names, a Def's defName and label, a thing's kind and ID (format facts
from RimWorld's own field names, in our words).
"""
from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
import sys

from ... import __version__
from ... import heap_reader as hr
from ...dotnet_snapshots import heap_owners
from ...sampling import UNKNOWN, Owner
from . import paths
from . import perf_snapshots as snap

# Field paths the reader follows to say which object this is; the first two it finds are shown. Pawn names (Verse.NameTriple's
# nick, first and last; NameSingle's name), then a Def's defName and label, then a thing's kind and ID, a hediff's load ID.
DESCRIBE = ("nameInt.nickInt", "nameInt.nameInt", "nameInt.firstInt", "defName", "def.defName", "label", "thingIDNumber",
            "loadID")
METHOD = "snapshot"
SURFACE = "look-inside"


def runtime_folder(game=None, environ=None, settings_file=None):
    """The game's install: where its coreclr.dll and its memory-reading library are."""
    return Path(paths.game_path(game, environ, settings_file))


def save_overview(heaps_root, ready, overview, label="", now=None):
    """Keep the overview as a heap beside the gcdump heaps; returns (folder, Heap)."""
    folder = snap.new_folder(heaps_root, label, now or datetime.now())
    heap = hr.heap_of(overview)
    (Path(folder) / snap.HEAP_DATA).write_text(heap.to_json(), encoding="utf-8")
    meta = {"kit_version": __version__, "taken_at": (now or datetime.now()).strftime("%Y-%m-%d %H:%M:%S"), "label": label or "",
            "pid": ready.get("pid"), "method": METHOD, "snapshot_ms": ready.get("snapshotMs"),
            "seconds": round((ready.get("snapshotMs") or 0) / 1000 + float(overview.get("seconds") or 0), 1),
            "free_bytes": overview.get("freeBytes"), "runtime_version": ready.get("runtime"), "runtime": {}}
    (Path(folder) / snap.META).write_text(json.dumps(meta, indent=1), encoding="utf-8")
    return folder, heap


def owners_data(heap, owner_map, top):
    """Who the heap belongs to and its largest types, as data for a program's page."""
    owners = heap_owners(heap, lambda module: owner_map.get(module) or Owner(UNKNOWN, module or "?"))
    totals = {}
    for t in heap.types:
        owner, _ = owners[(t.type, t.module)]
        entry = totals.setdefault(owner, [0, 0])
        entry[0] += t.bytes
        entry[1] += t.count
    by_owner = [{"name": o.name, "kind": o.kind, "bytes": b, "count": n}
                for o, (b, n) in sorted(totals.items(), key=lambda kv: (-kv[1][0], kv[0].name))]
    types = []
    for t in heap.types[:top]:
        owner, through = owners[(t.type, t.module)]
        types.append({"type": t.type, "module": t.module, "bytes": t.bytes, "count": t.count, "owner": owner.name,
                      "ownerKind": owner.kind, "through": through})
    return {"owners": by_owner, "types": types, "typeCount": len(heap.types)}


def refuse(message, stdout=None):
    """look-serve's one line when no snapshot can be taken (the game is not running), in the shape its first line always has."""
    stdout = stdout or sys.stdout
    stdout.write(json.dumps({"ready": False, "error": message}) + "\n")
    stdout.flush()
    return 1


def serve(pid, folder, heaps_root, owners_for, label="", limit_seconds=hr.LIMIT_SECONDS, top=200, stdin=None, stdout=None,
          session_class=hr.Session, now=None, checks_answer=None):
    """Hold a snapshot and answer one JSON request a line from stdin, one answer a line on stdout (the reader's requests). An
    overview's answer gains who each type belongs to, and is kept as a heap for heap-compare. `{"op": "checks"}` (1.123.0) runs
    every live check from the snapshot held: checks_answer(ask) gives its data, ask being one request to the held snapshot.
    Returns an exit code."""
    stdin, stdout = stdin or sys.stdin, stdout or sys.stdout

    def say(message):
        stdout.write(json.dumps(message) + "\n")
        stdout.flush()

    try:
        session = session_class(pid, folder, DESCRIBE, limit_seconds=limit_seconds)
    except (hr.LookError, hr.HeapReaderError, OSError) as error:
        return refuse(str(error), stdout)
    try:
        say(session.ready)
        for line in stdin:
            if not line.strip():
                continue
            given = None
            try:
                request = json.loads(line)
                given = request.pop("id", None)
                if request.get("op") == "checks":
                    if checks_answer is None:
                        raise ValueError("These tools have no live checks to run.")
                    answer = {"ok": True, "data": checks_answer(session.ask)}
                else:
                    answer = session.ask(request)
                if request.get("op") == "overview" and answer.get("ok"):
                    data = answer["data"]
                    kept, heap = save_overview(heaps_root, session.ready, data, label, now)
                    owner_map, notes = owners_for(sorted({t.module for t in heap.types}))
                    answer["data"] = {key: data[key] for key in ("totalObjects", "totalBytes", "freeBytes", "untyped", "seconds")}
                    answer["data"].update(owners_data(heap, owner_map, top), kept=Path(kept).name, notes=notes)
            except hr.LookError as error:
                say({"ok": False, "error": str(error), "id": given, "released": True})
                return 0
            except (ValueError, KeyError, OSError, snap.SnapshotsError) as error:
                answer = {"ok": False, "error": str(error)}
            if given is not None:
                answer["id"] = given
            say(answer)
            if answer.get("released"):
                break
    finally:
        session.close()
    return 0
