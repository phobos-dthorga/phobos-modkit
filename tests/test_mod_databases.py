"""The community lists fetched by the kit itself, and the owner's rules brought over from RimSort (1.144.0). A stand-in GitHub and
a synthetic RimWorld install; nothing reads a real one."""
import gzip
import io
import json
import os
from pathlib import Path
import tempfile
import unittest

from phobos_modkit import mod_databases
from phobos_modkit import mod_list_cli as cli
from phobos_modkit import mod_sort
from phobos_modkit.games.rimworld.mod_list import RimWorld
from phobos_modkit.github import GitHubError
from phobos_modkit.mod_databases import Database

import support
from test_mod_list import FakeRimWorld

RULES = {"rules": {"example.hostel": {"loadAfter": {"example.market": {"comment": ["the community says so"]}}}}}


class StandIn:
    """GitHub's raw files: each path's body and ETag; a matching If-None-Match is answered 304."""

    def __init__(self, files):
        self.files, self.asked = files, []

    def __call__(self, url, timeout=None, headers=None):
        self.asked.append((url, dict(headers or {})))
        for path, (body, tag) in self.files.items():
            if url.endswith("/" + path):
                if (headers or {}).get("If-None-Match") == tag:
                    return 304, b"", {}
                return 200, body, {"ETag": tag}
        return 404, b"", {}


LISTS = (Database("rules", "Rules", "someone/rules", ("rules.json",), "CC0-1.0", manager="dbs/rules"),
         Database("known", "Known", "someone/known", ("{version}/ids.xml",), "MIT"),
         Database("packed", "Packed", "someone/packed", ("big.json",), "MIT", packed=("big.json",)))


