"""issue-links: ours or theirs for each mod a fault names, the new-issue form's address, and an author's issues from made-up
answers (1.94.0). Nothing reaches the network, and nothing is ever posted."""
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
import urllib.parse

import support  # noqa: F401  (puts the package on the path)
from phobos_modkit import issue_links
from phobos_modkit.github import API, Client
from phobos_modkit.mod_list import Mod

NOW = 1_800_000_000


class Adapter:
    def __init__(self, mods):
        self.mods = mods

    def installed(self):
        return self.mods


def repository(path, remote, mods=(), register=None):
    path.mkdir(parents=True)
    for args in (("init", "-q"), ("config", "core.fsmonitor", "false"), ("remote", "add", "origin", remote)):
        subprocess.run(["git", "-C", str(path), *args], check=True, capture_output=True)
    (path / "config").mkdir()
    (path / "config" / "installs.json").write_text(json.dumps({
        "schemaVersion": 1, "game": "rimworld", "mods": "mods", "backups": "x"}), encoding="utf-8")
    for mod in mods:
        (path / "mods" / mod).mkdir(parents=True)
        (path / "mods" / mod / "CHANGELOG.md").write_text("# x\n", encoding="utf-8")
    if register is not None:
        (path / "config" / "source-repos.json").write_text(json.dumps({"mods": register}), encoding="utf-8")


class WhereTests(unittest.TestCase):
    def test_a_mod_is_ours_theirs_or_unknown(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "game"
            repository(root, "https://github.com/me/game.git", mods=["PhobosFramework"], register={
                "vf": {"name": "Vehicle Framework", "package_id": "SmashPhil.VehicleFramework", "confirmed": "About/About.xml",
                       "repository": "https://github.com/SmashPhil/Vehicle-Framework"},
                "maybe": {"name": "Unconfirmed", "package_id": "some.one", "repository": "https://github.com/a/b"}})
            adapter = Adapter([Mod("phobosdthorga.framework", "D'thorga Framework", "local", folder="C:/Mods/PhobosFramework"),
                               Mod("smashphil.vehicleframework", "Vehicle Framework", "workshop", folder="C:/W/1"),
                               Mod("some.one", "Unconfirmed", "workshop", folder="C:/W/2")])
            found = issue_links.where(adapter, [root], ["D'thorga Framework", "Vehicle Framework", "Unconfirmed", "Gone"])
        self.assertEqual([(f["whose"], f["repository"]) for f in found],
                         [("ours", "me/game"), ("theirs", "SmashPhil/Vehicle-Framework"), ("unknown", None),
                          ("unknown", None)])


class NewIssueTests(unittest.TestCase):
    def test_the_form_is_filled_in_and_a_long_text_goes_to_the_clipboard(self):
        short = issue_links.new_issue("me/game", "  A fault\nin two lines ", "The log says x.", "Bug")
        query = urllib.parse.parse_qs(urllib.parse.urlparse(short["url"]).query)
        self.assertTrue(short["url"].startswith("https://github.com/me/game/issues/new?"))
        self.assertEqual((query["title"], query["body"], query["labels"]), (["A fault in two lines"], ["The log says x."], ["Bug"]))
        self.assertIsNone(short["clipboard"])
        long = issue_links.new_issue("me/game", "A fault", "x" * 9000)
        self.assertEqual("x" * 9000, long["clipboard"])
        self.assertLess(len(long["url"]), 300)
        self.assertIn("Paste+the+report", long["url"])

    def test_only_a_repository_name_and_a_title_are_taken(self):
        for repo, title in (("https://evil.example/x", "t"), ("me/game/../x", "t"), ("me/game", "  ")):
            with self.subTest(repo=repo), self.assertRaises(issue_links.LinkError):
                issue_links.new_issue(repo, title)


class IssuesTests(unittest.TestCase):
    def test_issues_that_name_every_word_come_first_and_pull_requests_are_left_out(self):
        page = [{"number": 7, "title": "Turret queue lost on save", "body": "saved mid-burst", "state": "open",
                 "updated_at": "2026-11-20", "html_url": "https://github.com/a/b/issues/7"},
                {"number": 9, "title": "Unrelated", "body": "", "state": "closed", "updated_at": "2026-11-21",
                 "html_url": "https://github.com/a/b/issues/9"},
                {"number": 8, "title": "A pull request", "pull_request": {}, "state": "open"}]

        def get(url, headers=None):
            self.assertEqual(f"{API}/repos/a/b/issues?state=all&per_page=100&page=1", url)
            return 200, json.dumps(page).encode("utf-8"), {}

        with tempfile.TemporaryDirectory() as tmp:
            client = Client(Path(tmp), get=get, sleep=lambda s: None, clock=lambda: NOW)
            found = issue_links.issues(client, "a/b", "turret queue")
        self.assertEqual([(7, True), (9, False)], [(i["number"], i["matches"]) for i in found])


if __name__ == "__main__":
    unittest.main()
