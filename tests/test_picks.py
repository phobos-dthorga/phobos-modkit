"""picks: the pictures and sounds waiting for the owner from config/picks.json, and the owner's picks (1.83.0)."""
import io
import json
from pathlib import Path
import tempfile
import unittest
import unittest.mock

import support  # noqa: F401  (puts the package on the path)
from phobos_modkit import picks


def kettle(tries=("3", "4")):
    return {"id": "billy-kettle", "title": "The billy kettle", "kind": "picture", "inUse": "mods/Thing/Kettle.png",
            "tries": [{"id": t, "label": f"Try {t}", "path": f"tries/kettle-{t}.png"} for t in tries],
            "context": "A redraw.", "from": "assets/thing/requests/redraw.json"}


class PicksTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "sample-repo"
        (self.root / "tries").mkdir(parents=True)
        (self.root / "tries" / "kettle-3.png").write_bytes(b"png")
        self.environ = {"PHOBOS_PICKS": str(Path(self.temp.name) / "answers")}

    def tearDown(self):
        self.temp.cleanup()

    def test_a_repository_with_no_picks_file_waits_on_nothing(self):
        self.assertEqual(picks.listed(self.root, self.environ), ([], []))

    def test_an_offer_is_listed_with_its_files_made_absolute_and_found(self):
        picks.offer(self.root, kettle(), grounds=[{"name": "Soil", "colour": "#5c4c3a"}, {"name": "Bad", "colour": "red"}])
        grounds, found = picks.listed(self.root, self.environ)
        self.assertEqual(grounds, [{"name": "Soil", "colour": "#5C4C3A"}])
        pick = found[0]
        self.assertEqual([(t["id"], t["there"]) for t in pick["tries"]], [("3", True), ("4", False)])
        self.assertTrue(Path(pick["tries"][0]["path"]).is_absolute())
        self.assertFalse(pick["inUseThere"])
        self.assertTrue(pick["asked"])

    def test_offering_again_replaces_and_settling_removes(self):
        picks.offer(self.root, kettle())
        picks.offer(self.root, kettle(tries=("5",)))
        self.assertEqual([t["id"] for t in picks.listed(self.root, self.environ)[1][0]["tries"]], ["5"])
        picks.settle(self.root, "billy-kettle")
        self.assertEqual(picks.listed(self.root, self.environ)[1], [])
        with self.assertRaises(picks.PickError):
            picks.settle(self.root, "billy-kettle")

    def test_a_sound_never_replaces_a_picture_of_the_same_id(self):
        picks.offer(self.root, kettle())
        with self.assertRaises(picks.PickError) as caught:
            picks.offer(self.root, {**kettle(), "kind": "sound"})
        self.assertIn("already waiting as a picture", str(caught.exception))
        self.assertEqual([p["kind"] for p in picks.listed(self.root, self.environ)[1]], ["picture"])

    def test_the_file_is_swapped_in_again_while_another_program_holds_it(self):
        real, calls = Path.replace, []

        def held_once(self_path, target):
            calls.append(target)
            if len(calls) == 1:
                raise PermissionError(5, "Access is denied")
            return real(self_path, target)

        with unittest.mock.patch.object(Path, "replace", held_once):
            picks.offer(self.root, kettle())
        self.assertEqual(len(calls), 2)
        self.assertEqual([p["id"] for p in picks.listed(self.root, self.environ)[1]], ["billy-kettle"])

    def test_the_last_answer_decides_and_answered_picks_come_last(self):
        picks.offer(self.root, kettle())
        picks.offer(self.root, {**kettle(), "id": "tent-lamp", "kind": "sound"})
        picks.answer(self.root, "billy-kettle", "3", environ=self.environ)
        picks.answer(self.root, "billy-kettle", "none", "the spout is still hidden", environ=self.environ)
        found = picks.listed(self.root, self.environ)[1]
        self.assertEqual([p["id"] for p in found], ["tent-lamp", "billy-kettle"])
        self.assertEqual((found[1]["answer"]["pick"], found[1]["answer"]["words"]), ("none", "the spout is still hidden"))

    def test_an_unknown_pick_or_try_and_a_malformed_offer_are_refused(self):
        picks.offer(self.root, kettle())
        with self.assertRaises(picks.PickError):
            picks.answer(self.root, "billy-kettle", "9", environ=self.environ)
        with self.assertRaises(picks.PickError):
            picks.answer(self.root, "nothing", "3", environ=self.environ)
        for bad in ({**kettle(), "kind": "video"}, {**kettle(), "tries": []}, {**kettle(), "id": "Bad Id"},
                    {**kettle(), "tries": [{"id": "none", "path": "x.png"}]}):
            with self.assertRaises(picks.PickError):
                picks.offer(self.root, bad)

    def test_the_command_lists_offers_and_answers(self):
        offered = Path(self.temp.name) / "pick.json"
        offered.write_text(json.dumps(kettle()), encoding="utf-8")
        out = io.StringIO()
        self.assertEqual(picks.main(["offer", "--root", str(self.root), "--file", str(offered), "--json"], out, self.environ), 0)
        out = io.StringIO()
        self.assertEqual(picks.main(["answer", "--root", str(self.root), "--id", "billy-kettle", "--pick", "3", "--json"], out,
                                    self.environ), 0)
        out = io.StringIO()
        picks.main(["list", "--root", str(self.root), "--json"], out, self.environ)
        data = json.loads(out.getvalue())["data"]
        self.assertEqual((data["waiting"], data["repositories"][0]["picks"][0]["answer"]["pick"]), (0, "3"))
        out = io.StringIO()
        self.assertEqual(picks.main(["answer", "--root", str(self.root), "--id", "x", "--pick", "3", "--json"], out, self.environ),
                         picks.EXIT_REFUSED)

    def test_the_owners_words_are_shown_with_the_pick(self):
        # 1.123.1: the list showed "PICKED none" without the reason the owner gave, so nobody read it.
        picks.offer(self.root, kettle())
        picks.answer(self.root, "billy-kettle", "none", "white left in the centre of try 4", environ=self.environ)
        out = io.StringIO()
        picks.main(["list", "--root", str(self.root)], out, self.environ)
        self.assertIn('PICKED none: "white left in the centre of try 4"', out.getvalue())