class Fetching(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.environ = support.isolated_environ(self.tmp.name)
        self.github = StandIn({"rules.json": (b'{"rules": {}}', '"a"'), "1.7/ids.xml": (b"<li>x</li>", '"b"'),
                               "big.json.gz": (gzip.compress(b'{"rules": []}'), '"c"')})

    def tearDown(self):
        self.tmp.cleanup()

    def fetch(self, version="1.7", now=1_000_000.0, **kw):
        return mod_databases.fetch("game", LISTS, version, self.environ, get=self.github, now=now, **kw)

    def test_each_file_is_fetched_unpacked_and_then_asked_for_by_its_etag(self):
        first = self.fetch()
        self.assertEqual([r["fetched"] for r in first], [1, 1, 1])
        packed = mod_databases.our_copy("game", LISTS[2], "big.json", self.environ)
        self.assertEqual(packed.read_bytes(), b'{"rules": []}')
        self.assertTrue(self.github.asked[2][0].endswith("someone/packed/main/big.json.gz"))
        again = self.fetch(now=2_000_000.0)
        self.assertEqual([r["unchanged"] for r in again], [1, 1, 1])
        self.assertEqual(self.github.asked[3][1], {"If-None-Match": '"a"'})
        # An unchanged file counts as fresh from the time it was asked again.
        self.assertEqual(packed.stat().st_mtime, 2_000_000.0)

    def test_a_version_path_needs_the_version_and_a_missing_file_is_named(self):
        self.assertEqual(LISTS[1].paths(""), [])
        github = StandIn({})
        results = mod_databases.fetch("game", LISTS[:1], "1.7", self.environ, get=github, now=1.0)
        self.assertEqual(results[0]["missing"], ["rules.json"])

    def test_github_out_of_reach_leaves_the_last_copy(self):
        self.fetch()

        def down(url, timeout=None, headers=None):
            raise GitHubError("GitHub could not be reached: no network")
        results = mod_databases.fetch("game", LISTS[:1], "1.7", self.environ, get=down, now=5.0)
        self.assertIn("could not be reached", results[0]["error"])
        self.assertTrue(mod_databases.our_copy("game", LISTS[0], "rules.json", self.environ).is_file())

    def test_the_newer_copy_is_read_and_an_old_one_is_stale(self):
        manager = Path(self.tmp.name) / "manager"
        theirs = manager / "dbs" / "rules" / "rules.json"
        theirs.parent.mkdir(parents=True)
        theirs.write_text("{}", encoding="utf-8")
        os.utime(theirs, (500_000.0, 500_000.0))
        self.fetch(now=1_000_000.0)
        rows = mod_databases.status("game", LISTS, "1.7", manager, self.environ, now=1_000_000.0 + 8 * 86400)
        self.assertEqual(rows[0]["read"], "ours")
        self.assertTrue(rows[0]["stale"])
        os.utime(theirs, (3_000_000.0, 3_000_000.0))
        rows = mod_databases.status("game", LISTS, "1.7", manager, self.environ, now=3_000_000.0)
        self.assertEqual((rows[0]["read"], rows[0]["stale"]), ("theirs", False))
        self.assertEqual(mod_databases.newest(mod_databases.our_copy("game", LISTS[0], "rules.json", self.environ), theirs),
                         theirs)


class RimWorldLists(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.fake = FakeRimWorld(self.tmp.name, ["ludeon.rimworld", "example.hostel", "example.market"])
        self.environ = self.fake.environ(self.tmp.name)
        dbs = Path(self.environ["PHOBOS_RIMSORT"]) / "dbs"
        dbs.mkdir(parents=True)
        self.theirs = dbs / "userRules.json"
        self.theirs.write_text(json.dumps({"rules": {"example.hostel": {"loadTop": {"value": True, "comment": "mine"}},
                                                     "example.market": {"loadAfter": {"example.hostel": {}}}}}),
                               encoding="utf-8")
        body = json.dumps(RULES).encode()
        self.github = StandIn({"communityRules.json": (body, '"r"')})

    def tearDown(self):
        self.tmp.cleanup()

    def run_cli(self, *argv):
        out = io.StringIO()
        code = cli.main(list(argv) + ["--json"], self.environ, out, running=lambda names: [], get=self.github)
        return code, json.loads(out.getvalue())["data"]

    def test_fetched_community_rules_are_read_by_the_sorter(self):
        code, data = self.run_cli("databases", "--name", "RimWorld")
        self.assertEqual(code, 0)
        self.assertTrue(all(r["stale"] for r in data["databases"]))
        code, data = self.run_cli("databases", "--name", "RimWorld", "--fetch", "--only", "community-rules")
        self.assertEqual(data["fetched"][0]["fetched"], 1)
        sets = [s for s in RimWorld(self.environ).rule_sets() if s.source == mod_sort.COMMUNITY]
        self.assertEqual(sets[0].label, "The community rules (fetched by the tools)")
        self.assertIn("example.hostel", sets[0].rules)

    def test_rimsort_rules_come_over_once_with_their_notes_and_stop_being_read_twice(self):
        code, data = self.run_cli("rules", "--name", "RimWorld", "--import-manager")
        self.assertEqual([r["words"] for r in data["imported"]],
                         ["example.hostel loads at the top", "example.market loads after example.hostel"])
        self.assertFalse(data["applied"])
        self.assertEqual(data["rules"], [])
        code, data = self.run_cli("rules", "--name", "RimWorld", "--import-manager", "--apply")
        self.assertTrue(data["applied"])
        self.assertEqual(data["rules"][0]["note"], "mine")
        self.assertTrue(data["manager"]["broughtOver"])
        self.assertEqual(data["theirs"], [])
        self.assertNotIn(mod_sort.YOURS, [s.source for s in RimWorld(self.environ).rule_sets()])
        # Again: nothing new to bring.
        code, data = self.run_cli("rules", "--name", "RimWorld", "--import-manager", "--apply")
        self.assertEqual(data["imported"], [])
        # A rule changed in RimSort afterwards is read again until brought over again.
        os.utime(self.theirs, None)
        stamp = self.theirs.stat().st_mtime_ns + 10_000_000_000
        os.utime(self.theirs, ns=(stamp, stamp))
        self.assertIn(mod_sort.YOURS, [s.source for s in RimWorld(self.environ).rule_sets()])


if __name__ == "__main__":
    unittest.main()
