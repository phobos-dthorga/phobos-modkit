"""Bring the repository's Workshop records up to date with what Steam shows: the reverse of an upload.

Reads each item's live state from Valve's GetPublishedFileDetails Web API, with no key or login, and for the chosen
areas plans changes to the repository:

    visibility    the item's visibility, as its uploadedVisibility in the catalogue
    description   the page file, from the item's live description
    changelog     the uploaded version's entry marked Released on a public item, dated by Steam's last update

Nothing is written unless write=True. Steam answers only for items anyone can see: a private or friends-only item
reads as not found, and its records are left alone.
"""
from __future__ import annotations

from datetime import datetime
import json
import re

from ...files import atomic_write
from ...release.changelog import mark_released
from .. import workshop
from ..vdf import VISIBILITY_NAMES
from . import notes

AREAS = ("visibility", "description", "changelog")
FOUND = 1  # EResult OK; anything else (usually 9, file not found) means Steam would not show the item


def steam_page(description):
    """Steam's description in the repository's form: LF line endings and one closing newline."""
    return description.replace("\r\n", "\n").rstrip() + "\n"


def plan(project, mods, areas, post=workshop.http_post):
    """(rows, changes): a row per mod with its changes and notes, and {path: (text now, text planned)}."""
    selected = project.select(mods, default=[m for m in project.order() if project.mods[m].get("itemId")])
    ids = [project.mods[m]["itemId"] for m in selected if project.mods[m].get("itemId")]
    details = {i.id: i for i in workshop.fetch_details(ids, post)} if ids else {}
    rows, changes = [], {}
    catalogue = json.loads(json.dumps(project.config))
    for name in selected:
        item = project.mods[name]
        row = {"mod": name, "itemId": item.get("itemId"), "changes": [], "notes": []}
        rows.append(row)
        if not item.get("itemId"):
            row["notes"].append("Not on the Workshop yet; nothing to pull.")
            continue
        live = details.get(item["itemId"])
        if live is None or live.result != FOUND:
            row["notes"].append("Steam does not show this item to the public (private, friends-only or removed); "
                                "its records are left as they are.")
            continue
        visibility = VISIBILITY_NAMES.get(live.visibility)
        # Local time, as the owner sees the date: in Australia a morning release is the day before in UTC.
        updated = datetime.fromtimestamp(live.time_updated).date().isoformat()
        version = project.info(name).version
        row.update(visibility=visibility, updated=updated)
        if visibility == "public" and item.get("hold"):
            row["notes"].append(f"Public on Steam but held in the catalogue ({item['hold']}). Lift the hold if intended.")
        if "visibility" in areas and visibility and item.get("uploadedVisibility") != visibility:
            catalogue["mods"][name]["uploadedVisibility"] = visibility
            row["changes"].append(f"Visibility: {item.get('uploadedVisibility')} -> {visibility}")
        if "description" in areas:
            path = project.path("page", name)
            before, after = path.read_text(encoding="utf-8-sig"), steam_page(live.description)
            if after != before:
                shown = re.search(r"(?m)^\[b\]Version:\[/b\] (\S+)$", after)
                if project.layout["pageRules"].get("version") and (not shown or shown[1] != version):
                    row["notes"].append(f"Steam describes version {shown[1] if shown else '(none)'} but the source is "
                                        f"{version}; the page was not pulled, so a newer page is not overwritten.")
                else:
                    changes[path] = (before, after)
                    row["changes"].append("Page description: replaced by the live Steam text")
        uploaded = item.get("uploadedVersion")
        if "changelog" in areas and visibility == "public" and uploaded:
            path = project.path("changelog", name)
            before = changes.get(path, (None, path.read_text(encoding="utf-8-sig")))[1]
            after = mark_released(before, uploaded, updated)
            if after:
                changes[path] = (before, after)
                row["changes"].append(f"Changelog: {uploaded} marked Released on {updated} (when Steam last updated "
                                      "the item)")
    if catalogue != project.config:
        changes[project.catalogue_path] = (project.catalogue_path.read_text(encoding="utf-8-sig"),
                                           json.dumps(catalogue, indent=2, ensure_ascii=False) + "\n")
    return rows, changes


def apply(project, changes):
    """Write the planned files, then write the release notes of every changed changelog again."""
    for path, (_, after) in changes.items():
        atomic_write(path, after.encode("utf-8"))
    if project.catalogue_path in changes:
        project.config = json.loads(project.catalogue_path.read_text(encoding="utf-8"))
        project.validate()
    changed = [m for m in project.mods if project.path("changelog", m) in changes]
    if changed:
        state, _, _ = notes.run(project, changed, write=True)
        if notes.run(project, changed)[0] != "valid":
            raise ValueError("Release notes did not regenerate cleanly; check them with steam-publish notes")
