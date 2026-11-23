"""The two ways an upload reaches Steam (1.98.0), behind one interface. Game-free.

The owner's choice of 23 Nov 2026, for D'thorga Companion's Publish page: "Both, chosen per upload": the running Steam client by
default, SteamCMD beside it. Both take the same verified candidate and write the same receipt; only the sending differs.

| | Steam client (`steam`) | SteamCMD (`steamcmd`) |
| --- | --- | --- |
| Login | The client already running and signed in; nothing asked | Typed into SteamCMD's own prompt, in its own console |
| Library | The game's own steam_api library, found from its install | Valve's SteamCMD, installed by the owner |
| Tags, Required items | Set | Not settable: reminders say what to set on Steam |
| Progress | Steam's own figures, as progress lines | SteamCMD's window |

Neither ever sees a password. **Only the owner's press or the owner's console runs either**; tests hand in stand-ins.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

from .. import client, vdf
from . import stage
from .project import PublishError

STEAMCMD_ENV = "PHOBOS_STEAMCMD"
STEAMCMD_DEFAULT = Path("C:/steamcmd/steamcmd.exe")
STEAMCMD_GUIDE = "https://developer.valvesoftware.com/wiki/SteamCMD"
CHOICES = ("steam", "steamcmd")
NEW_CONSOLE = getattr(subprocess, "CREATE_NEW_CONSOLE", 0)


@dataclass
class Outcome:
    """What a sender learnt from Steam. ok is the sender's own word, never proof: receipts stay unverified."""
    ok: bool
    item_id: str = None             # the item number Steam gave back for a create
    fields: dict = field(default_factory=dict)    # added to the receipt
    sets_extras: bool = False       # tags and Required items were set by the sender


def run_steamcmd(steamcmd, user, upload_file, new_console=False):
    """SteamCMD in this console, or in a console window of its own for a program (new_console), so its own password and
    Steam Guard prompts work and the program never sees them. Returns its exit code."""
    flags = NEW_CONSOLE if new_console and sys.platform == "win32" else 0
    return subprocess.run([str(steamcmd), "+login", user, "+workshop_build_item", str(upload_file), "+quit"],
                          creationflags=flags).returncode


def find_steamcmd(explicit, saved, environ):
    for candidate in (explicit, environ.get(STEAMCMD_ENV), saved.get("SteamCmdPath"), shutil.which("steamcmd"),
                      STEAMCMD_DEFAULT if STEAMCMD_DEFAULT.is_file() else None):
        if candidate:
            return Path(candidate)
    return None


class SteamCmd:
    name = "steamcmd"

    def __init__(self, run=run_steamcmd, new_console=False):
        self.run, self.new_console = run, new_console
        self.steamcmd = self.user = None

    def ready(self, project, request, saved, environ):
        """Checks before anything is written; returns the settings to remember (never a password)."""
        self.steamcmd = find_steamcmd(request.steamcmd, saved, environ)
        self.user = request.steam_user or saved.get("SteamUser")
        if not self.steamcmd or not self.steamcmd.is_file():
            raise PublishError(f"SteamCMD was not found. Install it ({STEAMCMD_GUIDE}) and pass --steamcmd once; it is "
                               "remembered locally.")
        if not self.user:
            raise PublishError("Pass --steam-user <account name> once; it is remembered locally. Never pass a password.")
        return {"SteamUser": self.user, "SteamCmdPath": self.steamcmd.as_posix()}

    def send(self, job, say):
        upload_file = job.receipt_dir / "upload.vdf"
        stage.upload_vdf(job.candidate, job.visibility, upload_file, job.started.date())
        say("Starting SteamCMD" + (" in its own window" if self.new_console else "") +
            ". Enter your password and Steam Guard code in its prompt if asked.")
        clock = time.time()
        code = self.run(self.steamcmd, self.user, upload_file, self.new_console) if self.new_console else \
            self.run(self.steamcmd, self.user, upload_file)
        logs = self.steamcmd.parent / "logs"
        if logs.is_dir():
            kept = job.receipt_dir / "steamcmd-logs"
            for log in logs.iterdir():
                if log.is_file() and log.stat().st_mtime >= clock - 5:
                    kept.mkdir(exist_ok=True)
                    shutil.copy2(log, kept / log.name)
        # SteamCMD writes a new item's number back into the upload file. Its exit code alone is not proof.
        returned = vdf.item_id(upload_file.read_text(encoding="utf-8-sig"))
        created = returned if returned != "0" else None
        return Outcome(ok=code == 0 if job.operation == "update" else bool(created), item_id=created,
                       fields={"steamCmdExitCode": code})