class RoundTwoTests(unittest.TestCase):
    """Round two (1.125.0): one pick per file, picks in the game settled by themselves, every listed repository, settle said."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        base = Path(self.temp.name)
        self.root = base / "sample-repo"
        (self.root / "tries").mkdir(parents=True)
        (self.root / "mods").mkdir()
        for name, data in (("a-1.png", b"one"), ("a-2.png", b"two"), ("b-1.png", b"three")):
            (self.root / "tries" / name).write_bytes(data)
        self.environ = {"PHOBOS_PICKS": str(base / "answers"), "PHOBOS_COMPANION_GAMES": str(base / "games.json")}

    def tearDown(self):
        self.temp.cleanup()

    def card(self, pick_id, tries, slot="mods/Purge.png"):
        return {"id": pick_id, "title": pick_id, "kind": "picture", "inUse": "mods/Purge.png", "slot": slot,
                "tries": [{"id": t, "path": f"tries/{pick_id}-{t}.png"} for t in tries]}

    def test_answering_one_card_answers_the_others_of_its_slot(self):
        picks.offer(self.root, self.card("a", ["1", "2"]))
        picks.offer(self.root, self.card("b", ["1"]))
        picks.offer(self.root, self.card("c", ["1"], slot="mods/Other.png"))
        line = picks.answer(self.root, "a", "2", environ=self.environ)
        self.assertEqual(line["alsoAnswered"], ["b"])
        found = {p["id"]: p for p in picks.listed(self.root, self.environ)[1]}
        self.assertEqual(found["b"]["answer"]["pick"], "none")
        self.assertIn("picked in a: 2", found["b"]["answer"]["words"])
        self.assertIsNone(found["c"]["answer"])

    def test_a_slot_must_be_inside_the_repository(self):
        for bad in ("../x.png", "C:/x.png"):
            with self.assertRaises(picks.PickError):
                picks.check_pick(self.card("a", ["1"], slot=bad))

    def test_a_picked_try_that_is_the_file_in_use_is_in_the_game_and_settles_by_itself(self):
        picks.offer(self.root, self.card("a", ["1", "2"]))
        picks.offer(self.root, self.card("b", ["1"]))
        picks.answer(self.root, "a", "2", environ=self.environ)
        self.assertFalse(picks.listed(self.root, self.environ)[1][0]["inGame"])
        (self.root / "mods" / "Purge.png").write_bytes(b"two")
        found = {p["id"]: p for p in picks.listed(self.root, self.environ)[1]}
        self.assertTrue(found["a"]["inGame"])
        self.assertFalse(found["b"]["inGame"], "a card answered none is never in the game itself")
        settled = picks.settle_applied(self.root, self.environ)
        self.assertEqual([pick_id for pick_id, _ in settled], ["a", "b"])
        self.assertEqual(picks.listed(self.root, self.environ)[1], [])
        self.assertEqual(picks.settle_applied(self.root, self.environ), [])

    def test_settle_says_what_it_settled_and_why_it_refused(self):
        picks.offer(self.root, self.card("a", ["1"], slot=None))
        picks.answer(self.root, "a", "1", environ=self.environ)
        out = io.StringIO()
        self.assertEqual(picks.main(["settle", "--root", str(self.root), "--id", "a"], out=out, environ=self.environ), 0)
        self.assertIn("Settled a (picked 1)", out.getvalue())
        out = io.StringIO()
        self.assertEqual(picks.main(["settle", "--root", str(self.root), "--id", "a"], out=out, environ=self.environ), 3)
        self.assertIn("settled already", out.getvalue())

    def test_list_with_no_root_reads_every_repository_on_the_games_list_and_says_so(self):
        other = Path(self.temp.name) / "no-picks-repo"
        other.mkdir()
        picks.offer(self.root, self.card("a", ["1"], slot=None))
        Path(self.environ["PHOBOS_COMPANION_GAMES"]).write_text(json.dumps(
            {"games": [{"id": "g", "name": "G", "repositories": [str(self.root), str(other)]}]}), encoding="utf-8")
        out = io.StringIO()
        self.assertEqual(picks.main(["list", "--json"], out=out, environ=self.environ), 0)
        data = json.loads(out.getvalue())["data"]
        self.assertEqual(data["readFrom"], "games list")
        self.assertEqual(data["waiting"], 1)
        self.assertEqual([r["hasFile"] for r in data["repositories"]], [True, False])
        out = io.StringIO()
        picks.main(["list"], out=out, environ=self.environ)
        self.assertIn("no-picks-repo (no config/picks.json)", out.getvalue())
