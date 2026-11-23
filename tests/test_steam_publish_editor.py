"""What a Publish page reads and writes (1.99.0): the Workshop page with every problem, saving it only without problems, and
one mod's card. Made-up mods; nothing reaches Steam."""
import io
import json
import unittest

import support  # noqa: F401
from phobos_modkit.steam.publish import cli, editor, stage, upload
from phobos_modkit.steam.publish.project import PublishError

import test_steam_publish as base


class Stdin:
    def __init__(self, text):
        self.buffer = io.BytesIO(text.encode("utf-8"))


class Editing(unittest.TestCase):
    setUp, tearDown, write, commit, load, catalogue_now, upload = (
        base.Publishing.setUp, base.Publishing.tearDown, base.Publishing.write, base.Publishing.commit,
        base.Publishing.load, base.Publishing.catalogue_now, base.Publishing.upload)

    def run_cli(self, *args, stdin=None):
        out = io.StringIO()
        code = cli.main([*args, "--root", str(self.root), "--cache", str(self.cache), "--json"], out=out, environ={},
                        stdin=stdin)
        return code, json.loads(out.getvalue())

    def test_page_reads_with_its_size(self):
        code, answer = self.run_cli("page", "Base")
        self.assertEqual(code, 0)
        data = answer["data"]
        self.assertEqual((data["path"], data["exists"], data["problems"]), ("workshop/Base/page.bbcode", True, []))
        self.assertEqual(data["bytes"], len(data["text"].encode()))
        self.assertEqual(data["budget"], 7500)

    def test_every_problem_at_once(self):
        text = '[h1]Wrong[/h1]\n[b]Version:[/b] 9.9.9\nA "quote" and [blink]x[/blink]\n'
        code, answer = self.run_cli("page", "Base", "--check", "--stdin", stdin=Stdin(text))
        self.assertEqual(code, 1)
        problems = answer["data"]["problems"]
        self.assertEqual(len(problems), 5, problems)   # tag, quotes, version, heading, status
        self.assertEqual((self.root / "workshop/Base/page.bbcode").read_text(), base.PAGE.format(mod="Base", version="0.3.0"))

    def test_save_only_without_problems(self):
        good = base.PAGE.format(mod="Base", version="0.3.0") + "\nMore, with “typographic” quotes.\r\n"
        code, answer = self.run_cli("page", "Base", "--write", "--stdin", stdin=Stdin(good))
        self.assertEqual(code, 0)
        self.assertEqual((self.root / "workshop/Base/page.bbcode").read_bytes(), good.replace("\r\n", "\n").encode())
        code, answer = self.run_cli("page", "Base", "--write", "--stdin", stdin=Stdin("[h1]Nope[/h1]\n"))
        self.assertEqual(code, 1)
        self.assertIn("not saved", answer["report"]["lines"][0])
        self.assertEqual((self.root / "workshop/Base/page.bbcode").read_bytes(), good.replace("\r\n", "\n").encode())

    def test_a_missing_page_is_offered_as_a_starter(self):
        (self.root / "workshop/Base/page.bbcode").unlink()
        found = editor.page_info(self.project, "Base")
        self.assertFalse(found["exists"])
        self.assertEqual(found["problems"], [])
        self.assertTrue(found["text"].startswith("[h1]Example Base[/h1]\n[b]Version:[/b] 0.3.0\n"))
        self.assertFalse((self.root / "workshop/Base/page.bbcode").exists())

    def test_show_a_new_and_an_uploaded_item(self):
        code, answer = self.run_cli("show", "Content")
        data = answer["data"]
        self.assertEqual((code, data["operation"], data["tags"]), (0, "create", ["Mod"]))
        self.assertEqual(data["requiredItems"], [{"name": "Base", "itemId": None}])
        self.assertIn("Base has no published item ID yet; publish it first", data["blockers"])
        self.assertIn("[h1]Example Content 0.3.0[/h1]", data["changeNote"])
        stage.prepare(self.project, "Base")
        self.upload("Base", "create")
        self.commit()
        found = editor.show(self.load(), "Base")
        self.assertEqual((found["itemId"], found["uploadedVersion"], found["due"]), (base.NEW_ID, "0.3.0", False))
        self.assertEqual(found["receipts"][0]["status"], "created-unverified")
        self.assertEqual(found["receipts"][0]["via"], "steamcmd")
        self.assertTrue(found["itemUrl"].endswith(base.NEW_ID))

    def test_status_and_pending_carry_data(self):
        code, answer = self.run_cli("status")
        self.assertEqual([m["mod"] for m in answer["data"]["mods"]], ["Base", "Content"])
        self.assertEqual(answer["data"]["appId"], "294100")
        code, answer = self.run_cli("pending")
        self.assertEqual([m["needsUpload"] for m in answer["data"]["mods"]], [False, False])

    # ---- 1.101.0: every answer a program reads carries data ----

    def test_a_refusal_is_data(self):
        code, answer = self.run_cli("upload", "Nothing", "--update")
        self.assertEqual(code, 1)
        self.assertEqual(answer["data"]["ok"], False)
        self.assertIn("Unknown mod: Nothing", answer["data"]["refusal"])

    def test_prepare_notes_and_what_if_carry_data(self):
        code, answer = self.run_cli("notes", "--check")
        self.assertEqual((code, answer["data"]["state"], answer["data"]["files"]), (0, "valid", []))
        code, answer = self.run_cli("prepare", "Base")
        self.assertEqual(answer["data"]["manifest"]["mod"], "Base")
        self.assertTrue(answer["data"]["candidate"])
        code, answer = self.run_cli("upload", "Base", "--create", "--what-if", "--via", "steamcmd", "--steam-user", "x",
                                    "--steamcmd", str(self.steamcmd))
        data = answer["data"]
        self.assertEqual((code, data["ok"], data["whatIf"], data["receipt"]), (0, True, True, None))
        self.assertTrue(any("What-if" in line for line in data["lines"]))
        self.assertEqual(answer["report"]["lines"], data["lines"])

    def test_a_noisy_build_leaves_the_json_whole(self):
        import sys
        config = json.loads((self.root / "config/workshop-publishing.json").read_text(encoding="utf-8"))
        config["layout"]["build"] = [sys.executable, "-c", "print('build output that must not reach the JSON')"]
        self.write("config/workshop-publishing.json", json.dumps(config, indent=2) + "\n")
        code, answer = self.run_cli("prepare", "Base", "--build")
        self.assertEqual(code, 0)
        self.assertEqual(answer["data"]["manifest"]["mod"], "Base")

    def test_an_upload_answers_with_its_receipt(self):
        import test_steam_publish_client as client_tests
        from phobos_modkit.steam.publish import senders
        self.run_cli("prepare", "Base")
        fake = client_tests.FakeUgc()
        sender = senders.SteamClient(library=lambda path: fake, environ={}, find_install=lambda app, environ: None)
        out = io.StringIO()
        code = cli.main(["upload", "Base", "--create", "--root", str(self.root), "--cache", str(self.cache), "--json"],
                        out=out, environ={}, sender=sender)
        data = json.loads(out.getvalue())["data"]
        self.assertEqual((code, data["ok"], data["itemId"], data["status"]), (0, True, base.NEW_ID, "created-unverified"))
        self.assertTrue(data["receipt"])
        fake = client_tests.FakeUgc(submit=2)
        sender = senders.SteamClient(library=lambda path: fake, environ={}, find_install=lambda app, environ: None)
        self.commit()
        self.write("mods/Base/About/About.xml", base.ABOUT.format(mod="Base", version="0.3.1"))
        self.write("workshop/Base/page.bbcode", base.PAGE.format(mod="Base", version="0.3.1"))
        self.write("mods/Base/CHANGELOG.md", base.CHANGELOG.format(mod="Base").replace(
            "## [0.3.0]", "## [0.3.1] - 2026-11-23 - Draft\n\n- Fix.\n\n## [0.3.0]"))
        self.run_cli("notes", "--write")
        self.run_cli("prepare", "Base")
        out = io.StringIO()
        code = cli.main(["upload", "Base", "--update", "--root", str(self.root), "--cache", str(self.cache), "--json"],
                        out=out, environ={}, sender=sender)
        data = json.loads(out.getvalue())["data"]
        self.assertEqual((code, data["ok"], data["status"]), (1, False, "submitted-unverified"))

    def test_show_names_what_is_not_ready(self):
        self.write("workshop/Base/page.bbcode", "[h1]Nope[/h1]\n")
        found = editor.show(self.load(), "Base")
        self.assertIn("error", found)
        self.assertEqual(found["receipts"], [])


if __name__ == "__main__":
    unittest.main()
