"""history: facts from a made-up repository's changelogs, the history log, a changelog as it stood, and the code of one commit.
Every file is written by hand in temporary folders; the cache and the log point there too."""
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

import support  # noqa: F401  (puts the package on the path)
from phobos_modkit import changes, history, history_cli

HEAD = "# Thing changelog\n\n## [Unreleased]\n\n"
V1 = "## [0.1.0] - 2026-11-01 - Draft\n\nFirst release\n\n### Added\n\n- **Wheels turn.** As they should.\n- **Lamps.** Lamps glow.\n\n"
V1_RELEASED = V1.replace("Draft", "Released").replace("As they should.", "As they should, now on ice too.")
V2 = "## [0.2.0] - 2026-11-03 - Draft\n\nBoats\n\n### Added\n\n- **Boats float.** On water.\n\n"
V2_MORE = V2 + "### Fixed\n\n- **Oars.** Boats row.\n\n"
OLD = "# Old changelog\n\n## [Unreleased]\n\n## [0.1.0] - 2026-11-01 - Draft\n\n### Added\n\n- **Bells.** Bells ring.\n"


def git(root, *args, when=None):
    environ = dict(os.environ)
    if when:
        environ.update(GIT_AUTHOR_DATE=when, GIT_COMMITTER_DATE=when)
    subprocess.run(["git", "-c", "core.fsmonitor=false", *args], cwd=root, check=True, capture_output=True, env=environ)


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def commit(root, message, when):
    git(root, "add", "-A", "mods", "src")
    git(root, "commit", "-q", "-m", message, when=when)


def repository(tmp):
    """Thing starts at 0.1.0 and Old beside it; Thing writes 0.2.0 and rewords wheels; Thing releases 0.1.0 and adds oars; Old is
    merged into Thing (its history kept under a heading); Thing drops lamps."""
    root = Path(tmp) / "repo"
    root.mkdir()
    git(root, "init", "-q")
    git(root, "config", "core.fsmonitor", "false")  # in the repository: the code under test runs plain git
    git(root, "config", "user.email", "test@example.com")
    git(root, "config", "user.name", "Test")
    git(root, "config", "core.autocrlf", "false")
    thing, old = root / "mods" / "Thing" / "CHANGELOG.md", root / "mods" / "Old" / "CHANGELOG.md"
    write(thing, HEAD + V1)
    write(old, OLD)
    write(root / "src" / "Wheel.cs", "class Wheel { }\n")
    commit(root, "Thing 0.1.0", "2026-11-01T10:00:00+00:00")
    write(thing, HEAD + V2 + V1.replace("As they should.", "As they should, now on ice too."))
    write(root / "src" / "Boat.cs", "class Boat { }\n")
    commit(root, "Thing 0.2.0: boats", "2026-11-03T10:00:00+00:00")
    write(thing, HEAD + V2_MORE + V1_RELEASED)
    write(root / "src" / "Boat.cs", "class Boat { int oars; }\n")
    commit(root, "Thing: oars, 0.1.0 released", "2026-11-04T10:00:00+00:00")
    old.unlink()
    write(thing, HEAD + V2_MORE + V1_RELEASED + "## Old history\n\n- **Bells.** Bells ring.\n")
    commit(root, "Old merged into Thing", "2026-11-05T10:00:00+00:00")
    write(thing, HEAD + V2_MORE + V1_RELEASED.replace("- **Lamps.** Lamps glow.\n", "") + "## Old history\n\n- **Bells.** Bells ring.\n")
    commit(root, "Thing: lamps out", "2026-11-06T10:00:00+00:00")
    return root


def environ(tmp):
    return support.isolated_environ(tmp, PHOBOS_MODKIT_CACHE=str(Path(tmp) / "cache"))


def kinds(facts, product="Thing"):
    return [(f["kind"], f.get("version")) for f in facts if f["product"] == product]


class FactsTests(unittest.TestCase):
    def test_every_kind_of_change_to_a_changelog_becomes_a_fact(self):
        with tempfile.TemporaryDirectory() as tmp:
            facts = history.repository_facts(repository(tmp), environ(tmp))
            self.assertEqual(kinds(facts), [
                ("product-started", None), ("version-written", "0.2.0"), ("entries-reworded", "0.1.0"),
                ("version-released", "0.1.0"), ("entries-added", "0.2.0"), ("entries-removed", "0.1.0")])
            reworded = [f for f in facts if f["kind"] == "entries-reworded"][0]
            self.assertEqual(reworded["entries"][0]["was"], "**Wheels turn.** As they should.")
            removed = [f for f in facts if f["kind"] == "entries-removed"][0]
            self.assertEqual(([e["lead"] for e in removed["entries"]], removed["subject"]), (["Lamps."], "Thing: lamps out"))
            self.assertTrue(all(f["repository"] == "repo" and f["source"] == "git" for f in facts))

    def test_a_removed_changelog_ends_its_product_and_names_where_it_went(self):
        with tempfile.TemporaryDirectory() as tmp:
            facts = history.repository_facts(repository(tmp), environ(tmp))
            self.assertEqual(kinds(facts, "Old"), [("product-started", None), ("product-ended", None)])
            ended = [f for f in facts if f["kind"] == "product-ended"][0]
            self.assertEqual((ended["mergedInto"], ended["changelog"]), ("Thing", "mods/Old/CHANGELOG.md"))

    def test_the_cache_reads_only_new_commits_and_gives_the_same_facts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = repository(tmp)
            first = history.repository_facts(root, environ(tmp))
            self.assertEqual(history.repository_facts(root, environ(tmp)), first)
            write(root / "mods" / "Thing" / "CHANGELOG.md", HEAD + "## [0.3.0] - 2026-11-07 - Draft\n\n### Added\n\n- **Sails.** Up.\n\n"
                  + V2_MORE + V1_RELEASED.replace("- **Lamps.** Lamps glow.\n", "") + "## Old history\n\n- **Bells.** Bells ring.\n")
            commit(root, "Thing 0.3.0", "2026-11-07T10:00:00+00:00")
            again = history.repository_facts(root, environ(tmp))
            self.assertEqual(again[:len(first)], first)
            self.assertEqual([(f["kind"], f.get("version")) for f in again[len(first):]], [("version-written", "0.3.0")])


