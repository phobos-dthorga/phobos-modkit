"""The owner-run uploader: a verified candidate sent to the Workshop through Valve's SteamCMD.

Run by the owner only, in their own console. SteamCMD is started in that console with "+login <account>", so the
password and Steam Guard code are typed into SteamCMD's own prompt; this module never sees, stores or passes them.
Agents, tests and continuous integration never run a real upload: tests pass a stand-in for SteamCMD.

Rules, in order: an update with nothing new does nothing; the candidate must verify and match the source, the
catalogue and the operation; new items are created Private; anything wider than Private needs a candidate prepared
from committed work, and making an item Public for the first time needs confirm_public; blockers can be passed only
for a Private upload with acknowledge_hold, and a missing cover never; a create is refused while an earlier one is
unresolved, because a blind retry could make a duplicate. A receipt is written before SteamCMD starts, and SteamCMD's
exit code is never taken as proof: receipts end "unverified" until the owner checks the item.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
import os
from pathlib import Path
import shutil
import subprocess
import time

from ...files import inside, sha256
from .. import vdf
from . import stage
from .project import ITEM_ID, PublishError

PENDING, SUBMITTED, CREATED = "pending", "submitted-unverified", "created-unverified"
RECONCILED, NOT_CREATED = "reconciled-submitted", "reconciled-not-created"
OPEN = (PENDING, SUBMITTED)
STEAMCMD_ENV = "PHOBOS_STEAMCMD"
STEAMCMD_DEFAULT = Path("C:/steamcmd/steamcmd.exe")
STEAMCMD_GUIDE = "https://developer.valvesoftware.com/wiki/SteamCMD"
ITEM_URL = "https://steamcommunity.com/sharedfiles/filedetails/?id={item}"
# Receipts written by the PowerShell uploader this replaces named visibilities in title case.
VISIBILITY_ALIASES = {"private": "private", "friendsonly": "friends", "friends": "friends", "unlisted": "unlisted",
                      "public": "public"}


def visibility_name(value):
    return VISIBILITY_ALIASES.get(str(value or "private").lower(), "private")


def run_steamcmd(steamcmd, user, upload_file):
    """SteamCMD in this console, so its own password and Steam Guard prompts work. Returns its exit code."""
    return subprocess.run([str(steamcmd), "+login", user, "+workshop_build_item", str(upload_file), "+quit"]).returncode


@dataclass
class Request:
    mod: str
    operation: str                 # create or update
    visibility: str = None         # default: private for a create; the recorded visibility for an update
    candidate: str = None          # default: the newest candidate for the mod
    steam_user: str = None         # account name only, remembered locally; never a password
    steamcmd: str = None
    acknowledge_hold: bool = False
    confirm_public: bool = False
    what_if: bool = False
    force: bool = False


def write_json(path, value):
    Path(path).write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def read_receipt(folder):
    path = Path(folder) / "receipt.json"
    if not path.is_file():
        raise PublishError(f"No receipt.json in {folder}")
    return json.loads(path.read_text(encoding="utf-8-sig"))


def settings(project):
    path = project.path("settings")
    return json.loads(path.read_text(encoding="utf-8-sig")) if path.is_file() else {}


def find_steamcmd(explicit, saved, environ):
    for candidate in (explicit, environ.get(STEAMCMD_ENV), saved.get("SteamCmdPath"), shutil.which("steamcmd"),
                      STEAMCMD_DEFAULT if STEAMCMD_DEFAULT.is_file() else None):
        if candidate:
            return Path(candidate)
    return None


def newest_candidate(project, mod):
    folder = project.staging() / mod
    found = sorted((p for p in folder.iterdir() if p.is_dir()), key=lambda p: p.stat().st_mtime_ns,
                   reverse=True) if folder.is_dir() else []
    if not found:
        raise PublishError(f"No prepared candidate for {mod}. Prepare one first: steam-publish prepare {mod}")
    return found[0]


def open_creates(project, mod):
    folder = project.path("receipts") / mod
    if not folder.is_dir():
        return []
    return [d for d in sorted(folder.iterdir()) if d.is_dir() and (d / "receipt.json").is_file()
            and read_receipt(d).get("operation") == "create" and read_receipt(d).get("status") in OPEN]


def upload(project, request, say=print, run=run_steamcmd, now=datetime.now, environ=None):
    """Send one mod's candidate. Returns the receipt folder, or None when nothing was sent."""
    environ = os.environ if environ is None else environ
    mod = project.resolve(request.mod)
    operation = request.operation.lower()
    if operation not in ("create", "update"):
        raise PublishError("The operation is create or update")
    item = project.mods[mod]
    current, version = item.get("itemId"), project.info(mod).version
    recorded = item.get("uploadedVisibility")
    visibility = visibility_name(request.visibility) if request.visibility else (
        recorded if operation == "update" and recorded else "private")

    # 0. Nothing new: another upload would only repeat this version's change note.
    if operation == "update" and current and item.get("uploadedVersion") == version and recorded == visibility \
            and not request.force:
        say(f"{mod} {version} is already on Steam as {visibility}; nothing to upload. Raise the version for a new "
            "release, or force it to send it again.")
        return None

    # 1. The candidate: verified, current and matching the requested operation.
    candidate = Path(request.candidate).resolve() if request.candidate else newest_candidate(project, mod)
    manifest = stage.verify(candidate)
    if manifest["mod"] != mod:
        raise PublishError(f"The candidate is for {manifest['mod']}, not {mod}.")
    if manifest["operation"] != operation:
        raise PublishError(f"The candidate is prepared for {manifest['operation']}, not {operation}.")
    if current and not manifest["itemId"]:
        raise PublishError(f"{mod} already has item {current}. Prepare a fresh candidate, which updates it instead of "
                           "creating a duplicate.")
    if manifest["itemId"] and manifest["itemId"] != current:
        raise PublishError("The catalogue's item ID changed since this candidate was prepared. Prepare a fresh one.")
    if current and manifest["uploadedVersion"] != item.get("uploadedVersion"):
        raise PublishError("Another upload was recorded since this candidate was prepared, so its change note is out "
                           "of date. Prepare a fresh candidate.")
    if manifest["version"] != version:
        raise PublishError(f"The candidate is {manifest['version']} but the source is now {version}. Prepare a fresh one.")

    # 2. Publication rules.
    blockers = list(manifest["blockers"])
    waivable = [b for b in blockers if (item.get("hold") and b == item["hold"]) or "has no published item ID yet" in b]
    if blockers and (visibility != "private" or not request.acknowledge_hold or len(waivable) != len(blockers)):
        raise PublishError("Blocked: " + "; ".join(blockers) + ". Only a Private upload with acknowledge-hold may pass "
                           "holds or unpublished dependencies.")
    if visibility != "private":
        if operation == "create":
            raise PublishError("New items are created Private. Test a subscription, then update with the wider visibility.")
        if manifest["workingTreeDirty"]:
            raise PublishError("The candidate was prepared from uncommitted changes. Commit, then prepare a fresh one.")
        if visibility == "public" and recorded != "public" and not request.confirm_public:
            raise PublishError("Making an item Public needs confirm-public, after a successful private subscription test.")
    if operation == "update" and item.get("uploadedVersion") == version:
        why = f"a visibility change from {recorded}" if recorded != visibility else "force"
        say(f"Warning: {version} is already on Steam; sending it again for {why} adds another change note for it.")
    if operation == "create" and open_creates(project, mod):
        raise PublishError(f"An earlier create for {mod} is unresolved: {open_creates(project, mod)[0]}. Check your "
                           "Workshop items on Steam, then reconcile it with an item ID or as not created. A retry "
                           "could create a duplicate.")
    if manifest["workingTreeDirty"]:
        say("Warning: the candidate was prepared from uncommitted changes; acceptable only for a private test.")

    required = [f"{r['name']} ({r['itemId']})" if r["itemId"] else f"{r['name']} (not published yet)"
                for r in manifest["requiredItemDetails"]]
    say(f"Upload plan: {operation} {mod} {version} as {visibility}")
    say(f"Candidate: {candidate}")
    if manifest["itemId"]:
        say("Item: " + ITEM_URL.format(item=manifest["itemId"]))
    say("Required items to set on Steam afterwards: " + ("; ".join(required) or "none"))
    covers = "Change note covers: " + ", ".join(manifest["changeNoteVersions"])
    if manifest["changeNoteOmitted"]:
        covers += " (too long for Steam, so it points to CHANGELOG.md for " + ", ".join(manifest["changeNoteOmitted"]) + ")"
    say(covers)
    if blockers:
        say("Proceeding past (private, acknowledged): " + "; ".join(blockers))

    saved = settings(project)
    steamcmd = find_steamcmd(request.steamcmd, saved, environ)
    user = request.steam_user or saved.get("SteamUser")
    if not steamcmd or not steamcmd.is_file():
        raise PublishError(f"SteamCMD was not found. Install it ({STEAMCMD_GUIDE}) and pass --steamcmd once; it is "
                           "remembered locally.")
    if not user:
        raise PublishError("Pass --steam-user <account name> once; it is remembered locally. Never pass a password.")
    if request.what_if:
        say("What-if: no receipt written and SteamCMD not started.")
        return None

    # 3. The receipt, before contacting Steam. The candidate itself stays untouched.
    settings_file = project.path("settings")
    settings_file.parent.mkdir(parents=True, exist_ok=True)
    write_json(settings_file, {**saved, "SteamUser": user, "SteamCmdPath": steamcmd.as_posix()})
    started = now()
    receipt_dir = inside(project.root, project.path("receipts") / mod /
                         f"{started.strftime('%Y%m%d-%H%M%S')}-{version}-{operation}")
    receipt_dir.mkdir(parents=True)
    upload_file = receipt_dir / "upload.vdf"
    stage.upload_vdf(candidate, visibility, upload_file, started.date())
    receipt = {"schemaVersion": 1, "mod": mod, "version": version, "operation": operation, "visibility": visibility,
               "itemId": manifest["itemId"], "candidate": str(candidate), "sourceCommit": manifest["sourceCommit"],
               "manifestSha256": sha256((candidate / "manifest.json").read_bytes()),
               "acknowledgedBlockers": blockers, "startedAt": started.astimezone().isoformat(), "status": PENDING}
    write_json(receipt_dir / "receipt.json", receipt)

    # 4. SteamCMD in this console.
    say("Starting SteamCMD. Enter your password and Steam Guard code in its prompt if asked.")
    clock = time.time()
    receipt["steamCmdExitCode"] = run(steamcmd, user, upload_file)
    receipt["finishedAt"] = now().astimezone().isoformat()
    logs = steamcmd.parent / "logs"
    if logs.is_dir():
        kept = receipt_dir / "steamcmd-logs"
        for log in logs.iterdir():
            if log.is_file() and log.stat().st_mtime >= clock - 5:
                kept.mkdir(exist_ok=True)
                shutil.copy2(log, kept / log.name)

    # 5. SteamCMD writes a new item's ID back into the upload file. Its exit code alone is not proof.
    returned = vdf.item_id(upload_file.read_text(encoding="utf-8-sig"))
    receipt["status"] = SUBMITTED
    if operation == "create" and returned != "0":
        receipt["itemId"] = returned
        write_json(receipt_dir / "receipt.json", receipt)
        written = stage.record_item_id(project, mod, returned)
        stage.record_uploaded_version(project, mod, version, visibility)
        receipt["status"] = CREATED
        say(f"Steam returned item {returned}; recorded with version {version} in {', '.join(written)} (commit it).")
    elif operation == "create":
        say(f"Warning: no item ID came back. Check your Workshop items on Steam before anything else, then run: "
            f"steam-publish reconcile \"{receipt_dir}\" --item-id <id>   (or --not-created)")
    elif receipt["steamCmdExitCode"] == 0:
        # The next change note starts after this version. A failed run records nothing, so its versions are
        # described again next time.
        stage.record_uploaded_version(project, mod, version, visibility)
        say(f"Recorded version {version} ({visibility}) as uploaded in {project.rel(project.catalogue_path)} (commit it).")
    else:
        say(f"Warning: SteamCMD exited with code {receipt['steamCmdExitCode']}; version {version} was not recorded as "
            f"uploaded. Check the item on Steam; if the update did arrive, run: steam-publish reconcile "
            f"\"{receipt_dir}\" --item-id {receipt['itemId']}")
    write_json(receipt_dir / "receipt.json", receipt)
    say(f"Receipt: {receipt_dir}")
    if receipt["itemId"]:
        say("Next: open " + ITEM_URL.format(item=receipt["itemId"]) + " and check the title, description, change "
            "note, cover and visibility. Accept the Workshop legal agreement if Steam asks.")
        say("Set Required items (Owner controls > Add/Remove Required Items): " + ("; ".join(required) or "none"))
        for reminder in project.adapter.after_upload(project, mod):
            say(reminder)
    if visibility == "public":
        say(f"After confirming the public item, mark {version} Released with today's date in its changelog, update "
            "the page's Publication status and write the release notes again (or run steam-publish pull).")
    return receipt_dir


