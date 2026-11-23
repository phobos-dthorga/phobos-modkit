"""The shared rules: this repository's own rules/ folder is whole, and a repository's uptake of it is read right. Stand-in
repositories are written by hand in temporary folders."""
import io
import json
from pathlib import Path
import tempfile
import unittest

import support  # noqa: F401  (puts the package on the path)
from phobos_modkit import rules, rules_cli

IMPORT = "@external/phobos-modkit/rules/every-session.md"


def consumer(tmp, claude="", agents="", fetched=True):
    root = Path(tmp)
    (root / "external" / "phobos-modkit").mkdir(parents=True)
    if fetched:
        (root / "external" / "phobos-modkit" / "rules").mkdir()
        (root / "external" / "phobos-modkit" / "rules" / "every-session.md").write_text("# Rules\n", encoding="utf-8")
    if claude is not None:
        (root / "CLAUDE.md").write_text(claude, encoding="utf-8")
    (root / "AGENTS.md").write_text(agents, encoding="utf-8")
    return root


class TheFolderItself(unittest.TestCase):
    def test_every_rules_file_is_in_the_index_and_the_every_session_file_is_there(self):
        self.assertEqual(rules.problems(), [])

    def test_the_every_session_file_comes_first_and_holds_rules(self):
        files = rules.rule_files()
        self.assertEqual(files[0].name, rules.EVERY_SESSION)
        self.assertGreater(files[0].rules, 0)
        self.assertTrue(files[0].read and files[0].covers)

    def test_a_design_to_edit_holds_no_rules(self):
        self.assertFalse(rules.rule_files()[0].design)
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            (folder / "every-session.md").write_text("# Rules\n\n- **One.** Text.\n", encoding="utf-8")
            (folder / "idea.md").write_text("# An idea\n\n**Status (1 Jan 2026):** a design to edit, **not yet rules**.\n\n"
                                            "- **A principle.** Text.\n", encoding="utf-8")
            designs = {f.name: f for f in rules.rule_files(folder) if f.design}
            self.assertEqual(list(designs), ["idea.md"])
            self.assertEqual(designs["idea.md"].rules, 0)

    def test_the_first_class_design_lives_in_docs_not_rules(self):
        self.assertFalse((rules.FOLDER / "first-class.md").exists())
        self.assertTrue((rules.FOLDER.parent / "docs" / "first-class.md").is_file())

    def test_this_repository_reads_its_own_rules(self):
        found = rules.uptake(rules.FOLDER.parent)
        self.assertEqual((found.kind, found.missing), ("kit", []))

    def test_a_file_left_out_of_the_index_is_named(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            (folder / "README.md").write_text("| File | Read | Covers |\n| --- | --- | --- |\n"
                                              "| [every-session.md](every-session.md) | Always | Commits |\n"
                                              "| [gone.md](gone.md) | Never | Nothing |\n", encoding="utf-8")
            (folder / "every-session.md").write_text("# Rules\n\n## Commits\n\n- **One.** Text.\n- **Two.** Text.\n  - not a rule\n",
                                                     encoding="utf-8")
            (folder / "art.md").write_text("# Art\n", encoding="utf-8")
            self.assertEqual(rules.problems(folder), ["art.md is not in the table in README.md",
                                                      "README.md lists gone.md, which is not in the folder"])
            first = rules.rule_files(folder)[0]
            self.assertEqual((first.name, first.rules, first.sections, first.read), ("every-session.md", 2, ["Commits"], "Always"))


class Uptake(unittest.TestCase):
    def test_a_repository_with_both_lines_reads_the_rules(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = consumer(tmp, f"@AGENTS.md\n{IMPORT}\n", "Read `external/phobos-modkit/rules/every-session.md` first.\n")
            found = rules.uptake(root)
            self.assertTrue(found.ok)
            out = io.StringIO()
            self.assertEqual(rules_cli.main(["check", "--root", str(root), "--json"], environ={}, out=out), 0)
            self.assertTrue(json.loads(out.getvalue())["data"]["ok"])

    def test_each_missing_line_is_named_and_fails_the_check(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = consumer(tmp, "@AGENTS.md\n", "Nothing about them.\n")
            found = rules.uptake(root)
            self.assertEqual(found.missing, [f"CLAUDE.md has no line {IMPORT}",
                                             "AGENTS.md does not name external/phobos-modkit/rules/every-session.md"])
            out = io.StringIO()
            self.assertEqual(rules_cli.main(["check", "--root", str(root), "--json"], environ={}, out=out), 1)

    def test_a_mention_in_passing_is_not_an_import(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = consumer(tmp, f"See {IMPORT} some day.\n", "external/phobos-modkit/rules/every-session.md\n")
            self.assertFalse(rules.uptake(root).imports)

    def test_a_pin_that_was_never_fetched_says_so(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = consumer(tmp, f"{IMPORT}\n", "external/phobos-modkit/rules/every-session.md\n", fetched=False)
            found = rules.uptake(root)
            self.assertFalse(found.ok)
            self.assertIn("git submodule update --init", found.missing[0])

    def test_a_repository_without_the_kit_has_nothing_to_read(self):
        with tempfile.TemporaryDirectory() as tmp:
            found = rules.uptake(tmp)
            self.assertEqual((found.kind, found.ok), ("none", False))

    def test_list_counts_the_rules(self):
        out = io.StringIO()
        self.assertEqual(rules_cli.main(["list", "--json"], environ={}, out=out), 0)
        data = json.loads(out.getvalue())["data"]
        self.assertEqual(data["files"][0]["name"], "every-session.md")
        self.assertEqual(data["problems"], [])


if __name__ == "__main__":
    unittest.main()