class LogTests(unittest.TestCase):
    def test_a_fact_is_appended_and_read_back_and_a_bad_line_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = environ(tmp)
            self.assertTrue(history.record("rimworld", "installed", env, mod="Thing", version="0.2.0", commit=None))
            with open(history.log_file("rimworld", env), "a", encoding="utf-8") as handle:
                handle.write("not json\n")
            self.assertTrue(history.record("rimworld", "went-back", env, mod="Thing", version="0.1.0"))
            facts = history.read_log("rimworld", env)
            self.assertEqual([(f["kind"], f["version"], f["source"]) for f in facts],
                             [("installed", "0.2.0", "log"), ("went-back", "0.1.0", "log")])
            self.assertNotIn("commit", facts[0])
            self.assertEqual(history.log_file("rimworld", env).parent, Path(tmp) / "history")

    def test_a_log_that_cannot_be_written_never_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            blocker = Path(tmp) / "file"
            blocker.write_text("x", encoding="utf-8")
            self.assertFalse(history.record("rimworld", "built", {"PHOBOS_HISTORY": str(blocker / "below")}))


class AsItStoodTests(unittest.TestCase):
    def test_a_changelog_at_a_commit_marks_what_happened_to_each_entry_since(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = repository(tmp)
            first = history.commits_of(root, "mods/Thing/CHANGELOG.md")[0][0]
            stood = history.as_it_stood(root, "mods/Thing/CHANGELOG.md", first)
            self.assertEqual(stood["product"], "Thing")
            entries = {e["lead"]: e for v in stood["versions"] for e in v["entries"]}
            self.assertEqual(entries["Wheels turn."]["since"], "reworded")
            self.assertEqual(entries["Wheels turn."]["now"], "**Wheels turn.** As they should, now on ice too.")
            self.assertEqual(entries["Lamps."]["since"], "removed")
            self.assertEqual(stood["since"], {"added": 2, "reworded": 1, "removed": 1})

    def test_a_moment_finds_the_commit_and_a_removed_changelog_can_still_be_read(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = repository(tmp)
            found = history.commit_at(root, "mods/Old/CHANGELOG.md", "2026-11-02T00:00:00+00:00")
            stood = history.as_it_stood(root, "mods/Old/CHANGELOG.md", found)
            self.assertEqual((stood["stillThere"], stood["versions"][1]["entries"][0]["since"]), (False, "removed"))
            self.assertIsNone(history.commit_at(root, "mods/Thing/CHANGELOG.md", "2026-10-01T00:00:00+00:00"))

    def test_the_command_refuses_a_file_that_was_never_a_changelog(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = repository(tmp)
            out = io.StringIO()
            code = history_cli.main(["at", "--root", str(root), "--changelog", "src/Wheel.cs", "--when", "2026-11-05", "--json"],
                                    environ=environ(tmp), out=out)
            self.assertEqual((code, json.loads(out.getvalue())["data"]["ok"]), (1, False))


class TimelineCommandTests(unittest.TestCase):
    def test_the_timeline_joins_git_and_the_log_newest_first(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, env = repository(tmp), environ(tmp)
            history.record("rimworld", "installed", env, now=None, mod="Thing", version="0.2.0", repository="repo")
            history.record("rimworld", "installed", env, mod="Other", version="1.0.0", repository="elsewhere")
            out = io.StringIO()
            code = history_cli.main(["timeline", "--root", str(root), "--game", "rimworld", "--json"], environ=env, out=out)
            data = json.loads(out.getvalue())["data"]
            self.assertEqual(code, 0)
            self.assertEqual(data["facts"][0]["kind"], "installed")
            self.assertNotIn("elsewhere", {f.get("repository") for f in data["facts"]})
            times = [f["time"] for f in data["facts"]]
            self.assertEqual(times, sorted(times, reverse=True))
            self.assertTrue(data["logExists"])

    def test_since_keeps_only_later_facts(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = io.StringIO()
            history_cli.main(["timeline", "--root", str(repository(tmp)), "--since", "2026-11-05", "--json"], environ=environ(tmp),
                             out=out)
            self.assertEqual({f["time"][:10] for f in json.loads(out.getvalue())["data"]["facts"]}, {"2026-11-05", "2026-11-06"})


class CommitCodeTests(unittest.TestCase):
    def test_a_commit_shows_its_code_and_every_entry_it_wrote(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = repository(tmp)
            second = history.commits_of(root, "mods/Thing/CHANGELOG.md")[1][0]
            found = changes.commit_code(root, "mods/Thing/CHANGELOG.md", second)
            self.assertEqual(found.commit.subject, "Thing 0.2.0: boats")
            self.assertIn("src/Boat.cs", [f.path for f in found.files])
            with self.assertRaises(changes.ChangesError):
                changes.commit_code(root, "mods/Thing/CHANGELOG.md", "not-a-commit")


if __name__ == "__main__":
    unittest.main()
