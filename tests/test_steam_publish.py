"""Workshop publishing on a made-up RimWorld repository: notes, staging, the uploader against a stand-in for SteamCMD,
reconciling, updating every due item, pulling from a stand-in for Steam's API, and change-note worksheets.

Nothing here reaches Steam: SteamCMD is a function that edits the upload file as SteamCMD would, and the Web API is a
function returning a hand-written answer. Mods, names and item IDs are made up."""
from datetime import datetime, timedelta
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

import support  # noqa: F401
from phobos_modkit.games import publish_adapters
from phobos_modkit.games.ostranauts.publish import Ostranauts
from phobos_modkit.steam import vdf
from phobos_modkit.steam.publish import cli, notes, pull, stage, upload, worksheets
from phobos_modkit.steam.publish.project import Project, PublishError

NEW_ID, BASE_ID = "3900000001", "3900000002"
ABOUT = """<?xml version="1.0" encoding="utf-8"?>
<ModMetaData>
  <packageId>Example.{mod}</packageId>
  <name>Example {mod}</name>
  <modVersion>{version}</modVersion>
</ModMetaData>
"""
CHANGELOG = """# Example {mod} changelog

## [Unreleased]

## [0.3.0] - 2026-11-08 - Draft

### Added

- Third: a "quoted" word.

## [0.2.0] - 2026-11-05 - Draft

- Second.

## [0.1.0] - 2026-11-01 - Released

- First.
"""
PAGE = """[h1]Example {mod}[/h1]
[b]Version:[/b] {version}
[b]Publication status:[/b] Not published yet

What it does.
"""


def git(root, *args):
    return subprocess.run(["git", "-c", "core.fsmonitor=false", *args], cwd=root, check=True, capture_output=True)


class Clock:
    def __init__(self):
        self.time = datetime(2026, 11, 8, 9, 0, 0)

    def __call__(self):
        self.time += timedelta(minutes=1)
        return self.time


class SteamCmd:
    """Stands in for SteamCMD: records each call and writes back an item ID for a create, as SteamCMD does."""
    def __init__(self, returns=NEW_ID, code=0):
        self.calls, self.returns, self.code = [], returns, code

    def __call__(self, steamcmd, user, upload_file):
        self.calls.append(Path(upload_file).read_text(encoding="utf-8"))
        text = Path(upload_file).read_text(encoding="utf-8")
        if self.returns:
            Path(upload_file).write_text(text.replace('"publishedfileid" "0"', f'"publishedfileid"\t\t"{self.returns}"'),
                                         encoding="utf-8")
        return self.code


