"""rimworld-sources and the keyless GitHub client: links, checking a repository against a package ID, the cache, the
rate limit and the register. GitHub and Steam are made-up answers here; nothing reaches the network."""
import io
import json
from pathlib import Path
import tempfile
import unittest

import support  # noqa: F401  (the package on the import path)
from phobos_modkit.github import API, RAW, Client, RateLimited, links
from phobos_modkit.games.rimworld.sources_cli import EXIT_OK, main, search_terms

ABOUT = "<ModMetaData><name>{name}</name><packageId>{pid}</packageId>{extra}</ModMetaData>"


def about(pid, extra=""):
    return ABOUT.format(name=pid, pid=pid, extra=extra)


def write(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


class FakeGitHub:
    """URL -> (status, body); anything not listed is a 404. Counts the calls."""

    def __init__(self, pages=None, limit_after=None):
        self.pages = dict(pages or {})
        self.calls = []
        self.limit_after = limit_after

    def repo(self, name, root_about=None, tree=None, branch="main", pushed="2026-11-01T00:00:00Z", licence="MIT"):
        self.pages[f"{API}/repos/{name}"] = json.dumps({"full_name": name, "html_url": f"https://github.com/{name}",
                                                        "pushed_at": pushed, "archived": False, "default_branch": branch,
                                                        "license": {"spdx_id": licence}})
        if root_about is not None:
            self.pages[f"{RAW}/{name}/HEAD/About/About.xml"] = root_about
        if tree is not None:
            self.pages[f"{API}/repos/{name}/git/trees/{branch}?recursive=1"] = json.dumps(
                {"tree": [{"path": p, "type": "blob"} for p in tree]})
            for path, text in tree.items():
                self.pages[f"{RAW}/{name}/{branch}/{path}"] = text

    def __call__(self, url):
        self.calls.append(url)
        if self.limit_after is not None and len(self.calls) > self.limit_after:
            return 403, b"rate limited", {"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "0"}
        if url in self.pages:
            return 200, self.pages[url].encode("utf-8"), {}
        return 404, b"", {}


def steam(descriptions):
    """A made-up Steam details API answering with these descriptions by Workshop ID."""
    def post(url, data):
        ids = [v for k, v in data.items() if k.startswith("publishedfileids")]
        details = [{"publishedfileid": i, "result": 1, "title": i, "creator": "1", "description": descriptions.get(i, "")} for i in ids]
        return 200, json.dumps({"response": {"publishedfiledetails": details}}).encode("utf-8")
    return post


class LinkTests(unittest.TestCase):
    def test_links_keep_owner_and_repository_only(self):
        text = ("See https://github.com/Dubwise56/Rimefeller/wiki and [url=https://github.com/a-b/c.d.git]x[/url], "
                "again github.com/a-b/C.D, and https://github.com/orgs/someone")
        self.assertEqual(links(text), ["Dubwise56/Rimefeller", "a-b/c.d"])


class ClientTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cache = Path(self.tmp.name) / "cache"

    def tearDown(self):
        self.tmp.cleanup()

    def test_an_answer_and_a_missing_file_are_both_cached(self):
        fake = FakeGitHub({f"{RAW}/a/b/HEAD/About/About.xml": about("x")})
        client = Client(self.cache, get=fake, sleep=lambda s: None)
        self.assertIsNotNone(client.raw("a/b", "HEAD", "About/About.xml"))
        self.assertIsNone(client.raw("a/c", "HEAD", "About/About.xml"))
        again = Client(self.cache, get=fake, sleep=lambda s: None)
        again.raw("a/b", "HEAD", "About/About.xml")
        again.raw("a/c", "HEAD", "About/About.xml")
        self.assertEqual(len(fake.calls), 2)
        self.assertEqual(again.reused, 2)

    def test_the_rate_limit_stops_further_calls_and_says_so(self):
        fake = FakeGitHub(limit_after=0)
        client = Client(self.cache, get=fake, sleep=lambda s: None)
        with self.assertRaises(RateLimited):
            client.repository("a/b")
        with self.assertRaises(RateLimited):
            client.repository("a/c")
        self.assertEqual(len(fake.calls), 1)

    def test_search_terms_drop_bracketed_tags(self):
        class Mod:
            name, package_id = "[sbz] Fridge (Continued)", "sbz.fridge"
        self.assertEqual(search_terms(Mod), "Fridge rimworld")


class CommandTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.project = root / "project"
        write(self.project / "mods" / "Ours" / "About" / "About.xml",
              ABOUT.format(name="Ours", pid="our.mod", extra="<loadAfter><li>linked.mod</li><li>workshop.mod</li>"
                                                             "<li>mono.mod</li><li>searched.mod</li><li>closed.mod</li></loadAfter>"))
        game = root / "steamapps" / "common" / "RimWorld"
        write(game / "Assembly-CSharp.dll", "x")
        shop = root / "steamapps" / "workshop" / "content" / "294100"
        # Its About.xml links Harmony's repository (another mod) before its own.
        write(shop / "1" / "About" / "About.xml",
              about("linked.mod", "<description>Needs https://github.com/pardeike/HarmonyRimWorld</description>"
                                  "<url>https://github.com/me/Linked</url>"))
        write(shop / "2" / "About" / "About.xml", about("workshop.mod"))
        write(shop / "3" / "About" / "About.xml", about("mono.mod", "<url>https://github.com/team/AllMods/tree/main</url>"))
        write(shop / "4" / "About" / "About.xml", ABOUT.format(name="Searched Mod", pid="searched.mod", extra=""))
        write(shop / "5" / "About" / "About.xml", about("closed.mod"))
        write(root / "Config" / "ModsConfig.xml", "<ModsConfigData><version>1.7.5013 rev95</version><activeMods>"
              "<li>ludeon.rimworld</li><li>linked.mod</li><li>workshop.mod</li><li>mono.mod</li><li>searched.mod</li>"
              "<li>closed.mod</li></activeMods></ModsConfigData>")
        self.fake = FakeGitHub()
        self.fake.repo("pardeike/HarmonyRimWorld", root_about=about("brrainz.harmony"))
        self.fake.repo("me/Linked", root_about=about("linked.mod"))
        self.fake.repo("you/FromWorkshop", root_about=about("workshop.mod"))
        self.fake.repo("team/AllMods", tree={"Mono/About/About.xml": about("mono.mod"), "Other/About/About.xml": about("other")})
        self.fake.pages[f"{API}/search/repositories?q=Searched%20Mod%20rimworld&per_page=3"] = json.dumps(
            {"items": [{"full_name": "found/SearchedMod"}]})
        self.fake.repo("found/SearchedMod", root_about=about("searched.mod"))
        self.fake.pages[f"{API}/search/repositories?q=closed.mod%20rimworld&per_page=3"] = json.dumps({"items": []})
        self.post = steam({"2": "Source: [url=https://github.com/you/FromWorkshop]GitHub[/url]"})
        self.argv = ["--root", str(self.project), "--game", str(game), "--workshop", str(shop), "--config", str(root / "Config"),
                     "--cache", str(root / "cache"), "--no-redact"]

    def tearDown(self):
        self.tmp.cleanup()

    def run_main(self, extra=(), fake=None):
        out = io.StringIO()
        code = main(self.argv + list(extra), environ={}, out=out, get=fake or self.fake, post=self.post,
                    sleep=lambda s: None, clock=lambda: 1_800_000_000)
        return code, out.getvalue()

    def test_each_mod_is_confirmed_from_the_cheapest_place_that_holds_it(self):
        code, text = self.run_main(["--write"])
        self.assertEqual(code, EXIT_OK, text)
        self.assertIn("5 mods: 4 with a confirmed public repository, 0 with only unconfirmed candidates, 1 with none found", text)
        register = json.loads((self.project / "config" / "source-repos.json").read_text(encoding="utf-8"))["mods"]
        self.assertEqual(register["linked.mod"]["repository"], "https://github.com/me/Linked")
        self.assertEqual(register["linked.mod"]["found"], "About.xml")
        self.assertEqual(register["linked.mod"]["candidates"][0]["note"], "it is brrainz.harmony's repository")
        self.assertEqual(register["workshop.mod"]["found"], "Workshop page")
        self.assertEqual(register["mono.mod"]["confirmed"], "Mono/About/About.xml")
        self.assertEqual(register["searched.mod"]["found"], "GitHub search")
        self.assertEqual(register["searched.mod"]["licence"], "MIT")
        self.assertFalse(register["closed.mod"]["repository"])
        self.assertIn("closed.mod", text)

    def test_a_search_is_made_only_when_no_link_holds_the_mod(self):
        self.run_main()
        searches = [u for u in self.fake.calls if "/search/" in u]
        self.assertEqual(len(searches), 2)   # the searched mod and the closed one; never the three found by links

    def test_the_register_spares_confirmed_mods_a_second_look(self):
        self.run_main(["--write"])
        fresh = FakeGitHub()
        code, text = self.run_main(["--refresh"], fake=fresh)
        self.assertIn("4 taken from the register", text)
        self.assertFalse([u for u in fresh.calls if "me/Linked" in u])

    def test_a_rate_limit_keeps_what_was_found_and_says_what_is_left(self):
        limited = FakeGitHub(self.fake.pages, limit_after=3)
        code, text = self.run_main(fake=limited)
        self.assertEqual(code, EXIT_OK, text)
        self.assertIn("limiting keyless requests", text)
        self.assertIn("Not looked up yet", text)


if __name__ == "__main__":
    unittest.main()
