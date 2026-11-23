"""What a program's Publish page reads and writes (1.99.0, for D'thorga Companion). Game-free.

- `page`: a mod's Workshop page as text, with every problem the checks find, its size and budget; `--check` checks a text
  without writing; `--write` saves it, only when it has no problems.
- `show`: everything one mod's card shows: the change note Steam would get next, the tags and Required items it would set,
  blockers, sizes, the item and what was last sent, and each upload's receipt, newest first.

Reading changes nothing; `--write` writes only the page file.
"""
from __future__ import annotations

import json

from ...files import atomic_write
from . import notes, stage
from .project import PublishError

ITEM_URL = "https://steamcommunity.com/sharedfiles/filedetails/?id={item}"


def starter(info):
    """A new page's first lines: the three lines every page needs."""
    return (f"[h1]{info.title}[/h1]\n[b]Version:[/b] {info.version}\n"
            "[b]Publication status:[/b] Not published yet\n\nWhat it does, in plain words.\n")


def page_info(project, mod, text=None):
    """The page (or text, when given) with its problems. A missing page is offered as a starter, not written."""
    info = project.info(mod)
    path = project.path("page", mod)
    exists = path.is_file()
    if text is None:
        text = path.read_text(encoding="utf-8-sig") if exists else starter(info)
    text = text.replace("\r\n", "\n")
    return {"mod": mod, "path": project.rel(path), "exists": exists, "text": text, "title": info.title,
            "version": info.version, "bytes": len(text.encode("utf-8")), "budget": project.layout["pageMaxBytes"],
            "problems": notes.page_problems(project, mod, info.title, info.version, text)}


def page_write(project, mod, text):
    """Save the page when it has no problems; returns its info. The release notes it feeds are not rewritten here."""
    found = page_info(project, mod, text)
    if found["problems"]:
        raise PublishError(f"{mod}: not saved: " + "; ".join(found["problems"]))
    path = project.path("page", mod)
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write(path, found["text"].encode("utf-8"))
    found["exists"] = True
    return found


def receipts(project, mod):
    """Each upload's receipt for mod, newest first."""
    folder = project.path("receipts") / mod
    found = []
    for receipt in sorted(folder.glob("*/receipt.json"), reverse=True) if folder.is_dir() else []:
        try:
            data = json.loads(receipt.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            continue
        found.append({"folder": receipt.parent.name, **{k: data.get(k) for k in (
            "version", "operation", "visibility", "via", "status", "itemId", "startedAt", "finishedAt", "needsAgreement")}})
    return found


def show(project, mod):
    """One mod's card, read-only. A mod whose package is not ready says why in error and shows the rest."""
    item = project.mods[mod]
    found = {"mod": mod, "itemId": item.get("itemId"), "uploadedVersion": item.get("uploadedVersion"),
             "uploadedVisibility": item.get("uploadedVisibility"), "hold": item.get("hold"),
             "requires": item.get("requires", []), "itemUrl": ITEM_URL.format(item=item["itemId"]) if item.get("itemId")
             else None, "receipts": receipts(project, mod), "reminders": project.adapter.after_upload(project, mod)}
    try:
        info = project.info(mod)
        found.update(title=info.title, version=info.version, tags=list(info.tags))
        manifest, _, _, note = stage.plan(project, mod)
        found.update(operation=manifest["operation"], blockers=manifest["blockers"], sizes=manifest["sizes"],
                     requiredItems=manifest["requiredItemDetails"], changeNote=note,
                     changeNoteVersions=manifest["changeNoteVersions"], changeNoteOmitted=manifest["changeNoteOmitted"],
                     preview=manifest["preview"], files=len(manifest["files"]))
        found["due"] = bool(item.get("itemId")) and item.get("uploadedVersion") != info.version
    except (ValueError, OSError, KeyError, IndexError) as error:
        found["error"] = str(error)
    return found
