"""Steam Workshop collections and stored descriptions, with the fake Steam from the Workshop tests. No network."""
import io
import json
import sqlite3
import unittest
from contextlib import closing

from support import fixture_text
from test_steam_workshop import NOW, CacheBase, FakeSteam
from phobos_modkit.games.rimworld import workshop_cli as rimworld_cli
from phobos_modkit.report import render_markdown
from phobos_modkit.steam import workshop
from phobos_modkit.steam import workshop_cli as core_cli
from phobos_modkit.steam import workshop_reports as reports

COLLECTION = json.loads(fixture_text("steam/collection.json"))
GOOD, GONE = "4444444444", "5555555555"


class FakeSteamWithCollections(FakeSteam):
    def __call__(self, url, data):
        if url != workshop.COLLECTION_URL:
            return super().__call__(url, data)
        self.calls.append((url, dict(data)))
        wanted = [v for k, v in data.items() if k.startswith("publishedfileids")]
        found = [c for c in COLLECTION["response"]["collectiondetails"] if c["publishedfileid"] in wanted]
        found += [{"publishedfileid": w, "result": 9} for w in wanted if w not in {c["publishedfileid"] for c in found}]
        return 200, json.dumps({"response": {"collectiondetails": found}}).encode()

    def collection_calls(self):
        return [u for u, _ in self.calls if u == workshop.COLLECTION_URL]

    def comment_calls(self):
        return [u for u, _ in self.calls if u not in (workshop.DETAILS_URL, workshop.COLLECTION_URL)]


class Parsing(unittest.TestCase):
    def test_children_in_the_collections_order_and_a_missing_collection(self):
        found = workshop.parse_collections(COLLECTION)
        self.assertEqual(found, {GOOD: ["1111111111", "2222222222", "3333333333"], GONE: None})

    def test_descriptions_are_parsed(self):
        items = workshop.parse_details(json.loads(fixture_text("steam/details.json")))
        self.assertIn("[b]hover[/b]", items[0].description)

    def test_plain_text_drops_tags_and_addresses(self):
        self.assertEqual(reports.plain_text("[h1]Title[/h1]\nAdds [b]hover[/b] widgets. [url=https://x.y]Guide[/url] "
                                            "https://i.imgur.com/abc.png"), "Title Adds hover widgets. Guide")


class Cache(CacheBase):
    def refresh_collections(self, steam, ids=(GOOD, GONE), now=NOW, **options):
        return workshop.refresh_collections(list(ids), self.cache, post=steam, clock=lambda: now, **options)

    def test_children_and_their_details_are_fetched_without_comments(self):
        steam = FakeSteamWithCollections()
        done, children = self.refresh_collections(steam)
        self.assertEqual(children, {GOOD: ["1111111111", "2222222222", "3333333333"], GONE: None})
        self.assertEqual(len(steam.collection_calls()), 1)
        self.assertEqual(steam.comment_calls(), [])
        self.assertIn(f"Steam returned no public collection {GONE}.", done.problems)
        with closing(workshop.connect(self.cache)) as conn:
            self.assertEqual(conn.execute("SELECT description FROM item WHERE id = '2222222222'").fetchone()[0],
                             "An old mod. Nothing floats here.")
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM collection WHERE collection_id = ?", (GOOD,)).fetchone()[0],
                             3)

    def test_a_fresh_collection_is_reused(self):
        self.refresh_collections(FakeSteamWithCollections(), ids=(GOOD,))
        again = FakeSteamWithCollections()
        done, children = self.refresh_collections(again, ids=(GOOD,), now=NOW + 3600)
        self.assertEqual(again.calls, [])
        self.assertEqual((done.reused, children[GOOD][0]), (1, "1111111111"))
        later = FakeSteamWithCollections()
        self.refresh_collections(later, ids=(GOOD,), now=NOW + 25 * 3600)
        self.assertEqual(len(later.collection_calls()), 1)

    def test_an_old_cache_gains_the_description_column(self):
        self.cache.mkdir(parents=True)
        with closing(sqlite3.connect(workshop.index_path(self.cache))) as old:
            old.execute("CREATE TABLE item (id TEXT PRIMARY KEY, fetched_at INTEGER NOT NULL, result INTEGER, title TEXT,"
                        " creator TEXT, time_created INTEGER, time_updated INTEGER, subscriptions INTEGER, favorited INTEGER,"
                        " visibility INTEGER, banned INTEGER, tags TEXT, comments_fetched_at INTEGER, comments_total INTEGER)")
            old.commit()
        with closing(workshop.connect(self.cache)) as conn:
            columns = {row[1] for row in conn.execute("PRAGMA table_info(item)")}
        self.assertLessEqual({"comments_note", "description"}, columns)


