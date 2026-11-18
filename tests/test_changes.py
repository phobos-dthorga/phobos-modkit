"""changes: the changelogs of a made-up repository, and the commit and diff behind an entry. Every file is written by hand."""
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

import support  # noqa: F401  (puts the package on the path)
from phobos_modkit import changes, changes_cli

HEAD = "# Thing changelog\n\n## [Unreleased]\n\n"
V1 = "## [0.1.0] - 2026-11-01 - Draft\n\nFirst release\n\n### Added\n\n- **Wheels turn.** As they should.\n"
V2 = ("## [0.2.0] - 2026-11-02 - Draft\n\nBoats\n\n### Added\n\n- **Boats float.** On water,\n  mostly.\n- **Sails.** Boats have sails.\n\n"
      "### Save compatibility\n\n- Safe with a running save.\n\n")


def git(root, *args):
    subprocess.run(["git", "-c", "core.fsmonitor=false", *args], cwd=root, check=True, capture_output=True)


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def repository(tmp):
    """Two commits: wheels (code and its entry), then boats (two entries, code, data, a picture), with a rewording left uncommitted."""
    root = Path(tmp)
    git(root, "init", "-q")
    git(root, "config", "core.fsmonitor", "false")  # in the repository: the code under test runs plain git
    git(root, "config", "user.email", "test@example.com")
    git(root, "config", "user.name", "Test")
    git(root, "config", "core.autocrlf", "false")
    write(root / "mods" / "Thing" / "CHANGELOG.md", HEAD + V1)
    write(root / "src" / "Wheel.cs", "class Wheel\n{\n    void Turn() { }\n}\n")
    write(root / "node_modules" / "x" / "CHANGELOG.md", "# Not ours\n\n## [9.9.9]\n\n- Skipped.\n")
    git(root, "add", "-f", "mods", "src")
    git(root, "commit", "-q", "-m", "Thing 0.1.0: wheels")
    write(root / "mods" / "Thing" / "CHANGELOG.md", HEAD + V2 + V1)
    write(root / "src" / "Wheel.cs", "class Wheel\n{\n    void Turn() { Spin(); }\n    void Spin() { }\n}\n")
    write(root / "src" / "Boat.cs", "class Boat\n{\n    bool floats = true;\n}\n")
    write(root / "mods" / "Thing" / "Defs" / "Boats.xml", "<Defs>\n  <ThingDef><defName>Boat</defName></ThingDef>\n</Defs>\n")
    (root / "mods" / "Thing" / "Boat.png").write_bytes(b"\x89PNG\r\n\x1a\n\0\0\0\0")
    git(root, "add", "-f", "mods", "src")
    git(root, "commit", "-q", "-m", "Thing 0.2.0: boats")
    return root


