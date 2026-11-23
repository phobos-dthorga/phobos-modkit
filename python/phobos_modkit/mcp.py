"""mcp: the kit's read-only reports offered to AI programs over the Model Context Protocol (1.109.0).

    mcp serve [--online]                   an AI program starts this itself, and speaks to it on standard input and output
    mcp setup [--name NAME] [--online]     what to paste into an AI program's settings so it can start `serve`
    mcp tools [--online]                   the three tools as a program hands them to a model (1.110.0)
    mcp call --tool T --arguments JSON     one tool call a model asked for, answered as `serve` would (1.110.0)

`tools` and `call` let a program that asks a model itself (D'thorga Companion's help on pages) offer the same tools, behind the
same checks, without starting the server: one process for each call, like every other report.

The server offers three tools, not one for each report: find_reports, describe_report and ask_report. **ask_report runs only a
report whose manifest effect is `reads`** (and `reads-online` when started with --online), checked against the manifest at every
call; it never runs one that writes, runs a repository's code, or is the owner's alone. A repository is named from the games list
(D'thorga Companion's games.json), never by a path the program types, and a text value that looks like a path is refused. Every
answer is redacted: the home folder reads ~.

Messages are JSON-RPC 2.0, one a line (the stdio transport). It answers both eras of the protocol: revision 2026-07-28, where each
request carries its version in `_meta` and `server/discover` says what the server supports, and the older `initialize` handshake
(2024-11-05 to 2025-11-25), which the specification lets a server serve beside it. Standard output carries only messages; anything
else goes to standard error. Game-free: what is offered comes from the manifest, so every game with an adapter is reached.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import traceback

from . import __version__, games_list
from .manifest import ONLINE, READS
from .report import Bullets, Code, Fact, Report, envelope_text, home_redactor, keep, render_markdown

EXIT_OK, EXIT_USAGE = 0, 2

MODERN = "2026-07-28"
LEGACY = ("2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05")
SUPPORTED = (MODERN, *LEGACY)
META = "io.modelcontextprotocol/"
NAME = "dthorga-reports"                 # agent choice: the name a program lists the server by
TITLE = "D'thorga Reports"
INSTRUCTIONS = ("Reports from D'thorga's tool kit about game mods: logs, saves, mod lists, code, changes and tests. Use "
                "find_reports to find one, describe_report to read its options, then ask_report. Every report only reads, and "
                "home folders show as ~.")

PARSE_ERROR, INVALID_REQUEST, METHOD_NOT_FOUND, INVALID_PARAMS, INTERNAL = -32700, -32600, -32601, -32602, -32603
UNSUPPORTED_VERSION = -32022

SELF = "mcp"                             # never offered to itself
RESERVED = {"json", "no-redact", "root"}  # the server sets these, or never does
FIND_LIMIT = 25
MAX_TEXT = 60_000                        # characters of a report's answer given back; the rest is cut, and it says so
MAX_ERROR = 3_000
TIMEOUT = 300                            # seconds before a report is stopped (agent default)
FORMS = ("markdown", "json")
TOOLS = ("find_reports", "describe_report", "ask_report")
MAX_ARGUMENTS = 8_000                    # characters of a model's arguments `mcp call` takes
# A text value is refused when it could name a file: a slash, a drive, the home folder or a step up.
PATH_LIKE = re.compile(r"[\\/]|^[A-Za-z]:|^~|^\.|\.\.")


class Refused(ValueError):
    """A tool call the server will not make, with the reason in words for the AI program."""


# ---- What is offered ----

def _key(name):
    return (name or "").lstrip("-").replace("_", "-").lower()


def catalogue(online=False, manifest=None):
    """Every report the server may run, as plain data: only `reads`, and `reads-online` when online is on."""
    if manifest is None:
        from .manifest import manifest as read_manifest
        manifest = read_manifest()
    allowed = {READS, ONLINE} if online else {READS}
    found = []
    for command in manifest["commands"]:
        if command["name"] == SELF:
            continue
        for report in command["reports"]:
            if report["effect"] not in allowed:
                continue
            options = [o for o in report["options"] if _key(o["name"]) not in RESERVED]
            found.append({"command": command["name"], "report": report["name"], "game": command["game"],
                          "effect": report["effect"], "question": report.get("question"), "help": report.get("help") or "",
                          "note": report.get("note"), "summary": command.get("summary") or "", "options": options,
                          "takes_root": any(_key(o["name"]) == "root" for o in report["options"])})
    return found


def listed_repositories(environ=None):
    """The repositories on the games list, by folder name; [] when there is no list."""
    try:
        listed = games_list.entries(games_list.games_file(None, environ))
    except games_list.GamesListError:
        return []
    found, names = [], set()
    for entry in listed:
        if entry.name not in names and entry.folder.is_dir():
            names.add(entry.name)
            found.append(entry)
    return found


# ---- Building a report's command line ----

def _value(option, value):
    """One value as its command-line text, checked against the option's kind; raises Refused."""
    name, kind = option["name"], option["kind"]
    if kind == "integer":
        if isinstance(value, bool) or not isinstance(value, int):
            raise Refused(f"{name} takes a whole number")
        text = str(value)
    elif kind == "number":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise Refused(f"{name} takes a number")
        text = str(value)
    else:
        if isinstance(value, bool) or not isinstance(value, (str, int, float)):
            raise Refused(f"{name} takes text")
        text = str(value).strip()
        if not text:
            raise Refused(f"{name} was given no text")
        if PATH_LIKE.search(text):
            raise Refused(f"{name}: {text!r} looks like a file path, and paths are not taken from AI programs. Leave it out "
                          "and the report uses its own default, or name a repository with `repository`.")
    if option["choices"] and text not in option["choices"]:
        raise Refused(f"{name} takes one of: {', '.join(option['choices'])}")
    return text


