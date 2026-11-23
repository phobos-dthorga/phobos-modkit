"""command-docs: the generated reports-and-options block in each command's doc, and the README's command index. The commands
are written by hand as the manifest describes them, and the docs live in temporary folders; one test reads the kit's own config."""
import io
import json
from pathlib import Path
import tempfile
import unittest

import support  # noqa: F401  (puts the package on the path)
from phobos_modkit import command_docs
from phobos_modkit.commands import COMMANDS


def option(name, help="", kind="text", default=None, positional=False, required=False, repeatable=False, choices=None,
           metavar=None):
    return {"name": name, "positional": positional, "kind": kind, "required": required, "repeatable": repeatable,
            "choices": choices, "default": default, "metavar": metavar, "help": help}


JSON = option("--json", "print JSON instead of Markdown", kind="flag", default=False)
REDACT = option("--no-redact", "show the home folder instead of ~", kind="flag", default=False)


def report(name, help, options, effect="reads", when=None, note=None, exclusive=()):
    return {"name": name, "help": help, "effect": effect, "when": when, "note": note, "question": None, "surface": None,
            "options": options + [JSON, REDACT], "exclusive": [list(g) for g in exclusive]}


def commands():
    top = option("--top", "rows per table (default 15)", kind="integer", default=15)
    game = option("--game", "the game's folder (else GAME_PATH, settings, the default)")
    return [
        {"name": "alpha", "summary": "what alpha answers", "game": None, "reports": [
            report("summary", "the whole picture", [top, game]),
            report("mod", "one mod", [top, game, option("name", "a mod's name; * and ? are wildcards", positional=True,
                                                         required=True)]),
            report("fix", "put it right", [top, game, option("--apply", "write it", kind="flag", default=False),
                                           option("--check", "only check", kind="flag", default=False),
                                           option("--via", "how to send it", choices=["a", "b"], default="a"),
                                           option("--set", "a new value", repeatable=True, metavar="KEY=VALUE")],
                   effect="writes", when="--apply", note="writes the <Name> file", exclusive=[("--apply", "--check")])]},
        {"name": "beta", "summary": "what beta answers", "game": "somegame", "reports": [
            report(None, "beta", [option("--root", "the repository", required=True)], effect="runs")]},
        {"name": "gamma", "summary": "what gamma answers", "game": None, "reports": [report(None, "gamma", [])]},
    ]


CONFIG = {"schemaVersion": 1, "readme": "README.md", "settingsDoc": "docs/settings.md", "brief": ["--json", "--no-redact"],
          "paths": ["--game"], "docs": {"alpha": "docs/alpha.md", "beta": "docs/shared.md", "gamma": "docs/shared.md"}}


class Repository:
    def __init__(self, tmp, config=CONFIG):
        self.root = Path(tmp)
        (self.root / "config").mkdir()
        (self.root / "docs").mkdir()
        (self.root / "config" / "command-docs.json").write_text(json.dumps(config), encoding="utf-8")
        self.put("docs/alpha.md", "# alpha\n\nIts own words.\n")
        self.put("docs/shared.md", "# shared\n\nTwo commands.\n")
        self.put("README.md", "# Kit\n\n## Tools\n\n<!-- generated: command index -->\nold\n<!-- end generated -->\n\n## Licence\n")

    def put(self, relative, text):
        (self.root / relative).write_bytes(text.encode("utf-8"))

    def text(self, relative):
        return (self.root / relative).read_bytes().decode("utf-8")

    def run(self, *argv):
        out = io.StringIO()
        code = command_docs.main(["--root", str(self.root), "--json", *argv], out=out, commands=commands())
        return code, json.loads(out.getvalue())["data"]