class Publishing(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "repo"
        self.cache = Path(self.tmp.name) / "cache"
        self.steamcmd = Path(self.tmp.name) / "steamcmd" / "steamcmd.exe"
        self.steamcmd.parent.mkdir()
        self.steamcmd.write_bytes(b"stand-in")
        for mod in ("Base", "Content"):
            self.write(f"mods/{mod}/About/About.xml", ABOUT.format(mod=mod, version="0.3.0"))
            self.write(f"mods/{mod}/About/Preview.png", "not really a picture")
            self.write(f"mods/{mod}/1.7/Defs/Things.xml", "<Defs />\n")
            self.write(f"mods/{mod}/CHANGELOG.md", CHANGELOG.format(mod=mod))
            self.write(f"workshop/{mod}/page.bbcode", PAGE.format(mod=mod, version="0.3.0"))
        self.catalogue = {"appId": "294100", "layout": {"exclude": ["*.record.md"]}, "mods": {
            "Base": {"itemId": None, "requires": [], "hold": None},
            "Content": {"itemId": None, "requires": ["Base"], "hold": None}}}
        self.write("config/workshop-publishing.json", json.dumps(self.catalogue, indent=2) + "\n")
        self.write(".gitignore", ".local/\n")
        git(self.root, "init", "-q")
        git(self.root, "config", "user.email", "test@example.com")
        git(self.root, "config", "user.name", "Test")
        git(self.root, "config", "core.autocrlf", "false")
        self.project = self.load()
        notes.run(self.project, write=True)
        self.commit()
        self.clock = Clock()
        self.lines = []

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, name, text):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")

    def commit(self):
        git(self.root, "add", "-A")
        git(self.root, "commit", "-q", "-m", "change", "--allow-empty")

    def load(self):
        return Project.load(self.root, publish_adapters(), cache_folder=self.cache)

    def upload(self, mod, operation, steam=None, **options):
        steam = steam or SteamCmd()
        request = upload.Request(mod, operation, steam_user="example", steamcmd=str(self.steamcmd), **options)
        return upload.upload(self.project, request, self.lines.append, steam, self.clock, environ={}), steam

    def catalogue_now(self):
        return json.loads((self.root / "config/workshop-publishing.json").read_text(encoding="utf-8"))["mods"]

    # ---- notes ----

    def test_notes_check_write_and_refusals(self):
        self.assertEqual(notes.run(self.project)[0], "valid")
        generated = self.root / "workshop/Base/releases/0.3.0.bbcode"
        text = generated.read_text(encoding="utf-8")
        self.assertTrue(text.startswith("[h1]Example Base 0.3.0[/h1]\n[b]Draft - not published | 2026-11-08[/b]"))
        self.assertIn("“quoted”", text)
        self.assertIn("[b]Released | 2026-11-01[/b]", (self.root / "workshop/Base/releases/0.1.0.bbcode").read_text(encoding="utf-8"))
        generated.write_text("stale", encoding="utf-8")
        self.assertEqual(notes.run(self.project)[0], "stale")
        out = io.StringIO()
        self.assertEqual(cli.main(["notes", "--check", "--root", str(self.root), "--cache", str(self.cache)], out=out), 1)
        self.assertEqual(notes.run(self.project, write=True)[0], "written")
        (self.root / "workshop/Base/releases/9.9.9.bbcode").write_text("orphan", encoding="utf-8")
        with self.assertRaisesRegex(PublishError, "no changelog entry: 9.9.9"):
            notes.run(self.project)
        (self.root / "workshop/Base/releases/9.9.9.bbcode").unlink()
        for page, message in ((PAGE.format(mod="Base", version="0.2.0"), "Version:"),
                              (PAGE.format(mod="Other", version="0.3.0"), "heading"),
                              (PAGE.format(mod="Base", version="0.3.0").replace("Not published yet", ""), "Publication"),
                              (PAGE.format(mod="Base", version="0.3.0") + "x" * 8000, "budget"),
                              (PAGE.format(mod="Base", version="0.3.0") + 'a "quote"\n', "double quotes")):
            self.write("workshop/Base/page.bbcode", page)
            with self.subTest(message), self.assertRaisesRegex(PublishError, message):
                notes.run(self.project)

    def test_changed_content_needs_its_records(self):
        self.write("mods/Base/1.7/Defs/Things.xml", "<Defs><!-- changed --></Defs>\n")
        with self.assertRaisesRegex(PublishError, "Base: changed content needs"):
            notes.run(self.project, base="HEAD")
        self.write("mods/Base/CHANGELOG.md", CHANGELOG.format(mod="Base").replace("Third:", "Third,"))
        self.write("workshop/Base/page.bbcode", PAGE.format(mod="Base", version="0.3.0") + "More.\n")
        notes.run(self.project, write=True, base="HEAD")
        with self.assertRaisesRegex(PublishError, "commit"):
            notes.run(self.project, base="no-such-ref")

    # ---- staging ----

    def test_prepare_verify_and_blockers(self):
        folder, manifest = stage.prepare(self.project, "Base")
        self.assertTrue(folder.is_relative_to(self.cache))
        self.assertEqual((manifest["operation"], manifest["version"], manifest["blockers"]), ("create", "0.3.0", []))
        self.assertEqual(manifest["changeNoteVersions"], ["0.3.0"])
        self.assertIn("About/Preview.png", manifest["files"])
        self.assertFalse(manifest["workingTreeDirty"])
        self.assertEqual(stage.verify(folder)["mod"], "Base")
        (folder / "content/1.7/Defs/Things.xml").write_text("tampered", encoding="utf-8")
        with self.assertRaisesRegex(PublishError, "changed"):
            stage.verify(folder)
        content = stage.plan(self.project, "Content")[0]
        self.assertEqual(content["blockers"], ["Base has no published item ID yet; publish it first"])
        (self.root / "mods/Base/About/Preview.png").unlink()
        self.project.mods["Base"]["hold"] = "Held: awaiting play checks"
        self.assertEqual(stage.plan(self.project, "Base")[0]["blockers"],
                         ["Held: awaiting play checks", "No cover at About/Preview.png; add one before upload"])

    def test_change_note_covers_every_version_since_the_last_upload(self):
        note, covered, omitted = stage.change_note(self.project, "Base", "0.3.0", "0.1.0")
        self.assertEqual((covered, omitted), (["0.3.0", "0.2.0"], []))
        self.assertLess(note.index(b"0.3.0"), note.index(b"0.2.0"))
        with mock.patch.object(vdf, "TEXT_MAX_BYTES", 200):
            note, covered, omitted = stage.change_note(self.project, "Base", "0.3.0", "0.1.0")
        self.assertEqual((covered, omitted), (["0.3.0"], ["0.2.0"]))
        self.assertIn(b"Earlier changes in version 0.2.0 are listed in CHANGELOG.md", note)

    def test_public_text_reads_published(self):
        page, note = stage.published_text(PAGE.format(mod="Base", version="0.3.0"),
                                          "[b]Draft - not published | 2026-11-08[/b]\n", "public",
                                          datetime(2026, 11, 9).date())
        self.assertIn("[b]Publication status:[/b] Public on the Steam Workshop", page)
        self.assertEqual(note, "[b]Released | 2026-11-09[/b]\n")
        self.assertEqual(stage.published_text("a", "b", "private"), ("a", "b"))

    # ---- uploading ----

    def test_create_records_the_item_and_the_game_file(self):
        stage.prepare(self.project, "Base")
        receipt, steam = self.upload("Base", "create")
        self.assertEqual(len(steam.calls), 1)
        sent = steam.calls[0]
        self.assertIn('"publishedfileid" "0"', sent)
        self.assertIn('"visibility" "2"', sent)
        self.assertIn('"appid" "294100"', sent)
        self.assertEqual(self.catalogue_now()["Base"],
                         {"itemId": NEW_ID, "requires": [], "hold": None, "uploadedVersion": "0.3.0",
                          "uploadedVisibility": "private"})
        self.assertEqual((self.root / "mods/Base/About/PublishedFileId.txt").read_text(encoding="utf-8"), NEW_ID)
        record = json.loads((receipt / "receipt.json").read_text(encoding="utf-8"))
        self.assertEqual((record["status"], record["itemId"]), (upload.CREATED, NEW_ID))
        saved = json.loads((self.root / ".local/workshop-settings.json").read_text(encoding="utf-8"))
        self.assertEqual(saved["SteamUser"], "example")
        self.assertNotIn("password", json.dumps(saved).lower())
        self.assertTrue(any("tags" in line for line in self.lines))
        # Nothing new: no SteamCMD, no receipt.
        self.project = self.load()
        result, steam = self.upload("Base", "update")
        self.assertIsNone(result)
        self.assertEqual(steam.calls, [])

    def test_publication_rules(self):
        stage.prepare(self.project, "Base")
        for options, message in (({"visibility": "public"}, "created Private"),):
            with self.subTest(message), self.assertRaisesRegex(PublishError, message):
                self.upload("Base", "create", **options)
        with self.assertRaisesRegex(PublishError, "prepared for create"):
            self.upload("Base", "update")
        self.upload("Base", "create")
        self.project = self.load()
        self.write("mods/Base/About/About.xml", ABOUT.format(mod="Base", version="0.3.0") + "<!-- edit -->\n")
        stage.prepare(self.project, "Base")
        with self.assertRaisesRegex(PublishError, "uncommitted"):
            self.upload("Base", "update", visibility="public")
        self.commit()
        stage.prepare(self.project, "Base")
        with self.assertRaisesRegex(PublishError, "confirm-public"):
            self.upload("Base", "update", visibility="public")
        receipt, steam = self.upload("Base", "update", visibility="public", confirm_public=True)
        self.assertIn('"visibility" "0"', steam.calls[0])
        self.assertIn("Public on the Steam Workshop", steam.calls[0])
        self.assertIn("[b]Released | 2026-11-08[/b]", steam.calls[0])
        self.assertEqual(self.catalogue_now()["Base"]["uploadedVisibility"], "public")
        self.assertTrue(any("warning" in line.lower() and "already on Steam" in line for line in self.lines))

    def test_blockers_pass_only_privately_with_acknowledgement(self):
        stage.prepare(self.project, "Content")
        with self.assertRaisesRegex(PublishError, "Blocked: Base has no published"):
            self.upload("Content", "create")
        receipt, _ = self.upload("Content", "create", acknowledge_hold=True)
        self.assertEqual(json.loads((receipt / "receipt.json").read_text(encoding="utf-8"))["acknowledgedBlockers"],
                         ["Base has no published item ID yet; publish it first"])

    def test_uncertain_create_must_be_reconciled(self):
        stage.prepare(self.project, "Base")
        receipt, _ = self.upload("Base", "create", steam=SteamCmd(returns=None))
        self.assertIsNone(self.catalogue_now()["Base"]["itemId"])
        self.assertTrue(any("no item ID came back" in line for line in self.lines))
        with self.assertRaisesRegex(PublishError, "unresolved"):
            self.upload("Base", "create")
        with self.assertRaisesRegex(PublishError, "exactly one"):
            upload.reconcile(self.project, receipt)
        self.assertEqual(upload.reconcile(self.project, receipt, item_id=NEW_ID), upload.RECONCILED)
        self.assertEqual(self.catalogue_now()["Base"]["itemId"], NEW_ID)
        with self.assertRaisesRegex(PublishError, "already"):
            upload.reconcile(self.project, receipt, not_created=True)

    def test_failed_update_records_nothing(self):
        stage.prepare(self.project, "Base")
        self.upload("Base", "create")
        self.project = self.load()
        self.write("mods/Base/About/About.xml", ABOUT.format(mod="Base", version="0.3.0"))
        stage.prepare(self.project, "Base")
        receipt, _ = self.upload("Base", "update", force=True, steam=SteamCmd(returns=None, code=5))
        self.assertTrue(any("exited with code 5" in line for line in self.lines))
        self.assertEqual(json.loads((receipt / "receipt.json").read_text(encoding="utf-8"))["status"], upload.SUBMITTED)

    def test_what_if_writes_nothing(self):
        stage.prepare(self.project, "Base")
        result, steam = self.upload("Base", "create", what_if=True)
        self.assertIsNone(result)
        self.assertEqual(steam.calls, [])
        self.assertFalse((self.root / ".local").exists())
        with self.assertRaisesRegex(PublishError, "SteamCMD was not found"):
            upload.upload(self.project, upload.Request("Base", "create", steam_user="x",
                                                       steamcmd=str(self.steamcmd) + ".missing"), self.lines.append,
                          SteamCmd(), self.clock, environ={})

    def test_update_every_due_item(self):
        for mod in ("Base", "Content"):
            self.project.mods[mod]["itemId"] = NEW_ID if mod == "Base" else BASE_ID
            self.project.mods[mod].update(uploadedVersion="0.2.0", uploadedVisibility="public")
        self.project.mods["Content"]["uploadedVersion"] = "0.3.0"
        self.project.save()
        self.project.layout["build"] = ["build-tool", "{mod}"]
        built = []
        build = lambda command, cwd: built.append(command) or subprocess.CompletedProcess(command, 0)
        self.assertEqual(upload.update_all(self.project, say=self.lines.append, what_if=True), [])
        self.assertEqual(built, [])
        steam = SteamCmd(returns=None)
        done = upload.update_all(self.project, say=self.lines.append, steamcmd=str(self.steamcmd), steam_user="example",
                                 run=steam, build_run=build, environ={})
        self.assertEqual(done, ["Base 0.3.0"])
        self.assertEqual(built, [["build-tool", "Base"]])
        self.assertIn("Up to date: Content 0.3.0 (public)", self.lines)
        self.assertIn('"visibility" "0"', steam.calls[0])
        self.assertIn("[h1]Example Base 0.3.0[/h1]", steam.calls[0])
        self.assertNotIn("[h1]Example Base 0.2.0[/h1]", steam.calls[0])
        self.assertEqual(self.catalogue_now()["Base"]["uploadedVersion"], "0.3.0")

    # ---- pulling and worksheets ----

    def test_pull_from_steam(self):
        self.project.mods["Base"].update(itemId=NEW_ID, uploadedVersion="0.3.0", uploadedVisibility="private")
        self.project.save()
        live_page = PAGE.format(mod="Base", version="0.3.0").replace("Not published yet", "Public since 9 November 2026")
        updated = int(datetime(2026, 11, 9, 10, 0).timestamp())
        answer = {"response": {"publishedfiledetails": [
            {"publishedfileid": NEW_ID, "result": 1, "visibility": 0, "time_updated": updated,
             "description": live_page.replace("\n", "\r\n")}]}}
        post = lambda url, data: (200, json.dumps(answer).encode())
        rows, changes = pull.plan(self.project, None, set(pull.AREAS), post)
        self.assertEqual(rows[0]["changes"], ["Visibility: private -> public",
                                              "Page description: replaced by the live Steam text",
                                              "Changelog: 0.3.0 marked Released on 2026-11-09 (when Steam last updated the item)"])
        self.assertEqual(len(changes), 3)
        self.assertFalse((self.root / "workshop/Base/page.bbcode").read_text(encoding="utf-8").count("Public since"))
        pull.apply(self.project, changes)
        self.assertIn("## [0.3.0] - 2026-11-09 - Released", (self.root / "mods/Base/CHANGELOG.md").read_text(encoding="utf-8"))
        self.assertIn("[b]Released | 2026-11-09[/b]", (self.root / "workshop/Base/releases/0.3.0.bbcode").read_text(encoding="utf-8"))
        self.assertEqual(self.catalogue_now()["Base"]["uploadedVisibility"], "public")
        hidden = {"response": {"publishedfiledetails": [{"publishedfileid": NEW_ID, "result": 9}]}}
        rows, changes = pull.plan(self.project, None, set(pull.AREAS), lambda u, d: (200, json.dumps(hidden).encode()))
        self.assertEqual(changes, {})
        self.assertIn("does not show this item", rows[0]["notes"][0])

    def test_change_note_worksheets(self):
        stage.prepare(self.project, "Base")
        self.upload("Base", "create")
        self.project = self.load()
        stage.prepare(self.project, "Base")
        self.commit()
        stage.prepare(self.project, "Base")
        self.upload("Base", "update", visibility="public", confirm_public=True)
        rows = worksheets.run(self.project)
        self.assertEqual(rows, [("Base", 2, 2, ".local/workshop-change-notes/Base.md")])
        sheet = (self.root / ".local/workshop-change-notes/Base.md").read_text(encoding="utf-8")
        self.assertIn("Version 0.3.0 sent to make the item public on 8 November 2026.", sheet)
        self.assertIn("[b]Uploaded privately | 2026-11-08[/b]", sheet)

    # ---- adapters, catalogue and command line ----

    def test_catalogue_and_adapter_checks(self):
        self.write("mods/Base/About/PublishedFileId.txt", "3999999999")
        with self.assertRaisesRegex(PublishError, "game's own uploader"):
            self.load()
        (self.root / "mods/Base/About/PublishedFileId.txt").unlink()
        self.write("mods/Extra/About/About.xml", ABOUT.format(mod="Extra", version="1.0.0"))
        with self.assertRaisesRegex(PublishError, "missing Extra"):
            self.load()
        self.assertEqual(self.project.resolve("content"), "Content")
        with self.assertRaisesRegex(PublishError, "Unknown mod"):
            self.project.resolve("Nothing")
        self.assertEqual(self.project.order(), ["Base", "Content"])

    def test_ostranauts_metadata(self):
        folder = Path(self.tmp.name) / "ostranauts"
        folder.mkdir()
        (folder / "mod_info.json").write_text(json.dumps([{"strName": "Example", "strModVersion": "1.2.3"}]))
        info = Ostranauts().read(folder)
        self.assertEqual((info.title, info.version), ("Example", "1.2.3"))

    def test_command_line_reports(self):
        out = io.StringIO()
        args = ["--root", str(self.root), "--cache", str(self.cache)]
        self.assertEqual(cli.main(["status", *args], out=out), 0)
        self.assertIn("Publication order, dependencies first: Base, Content.", out.getvalue())
        self.assertIn("Content: Base has no published item ID yet", out.getvalue())
        out = io.StringIO()
        self.assertEqual(cli.main(["pending", *args, "--json"], out=out), 0)
        self.assertEqual(json.loads(out.getvalue())["lines"], ["0 of 2 items need an upload."])
        out = io.StringIO()
        self.assertEqual(cli.main(["prepare", "Base", *args], out=out), 0)
        self.assertIn("# Candidate prepared (offline)", out.getvalue())
        out = io.StringIO()
        self.assertEqual(cli.main(["upload", "Base", "--create", "--what-if", "--steam-user", "x", "--steamcmd",
                                   str(self.steamcmd), *args], out=out, run=SteamCmd(), environ={}), 0)
        self.assertIn("What-if: no receipt written", out.getvalue())
        out = io.StringIO()
        self.assertEqual(cli.main(["upload", "Nothing", "--update", *args], out=out), 1)
        self.assertIn("Unknown mod: Nothing", out.getvalue())


if __name__ == "__main__":
    unittest.main()
