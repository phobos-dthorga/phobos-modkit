"""Colony mood: the game's rules for remembered thoughts and break thresholds, Def inheritance, and the report on the
hand-written fixture save with a hand-written patched-Defs file. Nothing here reads a real game."""
import json
import unittest
import xml.etree.ElementTree as ET
from contextlib import closing
import sqlite3

import io

import support  # noqa: F401
import test_rimworld_save as save_tests
from phobos_modkit.games.rimworld import def_lookup, mood
from phobos_modkit.games.rimworld.save_cli import EXIT_OK, main

PATCHED = """<?xml version="1.0" encoding="utf-8"?>
<!-- Written for these tests in the shape D'thorga Framework writes: every Def after patches, before inheritance. -->
<Defs gameVersion="1.7.9999 rev1" written="2026-11-10T10:00:00Z" activeMods="3">
  <StatDef><defName>MentalBreakThreshold</defName><defaultBaseValue>0.35</defaultBaseValue></StatDef>
  <ThoughtDef><defName>AteWithoutTable</defName><nullifyingTraits><li>Ascetic</li></nullifyingTraits>
    <stages><li><label>ate without table</label><baseMoodEffect>-3</baseMoodEffect></li></stages></ThoughtDef>
  <ThoughtDef Name="SocialBase" Abstract="True"><thoughtClass>Thought_MemorySocial</thoughtClass>
    <stackedEffectMultiplier>0.5</stackedEffectMultiplier></ThoughtDef>
  <ThoughtDef ParentName="SocialBase"><defName>Insulted</defName>
    <stages><li><label>{0} insulted me</label><baseMoodEffect>-10</baseMoodEffect></li></stages></ThoughtDef>
  <ThoughtDef><defName>Example_Fading</defName><durationDays>1</durationDays><lerpMoodToZero>true</lerpMoodToZero>
    <stages><li><label>fading joy</label><baseMoodEffect>8</baseMoodEffect></li></stages></ThoughtDef>
  <TraitDef><defName>Industriousness</defName><degreeDatas><li><degree>2</degree>
    <statOffsets><MentalBreakThreshold>0.07</MentalBreakThreshold></statOffsets></li></degreeDatas></TraitDef>
  <NeedDef><defName>Food</defName><label>food</label></NeedDef>
  <NeedDef><defName>Chemical_Example</defName><needClass>Need_Chemical</needClass><label>example drug</label></NeedDef>
</Defs>
"""


def rule(xml, name="T"):
    return mood.thought_rule(ET.fromstring(xml), name)


