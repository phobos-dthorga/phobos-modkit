# Phobos ModKit

Out-of-game tools for game modders: read logs, saves, mod data and Steam Workshop pages, and answer the usual
questions in a short summary instead of a long read. One shared home for code that the
[Phobos](https://github.com/phobos-dthorga) game repositories had each been copying.

## Read this first (gotchas)

- **Six tools are built: RimWorld log triage, save index, Def index, Workshop research, Workshop publishing and
  release chores** (0.10.0, 8 Nov 2026). The rest are planned. See [log triage](docs/rimworld-log.md),
  [the save index](docs/rimworld-save.md), [the Def index](docs/rimworld-defs.md),
  [Workshop research](docs/workshop.md), [Workshop publishing](docs/workshop-publishing.md) and
  [release chores](docs/release.md).
- **The save index needs one Rust build:** add `--build-indexer` to its first command, with Rust from
  [rustup](https://rustup.rs). It builds outside the repository, so a cloud-synced clone does not upload hundreds
  of megabytes. Everything else is standard-library Python 3.10 or newer.
- **These tools never run inside a game.** They read files the game wrote. Runtime mod libraries (D'thorga
  Framework for RimWorld, PhobosLib for Project Zomboid and FS25, Phobos Framework for Ostranauts) stay in
  their own repositories.
- **Read-only towards the game.** Tools never write to a game's install, save or Workshop folders. Save
  tools work on a copy. The one exception is the install helper, which copies a mod into a game's mod
  folder only when asked, refuses while the game runs, and backs up first.
- **Only the owner uploads to Steam.** Workshop research and `steam-publish pull` read Steam's public, keyless
  pages and APIs, slowly. The one tool that uploads, `steam-publish upload` (and `update`), is run by the owner in
  their own console: SteamCMD asks for the login in its own prompt, so the tool never sees a password, and new items
  are always created Private. Agents, tests and CI never run a real upload.
- **Nothing from the games is committed.** No game files, saves, logs, assemblies, decompiled code or other
  authors' mod files. Test fixtures are written by hand.

## Run a tool

```text
cd python
python -m phobos_modkit rimworld-save --build-indexer   once: builds the save indexer
python -m phobos_modkit rimworld-log           summarise RimWorld's Player.log against the run before
python -m phobos_modkit rimworld-log --show ID one message in full
python -m phobos_modkit rimworld-save          summarise the newest save; also pawns, things, hediffs, find, sql
python -m phobos_modkit rimworld-defs who X    which active mods define and patch a Def; also show, list, patches
python -m phobos_modkit rimworld-workshop report "Mod name"   what players report about a mod lately
python -m phobos_modkit steam-publish notes --check   release notes and Workshop pages current?
python -m phobos_modkit steam-publish status          every mod's Workshop package, blockers and order
python -m phobos_modkit release changelog mods/*/CHANGELOG.md   changelogs in the Phobos form?
python -m phobos_modkit release constants --check     every copy of each version in step?
python -m phobos_modkit rimworld-settings --mod "X*"   the player's settings for matching mods; also snapshot, compare
python -m phobos_modkit gate --root ..         this repository's checks before a commit; only what failed
```

## Tools

Proposed on 7 Nov 2026 in phobos-rimworld's
[analysis tooling record](https://github.com/phobos-dthorga/phobos-rimworld/blob/main/docs/development/analysis-tooling.md),
in order of expected saving.

| # | Tool | What it answers | Language | Status |
| --- | --- | --- | --- | --- |
| 1 | [Log triage](docs/rimworld-log.md) (RimWorld) | What went wrong this run, which mod it came from, what is new since last run | Python | Built: 0.1.1 |
| 2 | [Save index and query](docs/rimworld-save.md) (RimWorld) | Where things are in a large XML save; pawns, hediffs, holders; map grids; what changed between two saves | Rust engine, Python reports | Built: 0.6.0, with map grids and save comparison |
| 3 | [Mod and Def index](docs/rimworld-defs.md) (RimWorld) | Which mod defines or patches something, in the player's load order, and which definition the game keeps | Python | Built: 0.4.0 |
| 4 | Assembly metadata reader | Which mods patch a method; what constants a DLL holds; does a consumer still match its provider | C# | Planned |
| 5 | [Workshop research](docs/workshop.md) | What players report about a mod lately; supported versions; last update | Python | Built: 0.5.0 |
| 6 | Startup sessions (RimWorld) | Load-time history and what changed between launches | Python | Planned |
| 7 | Version readiness scan | Which mods declare the new game version, and which use risky techniques | Python | Planned |
| 8 | [Release chores](docs/release.md) | Changelog checks, constants kept in step, a history screen before going public; doc links and layout rules to come | Python | Built: 0.10.0 |
| 11 | [Mod settings](docs/rimworld-settings.md) (RimWorld) | The settings the player runs with: which mod each file belongs to, values beside their defaults, files left by removed mods, what changed since a snapshot | Python | Built: 0.12.0 |
| 10 | [The gate](docs/gate.md) | Every build, test and check before a commit, from the repository's own list; only what failed, with the errors and failed tests | Python | Built: 0.11.0 |
| 9 | [Workshop publishing](docs/workshop-publishing.md) | Release notes from changelogs, offline staging, the owner-run uploader, pulling Steam's state back | Python | Built: 0.10.0, from phobos-ostranauts |

## How a repository uses it

```text
git submodule add https://github.com/phobos-dthorga/phobos-modkit.git external/phobos-modkit
```

Python scripts add `external/phobos-modkit/python` to their import path. The Rust and C# tools build from
the submodule, and their programs stay out of Git. Moving to a newer version is an ordinary commit that
moves the pin. See [project direction](docs/project-direction.md) for the rules.

## Project map

| Location | Holds |
| --- | --- |
| [docs/project-direction.md](docs/project-direction.md) | What belongs here, the three layers, languages, consumers |
| [docs/migration.md](docs/migration.md) | Scripts copied across the Phobos repositories and where each one moves |
| [docs/rimworld-log.md](docs/rimworld-log.md) | How to run RimWorld log triage and read its summary |
| [docs/rimworld-save.md](docs/rimworld-save.md) | How to index a RimWorld save and ask it questions |
| [docs/rimworld-defs.md](docs/rimworld-defs.md) | Which mods define and patch each Def, and the game's load rules it follows |
| [docs/workshop.md](docs/workshop.md) | Workshop research: details, comments, pacing and what Steam hides |
| [docs/workshop-publishing.md](docs/workshop-publishing.md) | Publishing to the Workshop: notes, staging, the owner-run uploader, the catalogue |
| [docs/release.md](docs/release.md) | Changelog checks, constants kept in step, the history screen |
| [docs/rimworld-settings.md](docs/rimworld-settings.md) | The player's mod settings: matching files to mods, defaults, snapshots |
| [docs/gate.md](docs/gate.md) | The gate: a repository's checks from config/gate.json, and what each output parser keeps |
| `python/phobos_modkit/` | Standard-library Python package: `report.py` (every tool's reports), `cache.py` (derived data), `query.py` (report filters), `steam/` (Workshop research; `publish/` for publishing), `release/` (changelogs, constants, history screen), `gate/` (the check runner and its output parsers), `logs/` (game-free triage), `games/rimworld/` (the adapter, with the save schema), `games/ostranauts/` (publishing only) |
| `crates/xml-index/` | Rust: streams any large XML file into SQLite, driven by a schema file; `cargo test` |
| `dotnet/` | C# tools (planned) |
| `fixtures/`, `tests/` | Hand-written test data and the tests: `python -m unittest discover -s tests` |

## Licence

MIT, for Phobos-authored work in this repository; see [LICENSE](LICENSE). Games and other authors' mods keep
their own terms, and this project is not affiliated with or endorsed by any game's developer or publisher.
