"""Worksheets for tidying each Workshop item's Change Notes tab by hand.

Steam offers no way for a tool to edit or delete a change note (ISteamUGC and SteamCMD only add one per upload); the
item's owner can edit each entry's text in the Change Notes tab. This rebuilds every item's entries from the upload
receipts, which keep the exact text and time of each upload, and suggests replacement text where an entry is untidy:

- an upload that sent a version the item already had (a re-send or a visibility change) becomes a one-line pointer
  to that version's entry;
- a "Draft - not published" heading, on an item now public, says how that version really went up: Released for a
  public upload, Uploaded privately otherwise.

Entries come newest first, as Steam lists them. Never contacts Steam.
"""
from __future__ import annotations

from datetime import datetime
import json
import re

from ..vdf import change_note
from .upload import CREATED, RECONCILED, SUBMITTED, read_receipt, visibility_name

REACHED = {CREATED, SUBMITTED, RECONCILED}
DRAFT = re.compile(r"(?m)^\[b\]Draft - not published \| \d{4}-\d{2}-\d{2}\[/b\]$")
CHANGELOG_URL = "https://steamcommunity.com/sharedfiles/filedetails/changelog/{item}"


def entries(project, mod):
    """Every upload of mod that reached Steam (SteamCMD exited 0, or the owner reconciled it), oldest first."""
    found = []
    folder = project.path("receipts") / mod
    for directory in sorted(folder.iterdir()) if folder.is_dir() else []:
        upload_file = directory / "upload.vdf"
        if not (directory / "receipt.json").is_file() or not upload_file.is_file():
            continue
        receipt = read_receipt(directory)
        if receipt.get("status") not in REACHED or (receipt.get("status") != RECONCILED
                                                    and receipt.get("steamCmdExitCode") not in (0, None)):
            continue
        note = change_note(upload_file.read_text(encoding="utf-8-sig"))
        if note is None:
            continue
        found.append({"time": datetime.fromisoformat(receipt["startedAt"]), "version": receipt["version"],
                      "visibility": visibility_name(receipt.get("visibility")), "operation": receipt.get("operation"),
                      "receipt": directory.name, "sent": note})
    return sorted(found, key=lambda e: e["time"])


def suggest(items, now_public):
    """Mark each entry (oldest first) keep or replace, with any replacement text."""
    seen = {}
    for entry in items:
        version, when = entry["version"], entry["time"].strftime("%d %B %Y").lstrip("0")
        if version in seen:
            reason = (f"to make the item {entry['visibility']}" if entry["visibility"] != seen[version]["visibility"]
                      else "again with no changes")
            entry["replacement"] = f"Version {version} sent {reason} on {when}. Its changes are in the {version} entry below."
            entry["why"] = "repeats a version the item already had"
        elif now_public and DRAFT.search(entry["sent"]):
            label = "Released" if entry["visibility"] == "public" else "Uploaded privately"
            entry["replacement"] = DRAFT.sub(lambda _: f"[b]{label} | {entry['time'].date().isoformat()}[/b]", entry["sent"])
            entry["why"] = "says Draft - not published on an item that is now public"
        seen.setdefault(version, entry)
    return items


def worksheet(mod, item_id, items):
    lines = [f"# {mod} change notes", "", "Item: " + CHANGELOG_URL.format(item=item_id), "",
             "Steam lists change notes newest first, each headed by its update time. Sign in as the",
             "item owner, open the Change Notes tab and edit each entry marked Replace: paste the text",
             "under it in place of the entry text. Entries marked Keep need nothing.", ""]
    for number, entry in enumerate(reversed(items), 1):
        stamp = entry["time"].strftime("%d %b %Y %H:%M").lstrip("0")
        action = "Replace" if "replacement" in entry else "Keep"
        lines += [f"## {number}. {stamp}: {entry['version']}, {entry['visibility']} {entry['operation']} - {action}", ""]
        if "replacement" in entry:
            lines += [f"Why: it {entry['why']}.", "", "```text", entry["replacement"].rstrip("\n"), "```", ""]
    if not items:
        lines.append("No uploads recorded in this checkout.")
    return "\n".join(lines).rstrip("\n") + "\n"


def run(project, mods=None, write=True):
    """Rows of (mod, entries, entries to replace, worksheet path) for every selected mod with an item."""
    rows = []
    for mod in project.select(mods, default=[m for m in project.order() if project.mods[m].get("itemId")]):
        item = project.mods[mod]
        if not item.get("itemId"):
            continue
        items = suggest(entries(project, mod), item.get("uploadedVisibility") == "public")
        path = project.path("worksheets") / f"{mod}.md"
        if write:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(worksheet(mod, item["itemId"], items), encoding="utf-8", newline="\n")
        rows.append((mod, len(items), sum("replacement" in e for e in items), project.rel(path)))
    return rows
