# Phobos ModKit contributor instructions

Standing rules for work in this repository, stated once in their current form. What each version delivered
lives in `CHANGELOG.md`; designs live in `docs/`. Conventions follow phobos-rimworld and Phobos Scope,
adapted to a tooling repository. The repository was created on 7 November 2026 at the owner's request.

## Working with the owner

- Author: Phobos A. D'thorga (phobosgekko).
- Practical working slices over speculative frameworks. Explain what works, what was checked and what
  remains uncertain. Never invent hour estimates.
- A unit test or a run on a synthetic fixture is never a game test. Tools read what games wrote; they do
  not show that a mod works in play.
- Do not control the owner's mouse or keyboard. Never edit, replace or delete the owner's saves; read-only
  copies for diagnosis are fine and are deleted afterwards.
- Owner choices, agent defaults and agent choices are labelled as such in design records.

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
- **Profiling is Phobos Scope's.** Measurement inside a running game belongs to
  [Phobos Scope](https://github.com/phobos-dthorga/phobos-scope), not here.

## Safety rules for every tool

- **Read-only towards games.** Never write to an install, save or Workshop folder. Save tools copy the save to
  a temporary folder first. The install helper is the one writer: only on request, never while the game
  runs, and it backs up what it replaces.
- **Never execute other authors' code.** Assemblies are read through their metadata
  (`System.Reflection.Metadata`), never loaded. Never run another mod's scripts.
- **Steam, read-only and slow.** Public, keyless pages and APIs only, with pacing and a cache. Never log in,
  handle credentials, subscribe, upload, announce or change an item's visibility.
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
- **C#** (`dotnet/`): for .NET assembly metadata. .NET 10, no assembly loading.
- A third-party dependency needs a stated reason and an entry in `THIRD_PARTY_NOTICES.md`.

## Tests and fixtures

- Fixtures are written by hand from format knowledge. Never commit a real save, log, assembly or another
  author's file, or an excerpt of one. Say in `fixtures/README.md` what each fixture follows and how faithful it is.
- Network and clock are passed in, so tests never reach Steam.
- **Before every commit, run every check, and commit only when all pass**, gated on their exit codes in the same
  command (`&&` or an `if`), never on reading the output. A commit chained after a step that may have failed is how
  the v0.2.2 tag came to carry a broken test (7 November 2026). The checks, which CI repeats on Windows and Linux:

  ```text
  cargo fmt --all -- --check
  cargo clippy --locked --all-targets -- -D warnings
  cargo test --locked
  cargo build --release --locked
  PHOBOS_REQUIRE_NATIVE=1 python -W error -m unittest discover -s tests
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
- Commit and push directly to `main`; no pull requests unless the owner asks. Never force-push or rewrite
  history. Several agent sessions may share a tree: commit explicit paths and leave others' work alone.
- Versions: a fix raises the last number, new functionality the middle, an incompatible change the first.
  Every change updates `CHANGELOG.md` in the same commit.
- **A version bump changes three files together**: `python/phobos_modkit/__init__.py`, the workspace version in
  `Cargo.toml`, and `Cargo.lock` through `cargo update --offline --workspace`. A lock file left behind makes every
  `--locked` build refuse to start, as v0.2.1's did; `tests/test_versions.py` checks the three agree. Tag each
  release `vX.Y.Z` and push the tag; never move a pushed tag, release a fixed version instead.
- Never commit credentials, personal paths, game files, saves, logs, assemblies, decompiled code or other
  authors' mod files.
- Write plainly: answer first, short sentences, **bold** for must-dos, tables for comparisons. Diagrams are
  Mermaid in the Markdown. Never use Figma.
- Name the organisation or author behind a claim, with a link. Never invent a citation.