class Rules(unittest.TestCase):
    def test_a_group_counts_its_average_once_then_each_further_thought_at_the_multiplier(self):
        self.assertEqual(mood.stacked([]), 0)
        self.assertAlmostEqual(mood.stacked([-3]), -3)
        self.assertAlmostEqual(mood.stacked([-3, -3]), -5.25)              # -3 x (1 + 0.75)
        self.assertAlmostEqual(mood.stacked([-2, -4], 0.5), -4.5)          # average -3 x (1 + 0.5)

    def test_a_memory_takes_its_stage_times_its_power_plus_its_offset_and_may_fade(self):
        plain = rule("<ThoughtDef><stages><li><baseMoodEffect>-6</baseMoodEffect></li></stages></ThoughtDef>")
        self.assertEqual(mood.memory_mood(plain), -6)
        self.assertEqual(mood.memory_mood(plain, 0, 0.5, 2), -1)
        fading = rule("<ThoughtDef><durationDays>2</durationDays><lerpMoodToZero>true</lerpMoodToZero>"
                      "<stages><li><baseMoodEffect>10</baseMoodEffect></li></stages></ThoughtDef>")
        self.assertAlmostEqual(mood.memory_mood(fading, age_ticks=30000), 7.5)
        self.assertAlmostEqual(mood.memory_mood(fading, age_ticks=60000, duration_override=60000), 0)

    def test_social_only_and_empty_stages_give_no_mood(self):
        social = rule("<ThoughtDef><stages><li><label>chat</label><baseMoodEffect>0</baseMoodEffect></li>"
                      "<li IsNull='True'/></stages></ThoughtDef>")
        self.assertIsNone(mood.memory_mood(social))
        self.assertIsNone(mood.memory_mood(social, 1))
        self.assertIsNone(mood.memory_mood(social, 5))
        self.assertIsNone(rule("<ThoughtDef><label>none</label></ThoughtDef>"))

    def test_groups_follow_the_def_the_stage_and_where_it_matters_the_other_pawn(self):
        plain = rule("<ThoughtDef><stages><li><label>sad</label><baseMoodEffect>-1</baseMoodEffect></li>"
                     "<li><label>sadder</label><baseMoodEffect>-2</baseMoodEffect></li></stages></ThoughtDef>")
        self.assertEqual(mood.group_key(plain, 0, "Thing_A"), mood.group_key(plain, 0, "Thing_B"))
        self.assertNotEqual(mood.group_key(plain, 0, None), mood.group_key(plain, 1, None))
        named = rule("<ThoughtDef><stages><li><label>{0} died</label><baseMoodEffect>-5</baseMoodEffect></li>"
                     "</stages></ThoughtDef>")
        self.assertNotEqual(mood.group_key(named, 0, "Thing_A"), mood.group_key(named, 0, "Thing_B"))
        social = rule("<ThoughtDef><thoughtClass>Thought_MemorySocial</thoughtClass><stages><li><label>insult</label>"
                      "<baseMoodEffect>-5</baseMoodEffect></li></stages></ThoughtDef>")
        self.assertNotEqual(mood.group_key(social, 0, "Thing_A"), mood.group_key(social, 0, "Thing_B"))

    def test_labels_drop_the_other_pawn(self):
        self.assertEqual(mood.label_of(rule("<ThoughtDef><stages><li><label>my wife {0} died</label>"
                                            "<baseMoodEffect>-20</baseMoodEffect></li></stages></ThoughtDef>"), 0),
                         "My wife died")
        self.assertEqual(mood.label_of(rule("<ThoughtDef><label>whole def</label><stages><li><label>{0} insulted me"
                                            "</label><baseMoodEffect>-5</baseMoodEffect></li></stages></ThoughtDef>"),
                                       0), "Someone insulted me")

    def test_traits_cancel_by_name_or_by_degree(self):
        thought = rule("<ThoughtDef><nullifyingTraits><li>Ascetic</li></nullifyingTraits><nullifyingTraitDegrees><li>"
                       "<def>Beauty</def><degree>-2</degree></li></nullifyingTraitDegrees><stages><li>"
                       "<baseMoodEffect>-3</baseMoodEffect></li></stages></ThoughtDef>")
        self.assertTrue(mood.nullified(thought, {"Ascetic": 0}))
        self.assertTrue(mood.nullified(thought, {"Beauty": -2}))
        self.assertFalse(mood.nullified(thought, {"Beauty": 2, "Kind": 0}))

    def test_break_thresholds_follow_the_stat_and_traits(self):
        minor, major, extreme = mood.thresholds(0.35)
        self.assertAlmostEqual(minor, 0.35)
        self.assertAlmostEqual(major, 0.2)
        self.assertAlmostEqual(extreme, 0.05)
        trait = ET.fromstring("<TraitDef><degreeDatas><li><degree>1</degree><statOffsets><MentalBreakThreshold>-0.09"
                              "</MentalBreakThreshold></statOffsets></li><li><statFactors><MentalBreakThreshold>2"
                              "</MentalBreakThreshold></statFactors></li></degreeDatas></TraitDef>")
        self.assertEqual(mood.trait_break_change(trait, 1), (-0.09, 1.0))
        self.assertEqual(mood.trait_break_change(trait, 0), (0.0, 2.0))
        self.assertEqual(mood.trait_break_change(None, 0), (0.0, 1.0))
        self.assertAlmostEqual(mood.thresholds(0.35, [(-0.09, 1.0)])[0], 0.26)
        self.assertEqual(mood.risk(0.04, (0.35, 0.2, 0.05)), "extreme")
        self.assertEqual(mood.risk(0.1, (0.35, 0.2, 0.05)), "major")
        self.assertEqual(mood.risk(0.3, (0.35, 0.2, 0.05)), "minor")
        self.assertIsNone(mood.risk(0.5, (0.35, 0.2, 0.05)))


