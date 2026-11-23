# Phobos ModKit

Out-of-game tools for game modders: read logs, saves, mod data and Steam Workshop pages, and answer the usual questions in a
short summary instead of a long read. One shared home for code that the [Phobos](https://github.com/phobos-dthorga) game
repositories had each been copying. Every command prints Markdown for a person, or one JSON envelope for a program such as
D'thorga Companion.

- **How the kit is built**: layers, modules, the command model, native parts and tests: [architecture](docs/architecture.md).
- **What another repository may import**, and which names are a promise: [library API](docs/library-api.md).
- **The rules every Phobos and D'thorga repository shares** live here too: [rules](rules/README.md).
- **Writing a tool's page**: [one template](docs/writing-a-tool-page.md); the options many commands share are on
  [common options](docs/common-options.md).

## Read this first

- **Run a command from `python/`**: `cd python && python -m phobos_modkit <command>`; `python -m phobos_modkit manifest` lists
  every command with what it reads and changes. Each command's page, in the index below, ends with every report and option it takes.
- **What it needs.** The Python package is standard library only, Python 3.10 or newer. Three parts build on first use, outside
  the repository, so a cloud-synced clone never uploads them:
  - **the save indexer** (Rust, from [rustup](https://rustup.rs)), for `rimworld-save`: add `--build-indexer` to its first command;
  - **the C# readers** (the .NET SDK 10 or newer): the assembly metadata reader behind the Harmony patch reader and the other
    commands that read assemblies, the names reader behind `connections names`, and the heap reader behind `rimworld-perf look`;
  - **`rimworld-perf`'s recorders**, Microsoft's dotnet-trace and dotnet-counters, which its first recording installs with the
    same SDK.

  `python -m phobos_modkit programs status` says which of these this PC has.
- **These tools never run inside a game.** They read files the game wrote. Runtime mod libraries (D'thorga Framework for RimWorld,
  PhobosLib for Project Zomboid and FS25, Phobos Framework for Ostranauts) stay in their own repositories.
- **Read-only towards games.** Tools never write to a game's install, save or Workshop folders; save tools work on a copy. The
  few exceptions (installing a mod, encoding textures, Windows' crash-dump setting, safe copies) write only when asked, and each
  page says what and when. Looking inside a running game pauses it briefly: ask before each snapshot, and save first.
- **Only the owner uploads to Steam.** Research reads Steam's public, keyless pages slowly; the uploader runs only in the owner's
  own console or by their own press in D'thorga Companion, and never sees a password ([publishing](docs/workshop-publishing.md)).
- **Nothing from the games is committed**: no game files, saves, logs, assemblies, decompiled code or other authors' mod files.
  Test fixtures are written by hand.

## How a repository adds it

| Piece | How |
| --- | --- |
| The pin | `git submodule add https://github.com/phobos-dthorga/phobos-modkit.git external/phobos-modkit`; moving to a newer kit is an ordinary commit that moves the pin, and `git submodule update --init` fetches it after cloning |
| Thin callers | One `scripts/<name>.py` per tool, which puts `external/phobos-modkit/python` on the import path and calls the command's `main` with the repository's own root and settings file (phobos-rimworld's `scripts/_modkit.py`) |
| Its gate | `config/gate.json`, run through the kit's [gate](docs/gate.md) |
| The rules | `CLAUDE.md` imports `external/phobos-modkit/rules/every-session.md`, and `AGENTS.md` points to it ([how](rules/README.md)) |

A fix lands in the kit first; the repository then moves its pin. [Architecture](docs/architecture.md) has the rest, and
[library API](docs/library-api.md) the names a repository may import directly.

## Commands

One row per command, generated from the manifest.

<!-- generated: command index -->
Generated from the manifest by `python -m phobos_modkit command-docs --write`. Each doc ends with every report and option its command takes.

| Command | Game | What it is for |
| --- | --- | --- |
| [`art-audit`](docs/art-audit.md) | any | every shipped image with its record and how it was made, and every borrowed picture |
| [`changes`](docs/changes.md) | any | what the changelogs say changed lately, and the code behind any one entry |
| [`claims`](docs/claims.md) | any | who is working on what: agent sessions take and release version numbers, test rows and files |
| [`cleanup`](docs/cleanup.md) | any | what the tools, builds and tests left behind; deletes only with `--apply` |
| [`code`](docs/code.md) | any | find, outline and show C# declarations, and every line using a name |
| [`command-docs`](docs/command-docs.md) | any | each command's doc lists its reports and options, and the README its commands, from the manifest |
| [`connections`](docs/connections.md) | any | how a repository's code fits together: calls, holds, builds on, overrides, patches, uses |
| [`crash-dump`](docs/crash-dump.md) | any | what a Windows crash dump says failed, whether a call loop ran away, and its methods from a full dump |
| [`decisions`](docs/decisions.md) | any | the questions waiting for the owner, with options and the agent's lean; records answers |
| [`doc-tables`](docs/doc-tables.md) | any | tables in a repository's own docs filled from its files: projects, Harmony patches, mod requirements |
| [`feeds`](docs/feeds.md) | any | a feed folder's index and checks, and reading feeds from GitHub with the last good copy kept |
| [`game-files`](docs/game-files.md) | any | what a game writes and what Steam records: what changed since you last played, saves, screenshots, space |
| [`gate`](docs/gate.md) | any | run a repository's checks before a commit and report only what failed |
| [`history`](docs/history.md) | any | what happened to a game's products over time, and any changelog as it stood at any moment |
| [`installs`](docs/installs.md) | any | what each installed mod would gain or lose by updating or going back to a backup; backs up, goes back, installs |
| [`issue-links`](docs/issue-links.md) | any | where a fault in a mod is reported, and GitHub's new-issue form filled in for a person to send |
| [`makeup`](docs/makeup.md) | any | what a repository is made of, how it grew, where the work goes, and what each product holds |
| [`manifest`](docs/manifest.md) | any | every command, its reports and options, and what each one reads or changes |
| [`mcp`](docs/mcp.md) | any | the kit's read-only reports offered to AI programs over the Model Context Protocol, and how to set one up |
| [`mod-list`](docs/mod-list.md) | any | what is wrong with a game's list of active mods and why; safe changes, each after a backup |
| [`picks`](docs/picks.md) | any | the pictures and sounds waiting for the owner to pick one, with their tries; records picks |
| [`pins`](docs/pins.md) | any | which version of this tool kit each repository pins, and what moving the pin would bring |
| [`programs`](docs/programs.md) | any | which other programs the tools use, whether each is on this PC, and where to get it |
| [`records`](docs/records.md) | any | a copy of D'thorga Companion's own records in a folder of your choosing, and how old the newest is |
| [`release`](docs/release.md) | any | changelog checks, version constants kept in step, history screen |
| [`repos`](docs/repos.md) | any | each repository's commits not pushed, files changed, and whether GitHub's checks passed for its last push |
| [`rimworld-archive`](docs/rimworld-archive.md) | rimworld | keep every version of the game's assembly and of tied mods, and compare two of them |
| [`rimworld-code`](docs/rimworld-code.md) | rimworld | another author's code: its source from a public clone or a decompile, and which assembly holds it |
| [`rimworld-defs`](docs/rimworld-defs.md) | rimworld | which active mods define and patch each RimWorld Def |
| [`rimworld-log`](docs/rimworld-log.md) | rimworld | summarise a RimWorld Player.log and name the mods involved |
| [`rimworld-patches`](docs/rimworld-patches.md) | rimworld | which active mods patch which methods with Harmony, from their metadata |
| [`rimworld-perf`](docs/rimworld-perf.md) | rimworld | where a running RimWorld spends its time, by mod, method and part of the game loop |
| [`rimworld-readiness`](docs/rimworld-readiness.md) | rimworld | which active mods are ready for a game version, and which are likeliest to break |
| [`rimworld-save`](docs/rimworld-save.md) | rimworld | answer questions about a RimWorld save from a fast index |
| [`rimworld-settings`](docs/rimworld-settings.md) | rimworld | the player's RimWorld mod settings, files left behind, changes since a snapshot |
| [`rimworld-sources`](docs/rimworld-sources.md) | rimworld | where each tied mod's public source lives, checked against its package ID |
| [`rimworld-startup`](docs/rimworld-startup.md) | rimworld | how long RimWorld takes to start, the costliest mods, what changed between launches |
| [`rimworld-targets`](docs/rimworld-targets.md) | rimworld | whether every member our C# names by string still exists in the game and the mods |
| [`rimworld-textures`](docs/rimworld-textures.md) | rimworld | whether active mods' encoded textures match their pictures, and encoding those that don't |
| [`rimworld-update-check`](docs/rimworld-update-check.md) | rimworld | the game or mods updated: our patches' targets, temporary patches, update sizes, our XML patches |
| [`rimworld-upstream`](docs/rimworld-upstream.md) | rimworld | whether an update or another author's source changed a method our code patches or names |
| [`rimworld-workshop`](docs/workshop.md) | rimworld | what players report about RimWorld mods on the Workshop lately |
| [`rules`](rules/README.md) | any | the rules every repository shares, and whether a repository reads them |
| [`safe-copies`](docs/safe-copies.md) | any | copies of what cannot be made again, kept apart by kind; checks them and copies them back |
| [`screen-notes`](docs/screen-notes.md) | any | what the owner flagged as looking wrong in D'thorga Companion; marks a note dealt with |
| [`settings`](docs/settings.md) | any | the settings the tools read, where each value comes from, and the central settings file |
| [`steam-publish`](docs/workshop-publishing.md) | any | release notes, staging and the owner-run Workshop uploader |
| [`steam-workshop`](docs/workshop.md) | any | what players report about Workshop items lately, by ID or URL |
| [`test-pass`](docs/test-pass.md) | any | what a repository's in-game test list is waiting for, from the game's notes and the owner's verdicts |
| [`windows-dumps`](docs/crash-dump.md) | any | whether Windows keeps full crash dumps of a program, and asking it to |
| [`zeroed`](docs/zeroed.md) | any | files a crash left filled with zero bytes, what each is, and putting tracked ones back from git |
<!-- end generated -->

## Licence

MIT, for Phobos-authored work in this repository; see [LICENSE](LICENSE). Games and other authors' mods keep
their own terms, and this project is not affiliated with or endorsed by any game's developer or publisher.