def command_line(entry, arguments, root=None):
    """The arguments after `python -m phobos_modkit` for one report; raises Refused."""
    if arguments is None:
        arguments = {}
    if not isinstance(arguments, dict):
        raise Refused("arguments must be an object of option names and values")
    by_key = {_key(o["name"]): o for o in entry["options"]}
    for given in arguments:
        if _key(given) in RESERVED:
            raise Refused(f"{given} is set by the server, not by a caller")
        if _key(given) not in by_key:
            known = ", ".join(o["name"] for o in entry["options"]) or "none"
            raise Refused(f"{entry['command']} {entry['report'] or ''} has no option {given!r}. Its options: {known}")
    values = {_key(k): v for k, v in arguments.items()}
    argv = [entry["command"]] + ([entry["report"]] if entry["report"] else [])
    for option in entry["options"]:
        value = values.get(_key(option["name"]))
        if value is None:
            if option["required"]:
                raise Refused(f"{option['name']} is required: {option['help']}")
            continue
        if option["kind"] == "flag":
            if not isinstance(value, bool):
                raise Refused(f"{option['name']} is a switch: true or false")
            if value and not option["positional"]:
                argv.append(option["name"])
            continue
        items = value if isinstance(value, list) else [value]
        if len(items) > 1 and not option["repeatable"]:
            raise Refused(f"{option['name']} takes one value")
        for item in items:
            text = _value(option, item)
            if option["positional"]:
                if text.startswith("-"):
                    raise Refused(f"{option['name']} may not start with -")
                argv.append(text)
            else:
                argv.append(f"{option['name']}={text}")
    if root is not None and entry["takes_root"]:
        argv.append(f"--root={root}")
    return argv


# ---- Running a report ----

def kit_folder():
    """The folder that holds the phobos_modkit package."""
    return Path(__file__).resolve().parent.parent