def reconcile(project, folder, item_id=None, not_created=False, now=datetime.now):
    """After an uncertain upload: record the item Steam shows, or that none was created. Returns the new status."""
    folder = Path(folder).resolve()
    receipt = read_receipt(folder)
    if receipt.get("status") not in OPEN:
        raise PublishError(f"The receipt is already {receipt.get('status')}.")
    if bool(item_id) == bool(not_created):
        raise PublishError("Give exactly one of --item-id (the item Steam shows) or --not-created.")
    mod = project.resolve(receipt["mod"])
    if item_id:
        if not ITEM_ID.fullmatch(item_id):
            raise PublishError("Item IDs are positive decimal numbers")
        if receipt["operation"] == "update" and item_id != receipt.get("itemId"):
            raise PublishError(f"This update was for item {receipt.get('itemId')}.")
        if receipt["operation"] == "create":
            stage.record_item_id(project, mod, item_id)
        stage.record_uploaded_version(project, mod, receipt["version"], visibility_name(receipt.get("visibility")))
        receipt.update(itemId=item_id, status=RECONCILED)
    else:
        receipt["status"] = NOT_CREATED
    receipt["reconciledAt"] = now().astimezone().isoformat()
    write_json(folder / "receipt.json", receipt)
    return receipt["status"]


