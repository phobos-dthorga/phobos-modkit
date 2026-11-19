"""rimworld-code on made-up sources: names as targets are written, public source before a decompile, the decompiler's notes
left out with each line's own number, and which assembly declares a type."""
import io
import json
from pathlib import Path
import tempfile
import unittest

import support  # noqa: F401  (the package on the import path)
from phobos_modkit.code import compare
from phobos_modkit.games.rimworld import code_cli
from phobos_modkit.games.rimworld.code_cli import (DECOMPILE, SOURCE, corpora, holders, main, plain_name, show,
                                                   type_candidates)

# Written for these tests; no real source.
TURRET = """namespace Example.Vehicles
{
    public class Turret
    {
        // The author's own comment.
        public float Rotation(float aim)
        {
            return aim * 2f;
        }
    }
}
"""

DECOMPILED = """namespace Example.Vehicles
{
    public class Turret
    {
        public float Rotation(float aim)
        {
            //IL_0001: Unknown result type (might be due to invalid IL or missing references)
            return aim * 2f;
        }

        public void Fire()
        {
        }
    }
}
"""


class Names(unittest.TestCase):
    def test_targets_as_harmony_and_our_graph_write_them(self):
        self.assertEqual(plain_name(".GroundRearm.FindFallback"), "GroundRearm.FindFallback")
        self.assertEqual(plain_name("Verse.Pawn:Kill"), "Verse.Pawn.Kill")
        self.assertEqual(plain_name("Outer+Inner.Go"), "Outer.Inner.Go")
        self.assertEqual(type_candidates("Example.Turret.Fire"), ["Example.Turret.Fire", "Example.Turret"])
        self.assertEqual(type_candidates("Turret"), ["Turret"])


class Folders(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.root = self.base / "repo"
        self.clones = self.base / "clones"
        self.made = self.base / "cache" / compare.CACHE_FOLDER
        self.cache = self.base / "cache" / "code-index"
        (self.clones / "Vehicles-src" / "Source").mkdir(parents=True)
        (self.clones / "Vehicles-src" / "Source" / "Turret.cs").write_text(TURRET, encoding="utf-8")
        local = self.root / ".local" / "decompiled" / "Vehicles"
        local.mkdir(parents=True)
        (local / "Turret.cs").write_text(DECOMPILED, encoding="utf-8")
        done = self.made / "Vehicles-0123456789abcdef"
        done.mkdir(parents=True)
        (done / "Turret.cs").write_text(DECOMPILED, encoding="utf-8")
        (done / compare.COMPLETE_MARKER).write_text(json.dumps({"source": "Vehicles.dll"}), encoding="utf-8")
        unfinished = self.made / "Other-fedcba9876543210.building"
        unfinished.mkdir()
        (unfinished / "Other.cs").write_text("class Other {}", encoding="utf-8")

    def tearDown(self):
        self.temp.cleanup()

    def test_places_public_source_first_and_skips_an_unfinished_decompile(self):
        places = corpora(self.root, self.clones, self.made)
        self.assertEqual([kind for _, kind in places], [SOURCE, DECOMPILE, DECOMPILE])
        self.assertTrue(places[2][0].name.startswith("Vehicles (decompiled 01234567"))

    def test_public_source_answers_alone_when_it_has_the_name(self):
        found = show("Example.Vehicles.Turret.Rotation", corpora(self.root, self.clones, self.made), self.cache, 400)
        self.assertEqual([f["source"] for f in found], [SOURCE])
        self.assertIn("// The author's own comment.", "\n".join(TURRET.splitlines()[:5]))
        self.assertEqual(found[0]["file"], "Source/Turret.cs")
        self.assertEqual(found[0]["numbers"][0], found[0]["start"])

    def test_a_decompile_answers_what_the_source_lacks_without_its_notes(self):
        found = show("Turret.Fire", corpora(self.root, self.clones, self.made), self.cache, 400)
        self.assertEqual([f["source"] for f in found], [DECOMPILE, DECOMPILE])
        rotation = show("Turret:Rotation", corpora(self.root, None, self.made), self.cache, 400)[0]
        self.assertFalse(any("//IL_" in line for line in rotation["lines"]))
        self.assertEqual(len(rotation["lines"]), len(rotation["numbers"]))
        self.assertIn(rotation["start"] + 3, rotation["numbers"])           # the line after the note keeps its number
        self.assertNotIn(rotation["start"] + 2, rotation["numbers"])

    def test_show_as_json_names_what_it_found_and_where_it_looked(self):
        out = io.StringIO()
        code = main(["show", "Turret.Rotation", "--root", str(self.root), "--clones", str(self.clones),
                     "--cache", str(self.base / "cache"), "--json"], environ={}, out=out)
        self.assertEqual(code, code_cli.EXIT_OK)
        data = json.loads(out.getvalue())
        self.assertEqual(data["data"]["looked_in"], 3)
        self.assertEqual(data["report"]["facts"][0], {"label": "From", "value": "their public source"})

    def test_a_name_nowhere_kept_says_so(self):
        out = io.StringIO()
        main(["show", "Nowhere.Thing", "--root", str(self.root), "--cache", str(self.base / "cache"), "--json"],
             environ={}, out=out)
        data = json.loads(out.getvalue())
        self.assertEqual(data["data"]["found"], [])
        self.assertIn("Decompile the assembly", data["report"]["lines"][0])


class Holders(unittest.TestCase):
    def test_the_type_a_member_belongs_to_and_its_mod(self):
        class Entry:
            class mod:
                name = "Example Vehicles"
        records = [{"type": "Example.Vehicles.Turret", "assembly": "Vehicles", "path": "M/Vehicles.dll"},
                   {"type": "Example.Base", "assembly": "Vehicles", "path": "M/Vehicles.dll"},
                   {"type": "Verse.Thing", "assembly": "Assembly-CSharp", "path": "G/Assembly-CSharp.dll"}]
        found = holders("Turret.Rotation", records, {"M/Vehicles.dll": Entry}, [Path("G/Assembly-CSharp.dll")])
        self.assertEqual(found, [{"type": "Example.Vehicles.Turret", "assembly": "Vehicles", "path": "M/Vehicles.dll",
                                  "mod": "Example Vehicles"}])
        game = holders("Verse.Thing", records, {}, [Path("G/Assembly-CSharp.dll")])
        self.assertEqual(game[0]["mod"], "the game")
        self.assertEqual(holders("Nothing.Here", records, {}, []), [])

    def test_decompile_refuses_what_is_not_an_assembly(self):
        out = io.StringIO()
        with tempfile.TemporaryDirectory() as temp:
            code = main(["decompile", "--assembly", str(Path(temp) / "missing.dll"), "--cache", temp, "--json"],
                        environ={}, out=out)
        self.assertEqual(code, code_cli.EXIT_FAILED)
        self.assertFalse(json.loads(out.getvalue())["data"]["ok"])


if __name__ == "__main__":
    unittest.main()