def run_report(argv, cwd, timeout=TIMEOUT, environ=None):
    """(exit code, standard output, standard error) of one kit command, run as its own process. Its input is closed, so it can
    never read the messages meant for the server."""
    environ = dict(os.environ if environ is None else environ)
    environ["PYTHONPATH"] = os.pathsep.join(p for p in (str(kit_folder()), environ.get("PYTHONPATH")) if p)
    environ["PYTHONIOENCODING"] = "utf-8"
    environ.pop("PHOBOS_MODKIT_PROGRESS", None)
    try:
        done = subprocess.run([sys.executable, "-m", "phobos_modkit", *argv], cwd=cwd, env=environ, stdin=subprocess.DEVNULL,
                              capture_output=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return None, "", f"it took longer than {timeout} seconds and was stopped"
    return done.returncode, done.stdout.decode("utf-8", "replace"), done.stderr.decode("utf-8", "replace")


def _cut(text, limit):
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n\n[Cut at {limit:,} of {len(text):,} characters. Ask with a smaller --top, or a narrower report.]"


# ---- The server ----

def _error(message_id, code, message, data=None):
    error = {"code": code, "message": message}
    if data is not None:
        error["data"] = data
    return {"jsonrpc": "2.0", "id": message_id, "error": error}


def _text_result(text, is_error=False, structured=None):
    result = {"content": [{"type": "text", "text": text}], "isError": is_error}
    if structured is not None:
        result["structuredContent"] = structured
    return result


class Server:
    """Answers one message at a time. `runner(argv, cwd)` runs a report; `repositories()` lists the games list; both are passed
    in so tests need neither a real kit run nor the owner's list."""

    def __init__(self, online=False, entries=None, repositories=None, runner=None, redact=None, workplace=None):
        self.online = online
        self._entries = entries
        self._repositories = repositories or listed_repositories
        self._runner = runner or run_report
        self._redact = redact or home_redactor()
        self._workplace = workplace
        self.legacy = False

    # What it offers.

    @property
    def entries(self):
        if self._entries is None:
            self._entries = catalogue(self.online)
        return self._entries

    def find_entry(self, command, report):
        if not isinstance(command, str) or not command:
            raise Refused("name a command (find_reports lists them)")
        report = report or None
        found = [e for e in self.entries if e["command"] == command]
        if not found:
            raise Refused(f"{command!r} is not offered. Only reports that only read are offered; find_reports lists them.")
        match = next((e for e in found if e["report"] == report), None)
        if match is None:
            names = ", ".join(e["report"] or "(none)" for e in found)
            raise Refused(f"{command} has no offered report {report!r}. Its offered reports: {names}")
        return match

    def tools(self):
        games = sorted({e["game"] for e in self.entries if e["game"]})
        names = [r.name for r in self._repositories()]
        repository = {"type": "string", "description": "the repository to ask about, from the games list; leave it out for a "
                                                       "report about a game as a whole"}
        if names:
            repository["enum"] = names
        report = {"type": "string", "description": "the report's name after the command; leave it out when the command has one"}
        return [
            {"name": "find_reports", "title": "Find a report",
             "description": "Finds the kit's read-only reports by words, with the question each answers. Start here.",
             "inputSchema": {"type": "object", "additionalProperties": False, "properties": {
                 "words": {"type": "string", "description": "words to look for, such as 'save colonists' or 'log errors'; "
                                                            "leave out to list them all"},
                 "game": {"type": "string", "enum": games, "description": "only this game's reports, and those for any game"}}},
             "annotations": {"readOnlyHint": True, "openWorldHint": False}},
            {"name": "describe_report", "title": "Describe a report",
             "description": "A report's question, what it does and every option it takes, with each option's kind and default.",
             "inputSchema": {"type": "object", "additionalProperties": False, "required": ["command"], "properties": {
                 "command": {"type": "string", "description": "the command, as find_reports names it"}, "report": report}},
             "annotations": {"readOnlyHint": True, "openWorldHint": False}},
            {"name": "ask_report", "title": "Ask a report",
             "description": "Runs one read-only report and gives back its answer, home folders shown as ~. Options are named "
                            "as describe_report lists them; values that look like file paths are refused.",
             "inputSchema": {"type": "object", "additionalProperties": False, "required": ["command"], "properties": {
                 "command": {"type": "string"}, "report": report, "repository": repository,
                 "arguments": {"type": "object", "description": "option name to value, such as {\"top\": 10}"},
                 "form": {"type": "string", "enum": list(FORMS),
                          "description": "markdown (the default) for the summary; json for the whole answer with its data"}}},
             "annotations": {"readOnlyHint": True, "openWorldHint": self.online}},
        ]

    # The tools.

    def find_reports(self, arguments):
        words = [w.lower() for w in str(arguments.get("words") or "").split()]
        game = arguments.get("game")
        found = []
        for e in self.entries:
            if game and e["game"] not in (game, None):
                continue
            text = " ".join(str(e[k] or "") for k in ("command", "report", "help", "question", "note", "summary")).lower()
            if all(w in text for w in words):
                found.append({"command": e["command"], "report": e["report"], "game": e["game"] or "any",
                              "question": e["question"], "help": e["help"]})
        found.sort(key=lambda r: r["question"] is None)
        shown = found[:FIND_LIMIT]
        data = {"reports": shown, "found": len(found),
                "repositories": [{"name": r.name, "game": r.game} for r in self._repositories()]}
        if len(found) > len(shown):
            data["more"] = f"{len(found) - len(shown)} more; add words or a game to narrow it"
        return _text_result(json.dumps(data, ensure_ascii=False, indent=1), structured=data)

    def describe_report(self, arguments):
        e = self.find_entry(arguments.get("command"), arguments.get("report"))
        data = {"command": e["command"], "report": e["report"], "game": e["game"] or "any", "effect": e["effect"],
                "question": e["question"], "help": e["help"], "note": e["note"],
                "repository": "taken from the repository you name" if e["takes_root"] else "not needed",
                "options": [{k: o.get(k) for k in ("name", "positional", "kind", "required", "repeatable", "choices",
                                                   "default", "help")} for o in e["options"]]}
        return _text_result(json.dumps(data, ensure_ascii=False, indent=1), structured=data)

    def ask_report(self, arguments):
        e = self.find_entry(arguments.get("command"), arguments.get("report"))
        form = arguments.get("form") or "markdown"
        if form not in FORMS:
            raise Refused(f"form is one of: {', '.join(FORMS)}")
        named = arguments.get("repository")
        root = None
        if named:
            match = next((r for r in self._repositories() if r.name == named), None)
            if match is None:
                raise Refused(f"{named!r} is not on the games list. On it: "
                              + (", ".join(r.name for r in self._repositories()) or "nothing yet"))
            root = match.folder
        argv = command_line(e, arguments.get("arguments"), root)
        if form == "json":
            argv.append("--json")
        if root is not None:
            code, out, err = self._runner(argv, str(root))
        else:
            with tempfile.TemporaryDirectory(prefix="phobos-mcp-") as empty:
                code, out, err = self._runner(argv, self._workplace or empty)
        out, err = self._redact(out), self._redact(err)
        if code == 0:
            return _text_result(_cut(out, MAX_TEXT))
        said = "\n\n".join(part for part in (out.strip(), err.strip()[-MAX_ERROR:]) if part)
        ended = "was stopped" if code is None else f"ended with code {code}"
        return _text_result(f"The report {ended}.\n\n" + _cut(said or "It said nothing.", MAX_TEXT), is_error=True)

    # Messages.

    def _info(self):
        return {"name": NAME, "title": TITLE, "version": __version__}

    def handle(self, message):
        """The reply to one message, or None for a notification."""
        if isinstance(message, list):
            return _error(None, INVALID_REQUEST, "batches are not supported")
        if not isinstance(message, dict) or message.get("jsonrpc") != "2.0" or not isinstance(message.get("method"), str):
            return _error(message.get("id") if isinstance(message, dict) else None, INVALID_REQUEST, "not a JSON-RPC 2.0 request")
        if "id" not in message:
            return None
        message_id, method = message["id"], message["method"]
        params = message.get("params") or {}
        if not isinstance(params, dict):
            return _error(message_id, INVALID_PARAMS, "params must be an object")
        meta = params.get("_meta") if isinstance(params.get("_meta"), dict) else {}
        version = meta.get(META + "protocolVersion")
        if method == "initialize":
            self.legacy = True
            requested = params.get("protocolVersion")
            return {"jsonrpc": "2.0", "id": message_id, "result": {
                "protocolVersion": requested if requested in LEGACY else LEGACY[0],
                "capabilities": {"tools": {"listChanged": False}}, "serverInfo": self._info(), "instructions": INSTRUCTIONS}}
        if version is not None and version not in SUPPORTED:
            return _error(message_id, UNSUPPORTED_VERSION, "Unsupported protocol version",
                          {"supported": list(SUPPORTED), "requested": version})
        modern = method == "server/discover" or version == MODERN
        try:
            result = self._dispatch(method, params)
        except _NoMethod:
            return _error(message_id, METHOD_NOT_FOUND, f"no method {method}")
        except _BadParams as bad:
            return _error(message_id, INVALID_PARAMS, str(bad))
        if modern:
            result["resultType"] = "complete"
            result["_meta"] = {META + "serverInfo": self._info()}
        return {"jsonrpc": "2.0", "id": message_id, "result": result}

    def _dispatch(self, method, params):
        if method == "server/discover":
            return {"supportedVersions": [MODERN], "capabilities": {"tools": {}}, "instructions": INSTRUCTIONS}
        if method == "ping":
            return {}
        if method == "tools/list":
            return {"tools": self.tools()}
        if method == "tools/call":
            name, arguments = params.get("name"), params.get("arguments") or {}
            tool = {"find_reports": self.find_reports, "describe_report": self.describe_report,
                    "ask_report": self.ask_report}.get(name)
            if tool is None:
                raise _BadParams(f"no tool {name!r}")
            if not isinstance(arguments, dict):
                raise _BadParams("arguments must be an object")
            try:
                return tool(arguments)
            except Refused as refused:
                return _text_result(str(refused), is_error=True)
        raise _NoMethod(method)


class _NoMethod(Exception):
    pass


class _BadParams(Exception):
    pass


def serve(instream, outstream, server, log=None):
    """Reads one JSON-RPC message a line from instream (bytes) and writes each reply as one line to outstream, until the input
    ends. A failure inside a reply is answered as an internal error and told to log; the loop goes on."""
    log = log or sys.stderr
    for raw in iter(instream.readline, b""):
        line = raw.strip()
        if not line:
            continue
        try:
            message = json.loads(line.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            reply = _error(None, PARSE_ERROR, "not JSON")
        else:
            try:
                reply = server.handle(message)
            except Exception:  # noqa: BLE001  (one bad request must not end the server)
                log.write(traceback.format_exc())
                log.flush()
                reply = _error(message.get("id") if isinstance(message, dict) else None, INTERNAL, "the server failed")
        if reply is not None:
            outstream.write(json.dumps(reply, ensure_ascii=False).encode("utf-8") + b"\n")
            outstream.flush()


# ---- Setting a program up ----

def setup(name=NAME, online=False):
    """How an AI program starts this server: its command, arguments and environment, and the lines for its settings."""
    args = ["-m", "phobos_modkit", "mcp", "serve"] + (["--online"] if online else [])
    server = {"command": sys.executable, "args": args, "env": {"PYTHONPATH": str(kit_folder())}}
    servers_json = json.dumps({"mcpServers": {name: server}}, indent=2)
    claude_code = f"claude mcp add-json --scope user {name} '{json.dumps({'type': 'stdio', **server})}'"
    return {"name": name, "online": online, **server, "serversJson": servers_json, "claudeCode": claude_code}


def _setup_report(found):
    report = Report("Set up an AI program to ask the kit's reports")
    report.facts += [Fact("Python", found["command"]), Fact("Kit", found["env"]["PYTHONPATH"])]
    report.lines.append(f"The program starts the server itself, as {found['name']}, and asks only reports that read"
                        + (", including those that read public pages." if found["online"] else "."))
    report.section("Programs that keep a list of servers (Claude Desktop, LM Studio, Gemini CLI and others)",
                   Bullets(["Add this to the program's own server list, beside any servers already there."]),
                   Code(found["serversJson"].splitlines(), "json"))
    report.section("Claude Code", Bullets(["Run this once in a terminal."]), Code([found["claudeCode"]], "text"))
    report.section("Limits", Bullets([
        "These lines hold this computer's own paths: they are shown in full only with --no-redact.",
        "Not yet tried in each program; each program's own documentation says where its server list lives."]))
    return report


# ---- Command line ----

def _parser():
    p = argparse.ArgumentParser(prog="mcp", description=__doc__.split("\n\n")[0],
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="report", required=True)
    s = sub.add_parser("serve", help="answers an AI program on standard input and output; the program starts it itself")
    s.add_argument("--online", action="store_true", help="also offer the reports that read public pages")
    u = sub.add_parser("setup", help="what to paste into an AI program's settings so it can start the server")
    u.add_argument("--name", default=NAME, help="the name the program lists the server by (default: %(default)s)")
    u.add_argument("--online", action="store_true", help="have the server offer the reports that read public pages too")
    u.add_argument("--json", action="store_true", help="print JSON instead of Markdown")
    u.add_argument("--no-redact", action="store_true", help="show the home folder instead of ~")
    t = sub.add_parser("tools", help="the server's three tools as a program hands them to a model, with the games list's "
                                     "repositories")
    t.add_argument("--online", action="store_true", help="as the server would offer them with --online")
    c = sub.add_parser("call", help="one call of one of the server's tools, as a model asked it, without starting the server")
    c.add_argument("--tool", required=True, choices=TOOLS, help="the tool the model asked for")
    c.add_argument("--arguments", default="{}", help="the model's arguments, as one JSON object (default: {})")
    c.add_argument("--online", action="store_true", help="also allow the reports that read public pages")
    for parser in (t, c):
        parser.add_argument("--json", action="store_true", help="print JSON instead of Markdown")
    return p


def call_tool(server, tool, arguments):
    """One tool call, as the server would answer it: (its text, whether it is an error). A malformed call is an error in words."""
    if tool not in TOOLS:
        return f"there is no tool {tool!r}", True
    if not isinstance(arguments, dict):
        return "arguments must be one JSON object", True
    result = server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                            "params": {"name": tool, "arguments": arguments}})
    if "error" in result:
        return result["error"]["message"], True
    return "\n".join(c.get("text", "") for c in result["result"]["content"]), bool(result["result"]["isError"])


