"""Steam Workshop research with a fake Steam: parsing, pacing, the cache, reports and both commands. No network."""
import io
import json
from pathlib import Path
import tempfile
import unittest
from contextlib import closing

from support import FIXTURES, fixture_text
from phobos_modkit.games.rimworld import workshop_cli as rimworld_cli
from phobos_modkit.report import render_markdown
from phobos_modkit.steam import workshop
from phobos_modkit.steam import workshop_cli as core_cli
from phobos_modkit.steam import workshop_reports as reports

DETAILS = json.loads(fixture_text("steam/details.json"))
COMMENTS = fixture_text("steam/comments-render.json")
NOW = 1790600000  # a little after the fixture's newest comment


class FakeSteam:
    """Answers like Steam by URL and records every request."""

    def __init__(self, comments_status=200, private=(), limit_after=None):
        self.calls, self.comments_status, self.private, self.limit_after = [], comments_status, set(private), limit_after

    def __call__(self, url, data):
        self.calls.append((url, dict(data)))
        if url == workshop.DETAILS_URL:
            wanted = [v for k, v in data.items() if k.startswith("publishedfileids")]
            items = [d for d in DETAILS["response"]["publishedfiledetails"] if d["publishedfileid"] in wanted]
            items += [{"publishedfileid": w, "result": 9} for w in wanted
                      if w not in {d["publishedfileid"] for d in items}]
            return 200, json.dumps({"response": {"publishedfiledetails": items}}).encode()
        comment_calls = sum(1 for u, _ in self.calls if u != workshop.DETAILS_URL)
        if self.limit_after is not None and comment_calls > self.limit_after:
            return 429, b"Too Many Requests"
        item = url.rstrip("/").rsplit("/", 1)[-1]
        if item in self.private:
            return 200, json.dumps({"success": False, "error": "This profile is private."}).encode()
        return self.comments_status, COMMENTS.encode()

    def comment_calls(self):
        return [u for u, _ in self.calls if u != workshop.DETAILS_URL]


class Sleeps:
    def __init__(self):
        self.slept, self.now = [], 0.0

    def sleep(self, seconds):
        self.slept.append(seconds)
        self.now += seconds

    def clock(self):
        return self.now

    def pacer(self):
        return workshop.Pacer(sleep=self.sleep, clock=self.clock)


class Parsing(unittest.TestCase):
    def test_item_ids_from_ids_and_urls(self):
        self.assertEqual(workshop.item_id("https://steamcommunity.com/sharedfiles/filedetails/?id=1111111111&x=1"),
                         "1111111111")
        self.assertEqual(workshop.item_id(" 2222222222 "), "2222222222")
        self.assertIsNone(workshop.item_id("Example Widgets"))

    def test_details(self):
        items = workshop.parse_details(DETAILS)
        self.assertEqual([(i.id, i.result) for i in items], [("1111111111", 1), ("2222222222", 1), ("3333333333", 9)])
        self.assertEqual(items[0].tags, ["Mod", "1.7", "1.6"])

    def test_comments_with_the_uploader_marked(self):
        found = workshop.parse_comments(json.loads(COMMENTS)["comments_html"], "76561197960265829")
        self.assertEqual([c.comment_id for c in found], ["903", "902", "901"])
        uploader, player, _ = found
        self.assertTrue(uploader.by_creator)
        self.assertEqual(uploader.text, "Fixed in today's update.\nThanks for the report!")
        self.assertFalse(player.by_creator)
        self.assertEqual(player.author, "Player & Friend")
        self.assertEqual(player.text, "Red errors on 1.7 when loading a save, see my log")
        self.assertEqual(player.timestamp, 1790400000)


class Pacing(unittest.TestCase):
    def test_requests_are_spaced_and_one_429_is_waited_out(self):
        clock = Sleeps()
        pacer = clock.pacer()
        answers = iter([(200, b"a"), (429, b""), (200, b"b")])
        pacer.call(lambda: next(answers))
        self.assertEqual(pacer.call(lambda: next(answers)), (200, b"b"))
        self.assertEqual(clock.slept, [workshop.PAUSE_SECONDS, workshop.BACKOFF_SECONDS])

    def test_a_second_429_stops(self):
        pacer = Sleeps().pacer()
        with self.assertRaises(workshop.RateLimited):
            pacer.call(lambda: (429, b""))


