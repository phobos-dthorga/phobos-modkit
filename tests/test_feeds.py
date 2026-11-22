"""feeds: a feed folder's index and checks, a nightly run's file, and reading a feed from made-up raw files, with the last good
copy kept when a new one fails or GitHub cannot be reached (1.90.0). Nothing reaches the network."""
import io
import json
from pathlib import Path
import tempfile
import unittest

import support  # noqa: F401  (puts the package on the path)
from phobos_modkit import feeds
from phobos_modkit.github import RAW, GitHubError

NOW = 1_800_000_000
WATCH = {"game": "rimworld", "checked": "2027-01-15T08:00:00Z", "days": 30,
         "findings": [{"mod": "Vehicle Framework", "commit": "abc1234", "member": "CompUpgradeTree.PrerequisitesMet",
                       "link": "https://github.com/me/vf/commit/abc1234"}]}


class FakeRaw:
    """URL -> bytes; anything else is a 404. `offline` makes every call fail as an unreachable GitHub would."""

    def __init__(self):
        self.pages = {}
        self.offline = False
        self.calls = 0

    def publish(self, folder, repo="me/game", ref="companion-results", path=""):
        for file in Path(folder).rglob("*"):
            if file.is_file():
                relative = file.relative_to(folder).as_posix()
                url = f"{RAW}/{repo}/{ref}/{path + '/' if path else ''}{relative}"
                self.pages[url] = file.read_bytes()

    def __call__(self, url, headers=None):
        self.calls += 1
        if self.offline:
            raise GitHubError("GitHub could not be reached: made up")
        if url in self.pages:
            return 200, self.pages[url], {}
        return 404, b"", {}


class Clock:
    def __init__(self):
        self.now = NOW

    def __call__(self):
        return self.now


class FolderTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name) / "feed"
        feeds.write_file(self.folder / "upstream-watch.json", "upstream-watch", WATCH)
        (self.folder / "guide").mkdir()
        (self.folder / "guide" / "entry.md").write_text("---\ntitle: A\n---\nWords.\n", encoding="utf-8")

    def test_an_index_lists_each_file_with_its_kind_size_and_hash(self):
        index = feeds.build_index(self.folder, "phobos-rimworld", updated="2027-01-15T08:00:00Z")
        self.assertEqual([("guide/entry.md", "guide"), ("upstream-watch.json", "upstream-watch")],
                         [(f["path"], f["kind"]) for f in index["files"]])
        self.assertEqual(64, len(index["files"][0]["sha256"]))

    def test_a_folder_matches_its_index_until_a_file_changes(self):
        out = io.StringIO()
        feeds.main(["index", "--folder", str(self.folder), "--name", "game", "--write"], out=out)
        self.assertEqual([], feeds.check_folder(self.folder))
        (self.folder / "guide" / "entry.md").write_text("changed\n", encoding="utf-8")
        (self.folder / "stray.json").write_text("{}", encoding="utf-8")
        faults = feeds.check_folder(self.folder)
        self.assertTrue(any("entry.md: changed since" in f for f in faults), faults)
        self.assertTrue(any("stray.json: in the folder but not in the index" in f for f in faults), faults)
        self.assertTrue(any("stray.json: of no kind" in f for f in faults), faults)
        self.assertEqual(feeds.EXIT_FAILED, feeds.main(["check", "--folder", str(self.folder)], out=io.StringIO()))

    def test_a_nightly_file_that_fails_its_kind_is_never_written(self):
        with self.assertRaises(feeds.FeedError):
            feeds.write_file(self.folder / "bad.json", "upstream-watch", {"game": "rimworld", "checked": "x",
                                                                          "findings": [{"mod": "A"}]})
        self.assertFalse((self.folder / "bad.json").exists())
        with self.assertRaises(feeds.FeedError):
            feeds.check_file("upstream-watch", json.dumps({"kind": "upstream-watch", "format": 1, "game": "g", "checked": "c",
                                                           "findings": [{"mod": "a", "commit": "b", "member": "c",
                                                                         "link": "https://example.com/x"}]}).encode())

    def test_a_night_that_found_nothing_new_changes_nothing(self):
        feeds.main(["index", "--folder", str(self.folder), "--name", "game", "--write"], out=io.StringIO())
        index_before = (self.folder / feeds.INDEX).read_bytes()
        file_before = (self.folder / "upstream-watch.json").read_bytes()
        later = {**WATCH, "checked": "2027-01-16T08:00:00Z"}
        self.assertFalse(feeds.write_file(self.folder / "upstream-watch.json", "upstream-watch", later, volatile=("checked",)))
        feeds.main(["index", "--folder", str(self.folder), "--name", "game", "--write"], out=io.StringIO())
        self.assertEqual(file_before, (self.folder / "upstream-watch.json").read_bytes())
        self.assertEqual(index_before, (self.folder / feeds.INDEX).read_bytes())
        changed = {**later, "findings": []}
        self.assertTrue(feeds.write_file(self.folder / "upstream-watch.json", "upstream-watch", changed, volatile=("checked",)))

    def test_a_kind_this_kit_does_not_know_is_refused(self):
        with self.assertRaises(feeds.FeedError):
            feeds.check_file("telemetry", b"{}")

    def test_an_address_names_a_repository_a_branch_and_a_folder(self):
        self.assertEqual(("me/game", "HEAD", "feeds"), feeds.parse_source("me/game"))
        self.assertEqual(("me/game", "companion-results", ""), feeds.parse_source("me/game@companion-results:"))
        for bad in ("me", "me/game:../x", "https://github.com/me/game"):
            with self.subTest(bad=bad), self.assertRaises(feeds.FeedError):
                feeds.parse_source(bad)
        self.assertIsNone(feeds.SAFE_PATH.match("../secret"))


class ReadTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.folder = root / "feed"
        self.cache = root / "cache"
        feeds.write_file(self.folder / "upstream-watch.json", "upstream-watch", WATCH)
        feeds.main(["index", "--folder", str(self.folder), "--name", "game", "--write"], out=io.StringIO())
        self.raw = FakeRaw()
        self.raw.publish(self.folder)
        self.clock = Clock()

    def read(self, *extra):
        out = io.StringIO()
        code = feeds.main(["read", "--source", "me/game@companion-results:", "--cache", str(self.cache), "--json", *extra],
                          out=out, environ={}, get=self.raw, clock=self.clock)
        self.assertEqual(feeds.EXIT_OK, code, out.getvalue())
        return json.loads(out.getvalue())["data"]["feeds"][0]

    def test_a_good_feed_is_read_checked_and_kept(self):
        feed = self.read()
        self.assertEqual(("read", "game"), (feed["state"], feed["feed"]))
        file = feed["files"][0]
        self.assertEqual(("upstream-watch", "new"), (file["kind"], file["state"]))
        self.assertEqual("abc1234", file["content"]["findings"][0]["commit"])
        self.clock.now += 7 * 3600
        self.assertEqual("same", self.read()["files"][0]["state"])

    def test_a_file_not_matching_its_index_keeps_the_last_good_copy(self):
        self.read()
        url = f"{RAW}/me/game/companion-results/upstream-watch.json"
        self.raw.pages[url] = self.raw.pages[url].replace(b"abc1234", b"evil999")
        self.clock.now += 7 * 3600
        file = self.read()["files"][0]
        self.assertEqual("kept", file["state"])
        self.assertIn("does not match the index", file["why"])
        self.assertEqual("abc1234", file["content"]["findings"][0]["commit"])

    def test_offline_the_last_good_copies_are_given(self):
        self.read()
        self.raw.offline = True
        self.clock.now += 7 * 3600
        feed = self.read()
        self.assertEqual(["abc1234"], [f["content"]["findings"][0]["commit"] for f in feed["files"]])
        self.assertTrue(feed["stale"] or all(f["state"] == "kept" for f in feed["files"]))

    def test_a_feed_never_read_and_unreachable_says_so(self):
        self.raw.offline = True
        feed = self.read()
        self.assertEqual("unreachable", feed["state"])
        self.assertEqual([], feed["files"])


if __name__ == "__main__":
    unittest.main()
