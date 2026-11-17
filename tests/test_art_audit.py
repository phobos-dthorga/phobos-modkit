"""art-audit: images paired with their records, classed by how they were made, and borrowed pictures. Every file is written here."""
import io
import json
from pathlib import Path
import tempfile
import unittest

import support  # noqa: F401  (puts the package on the path)
from phobos_modkit import artaudit, artaudit_cli
from phobos_modkit.games.rimworld import art as rimworld_art

CONFIG = {
    "game": "rimworld",
    "images": ["mods/*/**/Textures/**/*.png"],
    "groupBy": ["mods/*", "src/*"],
    "records": {"suffixes": [".record.md", ".export.json"]},
    "kinds": [
        {"kind": "generated", "label": "Generated", "patterns": ["AI-generated", "\\bFLUX\\b", "/generated/"]},
        {"kind": "code-drawn", "label": "Drawn in code", "listed": True, "patterns": ["drawn in code", "drawn with Pillow"]},
    ],
    "standIn": ["\\*\\*A stand-in"],
    "defs": ["mods/*/**/Defs/**/*.xml", "mods/*/**/Patches/**/*.xml"],
    "code": ["src/**/*.cs"],
    "commonWords": ["phobos", "vehicles", "things", "icons", "blueprint", "base"],
    "accepted": [
        {"texture": "Phobos/Vehicles/Crawler/*", "owner": "*TestHull*", "reason": "dev-only hull"},
        {"texture": "UI/Buttons/*", "reason": "the game's buttons, in place"},
        {"image": "mods/ModA/Textures/Phobos/Things/Frost.png", "reason": "drawn in code by design"},
    ],
}

