"""installs status's further checks (1.21.0): files, builds, settings changes, test rows, building and installing several mods. Every
file is written by hand in temporary folders; nothing reads a real install."""
from datetime import datetime
import io
import json
import os
import subprocess
from pathlib import Path
import tempfile
import time
import unittest

import support  # noqa: F401  (puts the package on the path)
from phobos_modkit import install_checks as checks
from phobos_modkit import installs, installs_cli

LOG = "# Thing changelog\n\n## [Unreleased]\n\n## [0.2.0] - 2026-11-02 - Draft\n\n### Added\n\n- **Boats.** Float.\n"


def write(path, text, when=None):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    if when is not None:
        os.utime(path, (when, when))
    return path


class FileTests(unittest.TestCase):
    def test_changes_are_counted_by_kind_and_install_only_files_are_left_out(self):
        with tempfile.TemporaryDirectory() as tmp:
            installed, repository = Path(tmp) / "installed", Path(tmp) / "repository"
            for folder in (installed, repository):
                write(folder / "About" / "About.xml", "<a/>", 1000)
                write(folder / "Common" / "Defs" / "Same.xml", "<Defs/>", 1000)
            # The same size; times apart, so the comparison never takes them for the same file by size and time alone.
            write(installed / "Common" / "Defs" / "Things.xml", "<Defs>old</Defs>", 1000)
            write(repository / "Common" / "Defs" / "Things.xml", "<Defs>new</Defs>", 2000)
            write(repository / "Common" / "Textures" / "Boat.png", "png")
            write(installed / "Common" / "Textures" / "Old.png", "png")
            write(installed / "Common" / "Textures" / "Old.dds", "dds")
            write(installed / "InstallRecord.json", "{}")
            write(repository / "1.7" / "Assemblies" / "Thing.dll", "dll")
            write(installed / "1.7" / "Assemblies" / "Thing.dll", "dll-old")
            write(repository / "obj" / "x.cache", "clutter")
            found = checks.compare_files(installed, repository, ["InstallRecord.json", "*.dds"])
            self.assertEqual(found["total"], 4)
            self.assertEqual(found["counts"], {"code": 1, "defs": 1, "textures": 2})
            changes = {p["path"]: p["change"] for p in found["paths"]}
            self.assertEqual(changes["Common/Textures/Boat.png"], "added")
            self.assertEqual(changes["Common/Textures/Old.png"], "removed")
            self.assertEqual(changes["Common/Defs/Things.xml"], "changed")

    def test_same_bytes_with_a_different_date_is_no_change(self):
        with tempfile.TemporaryDirectory() as tmp:
            write(Path(tmp) / "a" / "x.xml", "same", 1000)
            write(Path(tmp) / "b" / "x.xml", "same", 2000)
            self.assertEqual(checks.compare_files(Path(tmp) / "a", Path(tmp) / "b")["total"], 0)


