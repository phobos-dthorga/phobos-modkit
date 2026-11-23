"""Uploading through the Steam client (1.98.0), against a stand-in library. Nothing here speaks to a real Steam.

The stand-in answers as Steamworks would: CreateItem gives a new number, SubmitItemUpdate reports progress and then its result,
AddDependency sets each Required item. The structure layout test holds the one place the tools assume Valve's layout."""
import ctypes
import io
import json
import sys
import unittest

import support  # noqa: F401
from phobos_modkit.progress import Progress
from phobos_modkit.steam import client
from phobos_modkit.steam.publish import cli, senders, stage, upload
from phobos_modkit.steam.publish.project import PublishError

import test_steam_publish as base

BASE_ID, NEW_ID, Publishing = base.BASE_ID, base.NEW_ID, base.Publishing


class Answer:
    def __init__(self, **fields):
        self.__dict__.update(fields)


class FakeUgc:
    """Stands in for the Steamworks library: every call succeeds unless told otherwise."""

    def __init__(self, path=None, create=NEW_ID, submit=client.RESULT_OK, refuse=(), agreement=False):
        self.create, self.submit_result, self.refuse, self.agreement = create, submit, set(refuse), agreement
        self.calls, self.sets, self.ticks, self.shut = [], {}, 0, False

    def bind_upload(self):
        self.calls.append("bind")

    def init(self):
        return 0, ""

    def shutdown(self):
        self.shut = True

    def pump(self):
        pass

    def ugc(self):
        return 1

    def utils(self):
        return 2

    def completed(self, utils, call):
        self.ticks += 1
        return self.ticks % 2 == 0, False     # done on every second look, so progress is read in between

    def create_item(self, ugc, app):
        self.calls.append(("create", int(app)))
        return 501

    def start_update(self, ugc, app, item):
        self.calls.append(("start", int(item)))
        return 77

    def set_text(self, ugc, handle, what, value):
        self.sets[what] = str(value)
        return what not in self.refuse

    def set_visibility(self, ugc, handle, visibility):
        self.sets["Visibility"] = visibility
        return True

    def set_tags(self, ugc, handle, tags):
        self.sets["Tags"] = list(tags)
        return True

    def submit(self, ugc, handle, note):
        self.calls.append(("submit", note))
        return 502

    def update_progress(self, ugc, handle):
        return 3, 500, 1000

    def add_dependency(self, ugc, parent, child):
        self.calls.append(("dependency", int(parent), int(child)))
        return 503

    def call_result(self, utils, call, structure, callback):
        if callback == client.CREATE_ITEM_RESULT:
            return Answer(result=client.RESULT_OK if self.create else 2, item=int(self.create or 0),
                          needs_agreement=self.agreement)
        if callback == client.SUBMIT_ITEM_RESULT:
            return Answer(result=self.submit_result, needs_agreement=self.agreement, item=0)
        return Answer(result=client.RESULT_OK, parent=0, child=0)


