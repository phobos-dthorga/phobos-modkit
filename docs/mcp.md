# mcp: the kit's reports for AI programs

**Status (23 Nov 2026):** built in 1.109.0, the first part (A1) of D'thorga Companion's AI design (`docs/ai.md` there). Checked
by its tests and by one real run over standard input and output; **not yet tried from any AI program.**

`mcp serve` lets an AI program (Claude Desktop, Claude Code, LM Studio, Gemini CLI and others) ask the kit's reports in plain
words, through the Model Context Protocol. The program starts the server itself; `mcp setup` gives the lines to paste into the
program's settings.

## Read this first (gotchas)

- **Only reports that read are ever run.** The server offers a report only when its manifest effect is `reads` (and
  `reads-online` when started with `--online`), checked at every call. Never `writes`, `runs`, `owner-press` or `owner-only`, and
  never itself.
- **A program never names a path.** A repository is chosen by its folder name from the games list (D'thorga Companion's
  `games.json`); `--root`, `--json` and `--no-redact` are the server's own. A text value with a slash, a drive, `~`, a leading
  `.` or `..` is refused, so a report uses its own default instead. **So a value that really holds a slash is refused too**, such
  as a SQL query that divides.
- **Every answer is redacted**: the home folder reads `~`, in the answer and in any error.
- **Three tools, not one for each report.** The manifest holds about 200 reports, 118 that read: one tool each would fill a
  model's context. `find_reports`, `describe_report`, `ask_report`.
- **`mcp setup` shows this computer's own paths only with `--no-redact`**, since lines with `~` in them would not start anything.
  Its answer is for the person to paste, never for a model.
- **Both eras of the protocol.** Revision 2026-07-28 (the version in each request's `_meta`, `server/discover`, `resultType` on
  every result, error −32022 for a version it does not know) and the older `initialize` handshake (2024-11-05 to 2025-11-25),
  which the specification lets one server serve beside it.
- **A report is stopped after 300 seconds** and its answer cut at 60,000 characters, saying so. A helper a stopped report started
  may outlive it.

## Use

```text
python -m phobos_modkit mcp setup --no-redact     the lines to paste into an AI program's settings
python -m phobos_modkit mcp serve                 what the program starts; it waits for messages on standard input
```

The lines `setup` gives, for a program that keeps a list of servers:

```json
{"mcpServers": {"dthorga-reports": {
  "command": "<this Python>", "args": ["-m", "phobos_modkit", "mcp", "serve"],
  "env": {"PYTHONPATH": "<the folder holding phobos_modkit>"}}}}
```

and for Claude Code, one command: `claude mcp add-json --scope user dthorga-reports '<the same server, with "type": "stdio">'`.

**For a program that asks a model itself** (1.110.0; D'thorga Companion's help on pages, `docs/ai.md` there, slice 3b), the same
tools behind the same checks, one process for each call and no server to start:

```text
python -m phobos_modkit mcp tools --json                                  data.tools: the three, as handed to a model
python -m phobos_modkit mcp call --tool ask_report --arguments '{...}' --json   data.text and data.isError
```

`call` takes the model's arguments as one JSON object of at most 8,000 characters, and answers exactly as `serve` would: a
refusal is `isError` with the reason in words, never a failed command.

## The tools

| Tool | Takes | Gives |
| --- | --- | --- |
| `find_reports` | `words` (each must appear), `game` | Up to 25 reports with the question each answers, those with a question first, and the repositories on the games list |
| `describe_report` | `command`, `report` | Its question, what it does, its effect, whether it takes a repository, and every option a caller may set, with kind, choices and default |
| `ask_report` | `command`, `report`, `repository`, `arguments`, `form` | The report's Markdown summary, or with `form: "json"` its whole envelope. A refusal or a failure is a result marked as an error, in words the program can act on |

`arguments` names options as `describe_report` lists them, with or without the dashes (`{"top": 10}`). A switch takes `true` or
`false`, an option that repeats takes a list, a positional value may not start with `-`. Without a repository, a report runs in
an empty temporary folder.

## How it is built

- `python/phobos_modkit/mcp.py`: `catalogue` (what is offered, from the manifest), `command_line` (a call's arguments, checked),
  `run_report` (each report its own process, its input closed so it never reads the server's messages), `Server` (one message at
  a time) and `serve` (one JSON-RPC message a line; standard output carries only messages, written as bytes so Windows adds no
  carriage return).
- `python/phobos_modkit/games_list.py`: the games list, moved out of `safe_copies_daily` (which keeps its names) so both read it
  one way.
- `tests/test_mcp.py`: stand-ins for the runner and the games list; no real report runs in a test.

**Not verified:** which revision each AI program speaks today, and the exact place each keeps its server list.

## Reports and options

<!-- generated: options mcp -->
Generated from the command's own parser by `python -m phobos_modkit command-docs --write`: change a help text in the parser, not here.

| Report | What it does | Effect |
| --- | --- | --- |
| `serve` | Answers an AI program on standard input and output; the program starts it itself. Started by an AI program, never by a person's press; runs only reports that read (and read public pages with `--online`). | reads only |
| `setup` | What to paste into an AI program's settings so it can start the server. | reads only |
| `tools` | The server's three tools as a program hands them to a model, with the games list's repositories. For D'thorga Companion, which hands them to the model it asks. | reads only |
| `call` | One call of one of the server's tools, as a model asked it, without starting the server. Runs only reports that read, as serve does; the answer is redacted (1.110.0). | reads only |

| Option | Reports | What it does | Default |
| --- | --- | --- | --- |
| `--online` | `serve` | also offer the reports that read public pages |  |
| `--name VALUE` | `setup` | the name the program lists the server by (default: dthorga-reports) | `dthorga-reports` |
| `--online` | `setup` | have the server offer the reports that read public pages too |  |
| `--json` | `setup`, `tools`, `call` | print JSON instead of Markdown |  |
| `--no-redact` | `setup` | show the home folder instead of ~ |  |
| `--online` | `tools` | as the server would offer them with `--online` |  |
| `--tool VALUE` | `call` | the tool the model asked for. Required. One of `ask_report`, `describe_report`, `find_reports`. |  |
| `--arguments VALUE` | `call` | the model's arguments, as one JSON object (default: {}) | `{}` |
| `--online` | `call` | also allow the reports that read public pages |  |

[Common options](common-options.md) explains `--json` and `--no-redact`, which many commands share.
<!-- end generated -->