class SteamClient:
    name = "steam"

    def __init__(self, library=None, environ=None, find_install=None):
        self.library_factory = library          # tests: a stand-in taking the library's path
        self.environ = environ
        self.find_install = find_install
        self.path = None

    def ready(self, project, request, saved, environ):
        explicit = request.steam_library or environ.get("PHOBOS_STEAM_LIBRARY") or saved.get("SteamLibraryPath")
        if explicit:
            self.path = Path(explicit)
        else:
            install = (self.find_install or installed_game_folder)(project.config["appId"], environ)
            self.path = client.library_path(install) if install else None
        if (self.path is None or not self.path.is_file()) and self.library_factory is None:
            raise PublishError("The game's own Steam library (steam_api64.dll) was not found, so the Steam client cannot be "
                               "asked: is the game installed through Steam? Pass --steam-library, or send with SteamCMD.")
        return {"SteamLibraryPath": self.path.as_posix()} if explicit and self.path else {}

    def send(self, job, say):
        page, note = stage.published_text(*stage.candidate_texts(job.candidate), job.visibility, job.started.date())
        manifest, content = job.manifest, (job.candidate / "content").resolve()
        app, environ = manifest["appId"], self.environ if self.environ is not None else os.environ
        library = (self.library_factory or client.Library)(self.path)
        if hasattr(library, "bind_upload"):
            library.bind_upload()
        fields, item = {"via": self.name}, manifest["itemId"]
        say("Asking the Steam client, signed in on this PC; nothing is typed and no password is used.")
        with client.Session(library, app, environ) as steam:
            if job.operation == "create":
                say("Creating the item on the Workshop (always private at first).", progress=True)
                answer = steam.answer(library.create_item(steam.ugc, app), client.CreateItemResult,
                                      client.CREATE_ITEM_RESULT, client.UPLOAD_SECONDS)
                fields["createResult"] = answer.result if answer else None
                if not answer or answer.result != client.RESULT_OK or not answer.item:
                    return Outcome(False, fields=fields)
                item = str(answer.item)
                fields["needsAgreement"] = bool(answer.needs_agreement)
                job.on_created(item)
            page = stage.with_footer(page, manifest, item)
            handle = library.start_update(steam.ugc, app, item)
            folder = content / manifest["preview"]
            settings = [("Title", manifest["title"]), ("Description", page), ("Content", content), ("Preview", folder)]
            failed = [what for what, value in settings if not library.set_text(steam.ugc, handle, what, value)]
            if not library.set_visibility(steam.ugc, handle, vdf.VISIBILITY[job.visibility]):
                failed.append("Visibility")
            if manifest.get("tags") and not library.set_tags(steam.ugc, handle, manifest["tags"]):
                failed.append("Tags")
            if failed:
                fields["refused"] = failed
                say("Steam refused: " + ", ".join(failed) + ". Nothing was sent.")
                return Outcome(False, item_id=item if job.operation == "create" else None, fields=fields)
            last = [None]

            def tick():
                status, done, total = library.update_progress(steam.ugc, handle)
                words = client.UPDATE_STATUS.get(status)
                if words and (words, done) != last[0]:
                    last[0] = (words, done)
                    say(words + (f": {done:,} of {total:,} bytes" if total else ""), progress=True,
                        step=done if total else None, of=total or None)

            say("Uploading the files.", progress=True)
            answer = steam.answer(library.submit(steam.ugc, handle, note), client.SubmitItemUpdateResult,
                                  client.SUBMIT_ITEM_RESULT, client.UPLOAD_SECONDS, tick)
            fields["submitResult"] = answer.result if answer else None
            ok = bool(answer) and answer.result == client.RESULT_OK
            if answer and answer.needs_agreement:
                fields["needsAgreement"] = True
            if ok and manifest.get("requiredItems"):
                set_ = []
                for required in manifest["requiredItems"]:
                    done = steam.answer(library.add_dependency(steam.ugc, item, required), client.AddDependencyResult,
                                        client.ADD_DEPENDENCY_RESULT)
                    set_.append({"itemId": required, "result": done.result if done else None})
                fields["requiredItemsSet"] = set_
        if fields.get("needsAgreement"):
            say("Steam says the Workshop legal agreement must be accepted before others can see the item: open the item's "
                "page and accept it.")
        return Outcome(ok, item_id=item if job.operation == "create" else None, fields=fields, sets_extras=ok)


def installed_game_folder(app_id, environ=None):
    """The game's install folder from Steam's own records, or None."""
    from ...game_files import find_game, steam_root
    found = find_game(steam_root(environ), app_id=int(app_id))
    return Path(found["install"]) if found else None


def choose(via, run=run_steamcmd, library=None, environ=None, new_console=False, find_install=None):
    if via == "steamcmd":
        return SteamCmd(run, new_console)
    if via in (None, "steam"):
        return SteamClient(library, environ, find_install)
    raise PublishError(f"Send with one of {', '.join(CHOICES)}")