class BuildTests(unittest.TestCase):
    def repository(self, tmp, source_age, dll_age):
        root = Path(tmp)
        now = time.time()
        write(root / "src" / "Thing" / "Thing.csproj",
              "<Project><PropertyGroup><ModFolder>Thing</ModFolder><AssemblyName>Thing</AssemblyName></PropertyGroup>"
              '<ItemGroup><Compile Include="../../lib/*.cs" /></ItemGroup></Project>', now - 10_000)
        write(root / "src" / "Thing" / "Boat.cs", "class Boat {}", now - source_age)
        write(root / "lib" / "Log.cs", "class Log {}", now - 10_000)
        if dll_age is not None:
            write(root / "mods" / "Thing" / "1.7" / "Assemblies" / "Thing.dll", "dll", now - dll_age)
        config = {"mods": "mods", "build": {"projects": "src/*/*.csproj", "modProperty": "ModFolder"}}
        return root, config

    def test_a_source_newer_than_its_assembly_needs_a_build(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, config = self.repository(tmp, source_age=60, dll_age=600)
            state = checks.build_states(root, config)["Thing"][0]
            self.assertTrue(state["needsBuild"])
            self.assertEqual(state["newestFile"], "src/Thing/Boat.cs")

    def test_an_assembly_newer_than_its_sources_is_built(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, config = self.repository(tmp, source_age=600, dll_age=60)
            self.assertFalse(checks.build_states(root, config)["Thing"][0]["needsBuild"])

    def test_a_compiled_file_from_elsewhere_counts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, config = self.repository(tmp, source_age=600, dll_age=300)
            os.utime(root / "lib" / "Log.cs", (time.time() - 10, time.time() - 10))
            self.assertTrue(checks.build_states(root, config)["Thing"][0]["needsBuild"])

    def test_no_assembly_yet_needs_a_build(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, config = self.repository(tmp, source_age=600, dll_age=None)
            self.assertTrue(checks.build_states(root, config)["Thing"][0]["needsBuild"])


class LookOutTests(unittest.TestCase):
    def test_rows_naming_a_version_between_the_two_are_listed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write(root / "config" / "test-evidence.json", json.dumps({
                "doc": "docs/tests.md", "rows": {}, "versionNames": {"Thing": "Thing"}}))
            write(root / "docs" / "tests.md", "# Tests\n\n## Rows\n\n| # | What it proves | What passes |\n| --- | --- | --- |\n"
                  "| 1 | **Old boats** (Thing 0.1.0) | Float |\n| 2 | **New sails** (Thing 0.3.0) | Sail |\n"
                  "| 3 | **Later masts** (Thing 0.5.0) | Stand |\n| 4 | **Passed oars** (Thing 0.3.0) | Row. **Passed: the owner, 1 Nov 2026** |\n")
            found = checks.look_out(root, "Thing", "0.2.0", "0.4.0")
            self.assertEqual([(r["id"], r["version"]) for r in found], [("2", "0.3.0")])
            self.assertEqual(checks.look_out(root, "Thing", "0.4.0", "0.4.0"), [])
            self.assertEqual(checks.look_out(root, "Other", "0.2.0", "0.4.0"), [])


class SettingsTests(unittest.TestCase):
    def test_the_repository_command_is_run_with_the_commit(self):
        seen = {}

        def run(command, **kwargs):
            seen["command"] = command

            class Result:
                returncode, stdout, stderr = 0, json.dumps([{"mod": "Thing", "key": "Thing_Sails", "what": "added"}]), ""
            return Result()

        found, note = checks.settings_changes("repo", {"settingsChanges": ["{python}", "s.py", "--since", "{commit}"]}, "abc", run)
        self.assertEqual(seen["command"][1:], ["s.py", "--since", "abc"])
        self.assertEqual((found[0]["key"], note), ("Thing_Sails", None))

    def test_a_failing_command_is_a_note_not_a_failure(self):
        class Result:
            returncode, stdout, stderr = 2, "", "git could not read abc"
        found, note = checks.settings_changes("repo", {"settingsChanges": ["x", "{commit}"]}, "abc", lambda *a, **k: Result())
        self.assertIsNone(found)
        self.assertIn("git could not read", note)


class RebuiltTests(unittest.TestCase):
    """An assembly whose own sources are unchanged since the installed commit was only rebuilt."""

    def repository(self, tmp):
        root = Path(tmp)
        for args in (["init", "-q"], ["config", "core.fsmonitor", "false"], ["config", "user.email", "t@example.com"],
                     ["config", "user.name", "T"]):
            subprocess.run(["git", "-c", "core.fsmonitor=false", *args], cwd=root, check=True, capture_output=True)
        write(root / "src" / "Thing" / "Thing.csproj", "<Project><PropertyGroup><ModFolder>Thing</ModFolder>"
              "<AssemblyName>Thing</AssemblyName></PropertyGroup></Project>")
        write(root / "src" / "Thing" / "Boat.cs", "class Boat {}")
        write(root / "src" / "Other" / "Other.csproj", "<Project><PropertyGroup><ModFolder>Thing</ModFolder>"
              "<AssemblyName>Other</AssemblyName></PropertyGroup></Project>")
        write(root / "src" / "Other" / "Oar.cs", "class Oar {}")
        subprocess.run(["git", "-c", "core.fsmonitor=false", "add", "src"], cwd=root, check=True, capture_output=True)
        subprocess.run(["git", "-c", "core.fsmonitor=false", "commit", "-q", "-m", "one"], cwd=root, check=True, capture_output=True)
        commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, check=True, capture_output=True, text=True).stdout.strip()
        config = {"mods": "mods", "build": {"projects": "src/*/*.csproj", "modProperty": "ModFolder"}}
        return root, config, commit

    def files(self, *names):
        return {"total": len(names), "counts": {"code": len(names)},
                "paths": [{"path": f"1.7/Assemblies/{n}", "change": "changed", "category": "code"} for n in names]}

    def test_an_assembly_whose_own_code_is_unchanged_is_marked_rebuilt(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, config, commit = self.repository(tmp)
            write(root / "src" / "Other" / "Oar.cs", "class Oar { int blades = 2; }")
            builds = checks.build_states(root, config)["Thing"]
            files = self.files("Thing.dll", "Other.dll")
            self.assertEqual(checks.mark_rebuilt(files, builds, root, commit), 1)
            self.assertEqual([p.get("rebuilt", False) for p in files["paths"]], [True, False])
            self.assertEqual(files["rebuilt"], 1)

    def test_a_new_source_file_git_has_not_seen_counts_as_a_change(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, config, commit = self.repository(tmp)
            write(root / "src" / "Thing" / "Sail.cs", "class Sail {}")
            files = self.files("Thing.dll")
            checks.mark_rebuilt(files, checks.build_states(root, config)["Thing"], root, commit)
            self.assertNotIn("rebuilt", files["paths"][0])

    def test_without_a_known_commit_nothing_is_called_rebuilt(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, config, _ = self.repository(tmp)
            files = self.files("Thing.dll")
            self.assertEqual(checks.mark_rebuilt(files, checks.build_states(root, config)["Thing"], root, None), 0)


class MovesTests(unittest.TestCase):
    def fixture(self, tmp):
        repo, game = Path(tmp) / "repo", Path(tmp) / "Game"
        for name in ("Thing", "Other"):
            write(repo / "mods" / name / "CHANGELOG.md", LOG)
            write(repo / "mods" / name / "About" / "About.xml", "<ModMetaData><name>T</name><modVersion>0.2.0</modVersion></ModMetaData>")
        write(repo / ".local" / "settings.json", json.dumps({"rimworldPath": str(game)}))
        write(repo / "config" / "installs.json", json.dumps({
            "schemaVersion": 1, "game": "rimworld", "mods": "mods", "backups": ".local/backups", "settings": ".local/settings.json",
            "install": ["{python}", "deploy.py", "--apply", "{mod}"],
            "build": {"command": ["{python}", "deploy.py", "--build-only"]}}))
        (game / "Mods").mkdir(parents=True)
        return repo

    def run_cli(self, repo, *argv, running=lambda names: []):
        seen = {}

        def run(command, **kwargs):
            seen["command"] = command

            class Result:
                returncode, stdout, stderr = 0, "done\n", ""
            return Result()

        out = io.StringIO()
        code = installs_cli.main([*argv, "--root", str(repo), "--json"], environ={}, out=out, now=datetime(2026, 11, 18),
                                 running=running, run=run)
        return code, json.loads(out.getvalue()), seen

    def test_several_mods_install_in_one_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, answer, seen = self.run_cli(self.fixture(tmp), "install", "--mod", "Thing", "--mod", "Other")
            self.assertEqual(code, 0)
            self.assertEqual(seen["command"][1:], ["deploy.py", "--apply", "Thing", "Other"])
            self.assertEqual(answer["data"]["mods"], ["Thing", "Other"])

    def test_build_runs_while_the_game_does(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, answer, seen = self.run_cli(self.fixture(tmp), "build", running=lambda names: ["rimworld.exe"])
            self.assertEqual((code, answer["data"]["ok"]), (0, True))
            self.assertEqual(seen["command"][1:], ["deploy.py", "--build-only"])

    def test_status_says_whether_the_repository_can_build(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, answer, _ = self.run_cli(self.fixture(tmp), "status")
            self.assertEqual(code, 0)
            self.assertTrue(answer["data"]["canBuild"])
            self.assertEqual(answer["report"]["title"].split(",")[0], "Installs: 2 mods")


if __name__ == "__main__":
    unittest.main()