class ClientSending(unittest.TestCase):
    setUp, tearDown, write, commit, load, catalogue_now = (Publishing.setUp, Publishing.tearDown, Publishing.write,
                                                          Publishing.commit, Publishing.load, Publishing.catalogue_now)

    def send(self, mod, operation, fake=None, **options):
        fake = fake or FakeUgc()
        sender = senders.SteamClient(library=lambda path: fake, environ={}, find_install=lambda app, environ: None)
        request = upload.Request(mod, operation, via="steam", **options)
        receipt = upload.upload(self.project, request, self.lines.append, now=self.clock, environ={}, sender=sender)
        return receipt, fake

    def test_create_sets_everything_and_records_the_item(self):
        stage.prepare(self.project, "Base")
        receipt, fake = self.send("Base", "create")
        self.assertEqual(fake.calls[:3], ["bind", ("create", 294100), ("start", int(NEW_ID))])
        self.assertEqual(fake.sets["Title"], "Example Base")
        self.assertIn("[h1]Example Base[/h1]", fake.sets["Description"])
        self.assertTrue(fake.sets["Content"].endswith("content"))
        self.assertTrue(fake.sets["Preview"].replace("\\", "/").endswith("content/About/Preview.png"))
        self.assertEqual(fake.sets["Visibility"], 2)              # always private at first
        self.assertEqual(fake.sets["Tags"], ["Mod"])
        self.assertTrue(fake.shut)
        self.assertEqual(self.catalogue_now()["Base"]["itemId"], NEW_ID)
        self.assertEqual(self.catalogue_now()["Base"]["uploadedVersion"], "0.3.0")
        self.assertEqual((self.root / "mods/Base/About/PublishedFileId.txt").read_text(), NEW_ID)
        saved = json.loads((receipt / "receipt.json").read_text())
        self.assertEqual((saved["status"], saved["via"], saved["tags"]), ("created-unverified", "steam", ["Mod"]))
        self.assertFalse(any("Set Required items" in line for line in self.lines))   # the client sets them

    def test_required_items_are_set_on_steam(self):
        stage.prepare(self.project, "Base")
        self.send("Base", "create")
        self.commit()
        self.project = self.load()
        stage.prepare(self.project, "Content")
        _, fake = self.send("Content", "create", FakeUgc(create=BASE_ID))
        self.assertIn(("dependency", int(BASE_ID), int(NEW_ID)), fake.calls)

    def test_a_failed_submit_keeps_the_new_item_but_not_the_version(self):
        stage.prepare(self.project, "Base")
        receipt, _ = self.send("Base", "create", FakeUgc(submit=2))
        self.assertEqual(self.catalogue_now()["Base"]["itemId"], NEW_ID)
        self.assertNotIn("uploadedVersion", self.catalogue_now()["Base"])
        self.assertTrue(any("did not go up" in line for line in self.lines))
        self.assertEqual(json.loads((receipt / "receipt.json").read_text())["status"], "submitted-unverified")

    def test_no_number_back_means_reconcile_first(self):
        stage.prepare(self.project, "Base")
        self.send("Base", "create", FakeUgc(create=None))
        self.assertIsNone(self.catalogue_now()["Base"]["itemId"])
        stage.prepare(self.project, "Base")
        with self.assertRaisesRegex(PublishError, "unresolved"):
            self.send("Base", "create")

    def test_a_refused_setting_sends_nothing(self):
        stage.prepare(self.project, "Base")
        _, fake = self.send("Base", "create", FakeUgc(refuse={"Preview"}))
        self.assertFalse(any(c[0] == "submit" for c in fake.calls if isinstance(c, tuple)))
        self.assertTrue(any("Steam refused: Preview" in line for line in self.lines))

    def test_legal_agreement_is_said(self):
        stage.prepare(self.project, "Base")
        receipt, _ = self.send("Base", "create", FakeUgc(agreement=True))
        self.assertTrue(json.loads((receipt / "receipt.json").read_text())["needsAgreement"])
        self.assertTrue(any("legal agreement" in line for line in self.lines))

    def test_progress_lines_for_a_program(self):
        stream = io.StringIO()
        fake = FakeUgc()
        stage.prepare(self.project, "Base")
        sender = senders.SteamClient(library=lambda path: fake, environ={}, find_install=lambda app, environ: None)
        upload.upload(self.project, upload.Request("Base", "create", via="steam"), self.lines.append, now=self.clock,
                      environ={}, sender=sender, progress=Progress({"PHOBOS_MODKIT_PROGRESS": "1"}, stream))
        lines = [json.loads(line) for line in stream.getvalue().splitlines()]
        self.assertIn({"progress": 1, "label": "Uploading the files: 500 of 1,000 bytes", "step": 500, "of": 1000}, lines)

    def test_no_library_found_is_said_before_anything_is_written(self):
        stage.prepare(self.project, "Base")
        sender = senders.SteamClient(environ={}, find_install=lambda app, environ: None)
        with self.assertRaisesRegex(PublishError, "Steam library"):
            upload.upload(self.project, upload.Request("Base", "create", via="steam"), self.lines.append,
                          now=self.clock, environ={}, sender=sender)
        self.assertFalse((self.root / ".local/workshop-receipts").exists())

    def test_command_line_defaults_to_the_steam_client(self):
        where = ["--root", str(self.root), "--cache", str(self.cache)]
        self.assertEqual(cli.main(["prepare", "Base", *where], out=io.StringIO(), environ={}), 0)
        out = io.StringIO()
        fake = FakeUgc()
        sender = senders.SteamClient(library=lambda path: fake, environ={}, find_install=lambda app, environ: None)
        code = cli.main(["upload", "Base", "--create", *where], out=out, environ={}, sender=sender)
        self.assertEqual(code, 0)
        self.assertIn("Sending with: the Steam client", out.getvalue())
        self.assertEqual(self.catalogue_now()["Base"]["itemId"], NEW_ID)

    def test_choose(self):
        self.assertIsInstance(senders.choose("steam"), senders.SteamClient)
        self.assertIsInstance(senders.choose("steamcmd"), senders.SteamCmd)
        with self.assertRaises(PublishError):
            senders.choose("carrier pigeon")


class Layout(unittest.TestCase):
    """Valve's answer structures, as the headers lay them out (8-byte packing on Windows, 4 on Linux and macOS)."""

    def test_structures(self):
        large = sys.platform not in ("linux", "darwin")
        self.assertEqual(client.CreateItemResult.item.offset, 8 if large else 4)
        self.assertEqual(ctypes.sizeof(client.CreateItemResult), 24 if large else 16)
        self.assertEqual(client.SubmitItemUpdateResult.needs_agreement.offset, 4)
        self.assertEqual(client.SubmitItemUpdateResult.item.offset, 8)
        self.assertEqual(ctypes.sizeof(client.SubmitItemUpdateResult), 16)
        self.assertEqual(client.AddDependencyResult.child.offset, 16 if large else 12)

    def test_tags_array(self):
        lib = client.Library.__new__(client.Library)
        seen = {}

        def set_tags(ugc, handle, array, admin):
            value = array._obj
            seen["tags"] = [value.strings[i].decode() for i in range(value.count)]
            return True

        lib.SteamAPI_ISteamUGC_SetItemTags = set_tags
        self.assertTrue(lib.set_tags(1, 2, ["Mod", "1.7"]))
        self.assertEqual(seen["tags"], ["Mod", "1.7"])


if __name__ == "__main__":
    unittest.main()
