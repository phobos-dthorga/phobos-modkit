# Phobos ModKit contributor instructions

Standing rules for work in this repository, stated once in their current form. What each version delivered
lives in `CHANGELOG.md`; designs live in `docs/`. Conventions follow phobos-rimworld and Phobos Scope,
adapted to a tooling repository. The repository was created on 7 November 2026 at the owner's request.

## Rules shared by every repository

**This repository holds them, in [`rules/`](rules/README.md)** (owner, 19 November 2026: "a central point from which global rules
for all mods can be read and modified"). **Read [`rules/every-session.md`](rules/every-session.md) at the start of every
session**; `CLAUDE.md` imports it. The rules below are this repository's own, and add to them.

- **A rule that holds across games goes in `rules/`, never in one repository's `AGENTS.md`**: `rules/README.md` says which file,
  how a rule is changed (the owner decides; a new or changed rule raises the middle version number) and how a repository takes
  the rules up. Its "Moved here on 23 Nov 2026" table lists the twelve rules that had been repeated in every repository.
- **A rule moves here only on the owner's word**, in one wording they have chosen, and each repository drops its own copy when
  its pin next moves, so a rule is never stated twice.
- `python -m phobos_modkit rules list` prints the files; `rules check --root REPO` says whether a repository reads them, for
  its gate. `tests/test_rules.py` keeps the folder and its index in step.

## Working with the owner

- Author: Phobos A. D'thorga (phobosgekko). The shared rules cover how to work with the owner (`rules/every-session.md`).
- Tools read what games wrote; they never show that a mod works in play.

## What belongs here: three layers

| Layer | What it is | Where |
| --- | --- | --- |
| Core | Code with no game in it: paths, Steam, log grouping, XML indexing, assembly metadata, release tooling | here |
| Game adapter | Public file-format knowledge for one game: log line formats, save schemas, mod metadata files | here, under `games/<game>/` |
| Project policy | What one project's mods require: which data matters, its own checks, its disclaimer text | the game repository |

- **Core never names a game.** A game's knowledge enters through an adapter or a data file.
- **An adapter holds format facts, in our own words.** Facts learned by decompiling a game are summarised,
  never copied; the decompile itself stays on the researcher's machine.
- **Runtime mod libraries are out of scope.** Code that runs inside a game stays in that game's repository.
- **In-game instrumentation is Phobos Scope's.** Recorders that run inside a game and time the sections a mod marks belong to
  [Phobos Scope](https://github.com/phobos-dthorga/phobos-scope), not here. **Sampling a game from outside belongs here**
  (owner's go-ahead, 17 November 2026, for rimworld-perf): Microsoft's diagnostics tools attach through the runtime's own pipe,
  nothing of ours runs in the game, and the kit reads what they write, as it reads a log.

## Safety rules for every tool

- **Read-only towards games.** Never write to an install, save or Workshop folder. Save tools copy the save to
  a temporary folder first. The install helper is the one writer: only on request, never while the game
  runs, and it backs up what it replaces. **One more writer, for textures only** (owner, 18 November 2026, for
  D'thorga Companion): `rimworld-textures encode` writes `.dds` files beside the pictures of the active mods it is
  named, Workshop ones included, with RimSort's own todds preset, only on request and never while the game runs; it
  never deletes a file. **One more, for Windows' crash dump setting** (owner's go-ahead, 18 November 2026): `windows-dumps
  --apply` and `--off` write only the LocalDumps key of the program named, only on request and from an administrator
  window; **agents never run them**, the owner does. **Reading a running game's memory is reading** (owner's yes, 20 November 2026,
  for D'thorga Companion's look inside): the heap reader takes a Windows snapshot, which pauses the game for about half a second,
  and never writes to it; **ask before every snapshot of the owner's game**, as for every tool that attaches to one. **One more, for
  safe copies** (owner's go-ahead, 21 November 2026, with the art backups plan): `safe-copies run`, `restore` and `mark` write only into
  the folders the owner chose and marked, and a restore folder the owner names, and push only to the private repository the owner
  chose; they never write to a game's folders, and never delete anything but earlier copies beyond the number a set keeps
  (`keepEarlier`, the owner's word of 22 November 2026, for the saves), inside a destination's own `_safe-copies/earlier`, and, on
  request with `--apply`, `safe-copies let-go`'s copies of files the list no longer takes, each named (1.69.0). **Anything made from a game's files goes only to a folder marked
  private and local**, never to a repository. `safe-copies run-all` is `run` for every list on the games list. **`safe-copies
  schedule --at` or `--off` sets or removes one Windows scheduled task of the owner's own**, "D'thorga Safe Copies" (the owner's word
  of 22 November 2026, for the daily run), and touches no other task; without them it only reads. Release and publishing tools write only inside the repository they are run on, and only
  when asked (`--write`, `--apply`, an upload's records).
- **Never execute other authors' code.** Assemblies are read through their metadata
  (`System.Reflection.Metadata`), never loaded. Never run another mod's scripts. **One exception** (owner's yes, 20 November
  2026): the heap reader loads a game's own memory-reading library (`mscordaccore.dll`), the part of the game's .NET runtime that
  knows its memory layout, and only the one beside the running game's own `coreclr.dll` in the install its adapter names. Never a
  mod's file (`docs/heap-reader.md`).
- **Steam, read-only and slow, with one owner-run exception.** Tools read public, keyless pages and APIs only,
  with pacing and a cache, and never log in, handle credentials, subscribe, announce or change an item's
  visibility. The exception is the Workshop uploader (`steam-publish upload` and `update`; owner, 8 November
  2026, moving phobos-ostranauts' uploader here): **only the owner runs it**, in their own console **or by their own press in
  D'thorga Companion** (owner, 23 November 2026, for the Publish page; the manifest's `owner-press`). It sends through the
  Steam client already running and signed in, or through SteamCMD, which takes the login in its own prompt and console, so
  the tool never sees, stores or passes a password. **Agents, tests and CI never run a real upload**: tests pass stand-ins
  for SteamCMD and for the Steam library, and an agent may run `--what-if` at most.
- **Open logs for shared reading.** A game may hold its log open.
- **Paths** come from one resolver: argument, then environment variable, then a local settings file, then
  the platform default. Never hard-code a personal path.

## Output

- Deterministic: the same input gives the same output, in a stable order.
- Two forms: JSON for programs and a short Markdown summary for people and agent sessions. The summary is
  the point of the tool: counts, top items and differences, never raw dumps.
- State every limit in the output itself (for example "patches not applied").
- **Every report goes through `phobos_modkit.report`** (owner agreed, 7 November 2026): build a `Report` of
  paragraphs, bullets, tables and code blocks and render it with `render_markdown` or `render_json`, which apply
  redaction everywhere. Never hand-write Markdown in a tool. A tool may add its own richer JSON data export, as
  log triage's is.
- **Every command's `--json` prints `report.envelope_text`**: one shape, with the report under `report` and anything of the
  tool's own under `data`. Never `json.dumps` a report in a tool.
- **Every command declares a `MANIFEST`** beside its parser (its game, the parser and what it reads or changes), and is
  listed in `commands.py`; `tests/test_manifest.py` holds it to that (`docs/manifest.md`).
- **Every command's doc ends with a generated table of its reports and options**, and the README with an index of every
  command: `python -m phobos_modkit command-docs --write` writes them from the manifest, `config/command-docs.json` names each
  command's doc, and the gate fails when one is out of date (`docs/command-docs.md`). Change a help text in the parser, never
  in the block.
- **Report filters and capped queries go through `phobos_modkit.query`**: `like` for users' wildcards (`*` and `?`,
  with `%` and `_` literal), `Filters` for WHERE clauses with parameters, `count` and `rows` for tables cut at
  `--top`. Never build SQL from a user's text by hand.

## Derived data

- **Derived data is SQLite with a `meta` table of provenance** (owner agreed, 7 November 2026): indexes, caches
  and fetched pages live in the kit's cache folder (`phobos_modkit.cache.folder`), outside any cloud-synced
  repository, and record what they were built from (`source`, `source_size`, `source_mtime_ns`, `schema_sha`,
  `kit_version` and the like). Use `phobos_modkit.cache` to stamp, check and rebuild them, and its
  `frozen_copy` to read a file another program may be writing. One SQLite substrate lets a question that
  crosses tools be a single query, with ATTACH.
- Rust tools build outside the repository too (`phobos_modkit.native.build_dir`). **When developing, set
  `CARGO_TARGET_DIR` to that folder** (`%LOCALAPPDATA%\phobos-modkit\target` on Windows,
  `~/.cache/phobos-modkit/target` elsewhere) before any `cargo` command: a plain `cargo build` writes hundreds of
  megabytes into `target/` here, and a cloud-synced clone uploads them (526 MB did, 7 November 2026).

## Languages

- **Python** (`python/phobos_modkit/`): standard library only, Python 3.10 or newer, `unittest`. The default.
- **Rust** (`crates/`): for large inputs where speed changes how the tool is used. Pinned toolchain, edition
  2024, as Phobos Scope does.
- **C#** (`dotnet/`): for .NET assembly metadata and the heap reader. .NET 10, no assembly loading, no package references, with
  **one exception** (owner's yes, 20 November 2026): the heap reader's Microsoft ClrMD, pinned in its project and listed in
  `THIRD_PARTY_NOTICES.md`. `dotnet/Directory.Build.props`
  sends `obj/` and `bin/` to the build folder outside the repository; a C# fixture under `fixtures/dotnet/` imports it.
- A third-party dependency needs a stated reason and an entry in `THIRD_PARTY_NOTICES.md`.

## Tests and fixtures

- Fixtures are written by hand from format knowledge. Never commit a real save, log, assembly or another
  author's file, or an excerpt of one. Say in `fixtures/README.md` what each fixture follows and how faithful it is.
- Network and clock are passed in, so tests never reach Steam.
- **This repository's gate is `cd python && python -m phobos_modkit gate --root ..`** (the shared rule: chain the commit on
  it). It runs every check from `config/gate.json` and prints only what failed. A commit chained after a step that may have failed
  is how the v0.2.2 tag came to carry a broken test (7 November 2026). The checks, which CI repeats on Windows and Linux:

  ```text
  cargo fmt --all -- --check
  cargo clippy --locked --all-targets -- -D warnings
  cargo test --locked
  cargo build --release --locked
  PHOBOS_REQUIRE_NATIVE=1 python -W error -m unittest discover -s tests
  cd python && python -m phobos_modkit command-docs
  ```

  Run the Python tests on the oldest supported Python too when syntax or the standard library is involved, for
  example `uv run --no-project --python 3.10 python -m unittest discover -s tests`.

## Consumers

- Game repositories pin this repository as a git submodule at `external/phobos-modkit`.
- A fix goes here first; the consumer then moves its pin. Never patch the submodule in place.
- Consumers adopt a tool when they next touch the script it replaces, not in a sweep.
- **A tool's first change in a consumer repository adds a rule to that repository's AGENTS.md**, in the same
  commit: which script to run, for what, before reading the raw material by hand. Without the rule, sessions keep
  reading the raw files and the tool saves nothing. Later features of the tool update that rule.
- An incompatible change raises the major version and says what consumers must change.

## Git, versions and documents

- **Public, MIT** (owner, 7 November 2026). Never change the repository's visibility.
- **The commit guard** (owner's go-ahead, 18 November 2026): this repository's `.githooks/pre-commit` runs `gate --verify-staged`,
  which refuses a commit whose staged files no full passing gate run saw exactly so. **After cloning, run
  `git config core.hooksPath .githooks`.** Never pass `--no-verify`; run the gate and chain the commit on it.
- **A version bump changes three files together**: `python/phobos_modkit/__init__.py`, the workspace version in
  `Cargo.toml`, and `Cargo.lock` through `cargo update --offline --workspace`. A lock file left behind makes every
  `--locked` build refuse to start, as v0.2.1's did; `tests/test_versions.py` checks the three agree. Tag each
  release `vX.Y.Z` and push the tag; never move a pushed tag, release a fixed version instead.
- Name the organisation or author behind a claim, with a link. Never invent a citation.
