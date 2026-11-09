"""The tool manifest and the envelope every command's --json prints."""
import io
import json
from pathlib import Path, PurePosixPath
import unittest

import support  # noqa: F401  (puts the package on the path)
from phobos_modkit import __version__, manifest as kit_manifest
from phobos_modkit.commands import COMMANDS
from phobos_modkit.report import Report, Table, envelope, envelope_text

PACKAGE = Path(kit_manifest.__file__).parent


def find(data, command):
    return next(c for c in data["commands"] if c["name"] == command)


def report_of(command, name):
    return next(r for r in command["reports"] if r["name"] == name)


class Manifest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = kit_manifest.manifest()

    def test_lists_every_command_in_order(self):
        self.assertEqual([c["name"] for c in self.data["commands"]], list(COMMANDS))

    def test_every_report_has_a_known_effect(self):
        for command in self.data["commands"]:
            for report in command["reports"]:
                self.assertIn(report["effect"], kit_manifest.EFFECTS, (command["name"], report["name"]))

    def test_declared_effects_name_real_reports(self):
        from importlib import import_module
        for name, (module, _) in COMMANDS.items():
            declared = import_module(module, "phobos_modkit").MANIFEST
            known = {r["name"] for r in find(self.data, name)["reports"]}
            self.assertLessEqual(set(declared.get("reports", {})), known, name)

    def test_the_uploader_is_marked_owner_only(self):
        publish = find(self.data, "steam-publish")
        self.assertEqual(report_of(publish, "upload")["effect"], kit_manifest.OWNER_ONLY)
        self.assertEqual(report_of(publish, "update")["effect"], kit_manifest.OWNER_ONLY)

    def test_writing_only_with_a_flag_says_which(self):
        constants = report_of(find(self.data, "release"), "constants")
        self.assertEqual((constants["effect"], constants["when"]), (kit_manifest.WRITES, "--apply"))

    def test_options_come_from_the_parser(self):
        find_report = report_of(find(self.data, "code"), "find")
        options = {o["name"]: o for o in find_report["options"]}
        self.assertTrue(options["pattern"]["positional"])
        self.assertTrue(options["pattern"]["required"])
        self.assertEqual(options["--top"]["kind"], "integer")
        self.assertEqual(options["--top"]["default"], 40)
        self.assertEqual(options["--json"]["kind"], "flag")
        self.assertTrue(options["--kind"]["repeatable"])

    def test_exclusive_options_are_listed(self):
        constants = report_of(find(self.data, "release"), "constants")
        self.assertIn(["--list", "--check", "--apply"], constants["exclusive"])

    def test_a_command_without_reports_has_one_unnamed(self):
        self.assertEqual([r["name"] for r in find(self.data, "gate")["reports"]], [None])

    def test_games_are_named_only_by_adapters(self):
        self.assertEqual(find(self.data, "rimworld-save")["game"], "rimworld")
        self.assertIsNone(find(self.data, "release")["game"])

    def test_command_line(self):
        out = io.StringIO()
        self.assertEqual(kit_manifest.main(["--json"], out=out), 0)
        parsed = json.loads(out.getvalue())
        self.assertEqual(parsed["tool"], "manifest")
        self.assertEqual(len(parsed["data"]["commands"]), len(COMMANDS))
        out = io.StringIO()
        self.assertEqual(kit_manifest.main([], out=out), 0)
        self.assertIn(f"{len(COMMANDS)} commands.", out.getvalue())


class Envelope(unittest.TestCase):
    def setUp(self):
        self.report = Report("Things")
        self.report.lines.append("under /home/me")
        self.report.section("Table", Table(["A"], [["/home/me/x"]]))
        self.redact = lambda text: text.replace("/home/me", "~")

    def test_shape(self):
        made = envelope("tool-name", self.report)
        self.assertEqual(sorted(made), ["data", "envelope", "kit_version", "report", "tool"])
        self.assertEqual((made["envelope"], made["tool"], made["kit_version"]), (1, "tool-name", __version__))
        self.assertEqual(made["data"], {})
        self.assertEqual(made["report"]["title"], "Things")

    def test_redaction_reaches_the_data(self):
        made = envelope("t", self.report, self.redact, {"path": PurePosixPath("/home/me/a"), "deep": [{"note": "/home/me/b"}], "n": 3})
        self.assertEqual(made["report"]["lines"], ["under ~"])
        self.assertEqual(made["data"]["path"], "~/a")
        self.assertEqual(made["data"]["deep"][0]["note"], "~/b")
        self.assertEqual(made["data"]["n"], 3)

    def test_text_is_json(self):
        self.assertEqual(json.loads(envelope_text("t", self.report))["tool"], "t")

    def test_no_command_prints_its_own_shape(self):
        for module, _ in COMMANDS.values():
            path = PACKAGE.joinpath(*module.strip(".").split(".")).with_suffix(".py")
            self.assertNotIn("render_json(", path.read_text(encoding="utf-8"), path.name)


if __name__ == "__main__":
    unittest.main()