FILES = {
    # Bowser: a multi-facing body with masks, one record for all of it.
    "mods/ModA/Textures/Phobos/Vehicles/Bowser/Bowser_north.png": "",
    "mods/ModA/Textures/Phobos/Vehicles/Bowser/Bowser_northm.png": "",
    "mods/ModA/Textures/Phobos/Vehicles/Bowser/Bowser_Hose_east.png": "",
    "mods/ModA/Textures/Phobos/Vehicles/Bowser/Bowser.record.md":
        "# Bowser\n\n**AI-generated**, with FLUX. Its reference was our own stand-in, drawn in code.\n",
    "mods/ModA/Textures/Phobos/Vehicles/Crawler/Crawler_south.png": "",
    "mods/ModA/Textures/Phobos/Vehicles/Crawler/Crawler.record.md": "**AI-generated**.\n",
    # A code-drawn icon whose record mentions the generated art that may replace it.
    "mods/ModA/Textures/Phobos/Icons/Winch.png": "",
    "mods/ModA/Textures/Phobos/Icons/Winch.record.md":
        "**Drawn in code** by `draw.py` (Pillow). AI-generated art can replace it later.\n",
    # An icon shared by name: two loadouts whose names match nothing in its path.
    "mods/ModA/Textures/Phobos/Icons/Lamp.png": "",
    "mods/ModA/Textures/Phobos/Icons/Lamp.record.md": "**AI-generated**.\n",
    # A generated picture the record calls a stand-in.
    "mods/ModA/Textures/Phobos/Things/Whip.png": "",
    "mods/ModA/Textures/Phobos/Things/Whip.record.md": "**AI-generated**.\n\n**A stand-in:** a mast, used for the whip.\n",
    # An export record only beside the image, the Markdown under a shorter name.
    "mods/ModA/Textures/Phobos/Things/Bed_south.png": "",
    "mods/ModA/Textures/Phobos/Things/Bed_south.export.json": json.dumps({"source": "assets/x/bed-12.png"}),
    "mods/ModA/Textures/Phobos/Things/Bed.record.md": "Made with FLUX.\n",
    # A folder record, an accepted image and an image with no record at all.
    "mods/ModA/Textures/Phobos/Atlas/Pipe_Atlas.png": "",
    "mods/ModA/Textures/Phobos/Atlas/Atlas.record.md": "Drawn with Pillow by a script.\n",
    "mods/ModA/Textures/Phobos/Things/Frost.png": "",
    "mods/ModA/Textures/Phobos/Things/Frost.record.md": "**Drawn in code** by `frost.py`.\n",
    "mods/ModB/Common/Textures/Phobos/Things/Mystery.png": "",
    "mods/ModB/Common/Textures/Phobos/Things/Odd.png": "",
    "mods/ModB/Common/Textures/Phobos/Things/Odd.record.md": "Painted by hand.\n",
    "mods/ModA/Defs/Vehicles.xml": """<?xml version="1.0" encoding="utf-8"?>
<Defs>
  <!-- <texPath>Phobos/Vehicles/Crawler/Crawler</texPath> in a comment is not a use -->
  <VehicleDef Name="PhobosBowserBase" Abstract="True">
    <graphicData><texPath>Phobos/Vehicles/Bowser/Bowser</texPath></graphicData>
  </VehicleDef>
  <VehicleDef ParentName="PhobosBowserBase"><defName>Phobos_FuelBowser</defName></VehicleDef>
  <VehicleDef ParentName="PhobosBowserBase"><defName>Phobos_ShowerTrailer</defName></VehicleDef>
  <VehicleDef ParentName="PhobosBowserBase">
    <defName>Phobos_Tipper</defName>
    <graphicData><texPath>Phobos/Vehicles/Crawler/Crawler</texPath></graphicData>
  </VehicleDef>
  <VehicleDef><defName>Phobos_Crawler</defName><graphicData><texPath>Phobos/Vehicles/Crawler/Crawler</texPath></graphicData></VehicleDef>
  <VehicleDef><defName>Phobos_TestHull</defName><graphicData><texPath>Phobos/Vehicles/Crawler/Crawler</texPath></graphicData></VehicleDef>
  <VehicleBuildDef><defName>Phobos_FuelBowser_Blueprint</defName><graphicData><texPath>Phobos/Vehicles/Bowser/Bowser</texPath></graphicData></VehicleBuildDef>
  <LoadoutDef><defName>PhobosLoadout_Land</defName><icon>Phobos/Icons/Lamp</icon></LoadoutDef>
  <LoadoutDef><defName>PhobosLoadout_Sea</defName><icon>Phobos/Icons/Lamp</icon></LoadoutDef>
  <UpgradeTreeDef>
    <defName>Phobos_Bowser_UpgradeTree</defName>
    <nodes>
      <li><key>HoseReel</key><icon>Phobos/Vehicles/Bowser/Bowser_Hose</icon></li>
    </nodes>
  </UpgradeTreeDef>
  <ThingDef><defName>Phobos_TentLamp</defName><graphicData><texPath>Things/Building/Furniture/LampStanding</texPath></graphicData></ThingDef>
  <SoundDef><defName>Phobos_Pump</defName><subSounds><li><clipPath>Phobos/Vehicles/Bowser</clipPath></li></subSounds></SoundDef>
</Defs>
""",
    "mods/ModA/Patches/Winch.xml": """<?xml version="1.0" encoding="utf-8"?>
<Patch>
  <Operation Class="PatchOperationAdd">
    <xpath>Defs/ThingDef[defName="Phobos_Winch"]</xpath>
    <value><uiIconPath>Phobos/Icons/Winch</uiIconPath></value>
  </Operation>
</Patch>
""",
    "mods/ModA/Defs/Broken.xml": "<Defs><ThingDef>",
    "src/ModA/Gizmos.cs": """namespace Phobos {
    // ContentFinder<Texture2D>.Get("Commented/Out") is not a use
    public static class Gizmos {
        static readonly Texture2D Plus = ContentFinder<Texture2D>.Get("UI/Buttons/Plus");
        static readonly Texture2D Grab = ContentFinder<Texture2D>.Get("Phobos/Icons/Winch");
        const string Lamp = "Phobos/Icons/Lamp";
    }
}
""",
}


class Repo:
    def __init__(self, config=CONFIG, files=FILES):
        self.folder = tempfile.TemporaryDirectory()
        self.root = Path(self.folder.name)
        for rel, text in files.items():
            path = self.root / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(text.encode("utf-8"))
        if config is not None:
            (self.root / "config").mkdir(exist_ok=True)
            (self.root / "config" / "art-audit.json").write_text(json.dumps(config), encoding="utf-8")

    def close(self):
        self.folder.cleanup()


class ImageNames(unittest.TestCase):
    def test_facing_mask_and_folder(self):
        names = rimworld_art.image_names("mods/A/1.7/Textures/Phobos/Vehicles/Bowser/Bowser_northm.png")
        self.assertEqual(names, ["Phobos/Vehicles/Bowser/Bowser_northm", "Phobos/Vehicles/Bowser/Bowser",
                                 "Phobos/Vehicles/Bowser"])

    def test_a_word_ending_in_m_keeps_it(self):
        self.assertEqual(rimworld_art.image_names("mods/A/Textures/Steam.png"), ["Steam"])

    def test_outside_textures_has_no_names(self):
        self.assertEqual(rimworld_art.image_names("assets/x/Steam.png"), [])