class Reports(CacheBase):
    def setUp(self):
        super().setUp()
        _, self.children = workshop.refresh_collections([GOOD, GONE], self.cache, post=FakeSteamWithCollections(),
                                                        clock=lambda: NOW)
        self.conn = workshop.connect(self.cache)

    def tearDown(self):
        self.conn.close()
        super().tearDown()

    def test_items_in_order_with_versions_and_openings(self):
        report = reports.collection(self.conn, self.children, "1.7")
        good, gone = report.sections
        self.assertEqual(good.heading, GOOD)  # the fake Steam has no details for the collection itself
        self.assertEqual([(r[0], r[1], r[4], r[5]) for r in good.table.rows],
                         [("1111111111", "Example Widgets", "yes",
                           "Example Widgets Adds hover widgets to the game. Guide"),
                          ("2222222222", "Example Old Mod", "no", "An old mod. Nothing floats here.")])
        text = render_markdown(report)
        self.assertIn("No public item for 3333333333", text)
        self.assertIn("Steam returned no public collection", text)
        self.assertEqual(gone.heading, GONE)

    def test_grep_keeps_matching_titles_or_descriptions(self):
        report = reports.collection(self.conn, {GOOD: self.children[GOOD]}, None, "*hover*")
        rows = report.sections[0].table.rows
        self.assertEqual([r[1] for r in rows], ["Example Widgets"])
        self.assertEqual(len(rows[0]), 5)  # no "Declares" column without a game version
        self.assertIn("1 of 3 items match", render_markdown(report))
        by_title = reports.collection(self.conn, {GOOD: self.children[GOOD]}, None, "*old mod*")
        self.assertEqual([r[0] for r in by_title.sections[0].table.rows], ["2222222222"])


class Commands(CacheBase):
    def run_core(self, *args, steam=None):
        out = io.StringIO()
        code = core_cli.main([*args, "--cache", str(self.cache)], environ={}, out=out,
                             post=steam or FakeSteamWithCollections(), pacer=self.sleeps.pacer(), clock=lambda: NOW)
        return code, out.getvalue()

    def test_collection_report_with_grep_and_json(self):
        code, text = self.run_core("collection", GOOD, "--grep", "*hover*")
        self.assertEqual(code, core_cli.EXIT_OK)
        self.assertIn("Example Widgets", text)
        self.assertNotIn("Example Old Mod", text)
        self.assertIn("items' details", text)
        data = json.loads(self.run_core("collection", GOOD, "--json")[1])
        self.assertEqual(data["report"]["title"], "Workshop collections")
        self.assertEqual(len(data["report"]["sections"][0]["blocks"][1]["rows"]), 2)

    def test_offline_reads_the_cached_collection(self):
        self.run_core("collection", f"https://steamcommunity.com/sharedfiles/filedetails/?id={GOOD}")

        def refuse(url, data):
            raise AssertionError("contacted Steam while offline")
        code, text = self.run_core("collection", GOOD, "--offline", steam=refuse)
        self.assertEqual(code, core_cli.EXIT_OK)
        self.assertIn("Example Old Mod", text)
        self.assertIn("From the cache only", text)

    def test_sql_sees_the_collection_table(self):
        self.run_core("collection", GOOD)
        self.assertIn("| 3 |", self.run_core("sql", f"SELECT COUNT(*) FROM collection WHERE collection_id = '{GOOD}'")[1])

    def test_rimworld_takes_ids_or_urls_only(self):
        out = io.StringIO()
        code = rimworld_cli.main(["collection", "Example Widgets", "--cache", str(self.cache), "--game", str(self.cache),
                                  "--workshop", str(self.cache), "--config", str(self.cache)], environ={}, out=out,
                                 post=FakeSteamWithCollections(), pacer=self.sleeps.pacer(), clock=lambda: NOW)
        self.assertEqual(code, core_cli.EXIT_USAGE)
        out = io.StringIO()
        code = rimworld_cli.main(["collection", GOOD, "--cache", str(self.cache), "--game", str(self.cache),
                                  "--workshop", str(self.cache), "--config", str(self.cache)], environ={}, out=out,
                                 post=FakeSteamWithCollections(), pacer=self.sleeps.pacer(), clock=lambda: NOW)
        self.assertEqual(code, core_cli.EXIT_OK)
        self.assertIn("Example Widgets", out.getvalue())


if __name__ == "__main__":
    unittest.main()