class OneBlock(unittest.TestCase):
    def setUp(self):
        self.alpha = commands()[0]
        self.lines = command_docs.command_block(self.alpha, "docs/alpha.md", CONFIG)
        self.text = "\n".join(self.lines)

    def test_every_report_is_listed_with_its_effect_and_note(self):
        self.assertIn("| `summary` | The whole picture. | reads only |", self.text)
        self.assertIn("| `fix` | Put it right. Writes the \\<Name> file. | writes, with `--apply` |", self.text)

    def test_an_option_every_report_takes_alike_is_one_row(self):
        self.assertEqual(sum(1 for line in self.lines if line.startswith("| `--top N`")), 1)
        self.assertIn("| `--top N` | all | rows per table (default 15) | `15` |", self.text)

    def test_an_option_of_one_report_names_it(self):
        self.assertIn("| `NAME` | `mod` | a mod's name; \\* and ? are wildcards |  |", self.text)

    def test_choices_repeats_and_placeholders_are_said(self):
        self.assertIn("| `--via VALUE` | `fix` | how to send it. One of `a`, `b`. | `a` |", self.text)
        self.assertIn("| `--set KEY=VALUE` | `fix` | a new value. Repeatable. |  |", self.text)

    def test_shared_options_are_said_once(self):
        self.assertFalse(any(line.startswith("| `--json`") for line in self.lines))
        self.assertIn("Every report also takes `--json` (print JSON instead of Markdown) and `--no-redact`", self.text)

    def test_paths_point_to_the_settings_doc_and_exclusions_are_named(self):
        self.assertIn("[settings](settings.md)", self.text)
        self.assertIn("Only one of `--apply`, `--check` at a time (`fix`).", self.text)
        self.assertIn("Names in capitals are given bare", self.text)

    def test_a_command_without_reports_has_no_reports_column(self):
        beta = "\n".join(command_docs.command_block(commands()[1], "rules/README.md", CONFIG))
        self.assertIn("Effect: runs other programs.", beta)
        self.assertIn("| `--root VALUE` | the repository. Required. |  |", beta)
        self.assertNotIn("| Report |", beta)

    def test_no_options_is_said(self):
        gamma = "\n".join(command_docs.command_block(commands()[2], "docs/shared.md", CONFIG))
        self.assertIn("It takes `--json`", gamma)

    def test_common_options_point_to_their_page_in_the_configs_order(self):
        config = dict(CONFIG, commonDoc="docs/common-options.md", common=["--root", "--game", "--top", "--json", "--no-redact"])
        alpha = "\n".join(command_docs.command_block(self.alpha, "docs/alpha.md", config))
        self.assertIn("[Common options](common-options.md) explains `--game`, `--top`, `--json` and `--no-redact`, which many "
                      "commands share.", alpha)
        beta = "\n".join(command_docs.command_block(commands()[1], "rules/README.md", config))
        self.assertIn("[Common options](../docs/common-options.md) explains `--root`, `--json` and `--no-redact`", beta)
        self.assertNotIn("Common options", self.text)

    def test_a_link_from_another_folder_climbs_out(self):
        self.assertEqual(command_docs._relative("docs/settings.md", "rules/README.md"), "../docs/settings.md")
        self.assertEqual(command_docs._relative("docs/alpha.md", "README.md"), "docs/alpha.md")

    def test_a_help_that_states_another_default_is_found(self):
        wrong = {"name": "x", "reports": [report(None, "x", [option("--top", "rows (default 25)", kind="integer", default=40)])]}
        self.assertEqual(command_docs.mismatched_defaults(wrong), [(None, "--top", "25", 40)])
        self.assertEqual(command_docs.mismatched_defaults(commands()[0]), [])


