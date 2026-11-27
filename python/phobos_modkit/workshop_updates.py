"""Workshop items Steam has not brought up to date for a game, from Steam's own record of them (1.147.0).

Game-free. The owner's choice of 28 Nov 2026, "Workshop updates waiting", the last piece of retiring RimSort. Steam keeps a game's
Workshop items in `steamapps/workshop/appworkshop_<app id>.acf` (seen on the owner's PC, 28 Nov 2026): `WorkshopItemsInstalled`, each
item's files as they are on disk (its `manifest` and `timeupdated`), and `WorkshopItemDetails`, what Steam knows of it (its
`latest_manifest` and `latest_timeupdated`, and while it downloads `BytesDownloaded` of `BytesToDownload`); the record's
`NeedsUpdate` and `NeedsDownload` say whether any waits. An item is

- **waiting** when Steam knows a newer version than the one on disk and has not fetched it (Steam usually holds a game's Workshop
  updates while the game runs: Steam's usual behaviour, not confirmed here);
- **downloading** when part of it has come;
- **missing** when it is subscribed but none of it is on disk.

Reads one local file; nothing is sent. The record's account fields are never read out.
"""
from __future__ import annotations

WAITING, DOWNLOADING, MISSING = "waiting", "downloading", "missing"
STATE_WORDS = {WAITING: "a newer version waits", DOWNLOADING: "downloading", MISSING: "subscribed, not downloaded"}


def _int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def item_states(record):
    """[{workshop_id, state, installed_at, newest_at, downloaded, to_download}] for each item Steam has not brought up to date, in
    the record's order. Times are Unix seconds, 0 when the record gives none."""
    installed = record.get("WorkshopItemsInstalled") if isinstance(record.get("WorkshopItemsInstalled"), dict) else {}
    details = record.get("WorkshopItemDetails") if isinstance(record.get("WorkshopItemDetails"), dict) else {}
    found = []
    for item, detail in details.items():
        if not isinstance(detail, dict):
            continue
        have = installed.get(item) if isinstance(installed.get(item), dict) else None
        got, total = _int(detail.get("BytesDownloaded")), _int(detail.get("BytesToDownload"))
        newest_manifest = detail.get("latest_manifest") or detail.get("manifest") or ""
        newest = _int(detail.get("latest_timeupdated") or detail.get("timeupdated"))
        if have is None:
            state = MISSING
        elif total and got < total:
            state = DOWNLOADING
        elif (newest_manifest and have.get("manifest") and newest_manifest != have.get("manifest")) \
                or (newest and newest > _int(have.get("timeupdated"))):
            state = WAITING
        else:
            continue
        found.append({"workshop_id": str(item), "state": state, "installed_at": _int((have or {}).get("timeupdated")),
                      "newest_at": newest, "downloaded": got, "to_download": total})
    return found


def flags(record):
    """(needs an update, needs a download), as the record says for the game as a whole."""
    return _int(record.get("NeedsUpdate")) == 1, _int(record.get("NeedsDownload")) == 1