def _call(args, out):
    """`mcp call`: the program that started it (D'thorga Companion) hands the model's call over whole and reads the answer."""
    if len(args.arguments) > MAX_ARGUMENTS:
        text, failed = f"the arguments are longer than {MAX_ARGUMENTS} characters", True
    else:
        try:
            arguments = json.loads(args.arguments)
        except ValueError:
            text, failed = "the arguments are not JSON", True
        else:
            text, failed = call_tool(Server(online=args.online), args.tool, arguments)
    report = Report(f"{args.tool}: " + ("refused or failed" if failed else "answered"))
    report.lines.extend(text.splitlines() or [""])
    data = {"text": text, "isError": failed}
    redact = home_redactor()
    out.write((envelope_text("mcp", report, redact, data) if args.json else render_markdown(report, redact)) + "\n")
    return EXIT_OK


def main(argv=None, out=None, instream=None, outstream=None):
    try:
        args = _parser().parse_args(list(sys.argv[1:] if argv is None else argv))
    except SystemExit as stop:
        return EXIT_USAGE if stop.code else EXIT_OK
    if args.report == "serve":
        serve(instream or sys.stdin.buffer, outstream or sys.stdout.buffer, Server(online=args.online))
        return EXIT_OK
    out = out or sys.stdout
    if args.report == "call":
        return _call(args, out)
    if args.report == "tools":
        tools = Server(online=args.online).tools()
        report = Report(f"The server's tools: {len(tools)}")
        report.section("Tools", Bullets([f"{tool['name']}: {tool['description']}" for tool in tools]))
        out.write((envelope_text("mcp", report, home_redactor(), {"tools": tools}) if args.json
                   else render_markdown(report, home_redactor())) + "\n")
        return EXIT_OK
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", args.name):
        out.write("A server's name is letters, digits, - and _ only.\n")
        return EXIT_USAGE
    redact = keep if args.no_redact else home_redactor()
    found = setup(args.name, args.online)
    report = _setup_report(found)
    out.write((envelope_text("mcp", report, redact, found) if args.json else render_markdown(report, redact)) + "\n")
    return EXIT_OK


MANIFEST = {"game": None, "parser": _parser, "effect": READS,
            "reports": {"serve": {"effect": READS, "when": None,
                                  "note": "started by an AI program, never by a person's press; runs only reports that read "
                                          "(and read public pages with --online)"},
                        "setup": {"question": "How do I let an AI program ask the kit's reports?"},
                        "tools": {"note": "for D'thorga Companion, which hands them to the model it asks"},
                        "call": {"note": "runs only reports that read, as serve does; the answer is redacted (1.110.0)"}}}


if __name__ == "__main__":
    sys.exit(main())