class Inheritance(unittest.TestCase):
    def test_children_override_elements_and_add_list_items(self):
        parent = ET.fromstring("<ThoughtDef><label>base</label><nullifyingTraits><li>A</li></nullifyingTraits>"
                               "<stages><li><baseMoodEffect>-1</baseMoodEffect></li></stages></ThoughtDef>")
        child = ET.fromstring("<ThoughtDef><defName>C</defName><label>child</label><nullifyingTraits><li>B</li>"
                              "</nullifyingTraits><stages Inherit='False'><li><baseMoodEffect>-9</baseMoodEffect></li>"
                              "</stages></ThoughtDef>")
        merged = def_lookup.merge([parent, child])
        self.assertEqual(def_lookup.text(merged, "label"), "child")
        self.assertEqual([li.text for li in merged.findall("nullifyingTraits/li")], ["A", "B"])
        self.assertEqual([def_lookup.number(li, "baseMoodEffect") for li in merged.findall("stages/li")], [-9.0])

    def test_the_patched_index_resolves_parents_by_name(self):
        with closing(sqlite3.connect(":memory:")) as conn:
            conn.execute("CREATE TABLE pdef (id INTEGER PRIMARY KEY, def_type TEXT, def_name TEXT, name TEXT, "
                         "parent TEXT, abstract INTEGER, xml TEXT)")
            conn.execute("INSERT INTO pdef VALUES (1, 'ThoughtDef', NULL, 'Base', NULL, 1, "
                         "'<ThoughtDef Name=\"Base\"><durationDays>3</durationDays></ThoughtDef>')")
            conn.execute("INSERT INTO pdef VALUES (2, 'ThoughtDef', 'X', NULL, 'Base', 0, "
                         "'<ThoughtDef ParentName=\"Base\"><defName>X</defName></ThoughtDef>')")
            source = def_lookup.DefSource(patched=conn)
            self.assertEqual(def_lookup.number(source.get("ThoughtDef", "X"), "durationDays"), 3.0)
            self.assertIsNone(source.get("ThoughtDef", "Missing"))
            self.assertEqual(source.used, {"patched"})
        self.assertFalse(def_lookup.DefSource().available)


@save_tests.needs_indexer
class Report(save_tests.Folders):
    def run_main(self, *args):
        out = io.StringIO()
        code = main([*args, "--saves", str(self.saves), "--cache", str(self.cache)], environ=save_tests.ONLY_INDEXER,
                    out=out)
        return code, out.getvalue()

    def run_mood(self, *args, patched=True):
        dump = self.saves.parent / "PatchedDefs.xml"
        dump.write_text(PATCHED, encoding="utf-8")
        nowhere = self.saves.parent / "no-game"
        return self.run_main("mood", "--patched-defs", str(dump if patched else nowhere / "none.xml"),
                             "--game", str(nowhere), "--config", str(nowhere), *args)

    def test_who_is_at_risk_what_hurts_and_what_helps(self):
        code, text = self.run_mood()
        self.assertEqual(code, EXIT_OK)
        self.assertIn("1 pawns (1 colonist): 1 below the extreme break threshold", text)
        # Two meals off the ground stack to -5.25, the insult is -10 x 0.5, the fading joy is half gone: -6.25.
        self.assertIn("Remembered events add -6.2 mood in all; the costliest is \"Ate without table\"", text)
        self.assertIn("| Annie | colonist | 4% | 42% | Extreme break risk | -6.2 | -39.8 | Food 0% |", text)
        self.assertIn("| Someone insulted me | 1 | -5.0 | -5.0 | Insulted |", text)
        self.assertIn("| Fading joy | 1 | +4.0 | +4.0 | Example_Fading |", text)
        self.assertIn("| Example drug | 1 | 20% | 1 | 0 | Chemical_Example |", text)
        self.assertIn("no ThoughtDef in the Defs read, so they are not counted: Example_Unknown", text)
        self.assertIn("the Defs with every patch applied", text)

    def test_charts_reach_the_json(self):
        code, text = self.run_mood("--json")
        charts = [b for s in json.loads(text)["report"]["sections"] for b in s["blocks"] if b["type"] == "chart"]
        self.assertEqual([c["title"] for c in charts], ["Mood against breaking point", "Costliest remembered events",
                                                        "Most cheering remembered events", "Needs across the colony"])
        first = charts[0]
        self.assertEqual((first["categories"], first["series"][0]["label"], first["series"][0]["values"]),
                         (["Annie"], "Extreme break risk", [4.0]))
        self.assertEqual([line["value"] for line in first["lines"]], [35.0, 20.0, 5.0])

    def test_one_pawn_in_full(self):
        code, text = self.run_mood("--pawn", "annie")
        self.assertIn("Annie (colonist): mood 4%, extreme break risk. Breaks below 42% (minor)", text)
        self.assertIn("| Ate without table | -5.2 | AteWithoutTable |", text)
        code, text = self.run_mood("--pawn", "Nobody")
        self.assertIn("No pawn of the colony", text)

    def test_without_defs_it_still_gives_levels_and_says_why(self):
        code, text = self.run_mood(patched=False)
        self.assertEqual(code, EXIT_OK)
        self.assertIn("could not be read", text)
        self.assertIn("1 below the extreme break threshold", text)
        code, text = self.run_main("mood", "--no-defs")
        self.assertIn("No Defs were read (--no-defs)", text)


if __name__ == "__main__":
    unittest.main()
