"""Offline staging: a candidate folder per upload, checked and hashed, and the catalogue records an upload writes.

No network, login or upload happens here. A candidate is a fresh folder in the staging area holding content/ (what
the item will hold), manifest.json (version, title, commit, blockers, sizes and a SHA-256 hash of every file) and
workshop.vdf.draft. The uploader re-verifies every hash before it uses one.
"""
from __future__ import annotations

from datetime import date
import json
from pathlib import Path
import re
import uuid

from ...files import is_link, read_tree, sha256
from ...release.changelog import parse, version_key
from .. import vdf
from . import notes
from .project import ITEM_ID, VERSION, PublishError

MANIFEST_FORMAT = 3
PAGE_FILE, NOTE_FILE = "Workshop-page.bbcode", "Release-notes.bbcode"
PUBLIC_STATUS = "[b]Publication status:[/b] Public on the Steam Workshop"
UNPUBLISHED_STATUS = re.compile(r"(?m)^\[b\]Publication status:\[/b\] Not published\b.*$")
DRAFT_HEADING = re.compile(r"(?m)^\[b\]Draft - not published \| \d{4}-\d{2}-\d{2}\[/b\]$")


def change_note(project, mod, version, uploaded):
    """Steam's change note: every changelog version after the one last uploaded, newest first, up to this one.

    A first upload, or a repeat of the same version, carries this version alone. Versions that would push the note
    past Steam's limit are named in a closing line instead, oldest left out first. Returns (bytes, covered, omitted).
    """
    releases = parse(project.path("changelog", mod).read_text(encoding="utf-8-sig"))
    since = version_key(uploaded or version)
    versions = sorted((v for v in releases if since < version_key(v) <= version_key(version)),
                      key=version_key, reverse=True) or [version]
    texts = []
    for release in versions:
        _, outputs = notes.plan(project, [mod], release)
        before, after = next(iter(outputs.values()))
        if before != after:
            raise PublishError(f"{mod}: generated release notes are stale; write them again")
        texts.append(after)

    def closing(left):
        span = left[0] if len(left) == 1 else f"{left[-1]} to {left[0]}"
        word = "version" if len(left) == 1 else "versions"
        return f"Earlier changes in {word} {span} are listed in CHANGELOG.md, which comes with the mod.\n".encode()

    for count in range(len(texts), 0, -1):
        note = b"\n".join(texts[:count]) + (b"\n" + closing(versions[count:]) if count < len(texts) else b"")
        if len(note) <= vdf.TEXT_MAX_BYTES or count == 1:
            return note, versions[:count], versions[count:]


def plan(project, mod):
    """(manifest, payload) for mod's next candidate, after every check; nothing is written."""
    item = project.mods[mod]
    info = project.info(mod)
    uploaded = item.get("uploadedVersion") if item.get("itemId") else None
    note, covered, omitted = change_note(project, mod, info.version, uploaded)
    page = project.path("page", mod).read_bytes()
    page_text = page.decode("utf-8-sig")
    vdf.limit("Workshop title", info.title.encode("utf-8"), vdf.TITLE_MAX_BYTES)
    vdf.limit("Workshop page description", page_text.encode("utf-8"), vdf.TEXT_MAX_BYTES)
    vdf.limit("Release change note", note, vdf.TEXT_MAX_BYTES)
    vdf.quote(page_text)
    vdf.quote(note.decode("utf-8"))
    payload = project.payload(mod)
    if not payload:
        raise PublishError(f"{mod}: the content is empty")
    folder = project.layout["textFolder"]
    if folder:
        payload[f"{folder}/{PAGE_FILE}"] = page
        payload[f"{folder}/{NOTE_FILE}"] = note
    blockers = [item["hold"]] if item.get("hold") else []
    preview, budget = project.preview(), project.layout["previewMaxBytes"]
    if preview not in payload:
        blockers.append(f"No cover at {preview}; add one before upload")
    elif len(payload[preview]) >= budget:
        blockers.append(f"{preview} is {len(payload[preview]):,} bytes, over the {budget:,}-byte cover budget")
    names = project.config.get("externalRequiredItemNames", {})
    required_ids = list(project.config.get("externalRequiredItems", []))
    required = [{"name": names[i], "itemId": i} for i in required_ids]
    for dependency in item.get("requires", []):
        dependency_id = project.mods[dependency].get("itemId")
        required.append({"name": dependency, "itemId": dependency_id})
        if dependency_id:
            required_ids.append(dependency_id)
        else:
            blockers.append(f"{dependency} has no published item ID yet; publish it first")
    manifest = {"format": MANIFEST_FORMAT, "mod": mod, "title": info.title, "version": info.version,
                "appId": str(project.config["appId"]), "itemId": item.get("itemId"),
                "operation": "update" if item.get("itemId") else "create", "preview": preview,
                "blockers": blockers, "requiredItems": required_ids, "requiredItemDetails": required,
                "uploadedVersion": uploaded, "changeNoteVersions": covered, "changeNoteOmitted": omitted,
                "sizes": {"titleBytes": len(info.title.encode("utf-8")), "descriptionBytes": len(page),
                          "changeNoteBytes": len(note)},
                "files": {p: sha256(data) for p, data in sorted(payload.items())}}
    return manifest, payload, page_text, note.decode("utf-8")