class CacheBase(unittest.TestCase):
    """A temporary cache and a fake clock; no tests of its own."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cache = Path(self.tmp.name) / "cache"
        self.sleeps = Sleeps()

    def tearDown(self):
        self.tmp.cleanup()

    def refresh(self, steam, ids=("1111111111", "2222222222"), now=NOW, **options):
        return workshop.refresh(list(ids), self.cache, post=steam, pacer=self.sleeps.pacer(), clock=lambda: now,
                                **options)


class Cache(CacheBase):
    def test_details_are_batched_and_comments_paced(self):
        steam = FakeSteam()
        ids = ["1111111111", "2222222222"] + [str(4000000000 + n) for n in range(120)]
        done = self.refresh(steam, ids)
        self.assertEqual(sum(1 for u, _ in steam.calls if u == workshop.DETAILS_URL), 2)
        self.assertEqual(len(steam.comment_calls()), 2)  # the 120 unknown IDs have no item, so no comments
        self.assertEqual(done.comments_fetched, 2)
        self.assertEqual(self.sleeps.slept, [workshop.PAUSE_SECONDS])

    def test_fresh_items_are_reused_and_old_ones_fetched_again(self):
        self.refresh(FakeSteam())
        again = FakeSteam()
        done = self.refresh(again, now=NOW + 3600)
        self.assertEqual((again.calls, done.reused), ([], 2))
        later = FakeSteam()
        self.refresh(later, now=NOW + 25 * 3600)
        self.assertEqual(len(later.comment_calls()), 2)
        forced = FakeSteam()
        self.refresh(forced, now=NOW + 3600, force=True)
        self.assertEqual(len(forced.comment_calls()), 2)

    def test_hidden_comments_are_remembered_not_asked_again(self):
        self.refresh(FakeSteam(private={"2222222222"}))
        with closing(workshop.connect(self.cache)) as conn:
            self.assertEqual(conn.execute("SELECT comments_note FROM item WHERE id = '2222222222'").fetchone()[0],
                             "This profile is private.")
        again = FakeSteam()
        self.refresh(again, now=NOW + 60)
        self.assertEqual(again.comment_calls(), [])

    def test_rate_limits_stop_comment_requests_and_say_so(self):
        steam = FakeSteam(limit_after=0)
        done = self.refresh(steam)
        self.assertTrue(done.rate_limited)
        self.assertEqual(len(steam.comment_calls()), 2)  # the first try and the one retry after the back-off
        self.assertEqual(done.comments_fetched, 0)


class Reports(CacheBase):
    def setUp(self):
        super().setUp()
        self.refresh(FakeSteam(private={"2222222222"}), ids=("1111111111", "2222222222", "3333333333"))
        self.conn = workshop.connect(self.cache)

    def tearDown(self):
        self.conn.close()
        super().tearDown()

    def test_research(self):
        report = reports.research(self.conn, ["1111111111", "2222222222", "3333333333"], days=30,
                                  game_version="1.7", now=NOW)
        widgets = report.sections[0].table.rows[0]
        self.assertEqual(widgets[:2], ("Example Widgets", "1111111111"))
        self.assertEqual(widgets[5:], ("3 of 120", 2, reports.date_text(1790500000), 1))
        flagged = report.sections[1].table.rows
        self.assertEqual([r[2] for r in flagged], ["Player & Friend"])
        self.assertEqual(report.sections[2].table.rows[0][2], "Fixed in today's update. Thanks for the report!")
        text = render_markdown(report)
        self.assertIn("| Example Old Mod | 2222222222 | 2022-04-15 | 1.5 | 42 | not shown to visitors |", text)
        self.assertIn("This profile is private.", text)
        self.assertIn("No details for: 3333333333.", text)

    def test_details_with_the_game_version(self):
        rows = reports.details(self.conn, ["1111111111", "2222222222"], "1.7").sections[0].table.rows
        self.assertEqual([(r[1], r[4]) for r in rows], [("Example Widgets", "yes"), ("Example Old Mod", "no")])

    def test_one_items_comments(self):
        rows = reports.comments(self.conn, "1111111111").sections[0].table.rows
        self.assertEqual(rows[0][1], "Example Author (uploader)")


class Commands(CacheBase):
    def run_core(self, *args, steam=None):
        out = io.StringIO()
        code = core_cli.main([*args, "--cache", str(self.cache)], environ={}, out=out, post=steam or FakeSteam(),
                             pacer=self.sleeps.pacer(), clock=lambda: NOW)
        return code, out.getvalue()

    def test_core_report_from_ids_and_urls(self):
        code, text = self.run_core("report", "1111111111",
                                   "https://steamcommunity.com/sharedfiles/filedetails/?id=2222222222")
        self.assertEqual(code, core_cli.EXIT_OK)
        self.assertIn("2 items' details and 2 comment pages fetched now", text)
        self.assertIn("Example Old Mod", text)

    def test_a_bare_id_means_report_and_bad_targets_are_refused(self):
        self.assertIn("# Workshop research", self.run_core("1111111111")[1])
        self.assertEqual(self.run_core("details", "not-an-id")[0], core_cli.EXIT_USAGE)

    def test_offline_never_contacts_steam(self):
        def refuse(url, data):
            raise AssertionError("contacted Steam while offline")
        code, text = self.run_core("details", "1111111111", "--offline", steam=refuse)
        self.assertEqual(code, core_cli.EXIT_OK)
        self.assertIn("From the cache only", text)

    def test_json_and_sql(self):
        self.run_core("details", "1111111111")
        data = json.loads(self.run_core("details", "1111111111", "--json")[1])
        self.assertEqual(data["report"]["sections"][0]["blocks"][0]["rows"][0][1], "Example Widgets")
        self.assertIn("| 1 |", self.run_core("sql", "SELECT COUNT(*) FROM item")[1])


class RimWorldCommand(CacheBase):
    def setUp(self):
        super().setUp()
        root = Path(self.tmp.name)
        self.game = root / "steamapps" / "common" / "RimWorld"
        self.workshop_folder = root / "steamapps" / "workshop" / "content" / "294100"
        for item, package_id, name in (("1111111111", "example.widgets", "Example Widgets"),
                                       ("2222222222", "example.old", "Example Old Mod")):
            about = self.workshop_folder / item / "About" / "About.xml"
            about.parent.mkdir(parents=True)
            about.write_text(f"<ModMetaData><name>{name}</name><packageId>{package_id}</packageId></ModMetaData>",
                             encoding="utf-8")
        self.config = root / "Config"
        self.config.mkdir()
        (self.config / "ModsConfig.xml").write_text(
            "<ModsConfigData><version>1.7.9999 rev1</version><activeMods><li>ludeon.rimworld</li>"
            "<li>example.widgets</li><li>example.old</li></activeMods></ModsConfigData>", encoding="utf-8")

    def run_rimworld(self, *args):
        out = io.StringIO()
        code = rimworld_cli.main([*args, "--cache", str(self.cache), "--game", str(self.game), "--workshop",
                                  str(self.workshop_folder), "--config", str(self.config)], environ={}, out=out,
                                 post=FakeSteam(), pacer=self.sleeps.pacer(), clock=lambda: NOW)
        return code, out.getvalue()

    def test_mods_by_name_package_id_or_wildcard(self):
        ids, unknown = rimworld_cli.resolve(["Example Widgets", "example.old", "Example *", "nothing"],
                                            rimworld_cli._installed(self.workshop_folder))
        self.assertEqual((ids, unknown), (["1111111111", "2222222222"], ["nothing"]))

    def test_report_flags_the_games_version_from_mods_config(self):
        code, text = self.run_rimworld("report", "example.widgets")
        self.assertEqual(code, core_cli.EXIT_OK)
        self.assertIn("and the game version 1.7", text)

    def test_versions_lists_active_mods_not_declaring_the_game_version(self):
        code, text = self.run_rimworld("versions")
        self.assertIn("1 of 2 active Workshop mods declare it", text)
        self.assertIn("| 2 | Example Old Mod | 2222222222 |", text)

    def test_an_unknown_name_is_a_usage_error(self):
        self.assertEqual(self.run_rimworld("report", "Nothing Like It")[0], core_cli.EXIT_USAGE)


if __name__ == "__main__":
    unittest.main()