class Files(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repo = Repository(self.temp.name)

    def test_a_check_names_missing_blocks_and_fails_without_writing(self):
        code, data = self.repo.run()
        self.assertEqual(code, command_docs.EXIT_FAILED)
        states = {d["path"]: d["state"] for d in data["docs"]}
        self.assertEqual(states, {"docs/alpha.md": "block missing", "docs/shared.md": "block missing", "README.md": "out of date"})
        self.assertEqual(self.repo.text("docs/alpha.md"), "# alpha\n\nIts own words.\n")

    def test_write_adds_a_section_keeps_the_doc_and_then_checks_clean(self):
        code, data = self.repo.run("--write")
        self.assertEqual(code, command_docs.EXIT_OK)
        self.assertEqual(sorted(data["written"]), ["README.md", "docs/alpha.md", "docs/shared.md"])
        alpha = self.repo.text("docs/alpha.md")
        self.assertTrue(alpha.startswith("# alpha\n\nIts own words.\n\n## Reports and options\n\n<!-- generated: options alpha -->\n"))
        self.assertTrue(alpha.endswith("<!-- end generated -->\n"))
        self.assertEqual(self.repo.run(), (command_docs.EXIT_OK, self.repo.run()[1]))

    def test_a_doc_with_two_commands_gets_a_heading_for_each(self):
        self.repo.run("--write")
        shared = self.repo.text("docs/shared.md")
        self.assertEqual(shared.count("## Reports and options"), 1)
        self.assertLess(shared.index("### `beta`"), shared.index("<!-- generated: options beta -->"))
        self.assertLess(shared.index("<!-- generated: options beta -->"), shared.index("### `gamma`"))

    def test_a_hand_edited_block_is_out_of_date_and_put_back_where_it_was(self):
        self.repo.run("--write")
        moved = self.repo.text("docs/alpha.md").replace("rows per table", "rows, edited by hand")
        moved = moved.replace("Its own words.\n", "Its own words.\n\n## Later\n\nStill mine.\n")
        self.repo.put("docs/alpha.md", moved)
        code, data = self.repo.run()
        self.assertEqual(code, command_docs.EXIT_FAILED)
        self.assertEqual(next(d for d in data["docs"] if d["path"] == "docs/alpha.md")["stale"], ["alpha"])
        self.repo.run("--write")
        alpha = self.repo.text("docs/alpha.md")
        self.assertIn("rows per table", alpha)
        self.assertIn("## Later\n\nStill mine.", alpha)
        self.assertEqual(alpha.count("<!-- generated: options alpha -->"), 1)

    def test_the_readme_index_links_each_doc_and_keeps_the_rest(self):
        self.repo.run("--write")
        readme = self.repo.text("README.md")
        self.assertIn("| [`alpha`](docs/alpha.md) | any | what alpha answers |", readme)
        self.assertIn("| [`beta`](docs/shared.md) | somegame | what beta answers |", readme)
        self.assertNotIn("old", readme)
        self.assertTrue(readme.endswith("<!-- end generated -->\n\n## Licence\n"))

    def test_crlf_stays_crlf(self):
        self.repo.put("docs/alpha.md", "# alpha\r\n\r\nIts own words.\r\n")
        self.repo.run("--write")
        raw = self.repo.text("docs/alpha.md")
        self.assertNotIn("\n", raw.replace("\r\n", ""))
        self.assertEqual(self.repo.run()[0], command_docs.EXIT_OK)

    def test_a_command_with_no_doc_and_a_doc_not_there_are_problems(self):
        config = dict(CONFIG, docs={"alpha": "docs/missing.md", "beta": "docs/shared.md", "ghost": "docs/shared.md"})
        (self.repo.root / "config" / "command-docs.json").write_text(json.dumps(config), encoding="utf-8")
        code, data = self.repo.run("--write")
        self.assertEqual(code, command_docs.EXIT_FAILED)
        self.assertIn("`gamma` has no doc in config/command-docs.json", data["problems"])
        self.assertIn("config/command-docs.json names `ghost`, which is not a command", data["problems"])
        self.assertTrue(any(p.startswith("docs/missing.md does not exist") for p in data["problems"]))

    def test_a_common_options_page_not_there_is_a_problem(self):
        config = dict(CONFIG, commonDoc="docs/common-options.md", common=["--top"])
        (self.repo.root / "config" / "command-docs.json").write_text(json.dumps(config), encoding="utf-8")
        code, data = self.repo.run("--write")
        self.assertEqual(code, command_docs.EXIT_FAILED)
        self.assertIn("docs/common-options.md does not exist (the common options page)", data["problems"])
        self.repo.put("docs/common-options.md", "# Common options\n")
        self.assertEqual(self.repo.run("--write")[0], command_docs.EXIT_OK)


class TheKitsOwnConfig(unittest.TestCase):
    def test_every_command_has_a_doc_that_exists(self):
        config = command_docs.load_config(command_docs.KIT_ROOT)
        self.assertEqual(set(config["docs"]), set(COMMANDS))
        for name, doc in config["docs"].items():
            self.assertTrue((command_docs.KIT_ROOT / doc).is_file(), (name, doc))
        self.assertTrue((command_docs.KIT_ROOT / config["commonDoc"]).is_file())


if __name__ == "__main__":
    unittest.main()
