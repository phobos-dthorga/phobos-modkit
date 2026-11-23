# Project direction (7 Nov 2026)

**Answer first.** Phobos ModKit is one home for out-of-game modding tools that are not specific to one
project: reading logs, saves, mod data, assemblies and Workshop pages, and the release chores every mod
repository repeats. It exists so that agent sessions read short, deterministic summaries instead of large
files, and so the owner's game repositories stop carrying drifting copies of the same scripts.

This page holds the decisions and what was set aside. How the kit is built (its layers, modules, languages and frameworks) is
in [architecture](architecture.md); what other repositories may import is in [library API](library-api.md); the rules are in
`AGENTS.md`; what each version delivered is in `CHANGELOG.md` (docs rewrite, step 4, 23 Nov 2026).

**Who decided what.** Owner (7 Nov 2026): build deterministic tools to save LLM work; put truly generic
code in its own repository; this name; public under MIT. Agent choices, open to revision: the three layers,
game adapters living here, the tool list and order, and the language of each tool.

The first consumer was phobos-rimworld; its
[analysis tooling record](https://github.com/phobos-dthorga/phobos-rimworld/blob/main/docs/development/analysis-tooling.md)
gives the first tools' designs.

## Why game adapters live here

The kit has three layers: core (no game in it), game adapters (one game's public file formats) and project policy (what one
repository's mods require, kept in that repository); [architecture](architecture.md) draws them. Adapters live here and not in
the game repositories (agent choice): the format knowledge is the part most worth sharing, and keeping it beside the core keeps
the core honest about what it must not know.

## Out of scope

- **Runtime mod libraries**, which run inside a game: D'thorga Framework (RimWorld), PhobosLib (Project
  Zomboid), FS25_PhobosLib, Phobos Framework (Ostranauts). They stay in their own repositories.
- **In-game profiling**, which is [Phobos Scope](https://github.com/phobos-dthorga/phobos-scope)'s.
- **Steam uploads by anyone but the owner.** Until 8 November 2026 the owner-run upload scripts stayed in the
  repository that publishes; that day the owner asked for phobos-ostranauts' publishing tools, uploader included,
  to move here, made generic. The uploader runs only in the owner's console or on the owner's own press in D'thorga
  Companion; agents, tests and CI never upload.

## Shared frameworks: what was agreed and what waits

Agreed with the owner on 7 November 2026, after two tools had shown what repeats (agent proposal, owner's go-ahead): the report
model, the derived-data cache and the SQLite substrate. All three are built; [architecture](architecture.md) says what each gives.

- **A game adapter contract waits for a second game whose logs or saves are read.** It would give generic commands (`log`,
  `save`) with a game option, each game registering its adapter, instead of commands named by game. Five games have adapters now
  (RimWorld; Project Zomboid's mod list; Workshop publishing data for Ostranauts, Kenshi and Workers & Resources), but only
  RimWorld's logs and saves are read, so building the contract would still guess at its shape.

## Not adopted, and why

- **Outside Python frameworks** (click, pandas, rich): they would break the standard-library rule that lets every Phobos
  repository run the kit with nothing installed.
- **clap for Rust**: not worth it for one command.
- **Sharing code with Phobos Scope**: it would need a third repository for no present gain, since Scope's reports are HTML for
  people and the kit's are Markdown for agents.
- **The uploader in PowerShell** (8 Nov 2026, agent choice, when phobos-ostranauts' publishing moved here): Python instead, one
  language, testable with a stand-in for SteamCMD, and it runs anywhere. Candidates are staged in the kit's cache, and each
  repository's own package checks stay with it as a payload hook.
- **Reports in Rust** (7 Nov 2026, agent choice for the save index): the Rust program only builds the index; the reports are
  Python, sharing the other tools' command line and Markdown, and read the index with Python's own SQLite.