def build(project, mod, run=subprocess.run):
    """The mod's build command (its catalogue entry's "build", else the layout's), if any, from the repository."""
    command = project.mods[mod].get("build") or project.layout["build"]
    if not command:
        return False
    if run([part.format(mod=mod) for part in command], cwd=project.root).returncode:
        raise PublishError(f"The build failed for {mod}; no candidate prepared.")
    return True


def update_all(project, mods=None, say=print, no_build=False, what_if=False, acknowledge_hold=False,
               steam_user=None, steamcmd=None, run=run_steamcmd, build_run=subprocess.run, environ=None):
    """Update only the items whose mod has a newer version than the one last uploaded, dependencies first.

    Each is built (unless no_build), prepared and sent as an update keeping its recorded visibility. Stops at the
    first failure or unrecorded upload. Returns the mods updated."""
    selected = set(project.select(mods)) if mods else None
    rows = [r for r in stage.pending(project) if selected is None or r["mod"] in selected]
    todo = [r for r in rows if r["needsUpload"]]
    for row in rows:
        if not row["itemId"]:
            say(f"Not on the Workshop yet: {row['mod']} {row['version']}. Create it with: steam-publish upload "
                f"{row['mod']} --create")
        elif not row["needsUpload"]:
            say(f"Up to date: {row['mod']} {row['version']} ({row['uploadedVisibility']})")
    for row in todo:
        say(f"To update: {row['mod']} {row['uploadedVersion'] or '(no version recorded)'} -> {row['version']}")
    if not todo:
        say("Nothing to update.")
        return []
    if what_if:
        say("What-if: nothing built, prepared or uploaded.")
        return []
    done = []
    for row in todo:
        say(f"--- {row['mod']} {row['version']}")
        if not no_build:
            build(project, row["mod"], build_run)
        stage.prepare(project, row["mod"])
        upload(project, Request(row["mod"], "update", steam_user=steam_user, steamcmd=steamcmd,
                                acknowledge_hold=acknowledge_hold), say, run, environ=environ)
        if project.mods[row["mod"]].get("uploadedVersion") != row["version"]:
            raise PublishError(f"{row['mod']} {row['version']} was not recorded as uploaded; check the item on Steam "
                               "before running this again.")
        done.append(f"{row['mod']} {row['version']}")
    say(f"Updated: {', '.join(done)}. Commit {project.rel(project.catalogue_path)}.")
    return done
