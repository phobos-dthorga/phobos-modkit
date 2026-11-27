"""steam-reviews (1.143.0): review counts and the newest reviews of a game or a DLC, from stand-in Steam pages; nothing online."""
import io
import json
import tempfile
import unittest

import support
from phobos_modkit.steam import reviews

CARD = """<div data-panel="x" role="button" class="apphub_Card modalContentLink interactable" style="display: none">
 <div class="vote_header"><div class="reviewInfo"><div class="thumb"></div>
 <div class="title">{title}</div>
 <div class="hours">{hours} hrs on record</div></div></div>
 <div class="apphub_CardTextContent">
 <div class="date_posted">Posted: {posted}</div>
 {words} </div>
 <div class="apphub_CardContentAuthorName"><a href="https://steamcommunity.com/profiles/1/">Someone</a></div>
</div>"""


def page(*cards):
    return "<div>" + "".join(CARD.format(**c) for c in cards) + "</div>"


class Steam:
    """A stand-in Steam: the game 100 with DLC 101 ("Game - Royal Things") and 102 ("Game Soundtrack")."""

    def __init__(self):
        self.asked = []

    def __call__(self, url):
        self.asked.append(url)
        if "appdetails?appids=100&" in url:
            return json.dumps({"100": {"success": True, "data": {"name": "Game", "dlc": [101, 102]}}})
        if "appdetails?appids=101&" in url:
            return json.dumps({"101": {"success": True, "data": {"name": "Game - Royal Things"}}})
        if "appdetails?appids=102&" in url:
            return json.dumps({"102": {"success": True, "data": {"name": "Game Soundtrack"}}})
        if "appreviewhistogram/100" in url:
            return json.dumps({"results": {"rollups": [{"recommendations_up": 90, "recommendations_down": 10}],
                                           "recent": [{"recommendations_up": 3, "recommendations_down": 1}]}})
        if "appreviewhistogram/101" in url:
            return json.dumps({"results": {"rollups": [{"recommendations_up": 8, "recommendations_down": 2}], "recent": []}})
        if "/app/100/homecontent/" in url and "&p=1&" in url:
            return page({"title": "Not Recommended", "hours": "12.5", "posted": "27 November", "words": "Crashes on &amp; load"},
                        {"title": "Recommended", "hours": "1,482", "posted": "26 November", "words": "<b>Great</b>"})
        if "/homecontent/" in url:
            return "<div></div>"
        if "appreviews/" in url:
            return "<!DOCTYPE html>"
        raise AssertionError(url)


class Reviews(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.environ = support.isolated_environ(self.tmp.name)
        self.steam = Steam()

    def run_main(self, *argv):
        out = io.StringIO()
        code = reviews.main([*argv, "--json"], out, self.environ, self.steam, sleep=lambda s: None)
        return code, json.loads(out.getvalue())

    def test_the_game_counts_its_reviews_and_reads_the_newest_without_names(self):
        code, answer = self.run_main("--app-id", "100")
        data = answer["data"]
        self.assertEqual((code, data["name"], data["dlc"]), (0, "Game", False))
        self.assertEqual((data["allShare"], data["recentShare"], data["read"]), (90, 75, 2))
        first = data["reviews"][0]
        self.assertEqual((first["recommended"], first["hours"], first["posted"], first["words"]),
                         (False, 12.5, "27 November", "Crashes on & load"))
        self.assertEqual(data["reviews"][1]["hours"], 1482.0)
        self.assertNotIn("Someone", json.dumps(answer))
        self.assertIn("1 do not recommend it", json.dumps(answer["report"]))

    def test_a_dlc_is_found_by_its_name_and_gives_its_counts_alone(self):
        code, answer = self.run_main("--app-id", "100", "--match", "Royal")
        data = answer["data"]
        self.assertEqual((data["app"], data["name"], data["dlc"], data["allShare"]), (101, "Game - Royal Things", True, 80))
        self.assertEqual(data["reviews"], [])
        self.assertFalse(any("/homecontent/" in u for u in self.steam.asked))
        # The DLC's names are kept for a week: a second look asks the store for the game alone.
        before = sum("appdetails" in u for u in self.steam.asked)
        self.run_main("--app-id", "100", "--match", "Royal")
        self.assertEqual(sum("appdetails" in u for u in self.steam.asked) - before, 1)

    def test_a_name_no_dlc_holds_is_the_game_itself(self):
        code, answer = self.run_main("--app-id", "100", "--match", "Core")
        self.assertEqual((answer["data"]["app"], answer["data"]["dlc"]), (100, False))

    def test_a_page_where_data_should_be_is_said_so(self):
        def broken(url):
            return "<!DOCTYPE html><html>"
        out = io.StringIO()
        code = reviews.main(["--app-id", "100", "--json"], out, self.environ, broken, sleep=lambda s: None)
        answer = json.loads(out.getvalue())
        self.assertEqual((code, answer["data"]["ok"]), (reviews.EXIT_FAILED, False))
        self.assertIn("a page, not data", answer["data"]["refusal"])


if __name__ == "__main__":
    unittest.main()
