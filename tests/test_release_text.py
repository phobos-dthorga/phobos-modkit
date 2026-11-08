"""Changelogs and Steam's BBCode: structure, the Markdown subset, refusals and the merged-mod history rule."""
import unittest

import support  # noqa: F401  (the package on the import path)
from phobos_modkit.release.changelog import ChangelogError, mark_released, parse, version_key
from phobos_modkit.steam import bbcode, vdf

LOG = """# Example changelog

Free text before the log.

## [Unreleased]

### Added

- Not yet released.

## [1.10.0] - 2026-11-08 - Draft

### Added

- A **bold** thing with a [link](https://example.com/a) and "quotes".
- A long bullet that the author wrapped
  onto a second line.

A paragraph wrapped
over two lines.

## [1.9.0] - 2026-11-01 - Released

- Older.

## Old Part history

### [0.3.0] - 2026-10-01 - Draft

- Kept as written, never read as a release; [brackets] allowed here.
"""


class Changelog(unittest.TestCase):
    def test_entries_in_order_and_history_closes_the_log(self):
        releases = parse(LOG)
        self.assertEqual(list(releases), ["1.10.0", "1.9.0"])
        self.assertEqual((releases["1.10.0"].status, releases["1.10.0"].date), ("Draft", "2026-11-08"))
        self.assertNotIn("0.3.0", releases)

    def test_structure_errors(self):
        for text, message in (("## [1.0.0] - 2026-01-01 - Draft\n- x\n", "Missing"),
                              ("## [Unreleased]\n## [1.0.0] - 2026-02-30 - Draft\n- x\n", "Invalid date"),
                              ("## [Unreleased]\n## [1.0.0] - 2026-01-01 - Draft\n- x\n## [1.0.0] - 2026-01-01 - Draft\n- y\n", "Duplicate"),
                              ("## [Unreleased]\n## [1.0.0] - 2026-01-01 - Draft\n\n", "Empty"),
                              ("## [Unreleased]\n## 1.0.0 - 2026-01-01\n- x\n", "Invalid release heading"),
                              ("## [1.0.0] - 2026-01-01 - Draft\n- x\n## [Unreleased]\n", "Unreleased must"),
                              ("## Something history\n## [Unreleased]\n", "Invalid release heading")):
            with self.subTest(message), self.assertRaisesRegex(ChangelogError, message):
                parse(text)

    def test_mark_released_and_version_order(self):
        marked = mark_released(LOG, "1.10.0", "2026-11-09")
        self.assertIn("## [1.10.0] - 2026-11-09 - Released", marked)
        self.assertIsNone(mark_released(LOG, "1.9.0", "2026-11-09"))
        self.assertLess(version_key("1.9.0"), version_key("1.10.0"))


class BBCode(unittest.TestCase):
    def test_subset_renders(self):
        body = parse(LOG)["1.10.0"].body
        text = bbcode.render(body)
        self.assertIn("[h2]Added[/h2]\n\n[list]\n[*]A [b]bold[/b] thing with a [url=https://example.com/a]link[/url] "
                      "and \u201cquotes\u201d.", text)
        self.assertIn("[*]A long bullet that the author wrapped onto a second line.\n[/list]", text)
        self.assertIn("A paragraph wrapped over two lines.", text)
        bbcode.validate(text)

    def test_refusals(self):
        for body in ("- `code`", "- a | b", "![x](https://e.com/i.png)", "- [b]raw[/b]", "1. numbered",
                     "- [x](ftp://e.com)", "- back\\slash", "- **[b]**", "\n  nested after a blank", "- # not a heading"):
            with self.subTest(body), self.assertRaises(bbcode.BBCodeError):
                bbcode.render(body)

    def test_hash_inside_a_line_is_text_and_refusals_name_what_they_found(self):
        self.assertEqual(bbcode.render("- The first C# assembly, issue #12."), "[list]\n[*]The first C# assembly, issue #12.\n[/list]")
        with self.assertRaisesRegex(bbcode.BBCodeError, r"\(`, \|\)"):
            bbcode.render("- a `b` | c")
        with self.assertRaisesRegex(bbcode.BBCodeError, "# at the start"):
            bbcode.render("- # heading")

    def test_validate(self):
        bbcode.validate("[h1]T[/h1]\n[list]\n[*]x\n[/list]\n[url=https://e.com]e[/url]")
        for text in ("[list][b]x[/list][/b]", "[*]x", "[img]x[/img]", "[b=1]x[/b]", "[url=javascript:x]x[/url]",
                     "[b]x", "x ] y", "## Markdown", "**bold**"):
            with self.subTest(text), self.assertRaises(bbcode.BBCodeError):
                bbcode.validate(text)


class Vdf(unittest.TestCase):
    def test_quoting_and_reading_back(self):
        text = vdf.workshop_item({"appid": "294100", "publishedfileid": "0", "changenote": "line one\nline two"})
        self.assertTrue(text.startswith('"workshopitem"\n{\n  "appid" "294100"\n'))
        self.assertEqual(vdf.change_note(text), "line one\nline two")
        self.assertEqual(vdf.item_id(text), "0")
        self.assertEqual(vdf.item_id(text.replace('"0"', '"\t3814698080"'.replace("\t", ""))), "3814698080")
        for bad in ('a "quote"', "C:\\path", "bell\x07"):
            with self.subTest(bad), self.assertRaises(vdf.VdfError):
                vdf.quote(bad)
        with self.assertRaisesRegex(vdf.VdfError, "at most 5"):
            vdf.limit("Title", b"123456", 5)


if __name__ == "__main__":
    unittest.main()
