"""Signatures blank what changes between occurrences of one message and keep what tells messages apart."""
import unittest

import support  # noqa: F401  (puts the package on the import path)
from phobos_modkit.logs.signature import MAX_LENGTH, normalise


class Blanking(unittest.TestCase):
    def test_decimal_numbers_share_a_signature(self):
        self.assertEqual(normalise("Parsed 5.5 as int."), normalise("Parsed 7.25 as int."))

    def test_ids_appended_to_names_share_a_signature(self):
        self.assertEqual(normalise("parent=Thing_Example12345678"), normalise("parent=Thing_Example87654321"))

    def test_reference_codes_and_hex_literals_are_blanked(self):
        self.assertEqual(normalise("[Ref 3ED61E44] at 0x1A2B"), "[Ref #] at #")

    def test_guids_are_blanked(self):
        self.assertEqual(normalise("job 64c9732c-e682-4ad6-9328-7f4de0ea6d1a done"), "job # done")

    def test_coordinates_and_times_are_blanked(self):
        self.assertEqual(normalise("at (171, 0, 235) since 21:23:32"), "at (#, #, #) since #")

    def test_whitespace_is_collapsed(self):
        self.assertEqual(normalise("  two   spaces\tand a tab "), "two spaces and a tab")


class Keeping(unittest.TestCase):
    def test_words_and_def_names_stay(self):
        self.assertEqual(normalise("No ThingDef named MF_Apparel_AmmoBackpack"), "No ThingDef named MF_Apparel_AmmoBackpack")

    def test_short_numbers_inside_names_stay(self):
        self.assertIn("PG17", normalise("Loading game from file PG17"))

    def test_eight_letter_words_made_of_hex_letters_stay(self):
        self.assertEqual(normalise("deadbeef accepted"), "deadbeef accepted")

    def test_different_messages_stay_apart(self):
        self.assertNotEqual(normalise("Failed to find Example_First"), normalise("Failed to find Example_Second"))


class Shape(unittest.TestCase):
    def test_normalising_twice_changes_nothing(self):
        for text in ("Parsed 5.5 as int.", "[Ref 3ED61E44] 0xFF", "Thing_Example12345678 at (1, 2)",
                     "x" * (MAX_LENGTH + 50), "Ammo_556x45mm_AP"):
            once = normalise(text)
            self.assertEqual(normalise(once), once, text)

    def test_long_messages_are_cut_with_a_marker(self):
        result = normalise("word " * 200)
        self.assertTrue(result.endswith("..."))
        self.assertLessEqual(len(result), MAX_LENGTH + 3)


if __name__ == "__main__":
    unittest.main()
