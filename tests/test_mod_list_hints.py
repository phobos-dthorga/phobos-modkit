"""Quieter version notes and continued versions (1.85.0), on a synthetic RimWorld install and made-up community lists. Nothing
reads a real one."""
import json
from pathlib import Path
import tempfile
import unittest

from phobos_modkit import mod_list as core
from phobos_modkit.games.rimworld.mod_list import RimWorld

from test_mod_list import FakeRimWorld, about


class Hints(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.fake = FakeRimWorld(self.tmp.name, ["ludeon.rimworld", "example.hostel", "example.market", "example.library",
                                                 "example.rival", "example.gone"])
        self.environ = self.fake.environ(self.tmp.name)
        workshop = self.fake.workshop
        for number, package, name in (("1000000001", "example.market", "Market"), ("1000000002", "example.hostel", "Hostel"),
                                      ("1000000004", "example.library", "Library"), ("1000000005", "example.rival", "Rival")):
            about(workshop / number, package, name, versions=("1.6",))
        (workshop / "1000000001" / "1.7").mkdir()
        (workshop / "1000000002" / "LoadFolders.xml").write_text("<loadFolders><v1.7><li>/</li></v1.7></loadFolders>",
                                                                encoding="utf-8")
        rimsort = Path(self.environ["PHOBOS_RIMSORT"]) / "dbs"
        (rimsort / "Steam-Workshop-Database").mkdir(parents=True)
        (rimsort / "Steam-Workshop-Database" / "steamDB.json").write_text(json.dumps({"version": 1, "database": {
            "1000000004": {"packageId": "example.library", "gameVersions": ["1.6", "1.7"]}}}), encoding="utf-8")
        (rimsort / "NoVersionWarning" / "1.7").mkdir(parents=True)
        (rimsort / "NoVersionWarning" / "1.7" / "ModIdsToFix.xml").write_text(
            "<ModIdsToFix><li>Example.Rival</li></ModIdsToFix>", encoding="utf-8")
        (rimsort / "UseThisInstead").mkdir()
        (rimsort / "UseThisInstead" / "replacements.json").write_text(json.dumps({"version": 1, "rules": [
            {"oldWorkshopId": "1000000077", "oldName": "Gone Mod", "newWorkshopId": "2000000077", "newName": "Gone Mod (Continued)",
             "newAuthor": "Someone", "newVersions": ["1.6", "1.7"]},
            {"oldWorkshopId": "1000000005", "oldName": "Rival", "newWorkshopId": "2000000005", "newName": "Rival (Continued)",
             "newAuthor": "Someone", "newVersions": ["1.7"]}]}), encoding="utf-8")
        memory = core.remembered_file("rimworld", self.environ)
        memory.parent.mkdir(parents=True, exist_ok=True)
        memory.write_text(json.dumps({"format": 1, "mods": {"example.gone": {"id": "example.gone", "name": "Gone Mod",
                                                                             "workshop_id": "1000000077"}}}), encoding="utf-8")
        self.adapter = RimWorld(self.environ)
        installed = core.Installed(self.adapter, self.adapter.installed())
        self.problems = core.check(self.adapter, self.adapter.lists()[0], installed,
                                   core.load_remembered(memory))

    def tearDown(self):
        self.tmp.cleanup()

    def of(self, kind):
        return [p for p in self.problems if p.kind == kind]

    def test_mods_known_or_likely_to_work_share_one_note_with_why(self):
        likely = self.of("version-likely")
        self.assertEqual(len(likely), 1)
        self.assertIn("4 more mods", likely[0].title)
        why = likely[0].why
        self.assertIn("it has a 1.7 folder: Market", why)
        self.assertIn("its LoadFolders.xml has a 1.7 section: Hostel", why)
        self.assertIn("its Workshop page names 1.7: Library", why)
        self.assertIn("No Version Warning list says it works: Rival", why)
        self.assertEqual(self.of("version"), [], "every mod here has a sign it works, so none is left in doubt")

    def test_a_continued_version_is_offered_for_a_missing_mod_and_one_without_the_version(self):
        offered = {p.name: p for p in self.of("replacement")}
        self.assertEqual(set(offered), {"Gone Mod", "Rival"})
        self.assertEqual(offered["Gone Mod"].workshop_id, "2000000077")
        self.assertIn("Gone Mod (Continued) by Someone", offered["Gone Mod"].title)

    def test_nothing_is_offered_when_the_continued_version_is_on_the_list(self):
        (self.fake.workshop / "2000000077").mkdir()
        about(self.fake.workshop / "2000000077", "someone.gonecontinued", "Gone Mod (Continued)")
        from test_mod_list import mods_config
        mods_config(self.fake.config / "ModsConfig.xml", ["ludeon.rimworld", "example.gone", "someone.gonecontinued"])
        adapter = RimWorld(self.environ)
        problems = core.check(adapter, adapter.lists()[0], core.Installed(adapter, adapter.installed()),
                              core.load_remembered(core.remembered_file("rimworld", self.environ)))
        self.assertEqual([p for p in problems if p.kind == "replacement"], [])


if __name__ == "__main__":
    unittest.main()
