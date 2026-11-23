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

    def test_show_names_what_is_not_ready(self):
        self.write("workshop/Base/page.bbcode", "[h1]Nope[/h1]\n")
        found = editor.show(self.load(), "Base")
        self.assertIn("error", found)
        self.assertEqual(found["receipts"], [])


if __name__ == "__main__":
    unittest.main()
