# Phobos ModKit

Out-of-game tools for game modders: read logs, saves, mod data and Steam Workshop pages, and answer the usual
questions in a short summary instead of a long read. One shared home for code that the
[Phobos](https://github.com/phobos-dthorga) game repositories had each been copying.

## Read this first (gotchas)

- **Ten tools are built**: RimWorld log triage, save index, Def index (with Defs as patched, 0.15.0), Workshop research,
  Workshop publishing, release chores, the gate (0.11.0), mod settings (0.12.0), the code index (0.13.0) and Harmony
  patches (0.14.0), startup sessions and the version readiness scan (0.17.0), and the target check (0.18.0). See [log triage](docs/rimworld-log.md),
  [the save index](docs/rimworld-save.md), [the Def index](docs/rimworld-defs.md), [Workshop research](docs/workshop.md),
  [Workshop publishing](docs/workshop-publishing.md), [release chores](docs/release.md), [the gate](docs/gate.md),
  [mod settings](docs/rimworld-settings.md), [the code index](docs/code.md), [Harmony patches](docs/rimworld-patches.md),
  [startup sessions](docs/rimworld-startup.md), [the readiness scan](docs/rimworld-readiness.md) and [the target check](docs/rimworld-targets.md).
- **The Harmony patch reader needs the .NET SDK** (10 or newer) for its first build, into the same folder outside the
  repository as the Rust tools.
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
python -m phobos_modkit rimworld-save mood     where the colony's mood suffers, and who may break
python -m phobos_modkit rimworld-save atlas    the whole world map, for a program to draw
python -m phobos_modkit rimworld-defs who X    which active mods define and patch a Def; also show, list, patches
python -m phobos_modkit rimworld-defs patched X --dump F   a Def with every patch applied, and what changed
python -m phobos_modkit rimworld-workshop report "Mod name"   what players report about a mod lately
python -m phobos_modkit steam-publish notes --check   release notes and Workshop pages current?
python -m phobos_modkit steam-publish status          every mod's Workshop package, blockers and order
python -m phobos_modkit release changelog mods/*/CHANGELOG.md   changelogs in the Phobos form?
python -m phobos_modkit release constants --check     every copy of each version in step?
python -m phobos_modkit rimworld-settings --mod "X*"   the player's settings for matching mods; also snapshot, compare
python -m phobos_modkit rimworld-patches who "Pawn.Kill"   which active mods patch a method; also mod, hotspots
python -m phobos_modkit rimworld-startup                 load-time history and the costliest mods; also compare, mod
python -m phobos_modkit rimworld-readiness               which active mods are ready for a game version
python -m phobos_modkit code --each-in DIR show Type.Member   a C# member's source by name; also find, outline, refs
python -m phobos_modkit code compare OLD.dll NEW.dll   what changed between two builds, member by member
python -m phobos_modkit crash-dump               why a program crashed, from its Windows crash dump
python -m phobos_modkit cleanup --root REPO      what the tools, builds and tests left behind; --apply deletes it
python -m phobos_modkit gate --root ..         this repository's checks before a commit; only what failed
python -m phobos_modkit manifest               every command, its options and what it reads or changes
```

## Tools

Proposed on 7 Nov 2026 in phobos-rimworld's
[analysis tooling record](https://github.com/phobos-dthorga/phobos-rimworld/blob/main/docs/development/analysis-tooling.md),
in order of expected saving.

| # | Tool | What it answers | Language | Status |
| --- | --- | --- | --- | --- |
| 1 | [Log triage](docs/rimworld-log.md) (RimWorld) | What went wrong this run, which mod it came from, what is new since last run | Python | Built: 0.1.1 |
| 2 | [Save index and query](docs/rimworld-save.md) (RimWorld) | Where things are in a large XML save; pawns, hediffs, holders; map grids; pollution on the world map; what changed between two saves; where a colony's mood suffers; the whole world map for a program to draw | Rust engine, Python reports | Built: 0.6.0, with map grids and save comparison; world-map pollution 0.19.0; colony mood 1.5.0, exact with the colony mood file and with advice 1.6.0; atlas 1.7.0 |
| 3 | [Mod and Def index](docs/rimworld-defs.md) (RimWorld) | Which mod defines or patches something, in the player's load order, and which definition the game keeps | Python | Built: 0.4.0 |
| 4 | [Harmony patches](docs/rimworld-patches.md) (RimWorld), the assembly metadata reader | Which active mods patch a method, what a mod patches, where several mods patch one method; read from metadata, never run | C# reader, Python reports | Built: 0.14.0 (patches; constants and API matching not yet) |
| 5 | [Workshop research](docs/workshop.md) | What players report about a mod lately; supported versions; last update | Python | Built: 0.5.0 |
| 6 | [Startup sessions](docs/rimworld-startup.md) (RimWorld) | Load-time history and what changed between launches | Python | Built |
| 7 | [Version readiness scan](docs/rimworld-readiness.md) (RimWorld) | Which mods declare the new game version, and which use risky techniques | Python | Built |
| 8 | [Release chores](docs/release.md) | Changelog checks, constants kept in step, a history screen before going public; doc links and layout rules to come | Python | Built: 0.10.0 |
| 12 | [Code index](docs/code.md) | Where a C# type or member is, what a type holds, its source by name, and every line that uses a name, across decompiled and own source trees | Python | Built: 0.13.0 |
| 11 | [Mod settings](docs/rimworld-settings.md) (RimWorld) | The settings the player runs with: which mod each file belongs to, values beside their defaults, files left by removed mods, what changed since a snapshot | Python | Built: 0.12.0 |
| 10 | [The gate](docs/gate.md) | Every build, test and check before a commit, from the repository's own list; only what failed, with the errors and failed tests | Python | Built: 0.11.0 |
| 13 | [Cleanup](docs/cleanup.md) | What the tools, builds and tests left behind, how big it is and why it may go; deleted only on request | Python | Built: 1.8.0 |
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
| [docs/rimworld-patches.md](docs/rimworld-patches.md) | Harmony patches across every active mod: how they are found, what the notes mean |
| [docs/code.md](docs/code.md) | The code index: find, outline, show and refs over C# trees, what the scanner reads, and compare for two builds |
| [docs/rimworld-settings.md](docs/rimworld-settings.md) | The player's mod settings: matching files to mods, defaults, snapshots |
| [docs/rimworld-startup.md](docs/rimworld-startup.md) | Start-up times from Loading Progress's sessions: launches, costliest mods, comparisons |
| [docs/rimworld-readiness.md](docs/rimworld-readiness.md) | Which active mods declare a game version, and how closely each depends on the game |
| [docs/manifest.md](docs/manifest.md) | The JSON envelope every command prints, and the manifest of commands, options and effects |
| [docs/crash-dump.md](docs/crash-dump.md) | Windows crash dumps: the exception, a call loop that ran away, and what a small dump cannot say |
| [docs/cleanup.md](docs/cleanup.md) | Cleanup: the kit's cache, its development build and a repository's own leftovers, previewed before anything is deleted |
| [docs/gate.md](docs/gate.md) | The gate: a repository's checks from config/gate.json, and what each output parser keeps |
| `python/phobos_modkit/` | Standard-library Python package: `report.py` (every tool's reports), `cache.py` (derived data), `query.py` (report filters), `steam/` (Workshop research; `publish/` for publishing), `release/` (changelogs, constants, history screen), `gate/` (the check runner and its output parsers), `code/` (the C# declaration scanner and index), `logs/` (game-free triage), `games/rimworld/` (the adapter, with the save schema), `games/ostranauts/` (publishing only) |
| `crates/xml-index/` | Rust: streams any large XML file into SQLite, driven by a schema file; `cargo test` |
| `dotnet/` | C# tools: `PhobosModKit.Assemblies`, the assembly metadata reader (System.Reflection.Metadata; builds outside the repository) |
| `fixtures/`, `tests/` | Hand-written test data and the tests: `python -m unittest discover -s tests` |

## Licence

MIT, for Phobos-authored work in this repository; see [LICENSE](LICENSE). Games and other authors' mods keep
their own terms, and this project is not affiliated with or endorsed by any game's developer or publisher.