class ChangelogsTests(unittest.TestCase):
    def test_changelogs_are_found_and_dependency_folders_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(changes.changelogs(repository(tmp)), ["mods/Thing/CHANGELOG.md"])

    def test_list_gives_the_newest_versions_with_their_entries(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = io.StringIO()
            code = changes_cli.main(["list", "--root", str(repository(tmp)), "--versions", "1", "--json"], environ={}, out=out)
            log = json.loads(out.getvalue())["data"]["changelogs"][0]
            self.assertEqual((code, log["product"], log["versionsInAll"]), (0, "Thing", 2))
            self.assertEqual([v["version"] for v in log["versions"]], ["0.2.0"])
            version = log["versions"][0]
            self.assertEqual((version["heading"], version["summary"]), ("2026-11-02 - Draft", "Boats"))
            self.assertEqual([e["lead"] for e in version["entries"]], ["Boats float.", "Sails.", "Safe with a running save."])

    def test_a_bare_changelog_title_is_named_by_what_follows_or_its_folder(self):
        self.assertEqual(changes_cli._product("Changelog (PhobosLib)", "CHANGELOG.md", "repo"), "PhobosLib")
        self.assertEqual(changes_cli._product("Changelog", "mods/Cat Ledger/CHANGELOG.md", "repo"), "Cat Ledger")
        self.assertEqual(changes_cli._product("", "CHANGELOG.md", Path("some/repo")), "repo")


class CommitMapTests(unittest.TestCase):
    def test_every_entry_is_given_the_commit_that_wrote_it_from_one_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = repository(tmp)
            commits = changes.entry_commits(root, "mods/Thing/CHANGELOG.md")
            log = changes.read(root, "mods/Thing/CHANGELOG.md")
            subjects = {e.lead: changes.describe(root, changes.commit_of(e, commits)).subject for e in log.entries}
            self.assertEqual(subjects, {"Boats float.": "Thing 0.2.0: boats", "Sails.": "Thing 0.2.0: boats",
                                        "Safe with a running save.": "Thing 0.2.0: boats", "Wheels turn.": "Thing 0.1.0: wheels"})

    def test_an_entry_running_over_two_lines_is_found_by_its_first(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = repository(tmp)
            log = changes.read(root, "mods/Thing/CHANGELOG.md")
            boats = next(e for e in log.entries if e.lead == "Boats float.")
            self.assertEqual(boats.first, "**Boats float.** On water,")
            self.assertIsNotNone(changes.commit_of(boats, changes.entry_commits(root, "mods/Thing/CHANGELOG.md")))

    def test_an_entry_in_no_commit_has_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = repository(tmp)
            write(root / "mods" / "Thing" / "CHANGELOG.md", HEAD.rstrip("\n") + "\n\n- **Oars.** Boats row.\n\n" + V2 + V1)
            log = changes.read(root, "mods/Thing/CHANGELOG.md")
            oars = next(e for e in log.entries if e.lead == "Oars.")
            self.assertIsNone(changes.commit_of(oars, changes.entry_commits(root, "mods/Thing/CHANGELOG.md")))

    def test_the_list_gives_each_entry_its_commit(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = io.StringIO()
            changes_cli.main(["list", "--root", str(repository(tmp)), "--json"], environ={}, out=out)
            versions = json.loads(out.getvalue())["data"]["changelogs"][0]["versions"]
            newest = {e["commit"] for e in versions[0]["entries"]}
            self.assertEqual(len(newest), 1)
            self.assertNotIn(None, newest)
            self.assertNotEqual(newest, {e["commit"] for e in versions[1]["entries"]})


class EntryTests(unittest.TestCase):
    def test_an_entry_shows_the_commit_that_wrote_it_code_first(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = repository(tmp)
            found = changes.entry_code(root, "mods/Thing/CHANGELOG.md", "Boats float.")
            self.assertEqual(found.commit.subject, "Thing 0.2.0: boats")
            self.assertEqual([(f.path, f.kind, f.change) for f in found.files], [
                ("src/Boat.cs", "code", "added"), ("src/Wheel.cs", "code", "changed"),
                ("mods/Thing/Defs/Boats.xml", "data", "added"), ("mods/Thing/Boat.png", "other", "added")])
            self.assertEqual([w[:10] for w in found.written_with], ["**Sails.**", "Safe with "])
            wheel = found.files[1]
            self.assertEqual((wheel.additions, wheel.deletions, wheel.language), (2, 1, "csharp"))
            lines = wheel.hunks[0]["lines"]
            self.assertIn({"kind": "-", "old": 3, "new": None, "text": "    void Turn() { }"}, lines)
            self.assertIn({"kind": "+", "old": None, "new": 4, "text": "    void Spin() { }"}, lines)
            self.assertTrue(found.files[3].binary)

    def test_an_older_entry_shows_its_own_commit_not_a_later_one_that_moved_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            found = changes.entry_code(repository(tmp), "mods/Thing/CHANGELOG.md", "**Wheels turn.** As they should.")
            self.assertEqual(found.commit.subject, "Thing 0.1.0: wheels")
            self.assertEqual([f.path for f in found.files], ["src/Wheel.cs"])
            self.assertEqual(found.written_with, [])

    def test_an_entry_in_no_commit_shows_the_uncommitted_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = repository(tmp)
            write(root / "mods" / "Thing" / "CHANGELOG.md", HEAD.rstrip("\n") + "\n\n- **Oars.** Boats row.\n\n" + V2 + V1)
            write(root / "src" / "Boat.cs", "class Boat\n{\n    bool floats = true;\n    int oars = 2;\n}\n")
            found = changes.entry_code(root, "mods/Thing/CHANGELOG.md", "Oars.")
            self.assertIsNone(found.commit)
            self.assertEqual([(f.path, f.additions) for f in found.files], [("src/Boat.cs", 1)])

    def test_what_is_not_an_entry_or_not_a_changelog_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = repository(tmp)
            with self.assertRaises(changes.ChangesError):
                changes.entry_code(root, "mods/Thing/CHANGELOG.md", "Nothing like this")
            with self.assertRaises(changes.ChangesError):
                changes.entry_code(root, "../elsewhere/CHANGELOG.md", "Boats float.")
            out = io.StringIO()
            code = changes_cli.main(["entry", "--root", str(root), "--changelog", "src/Wheel.cs", "--text", "x", "--json"],
                                    environ={}, out=out)
            self.assertEqual((code, json.loads(out.getvalue())["data"]["ok"]), (1, False))

    def test_long_files_are_cut_and_say_so(self):
        diff = "diff --git a/big.lua b/big.lua\nnew file mode 100644\n--- /dev/null\n+++ b/big.lua\n@@ -0,0 +1,50 @@\n" + \
            "\n".join(f"+line {n}" for n in range(50)) + "\n"
        found = changes.parse_diff(diff, max_file_lines=10)[0]
        self.assertEqual((found.additions, len(found.hunks[0]["lines"]), found.truncated, found.language), (50, 10, True, "lua"))


if __name__ == "__main__":
    unittest.main()