def draft_values(manifest, target, title, description, note, visibility="private"):
    content = Path(target) / "content"
    return {"appid": manifest["appId"], "publishedfileid": manifest["itemId"] or "0",
            "contentfolder": content.resolve().as_posix(),
            "previewfile": (content / manifest["preview"]).resolve().as_posix(),
            "visibility": str(vdf.VISIBILITY[visibility]), "title": title, "description": description,
            "changenote": note}


def prepare(project, mod):
    """Stage a fresh candidate; returns (folder, manifest). Older candidates are kept."""
    manifest, payload, page, note = plan(project, mod)
    target = project.staging() / mod / f"{manifest['version']}-{uuid.uuid4().hex[:12]}"
    target.mkdir(parents=True, exist_ok=False)
    for name, data in payload.items():
        output = target / "content" / name
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(data)
    (target / PAGE_FILE).write_text(page, encoding="utf-8", newline="\n")
    (target / NOTE_FILE).write_text(note, encoding="utf-8", newline="\n")
    draft = vdf.workshop_item(draft_values(manifest, target, manifest["title"], page, note)).encode("utf-8")
    (target / "workshop.vdf.draft").write_bytes(draft)
    manifest.update(vdfSha256=sha256(draft), pageSha256=sha256(page.encode()), noteSha256=sha256(note.encode()),
                    sourceCommit=project.commit(), workingTreeDirty=project.dirty())
    (target / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    verify(target)
    return target, manifest


def verify(target):
    """The candidate's manifest after re-hashing every file; raises when anything changed."""
    target = Path(target)
    if is_link(target) or not (target / "manifest.json").is_file():
        raise PublishError(f"Not a prepared candidate: {target}")
    manifest = json.loads((target / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("format") != MANIFEST_FORMAT:
        raise PublishError("The candidate was prepared by another version of the tool; prepare a fresh one")
    actual = {p: sha256(data) for p, data in read_tree(target / "content").items()}
    texts = {"vdfSha256": "workshop.vdf.draft", "pageSha256": PAGE_FILE, "noteSha256": NOTE_FILE}
    if actual != manifest["files"] or any(sha256((target / f).read_bytes()) != manifest[k] for k, f in texts.items()):
        raise PublishError("The candidate's files changed; prepare a fresh candidate")
    return manifest


def published_text(page, note, visibility, today=None):
    """The page and change note as a public upload sends them: a Not published status line reads public, and Draft
    headings read Released on the upload date. Other visibilities send the text unchanged."""
    if visibility != "public":
        return page, note
    released = f"[b]Released | {(today or date.today()).isoformat()}[/b]"
    page = UNPUBLISHED_STATUS.sub(lambda _: PUBLIC_STATUS, page)
    note = DRAFT_HEADING.sub(lambda _: released, note)
    vdf.limit("Workshop page description", page.encode("utf-8"), vdf.TEXT_MAX_BYTES)
    vdf.limit("Release change note", note.encode("utf-8"), vdf.TEXT_MAX_BYTES)
    return page, note


def upload_vdf(target, visibility, output, today=None):
    """Write the upload file for a verified candidate; the candidate stays unchanged. Returns its hash."""
    if visibility not in vdf.VISIBILITY:
        raise PublishError("Visibility must be private, friends, unlisted or public")
    manifest = verify(target)
    target = Path(target)
    page, note = published_text((target / PAGE_FILE).read_text(encoding="utf-8"),
                                (target / NOTE_FILE).read_text(encoding="utf-8"), visibility, today)
    data = vdf.workshop_item(draft_values(manifest, target, manifest["title"], page, note, visibility)).encode("utf-8")
    output = Path(output)
    if output.exists():
        raise PublishError("The upload file already exists; use a fresh receipt folder")
    output.write_bytes(data)
    return sha256(data)


def status(project):
    """Each mod, dependencies first: package readiness, blockers and sizes. Read-only."""
    rows = []
    for name in project.order():
        item = project.mods[name]
        try:
            manifest = plan(project, name)[0]
            row = {"mod": name, "version": manifest["version"], "itemId": item.get("itemId"),
                   "operation": manifest["operation"], "package": "ready", "blockers": manifest["blockers"],
                   "sizes": manifest["sizes"]}
        except (ValueError, OSError, KeyError, IndexError) as error:
            row = {"mod": name, "itemId": item.get("itemId"), "package": "not ready", "error": str(error),
                   "blockers": [item["hold"]] if item.get("hold") else []}
        row["requires"] = item.get("requires", [])
        rows.append(row)
    return rows


def pending(project):
    """Which items need an upload: those whose mod's version differs from the version last uploaded. Read-only."""
    rows = []
    for name in project.order():
        item = project.mods[name]
        version = project.info(name).version
        rows.append({"mod": name, "version": version, "itemId": item.get("itemId"),
                     "uploadedVersion": item.get("uploadedVersion"), "uploadedVisibility": item.get("uploadedVisibility"),
                     "needsUpload": bool(item.get("itemId")) and item.get("uploadedVersion") != version})
    return rows


def record_item_id(project, mod, item_id):
    """Save the item ID Steam assigned, once the owner has seen the item exist. Returns the files written."""
    if not ITEM_ID.fullmatch(item_id or ""):
        raise PublishError("Item IDs are positive decimal numbers")
    current = project.mods[mod].get("itemId")
    if current == item_id:
        return []
    if current is not None:
        raise PublishError(f"{mod} already has item {current}; correct the catalogue by hand if Steam disagrees")
    if any(m.get("itemId") == item_id for m in project.mods.values()) or \
            item_id in project.config.get("externalRequiredItems", []):
        raise PublishError("That item ID already belongs to another entry")
    project.mods[mod]["itemId"] = item_id
    written = project.adapter.item_recorded(project, mod, item_id)
    project.save()
    return [project.rel(project.catalogue_path), *written]


def record_uploaded_version(project, mod, version, visibility=None):
    """Save the version (and visibility) just sent, so the next change note starts after it and an update with
    nothing new is skipped. Returns True when the catalogue changed."""
    if not VERSION.fullmatch(version or ""):
        raise PublishError("Uploaded versions are numbers like 1.2.3")
    if visibility is not None and visibility not in vdf.VISIBILITY:
        raise PublishError("Visibility must be private, friends, unlisted or public")
    item = project.mods[mod]
    if not item.get("itemId"):
        raise PublishError(f"{mod} has no item ID; record the item before its uploaded version")
    visibility = visibility or item.get("uploadedVisibility")
    if item.get("uploadedVersion") == version and item.get("uploadedVisibility") == visibility:
        return False
    item["uploadedVersion"] = version
    if visibility:
        item["uploadedVisibility"] = visibility
    project.save()
    return True
