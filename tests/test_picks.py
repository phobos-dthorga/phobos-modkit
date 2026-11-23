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
