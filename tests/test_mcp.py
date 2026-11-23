"""mcp: the kit's read-only reports offered to AI programs over the Model Context Protocol (1.109.0). No real report runs and no
real games list is read: the runner and the repositories are stand-ins."""
import io
import json
from pathlib import Path
import tempfile
import unittest

import support  # noqa: F401  (puts the package on the path)
from phobos_modkit import games_list, mcp, safe_copies_daily
from phobos_modkit.manifest import ONLINE, OWNER_ONLY, READS, WRITES


def option(name, kind="text", positional=False, required=False, repeatable=False, choices=None, default=None):
    return {"name": name, "positional": positional, "kind": kind, "required": required, "repeatable": repeatable,
            "choices": choices, "default": default, "metavar": None, "help": f"the {name}"}


COMMON = [option("--json", "flag"), option("--no-redact", "flag")]
MANIFEST = {"manifest": 1, "commands": [
    {"name": "sample-save", "summary": "answers questions about a save", "game": "samplegame", "reports": [
        {"name": "pawns", "help": "every colonist and their health", "effect": READS, "question": "Who is in the colony?",
         "note": None, "options": [option("--top", "integer", default=15), option("--root"), option("--save"),
                                   option("--kind", choices=["animal", "human"]), option("--rebuild", "flag"),
                                   option("--name", repeatable=True)] + COMMON},
        {"name": "find", "help": "one thing by id", "effect": READS, "question": None, "note": None,
         "options": [option("thing_id", positional=True, required=True)] + COMMON},
        {"name": "snapshot", "help": "writes a snapshot", "effect": WRITES, "question": None, "note": None,
         "options": COMMON}]},
    {"name": "sample-web", "summary": "reads public pages", "game": None, "reports": [
        {"name": None, "help": "what players say", "effect": ONLINE, "question": "What do players say?", "note": None,
         "options": COMMON}]},
    {"name": "sample-upload", "summary": "the owner's own", "game": None, "reports": [
        {"name": None, "help": "uploads", "effect": OWNER_ONLY, "question": None, "note": None, "options": COMMON}]},
    {"name": "mcp", "summary": "itself", "game": None, "reports": [
        {"name": "serve", "help": "serves", "effect": READS, "question": None, "note": None, "options": []}]},
]}


class Calls:
    """A stand-in runner that keeps what it was asked and answers as told."""

    def __init__(self, code=0, out="# Answer\n\nC:\\Users\\someone\\Saves\n", err=""):
        self.calls, self.code, self.out, self.err = [], code, out, err

    def __call__(self, argv, cwd):
        self.calls.append((argv, cwd))
        return self.code, self.out, self.err


class McpTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.repo = Path(self.temp.name) / "sample-mods"
        self.repo.mkdir()
        self.listed = [games_list.Listed(self.repo, "samplegame", "Sample Game")]
        self.runner = Calls()
        self.server = self.make()

    def tearDown(self):
        self.temp.cleanup()

    def make(self, online=False, runner=None):
        return mcp.Server(online=online, entries=mcp.catalogue(online, MANIFEST), repositories=lambda: self.listed,
                          runner=runner or self.runner, redact=lambda text: text.replace("C:\\Users\\someone", "~"),
                          workplace=self.temp.name)

    def ask(self, method, params=None, message_id=1, server=None):
        message = {"jsonrpc": "2.0", "id": message_id, "method": method}
        if params is not None:
            message["params"] = params
        return (server or self.server).handle(message)

    def call(self, name, arguments, server=None):
        return self.ask("tools/call", {"name": name, "arguments": arguments}, server=server)["result"]

    # What is offered.

    def test_only_reports_that_read_are_offered(self):
        offered = {(e["command"], e["report"]) for e in mcp.catalogue(False, MANIFEST)}
        self.assertEqual(offered, {("sample-save", "pawns"), ("sample-save", "find")})

    def test_reading_public_pages_only_when_online(self):
        offered = {(e["command"], e["report"]) for e in mcp.catalogue(True, MANIFEST)}
        self.assertIn(("sample-web", None), offered)
        self.assertNotIn(("sample-upload", None), offered)
        self.assertNotIn(("mcp", "serve"), offered)

    def test_the_server_sets_json_redaction_and_root_itself(self):
        pawns = next(e for e in mcp.catalogue(False, MANIFEST) if e["report"] == "pawns")
        self.assertEqual([o["name"] for o in pawns["options"]], ["--top", "--save", "--kind", "--rebuild", "--name"])
        self.assertTrue(pawns["takes_root"])

    def test_the_real_manifest_offers_only_reading(self):
        for entry in mcp.catalogue(False):
            self.assertEqual(entry["effect"], READS, entry["command"])
            self.assertNotEqual(entry["command"], "mcp")

    # The handshakes.

    def test_the_older_handshake_echoes_a_version_it_knows(self):
        reply = self.ask("initialize", {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "x"}})
        self.assertEqual(reply["result"]["protocolVersion"], "2025-06-18")
        self.assertEqual(reply["result"]["capabilities"], {"tools": {"listChanged": False}})
        self.assertEqual(reply["result"]["serverInfo"]["name"], mcp.NAME)
        self.assertTrue(self.server.legacy)

    def test_the_older_handshake_offers_its_newest_for_an_unknown_version(self):
        reply = self.ask("initialize", {"protocolVersion": "2099-01-01"})
        self.assertEqual(reply["result"]["protocolVersion"], mcp.LEGACY[0])

    def test_notifications_are_not_answered(self):
        self.assertIsNone(self.server.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}))

    def test_discover_answers_the_new_revision(self):
        result = self.ask("server/discover", {"_meta": {mcp.META + "protocolVersion": mcp.MODERN,
                                                         mcp.META + "clientCapabilities": {}}})["result"]
        self.assertEqual(result["resultType"], "complete")
        self.assertEqual(result["supportedVersions"], [mcp.MODERN])
        self.assertEqual(result["capabilities"], {"tools": {}})
        self.assertEqual(result["_meta"][mcp.META + "serverInfo"]["title"], mcp.TITLE)

    def test_an_unknown_version_is_refused_with_what_is_supported(self):
        error = self.ask("tools/list", {"_meta": {mcp.META + "protocolVersion": "1900-01-01"}})["error"]
        self.assertEqual(error["code"], mcp.UNSUPPORTED_VERSION)
        self.assertEqual(error["data"], {"supported": list(mcp.SUPPORTED), "requested": "1900-01-01"})

    def test_new_revision_results_carry_their_type_and_old_ones_do_not(self):
        modern = self.ask("tools/list", {"_meta": {mcp.META + "protocolVersion": mcp.MODERN}})["result"]
        older = self.ask("tools/list")["result"]
        self.assertEqual(modern["resultType"], "complete")
        self.assertNotIn("resultType", older)

    def test_unknown_methods_and_tools_are_errors(self):
        self.assertEqual(self.ask("resources/list")["error"]["code"], mcp.METHOD_NOT_FOUND)
        self.assertEqual(self.ask("tools/call", {"name": "delete_everything"})["error"]["code"], mcp.INVALID_PARAMS)

    # The tools.

    def test_three_tools_and_the_repositories_by_name(self):
        tools = self.ask("tools/list")["result"]["tools"]
        self.assertEqual([t["name"] for t in tools], ["find_reports", "describe_report", "ask_report"])
        ask = tools[2]["inputSchema"]["properties"]
        self.assertEqual(ask["repository"]["enum"], ["sample-mods"])
        self.assertTrue(all(t["annotations"]["readOnlyHint"] for t in tools))

    def test_find_reports_by_words_and_game(self):
        found = self.call("find_reports", {"words": "colony"})["structuredContent"]
        self.assertEqual([(r["command"], r["report"]) for r in found["reports"]], [("sample-save", "pawns")])
        self.assertEqual(found["repositories"], [{"name": "sample-mods", "game": "samplegame"}])
        self.assertEqual(self.call("find_reports", {"game": "othergame"})["structuredContent"]["found"], 0)

    def test_describe_lists_the_options_a_caller_may_set(self):
        described = self.call("describe_report", {"command": "sample-save", "report": "pawns"})["structuredContent"]
        self.assertNotIn("--root", [o["name"] for o in described["options"]])
        self.assertEqual(described["repository"], "taken from the repository you name")

    def test_ask_runs_it_in_the_repository_with_its_root(self):
        result = self.call("ask_report", {"command": "sample-save", "report": "pawns", "repository": "sample-mods",
                                          "arguments": {"top": 5, "kind": "human", "rebuild": True, "--name": ["Ana", "Bo"]}})
        self.assertFalse(result["isError"])
        argv, cwd = self.runner.calls[0]
        self.assertEqual(argv, ["sample-save", "pawns", "--top=5", "--kind=human", "--rebuild", "--name=Ana", "--name=Bo",
                                f"--root={self.repo}"])
        self.assertEqual(cwd, str(self.repo))

    def test_answers_are_redacted(self):
        result = self.call("ask_report", {"command": "sample-save", "report": "find", "arguments": {"thing_id": "Pawn42"}})
        self.assertIn("~\\Saves", result["content"][0]["text"])
        self.assertNotIn("someone", result["content"][0]["text"])

    def test_json_form_asks_for_the_envelope(self):
        self.call("ask_report", {"command": "sample-save", "report": "find", "arguments": {"thing_id": "Pawn42"},
                                 "form": "json"})
        self.assertEqual(self.runner.calls[0][0], ["sample-save", "find", "Pawn42", "--json"])

    def test_without_a_repository_it_runs_somewhere_empty(self):
        self.call("ask_report", {"command": "sample-save", "report": "find", "arguments": {"thing_id": "Pawn42"}})
        self.assertEqual(self.runner.calls[0][1], self.temp.name)

    def refusal(self, arguments):
        result = self.call("ask_report", arguments)
        self.assertTrue(result["isError"], arguments)
        self.assertEqual(self.runner.calls, [], arguments)
        return result["content"][0]["text"]

    def test_reports_that_change_things_are_never_run(self):
        self.assertIn("no offered report", self.refusal({"command": "sample-save", "report": "snapshot"}))
        self.assertIn("not offered", self.refusal({"command": "sample-upload"}))
        self.assertIn("not offered", self.refusal({"command": "sample-web"}))

    def test_paths_are_refused(self):
        for value in ("C:\\Windows\\win.ini", "../secret", "/etc/passwd", "~/notes", ".hidden", "D:file"):
            self.assertIn("looks like a file path", self.refusal(
                {"command": "sample-save", "report": "pawns", "arguments": {"save": value}}), value)

    def test_options_the_server_sets_are_refused(self):
        for name in ("root", "--json", "no-redact"):
            self.assertIn("set by the server", self.refusal(
                {"command": "sample-save", "report": "pawns", "arguments": {name: "x"}}))

    def test_wrong_kinds_and_unknown_options_are_refused(self):
        base = {"command": "sample-save", "report": "pawns"}
        self.assertIn("whole number", self.refusal({**base, "arguments": {"top": "ten"}}))
        self.assertIn("whole number", self.refusal({**base, "arguments": {"top": True}}))
        self.assertIn("one of", self.refusal({**base, "arguments": {"kind": "robot"}}))
        self.assertIn("has no option", self.refusal({**base, "arguments": {"delete": True}}))
        self.assertIn("is required", self.refusal({"command": "sample-save", "report": "find"}))
        self.assertIn("may not start", self.refusal({"command": "sample-save", "report": "find",
                                                      "arguments": {"thing_id": "--rebuild"}}))
        self.assertIn("not on the games list", self.refusal({**base, "repository": "someone-elses"}))

    def test_a_failed_report_says_so(self):
        server = self.make(runner=Calls(code=3, out="", err="Traceback ...\nC:\\Users\\someone\\x.py failed"))
        result = self.call("ask_report", {"command": "sample-save", "report": "pawns"}, server=server)
        self.assertTrue(result["isError"])
        self.assertIn("ended with code 3", result["content"][0]["text"])
        self.assertIn("~\\x.py", result["content"][0]["text"])

    def test_long_answers_are_cut_and_say_so(self):
        server = self.make(runner=Calls(out="x" * (mcp.MAX_TEXT + 10)))
        text = self.call("ask_report", {"command": "sample-save", "report": "pawns"}, server=server)["content"][0]["text"]
        self.assertIn("[Cut at", text)

    # The stdio loop.

    def test_one_message_a_line_and_bad_lines_answered(self):
        lines = [{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-11-25"}},
                 {"jsonrpc": "2.0", "method": "notifications/initialized"},
                 {"jsonrpc": "2.0", "id": 2, "method": "ping"}]
        instream = io.BytesIO(b"\n".join(json.dumps(m).encode() for m in lines) + b"\n\nnot json\n")
        outstream = io.BytesIO()
        mcp.serve(instream, outstream, self.server, log=io.StringIO())
        replies = [json.loads(line) for line in outstream.getvalue().splitlines()]
        self.assertEqual([r.get("id") for r in replies], [1, 2, None])
        self.assertEqual(replies[1]["result"], {})
        self.assertEqual(replies[2]["error"]["code"], mcp.PARSE_ERROR)
        self.assertNotIn(b"\r", outstream.getvalue())

    def test_a_failure_inside_is_an_internal_error_and_the_loop_goes_on(self):
        class Broken(mcp.Server):
            def tools(self):
                raise RuntimeError("boom")

        server = Broken(entries=[], repositories=lambda: [])
        instream = io.BytesIO(b'{"jsonrpc":"2.0","id":1,"method":"tools/list"}\n{"jsonrpc":"2.0","id":2,"method":"ping"}\n')
        outstream, log = io.BytesIO(), io.StringIO()
        mcp.serve(instream, outstream, server, log=log)
        replies = [json.loads(line) for line in outstream.getvalue().splitlines()]
        self.assertEqual(replies[0]["error"]["code"], mcp.INTERNAL)
        self.assertEqual(replies[1]["result"], {})
        self.assertIn("boom", log.getvalue())

    # Setting a program up.

    def test_setup_names_this_python_and_the_kit(self):
        found = mcp.setup("my-reports", online=True)
        self.assertEqual(found["args"], ["-m", "phobos_modkit", "mcp", "serve", "--online"])
        self.assertTrue((Path(found["env"]["PYTHONPATH"]) / "phobos_modkit" / "mcp.py").is_file())
        self.assertIn('"my-reports"', found["serversJson"])
        self.assertTrue(found["claudeCode"].startswith("claude mcp add-json --scope user my-reports '"))

    def test_setup_refuses_odd_names(self):
        out = io.StringIO()
        self.assertEqual(mcp.main(["setup", "--name", "a b"], out=out), mcp.EXIT_USAGE)

    # One call at a time, for a program that asks a model itself (1.110.0).

    def test_a_call_answers_as_the_server_would(self):
        text, failed = mcp.call_tool(self.server, "ask_report", {"command": "sample-save", "report": "find",
                                                                 "arguments": {"thing_id": "Pawn42"}})
        self.assertFalse(failed)
        self.assertIn("~\\Saves", text)
        self.assertEqual(self.runner.calls[0][0], ["sample-save", "find", "Pawn42"])

    def test_a_call_keeps_every_refusal(self):
        for tool, arguments in (("ask_report", {"command": "sample-save", "report": "snapshot"}),
                                ("ask_report", {"command": "sample-save", "report": "pawns", "arguments": {"save": "../x"}}),
                                ("delete_everything", {}),
                                ("ask_report", ["not", "an", "object"])):
            text, failed = mcp.call_tool(self.server, tool, arguments)
            self.assertTrue(failed, (tool, arguments))
            self.assertTrue(text)
        self.assertEqual(self.runner.calls, [])

    def test_the_call_command_takes_json_and_says_what_was_wrong(self):
        for arguments, words in (("not json", "not JSON"), ("x" * (mcp.MAX_ARGUMENTS + 1), "longer than")):
            out = io.StringIO()
            self.assertEqual(mcp.main(["call", "--tool", "find_reports", "--arguments", arguments, "--json"], out=out),
                             mcp.EXIT_OK)
            data = json.loads(out.getvalue())["data"]
            self.assertTrue(data["isError"])
            self.assertIn(words, data["text"])

    def test_the_tools_command_lists_the_three(self):
        out = io.StringIO()
        self.assertEqual(mcp.main(["tools", "--json"], out=out), mcp.EXIT_OK)
        tools = json.loads(out.getvalue())["data"]["tools"]
        self.assertEqual([t["name"] for t in tools], list(mcp.TOOLS))

    # The games list, shared with the daily safe copies.

    def test_games_list_entries_name_their_game(self):
        path = Path(self.temp.name) / "games.json"
        path.write_text(json.dumps({"root": self.temp.name, "games": [
            {"id": "samplegame", "name": "Sample Game", "repositories": ["sample-mods", "sample-mods"]},
            {"id": "other", "repositories": ["sample-mods", "elsewhere"]}]}), encoding="utf-8")
        entries = games_list.entries(path)
        self.assertEqual([(e.name, e.game, e.game_name) for e in entries],
                         [("sample-mods", "samplegame", "Sample Game"), ("elsewhere", "other", "other")])
        self.assertEqual(safe_copies_daily.repositories(path), [self.repo, Path(self.temp.name) / "elsewhere"])

    def test_an_unreadable_games_list_is_still_the_daily_runs_own_error(self):
        with self.assertRaises(safe_copies_daily.DailyError):
            safe_copies_daily.repositories(Path(self.temp.name) / "missing.json")


if __name__ == "__main__":
    unittest.main()