class Pairing(unittest.TestCase):
    def test_candidates_run_from_the_stem_to_the_folder(self):
        self.assertEqual(artaudit.candidates("a/Tank/Tank_Damage_east.png"),
                         [("Tank_Damage_east", "own"), ("Tank_Damage", "prefix"), ("Tank", "prefix"), ("Tank", "folder")])

    def test_classify_takes_the_first_statement(self):
        kinds = artaudit.kinds_of(CONFIG)
        self.assertEqual(artaudit.classify("**Drawn in code** (Pillow). AI-generated art may replace it.", kinds)[0],
                         "code-drawn")
        self.assertEqual(artaudit.classify("**AI-generated**; its reference was drawn in code.", kinds)[0], "generated")
        self.assertEqual(artaudit.classify("Painted by hand.", kinds), (artaudit.UNCLASSIFIED, ""))

    def test_a_bad_pattern_is_reported(self):
        with self.assertRaises(artaudit.ArtAuditError):
            artaudit.kinds_of({"kinds": [{"kind": "x", "patterns": ["("]}]})

    def test_an_accepted_entry_needs_a_reason(self):
        with self.assertRaises(artaudit.ArtAuditError):
            artaudit.accepted_of({"accepted": [{"image": "*.png"}]})


class Audit(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.repo = Repo()
        cls.result = artaudit.audit(cls.repo.root, artaudit.load_config(cls.repo.root))
        cls.images = {Path(i.path).name: i for i in cls.result.images}

    @classmethod
    def tearDownClass(cls):
        cls.repo.close()

    def uses(self, owner, texture=None):
        return [u for u in self.result.uses if u.owner == owner and (texture is None or u.texture == texture)]

    def test_images_pair_and_class(self):
        self.assertEqual(len(self.result.images), 12)
        mask = self.images["Bowser_northm.png"]
        self.assertEqual((mask.kind, mask.paired_by, mask.group), ("generated", "prefix", "ModA"))
        self.assertEqual(self.images["Bowser_Hose_east.png"].records,
                         ["mods/ModA/Textures/Phobos/Vehicles/Bowser/Bowser.record.md"])
        self.assertEqual(self.images["Winch.png"].kind, "code-drawn")
        self.assertEqual((self.images["Pipe_Atlas.png"].kind, self.images["Pipe_Atlas.png"].paired_by),
                         ("code-drawn", "folder"))
        self.assertEqual(self.images["Mystery.png"].kind, artaudit.NO_RECORD)
        self.assertEqual(self.images["Odd.png"].kind, artaudit.UNCLASSIFIED)

    def test_every_record_is_read_markdown_first(self):
        bed = self.images["Bed_south.png"]
        self.assertEqual(bed.paired_by, "own")
        self.assertEqual(bed.records, ["mods/ModA/Textures/Phobos/Things/Bed_south.export.json",
                                       "mods/ModA/Textures/Phobos/Things/Bed.record.md"])
        self.assertEqual(bed.kind, "generated")

    def test_a_record_calling_its_image_a_stand_in(self):
        self.assertIn("A stand-in", self.images["Whip.png"].stand_in)
        self.assertEqual(self.images["Bowser_north.png"].stand_in, "")

    def test_accepted_image(self):
        self.assertEqual(self.images["Frost.png"].accepted, "drawn in code by design")

    def test_inherited_texture_is_borrowed_by_an_unrelated_child(self):
        shower = self.uses("Phobos_ShowerTrailer")
        self.assertEqual(len(shower), 1)
        self.assertEqual((shower[0].status, shower[0].inherited_from), (artaudit.BORROWED, "PhobosBowserBase"))
        self.assertEqual(shower[0].owners, ["Phobos_FuelBowser", "Phobos_FuelBowser_Blueprint"])
        self.assertEqual(self.uses("Phobos_FuelBowser")[0].status, artaudit.OWN)
        self.assertEqual(self.uses("Phobos_FuelBowser_Blueprint")[0].status, artaudit.OWN)
        self.assertEqual(self.uses("PhobosBowserBase"), [], "an abstract parent with children is reported through them")

    def test_a_child_writing_the_field_does_not_inherit_it(self):
        tipper = self.uses("Phobos_Tipper")
        self.assertEqual([u.texture for u in tipper], ["Phobos/Vehicles/Crawler/Crawler"])
        self.assertEqual(tipper[0].status, artaudit.BORROWED)

    def test_accepted_borrowing(self):
        hull = self.uses("Phobos_TestHull")[0]
        self.assertEqual((hull.status, hull.accepted), (artaudit.BORROWED, "dev-only hull"))
        self.assertEqual(self.uses("Phobos_Tipper")[0].accepted, "")

    def test_shared_when_no_name_matches(self):
        self.assertEqual({u.status for u in self.uses("PhobosLoadout_Land") + self.uses("PhobosLoadout_Sea")},
                         {artaudit.SHARED})

    def test_list_items_name_their_part(self):
        node = self.uses("Phobos_Bowser_UpgradeTree")[0]
        self.assertEqual((node.part, node.field, node.status), ("HoseReel", "nodes/li/icon", artaudit.OWN))

    def test_not_ours_and_sounds(self):
        lamp = self.uses("Phobos_TentLamp")[0]
        self.assertEqual((lamp.status, lamp.images), (artaudit.NOT_OURS, []))
        self.assertEqual(self.uses("Phobos_Pump"), [], "a sound clip's folder is not a picture")

    def test_patches_and_comments(self):
        winch = self.uses("Phobos_Winch")
        self.assertEqual([(u.owner_type, u.texture) for u in winch], [("Patch", "Phobos/Icons/Winch")])
        self.assertTrue(any("Broken.xml" in line for line in self.result.unreadable))
        self.assertFalse([u for u in self.result.uses if "Commented" in u.texture])

    def test_code_is_judged_only_on_whether_the_picture_is_ours(self):
        code = {u.texture: u for u in self.uses("Gizmos")}
        self.assertEqual(set(code), {"UI/Buttons/Plus", "Phobos/Icons/Winch", "Phobos/Icons/Lamp"})
        self.assertEqual(code["UI/Buttons/Plus"].accepted, "the game's buttons, in place")
        self.assertEqual(code["Phobos/Icons/Winch"].status, artaudit.SHARED)
        self.assertEqual(code["Phobos/Icons/Winch"].group, "ModA")


class Command(unittest.TestCase):
    def setUp(self):
        self.repo = Repo()

    def tearDown(self):
        self.repo.close()

    def run_cli(self, *argv):
        out = io.StringIO()
        code = artaudit_cli.main([argv[0], "--root", str(self.repo.root), *argv[1:]], out=out)
        return code, out.getvalue()

    def test_report(self):
        code, text = self.run_cli("report")
        self.assertEqual(code, 0)
        self.assertIn("# Art audit: 12 images; 2 drawn in code, 1 without a record, 3 borrowed pictures open", text)
        self.assertIn("## Drawn in code", text)
        self.assertIn("Icons/Winch.png", text)
        self.assertNotIn("Things/Frost.png", text.split("## By mod")[0], "accepted images are left out without --all")
        self.assertIn("## Called a stand-in, made another way", text)
        self.assertIn("## A record no rule recognises", text)
        self.assertIn("Phobos_ShowerTrailer, from PhobosBowserBase", text)
        self.assertIn("LampStanding", text)
        self.assertIn("Unclassified: 1; No record: 1.", text)
        self.assertIn("1 file could not be read", text)

    def test_all_lists_accepted(self):
        code, text = self.run_cli("report", "--all")
        self.assertIn("## Borrowed pictures, accepted", text)
        self.assertIn("dev-only hull", text)
        self.assertIn("## Images accepted as they are", text)

    def test_kind_and_mod_filters(self):
        code, text = self.run_cli("report", "--kind", "no-record", "--mod", "modb")
        self.assertIn("Mystery.png", text)
        self.assertNotIn("Winch.png", text)
        self.assertEqual(self.run_cli("report", "--kind", "painted")[0], artaudit_cli.EXIT_USAGE)

    def test_json_envelope(self):
        code, text = self.run_cli("report", "--json")
        data = json.loads(text)
        self.assertEqual((data["tool"], data["envelope"]), ("art-audit", 1))
        self.assertEqual(len(data["data"]["images"]), 12)
        self.assertIn("borrowed", {u["status"] for u in data["data"]["uses"]})

    def test_check_fails_on_an_image_without_a_record(self):
        code, text = self.run_cli("check")
        self.assertEqual(code, artaudit_cli.EXIT_FAILED)
        self.assertIn("Mystery.png", text)
        self.assertEqual(self.run_cli("check", "--mod", "ModA")[0], artaudit_cli.EXIT_OK)

    def test_missing_config(self):
        empty = Repo(config=None, files={})
        try:
            self.assertEqual(artaudit_cli.main(["report", "--root", str(empty.root)], out=io.StringIO()),
                             artaudit_cli.EXIT_USAGE)
        finally:
            empty.close()

    def test_no_game_reads_no_uses(self):
        config = dict(CONFIG)
        del config["game"]
        bare = Repo(config=config)
        try:
            result = artaudit.audit(bare.root, artaudit.load_config(bare.root))
            self.assertEqual((len(result.images), result.uses), (12, []))
        finally:
            bare.close()


if __name__ == "__main__":
    unittest.main()
