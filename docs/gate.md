# The gate: every check before a commit, and only what failed

Built in 0.11.0 (9 November 2026), at the owner's request for tools that keep agent sessions lean. A session that
checks its work before a commit used to type a long shell loop of builds, tests and checks, then read pages of
their output for the one line that mattered; phobos-rimworld's loop had quietly missed four of its seven test
projects. The gate runs a list the repository keeps, finds repeated steps by glob, and prints a few lines.

## Read this first

- **Commit only on its exit code**: `python -m phobos_modkit gate && git commit ...`. 0 means every step passed; 1
  means one failed; 2 means the list itself is wrong or nothing matched.
- **A passing run prints three lines.** A failing one names each failed step with its errors, failed tests and their
  messages (at most 12 each), and where its full output was kept: the kit's cache folder, `gate-logs/<repository>/`.
  Open that file only when the summary is not enough.
- **A failed stage stops the stages after it** (tests are pointless when the builds failed); `--keep-going` runs
  them anyway. Steps inside a stage all run.
- **A step whose program is missing is skipped, and says so** ("requires"), so a machine without Rust can still run
  the Python checks. The report lists what was skipped and why.
- It runs what it is told to: it never commits, pushes or writes anywhere but the cache.

## Use

```text
python -m phobos_modkit gate                       every step
python -m phobos_modkit gate --list                the steps, expanded, without running them
python -m phobos_modkit gate --only "test *"       only steps whose name matches; --skip leaves them out
python -m phobos_modkit gate --verbose             a row for every step, with its time
python -m phobos_modkit gate --json                the same report as JSON
```

Run it from the kit's `python` folder with `--root` naming the repository (`--root ..` for the kit itself), or through
a consumer's thin script (phobos-rimworld: `python scripts/check-all.py`).

## The step list: config/gate.json

```json
{
  "schemaVersion": 1,
  "stages": [
    {"name": "Build and check", "steps": [
      {"name": "build {stem}", "each": "src/*/*.csproj", "lane": "dotnet", "parser": "msbuild", "requires": "dotnet",
       "run": ["dotnet", "build", "{path}", "--nologo", "-v", "q"]},
      {"name": "python tests", "parser": "unittest", "run": ["{python}", "-m", "unittest", "discover", "-s", "tests"]}
    ]}
  ]
}
```

| Field | Meaning |
| --- | --- |
| `stages` | Run in order. A failed stage skips the rest unless `--keep-going` |
| `name` | The step's name in the report; `--only` and `--skip` match it |
| `run` | The program and its arguments, never through a shell |
| `each` | A glob, or a list of them, relative to the root: the step repeats for every file found, in sorted order |
| `lane` | Steps sharing a lane run one after another; lanes run side by side (`--jobs`, default up to 4). Give builds that share output folders one lane. Default: the step's own name |
| `parser` | `msbuild`, `dotnet-test`, `unittest`, `cargo` or `text` (the default: the exit code, and the output's last lines on failure) |
| `requires` | A program that must be on the PATH, else the step is skipped |
| `cwd`, `env` | A folder relative to the root; extra environment variables |
| `timeout` | Seconds before the step is stopped (default 1800) |

Placeholders work in `name`, `run`, `cwd` and `env`: `{python}` (the interpreter running the gate), `{root}`,
`{cargo_target}` (where the kit's Rust tools build, outside any repository), `{env:NAME}`; and in an `each` step
`{path}` (relative, forward slashes), `{name}`, `{stem}` and `{dir}`. Every step runs with `PYTHONIOENCODING=utf-8`,
`DOTNET_CLI_UI_LANGUAGE=en` and `DOTNET_NOLOGO=1` unless the step sets them, so the parsers see English, UTF-8 output.

## What each parser keeps

| Parser | Keeps | Summary |
| --- | --- | --- |
| `msbuild` | `file:line: CODE message` for each error and warning, once (MSBuild prints each twice), paths relative to the root | "built", "built, 2 warnings", "3 errors" |
| `dotnet-test` | Compile errors as above; each failed test with the first line of its message | "56 passed", "1 of 42 failed", "did not build: 2 errors" |
| `unittest` | Each FAIL and ERROR as `Class.test: last line of the traceback` (Python 3.10 and later) | "236 passed", "2 of 236 failed" |
| `cargo` | Errors and warnings with their `-->` location; failed tests; files `cargo fmt --check` would change | "12 passed", "1 of 3 failed", "2 files not formatted" |
| `text` | The last 15 lines when the step fails | "ok", "failed" |

The formats are the tools' console output as their authors print it (Microsoft's MSBuild and VSTest, the Python
project's unittest, the Rust project's cargo); the tests use outputs written by hand in those shapes. Anything a
parser does not recognise still fails the step by its exit code, with the output's tail.

## Limits

- Lanes share the machine: four lanes of builds would compete for the same processor. Give heavy steps one lane.
- The parsers read console output, which tools may change between versions; a change shows as a failed step whose
  problems are the output's tail rather than tidy lines. The fix is the parser, here.
- Steps never see the terminal, so a program that asks a question will wait until its timeout.
