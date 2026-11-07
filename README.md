# Phobos ModKit

Out-of-game tools for game modders: read logs, saves, mod data and Steam Workshop pages, and answer the usual
questions in a short summary instead of a long read. One shared home for code that the
[Phobos](https://github.com/phobos-dthorga) game repositories had each been copying.

## Read this first (gotchas)

- **Nothing is built yet.** This repository holds its design documents only (7 Nov 2026). The first tool
  will be log triage for RimWorld.
- **These tools never run inside a game.** They read files the game wrote. Runtime mod libraries (D'thorga
  Framework for RimWorld, PhobosLib for Project Zomboid and FS25, Phobos Framework for Ostranauts) stay in
  their own repositories.
- **Read-only towards the game.** Tools never write to a game's install, save or Workshop folders. Save
  tools work on a copy. The one exception is the install helper, which copies a mod into a game's mod
  folder only when asked, refuses while the game runs, and backs up first.
- **Never uploads to Steam.** Workshop tools read Steam's public, keyless pages and APIs, slowly. They never
  log in, handle credentials, subscribe, upload or change an item's visibility.
- **Nothing from the games is committed.** No game files, saves, logs, assemblies, decompiled code or other
  authors' mod files. Test fixtures are written by hand.

## Planned tools

Proposed on 7 Nov 2026 in phobos-rimworld's
[analysis tooling record](https://github.com/phobos-dthorga/phobos-rimworld/blob/main/docs/development/analysis-tooling.md),
in order of expected saving.

| # | Tool | What it answers | Language |
| --- | --- | --- | --- |
| 1 | Log triage | What went wrong this run, which mod it came from, what is new since last run | Python |
| 2 | Save index and query | Where things are in a large XML save; what changed between two saves | Rust |
| 3 | Mod and Def index (RimWorld) | Which mod defines or patches something, in the player's load order | Python |
| 4 | Assembly metadata reader | Which mods patch a method; what constants a DLL holds; does a consumer still match its provider | C# |
| 5 | Workshop research | What players report about a mod lately; supported versions; last update | Python |
| 6 | Startup sessions (RimWorld) | Load-time history and what changed between launches | Python |
| 7 | Version readiness scan | Which mods declare the new game version, and which use risky techniques | Python |
| 8 | Release tooling | Changelog checks, release notes, constants, doc links, layout rules | Python |

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
| `python/phobos_modkit/` | Standard-library Python package (planned) |
| `crates/` | Rust tools (planned) |
| `dotnet/` | C# tools (planned) |
| `fixtures/`, `tests/` | Hand-written test data and tests (planned) |

## Licence

MIT, for Phobos-authored work in this repository; see [LICENSE](LICENSE). Games and other authors' mods keep
their own terms, and this project is not affiliated with or endorsed by any game's developer or publisher.
