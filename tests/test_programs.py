"""programs: what other programs the tools use, and the kit's compiled tools ready-built for an installer (1.62.0)."""
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

import support  # noqa: F401  (puts the package on the path)
from phobos_modkit import assemblies, native, programs


def touch(path, data=b"x"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


class ReadyBuiltTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        base = Path(self.temp.name)
        self.tools = base / "runtime" / "tools"
        self.build = base / "build"
        self.environ = {native.BUNDLED_ENV: str(self.tools), native.BUILD_ENV: str(self.build)}

    def tearDown(self):
        self.temp.cleanup()

    def test_a_ready_built_tool_is_found_before_a_build(self):
        built = touch(self.build / "release" / native.program_name("xml-index"))
        self.assertEqual(native.tool_path("xml-index", environ=self.environ, root=Path(self.temp.name)), built)
        bundled = touch(self.tools / native.program_name("xml-index"))
        self.assertEqual(native.tool_path("xml-index", environ=self.environ, root=Path(self.temp.name)), bundled)

    def test_with_nothing_built_the_path_is_where_a_build_would_go(self):
        path = native.tool_path("xml-index", environ=self.environ, root=Path(self.temp.name))
        self.assertEqual(path, self.build / "release" / native.program_name("xml-index"))

    def test_the_ready_built_folder_defaults_to_tools_beside_the_package_folder(self):
        root = Path(self.temp.name) / "runtime"
        self.assertEqual(native.bundled_dir({}, root), root / "tools")

    def test_a_ready_built_reader_is_used_without_building(self):
        reader = touch(self.tools / assemblies.BUNDLED_FOLDER / native.program_name(assemblies.READER_NAME))

        def refuse(*args, **kwargs):
            raise AssertionError("nothing should be built when the reader came ready-built")
        self.assertEqual(assemblies.ensure_reader(self.environ, run=refuse), reader)

    def test_bundle_builds_both_and_stamps_the_folder_last(self):
        commands = []

        def run(command, **kwargs):
            commands.append(command)
            if command[:2] == ["cargo", "build"]:
                touch(self.build / "release" / native.program_name("xml-index"), b"indexer")
            if command[:2] == ["dotnet", "publish"]:
                folder = Path(command[command.index("-o") + 1])
                touch(folder / native.program_name(assemblies.READER_NAME), b"reader")
            return subprocess.CompletedProcess(command, 0, "", "")
        out = Path(self.temp.name) / "out"
        made = programs.bundle(out, self.environ, run=run, which=lambda name: name)
        self.assertEqual([c[:2] for c in commands], [["cargo", "build"], ["dotnet", "publish"]])
        self.assertIn(native.program_name("xml-index"), made["files"])
        self.assertIn(f"assemblies/{native.program_name(assemblies.READER_NAME)}", made["files"])
        stamp = json.loads((out / programs.STAMP).read_text(encoding="utf-8"))
        self.assertEqual(stamp["files"], made["files"])

    def test_bundle_refuses_a_folder_that_is_not_a_full_path(self):
        with self.assertRaises(native.ToolMissing):
            programs.bundle("relative/tools", self.environ, run=lambda *a, **k: None)

    def test_a_failed_publish_leaves_no_stamp(self):
        def run(command, **kwargs):
            return subprocess.CompletedProcess(command, 1 if command[:2] == ["dotnet", "publish"] else 0, "boom", "")
        out = Path(self.temp.name) / "out"
        touch(out / programs.STAMP, b"{}")
        with self.assertRaises(assemblies.ReaderError):
            programs.bundle(out, self.environ, run=run, which=lambda name: name)
        self.assertFalse((out / programs.STAMP).exists())


class StatusTests(unittest.TestCase):
    def test_every_program_says_what_needs_it_and_where_to_get_it(self):
        found = programs.status({})
        keys = [p["key"] for p in found["programs"]]
        for key in ("git", "xml-index", "assembly-reader", "dotnet", "ilspycmd", "steam"):
            self.assertIn(key, keys)
        for program in found["programs"]:
            self.assertTrue(program["neededBy"] and program["get"] and program["how"], program["key"])
        self.assertEqual(found["missing"], sum(1 for p in found["programs"] if not p["here"]))

    def test_a_game_brings_its_own_programs_through_its_adapter(self):
        games = {game for game, _ in programs.game_programs()}
        self.assertIn("rimworld", games)

    def test_a_lookup_that_fails_is_said_and_the_rest_still_reported(self):
        broken = programs.Program("broken", "Broken", "nothing", "nowhere",
                                  lambda environ: (_ for _ in ()).throw(OSError("denied")))
        saved = list(programs.CORE)
        programs.CORE.append(broken)
        try:
            row = next(p for p in programs.status({})["programs"] if p["key"] == "broken")
        finally:
            programs.CORE[:] = saved
        self.assertFalse(row["here"])
        self.assertIn("denied", row["how"])

    def test_dotnet_versions_are_read_from_its_folders(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            dotnet = touch(root / "dotnet.exe")
            (root / "shared" / "Microsoft.NETCore.App" / "10.0.15").mkdir(parents=True)
            (root / "sdk" / "10.0.402").mkdir(parents=True)
            self.assertEqual(programs.dotnet_versions(dotnet), (["10.0.15"], ["10.0.402"]))

    def test_the_report_and_its_envelope(self):
        out = io.StringIO()
        self.assertEqual(programs.main(["status", "--json"], out=out), 0)
        envelope = json.loads(out.getvalue())
        self.assertEqual(envelope["tool"], "programs")
        self.assertIn("programs", envelope["data"])


if __name__ == "__main__":
    unittest.main()
