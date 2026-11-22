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
- **rimworld-archive (1.15.0) keeps every version of the game's assembly and of the mods a project ties into**, outside the
  cache, so two builds can be compared after Steam has replaced the older one. See [rimworld-archive](docs/rimworld-archive.md).
- **rimworld-code (1.49.0) shows another author's code to a program**: a type's or member's source from its public clone or a
  decompile, which assembly declares it, and a decompile on request. See [rimworld-code](docs/rimworld-code.md).
- **rimworld-sources (1.16.0) finds where each tied mod's public source lives**, checking each repository's About.xml against
  the mod's package ID, keyless and paced. See [rimworld-sources](docs/rimworld-sources.md).
- **rimworld-perf (1.13.0) records a running RimWorld 1.7 from outside** with Microsoft's dotnet-trace and dotnet-counters, which
  its first recording installs (needs the .NET SDK); save the game first, as attaching can hitch it for a moment. See
  [rimworld-perf](docs/rimworld-perf.md).
- **The heap reader (1.65.0) looks inside a running game** from a Windows snapshot (a pause of about half a second): every
  object by type and by mod, any object's values, what holds it and why it is still in memory. Ask before each snapshot and save
  first. See [the heap reader](docs/heap-reader.md).
- **The Harmony patch reader needs the .NET SDK** (10 or newer) for its first build, into the same folder outside the
  repository as the Rust tools.
- **The save index needs one Rust build:** add `--build-indexer` to its first command, with Rust from
  [rustup](https://rustup.rs). It builds outside the repository, so a cloud-synced clone does not upload hundreds
  of megabytes. Everything else is standard-library Python 3.10 or newer.
- **These tools never run inside a game.** They read files the game wrote. Runtime mod libraries (D'thorga
  Framework for RimWorld, PhobosLib for Project Zomboid and FS25, Phobos Framework for Ostranauts) stay in
  their own repositories.
- **Read-only towards the game.** Tools never write to a game's install, save or Workshop folders. Save
  tools work on a copy. Two exceptions, each only when asked and never while the game runs: the install
  helper, which copies a mod into a game's mod folder and backs up first; and `rimworld-textures encode`, which
  writes encoded textures (`.dds`) into the mod folders it is named, Workshop ones included, as RimSort does.
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
python -m phobos_modkit rimworld-save          summarise the newest save; also pawns, things, hediffs, find, thing, sql
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
python -m phobos_modkit rimworld-perf record             where the running game spends its time, by mod; also report, mod, compare
python -m phobos_modkit rimworld-perf stack              a frozen game: where every thread is stuck; heap for memory by mod
python -m phobos_modkit rimworld-perf watch              the game's memory over time, without pausing it: bursts or a climb, .NET's or not
python -m phobos_modkit rimworld-perf look-why TYPE      inside the running game: why something is still in memory; look, look-kind too
python -m phobos_modkit rimworld-readiness               which active mods are ready for a game version
python -m phobos_modkit code --each-in DIR show Type.Member   a C# member's source by name; also find, outline, refs
python -m phobos_modkit code compare OLD.dll NEW.dll   what changed between two builds, member by member
python -m phobos_modkit rimworld-archive snapshot --root ..   keep every new version of the game and tied mods; also list, compare, get
python -m phobos_modkit rimworld-sources --root .. --write   where each tied mod's public source lives, checked
python -m phobos_modkit rimworld-code show Type.Member --root REPO   another author's code, from a clone or a decompile
python -m phobos_modkit rimworld-upstream --root REPO --clones DIR   updates and upstream commits that changed members we patch
python -m phobos_modkit rimworld-update-check --root REPO   after an update: our targets, temporary patches, update sizes, our XML patches
python -m phobos_modkit crash-dump               why a program crashed, from its Windows crash dump; names methods in a full one
python -m phobos_modkit windows-dumps --program X   whether Windows keeps full crash dumps of a program; --apply asks it to
python -m phobos_modkit cleanup --root REPO      what the tools, builds and tests left behind; --apply deletes it
python -m phobos_modkit test-pass report --root REPO   in-game tests waiting for the owner; apply writes verdicts in
python -m phobos_modkit installs status --root REPO    what updating or going back gains or loses; also backup, restore, install, build
python -m phobos_modkit rimworld-textures status       whether any active mod would show an old picture; encode fixes it
python -m phobos_modkit changes list --root REPO       what the changelogs say changed lately; entry shows one entry's code
python -m phobos_modkit history timeline --root REPO   what happened to every product over time; at reads a changelog as it stood
python -m phobos_modkit settings list                  every path the tools read, and where each value comes from
python -m phobos_modkit connections around --root REPO --node ID   how one method, class, Def or function connects to the rest
python -m phobos_modkit rules list                     the rules every repository shares; check says whether one reads them
python -m phobos_modkit art-audit report --root REPO   images drawn in code, without a record, or borrowed
python -m phobos_modkit gate --root ..         this repository's checks before a commit; only what failed
python -m phobos_modkit gate --verify-staged    the commit guard: were the staged files checked by a passing run?
python -m phobos_modkit manifest               every command, its options and what it reads or changes
```

## Tools

Proposed on 7 Nov 2026 in phobos-rimworld's
[analysis tooling record](https://github.com/phobos-dthorga/phobos-rimworld/blob/main/docs/development/analysis-tooling.md),
in order of expected saving.

| # | Tool | What it answers | Language | Status |
| --- | --- | --- | --- | --- |
| 1 | [Log triage](docs/rimworld-log.md) (RimWorld) | What went wrong this run, which mod it came from, what is new since last run | Python | Built: 0.1.1 |
| 2 | [Save index and query](docs/rimworld-save.md) (RimWorld) | Where things are in a large XML save; pawns, hediffs, holders; map grids; pollution on the world map; what changed between two saves; where a colony's mood suffers; the whole world map for a program to draw | Rust engine, Python reports | Built: 0.6.0, with map grids and save comparison; world-map pollution 0.19.0; colony mood 1.5.0, exact with the colony mood file and with advice 1.6.0; atlas 1.7.0; terrain 1.14.0; one thing's saved data 1.52.0 |
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
| 14 | [Test pass](docs/test-pass.md) | A repository's in-game test list, what the game has seen working and the owner's verdicts; writes verdicts into the list on request | Python | Built: 1.9.0; part passes and verdicts given in conversation 1.14.0 |
| 23 | [Connections](docs/connections.md) | How a repository's code fits together, in C# (exact from the built assemblies, with Harmony patches), XML Defs, Lua and Python: what calls what, holds what, builds on, overrides, patches and uses what; the things a commit changed; a flow of calls a few steps each way | Python, with the kit's C# assembly reader | Built: 1.33.0 |
| 22 | [Settings](docs/settings.md) | Every path the tools read, its value and where that comes from (the environment, a repository's own file, the central settings file or the default); sets one in the central file on request | Python | Built: 1.30.0 |
| 21 | [History](docs/history.md) | What happened to a game's products over time, as facts from git back to each repository's first commit (versions written, released, removed; entries added, reworded, removed; mods renamed or merged away) and from this PC's history log (installs, go-backs, backups, builds, encoded textures); any changelog as it stood at any moment | Python, with git | Built: 1.30.0 |
| 20 | [Shared rules](rules/README.md) | The owner's rules for every game, mod and tool repository, in one place, and a check that a repository reads them | Markdown, with a Python check | Built: 1.25.0 |
| 19 | [Changes](docs/changes.md) | What a repository's changelogs say changed lately, and the code behind any one entry: the commit that wrote it and its diff, file by file. Any game, any repository with a changelog | Python, with git | Built: 1.24.0 |
| 18 | [Textures](docs/rimworld-textures.md) (RimWorld) | Whether every active mod's encoded textures match its pictures (a stale one shows the old picture), and encoding those that don't with RimSort's own todds preset, on request | Python, with RimSort's todds | Built: 1.21.0 |
| 17 | [Installs](docs/installs.md) | Each mod's installed copy, the repository's and every backup, and what moving between them gains or loses by their changelogs; backs up, goes back to a backup, or runs the repository's install, on request | Python | Built: 1.20.0 |
| 15 | [Art audit](docs/art-audit.md) | Every shipped image with its record and how it was made; images drawn in code or without a record; pictures a Def borrows from another thing or another mod | Python | Built: 1.12.0 |
| 16 | [Performance in play](docs/rimworld-perf.md) (RimWorld 1.7) | Where the running game spends its time: by part of the game loop, by the mod that caused it, by method, with garbage collection; and whether a change made it faster. Since 1.22.0, where a frozen game is stuck and what holds its memory, by mod. Since 1.42.0, the game's memory over time, without pausing it: average or bursts, .NET's heap or the rest, with what the log says at each jump | Python, with Microsoft's dotnet-trace, dotnet-counters, dotnet-stack and dotnet-gcdump, and Windows' own memory figures | Built: 1.13.0, 1.22.0, 1.42.0 |
| 36 | [Picks](docs/picks.md) | The pictures and sounds waiting for the owner to pick one, from each repository's config/picks.json (offered by its art tools), with every try; the owner's picks, kept in the Companion's folder | Python | Built: 1.83.0 |
| 35 | [Zeroed](docs/zeroed.md) | Files a crash left filled with zero bytes across your repositories and the tools' own folders, what each is and what puts it right; tracked files put back from git on `--apply` | Python | Built: 1.81.0 |
| 34 | [Mod list](docs/mod-list.md) (RimWorld, Project Zomboid) | What is wrong with a game's list of active mods and why: missing mods with the reason they went and any clue that another mod now does their job, needs, order, clashes, early warnings from Steam and game versions; one change at a time, each after a backup, with an undo; a sorter that explains every move, from mods', community and your own rules (1.74.0); saved lists from saves, RimSort's history, files and each game start (1.76.0); subscribing and unsubscribing through Steam (1.77.0) | Python | Built: 1.72.0 |
| 30 | [Game files](docs/game-files.md) | For any Steam game: what changed since you last played (the game's build and every Workshop item updated since), its saves, its screenshots (its own and Steam's) and where its space goes; places guessed by name or given | Python | Built: 1.46.0 |
| 29 | [Decisions](docs/decisions.md) | The questions waiting for the owner, from each repository's config/decisions.json, with options and the agent's lean; the owner's answers, kept in the Companion's folder | Python | Built: 1.45.0 |
| 28 | [Claims](docs/claims.md) | Who is working on what: agent sessions sharing a machine take and release version numbers, test rows and files on one board, and are refused what another holds | Python | Built: 1.44.0 |
| 27 | [Records](docs/records.md) | A copy of D'thorga Companion's own records (verdicts, history log, marks, screen notes, shortcuts, central settings) in a folder of your choosing, and how old the newest copy is; never deletes | Python | Built: 1.43.0 |
| 26 | [Screen notes](docs/screen-notes.md) | What the owner flagged as looking wrong in D'thorga Companion with one key: the page's picture, its address and their words, for agent sessions to read at the start; marked dealt with, never deleted | Python | Built: 1.41.0 |
| 25 | [Make-up](docs/makeup.md) | What a repository is made of: every committed file by product, kind, lines and size; how that grew day by day; where the work goes; and what each product holds for players (Defs by type, pictures, sounds, text keys) | Python, with git | Built: 1.39.0 |
| 24 | [Pins](docs/pins.md) | Which version of this kit each repository pins, and what moving its pin would bring, by the kit's changelog | Python, with git | Built: 1.38.0 |
| 33 | [Safe copies](docs/safe-copies.md) | Copies of what cannot be made again (training sets, style models, notes) in folders the owner chose and a private repository, kept apart by kind so nothing made from a game's files reaches a shared place; checked by hash and copied back on request; never deletes at a source, and lets go only earlier copies beyond a set's keepEarlier. Every game's saves and settings from one small list each, and a daily run of everything (1.71.0) | Python, with git | Built: 1.66.0 |
| 32 | [The heap reader](docs/heap-reader.md) (RimWorld 1.7 first) | Inside a running .NET game from a snapshot: every object by type and by mod, one kind's objects described, any object with every value it holds, what holds it, and paths from a root that say why it is still in memory; a held snapshot for a program's page | C# (Microsoft's ClrMD), Python | Built: 1.65.0 |
| 31 | [Programs](docs/programs.md) | Which other programs the tools use (git, .NET, ilspycmd, Steam, a game's own), whether each is on this PC, what needs it and where to get it; builds the kit's compiled tools ready for an installer to carry | Python | Built: 1.62.0 |
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
| [rules/README.md](rules/README.md) | The shared rules: what the folder holds, how a repository takes them up, how a rule is changed, and what is waiting to move there |
| [docs/changes.md](docs/changes.md) | Changes: how an entry's commit is found, what the answer holds, and what it cannot know |
| [docs/history.md](docs/history.md) | History: the facts from git and from the history log, a changelog as it stood, and the limits |
| [docs/connections.md](docs/connections.md) | Connections: what each language's reader reads and how exactly, the ids, the answers, and the limits |
| [docs/settings.md](docs/settings.md) | Settings: the order every path is read in, the central settings file, and a repository's own settings |
| [docs/rimworld-textures.md](docs/rimworld-textures.md) | Textures: the game's rule for a .dds beside a .png, what counts as stale, the Workshop dates checked, and encoding |
| [docs/rimworld-perf.md](docs/rimworld-perf.md) | Recording a running RimWorld from outside: what is recorded, how time is put down to mods, and the limits |
| [docs/rimworld-readiness.md](docs/rimworld-readiness.md) | Which active mods declare a game version, and how closely each depends on the game |
| [docs/manifest.md](docs/manifest.md) | The JSON envelope every command prints, and the manifest of commands, options and effects |
| [docs/rimworld-code.md](docs/rimworld-code.md) | Another author's code for a program: where it is looked for, which assembly holds a type, and decompiling on request |
| [docs/rimworld-upstream.md](docs/rimworld-upstream.md) | Whether an update or another author's source changed a member our code patches or names |
| [docs/rimworld-update-check.md](docs/rimworld-update-check.md) | The game or mods updated: whether our patches' targets and XML patches still find what they name, whether a temporary patch's fault was touched, and how big each update was |
| [docs/crash-dump.md](docs/crash-dump.md) | Windows crash dumps: the exception, a call loop that ran away, the methods in a full dump, what a small dump cannot say, and windows-dumps |
| [docs/cleanup.md](docs/cleanup.md) | Cleanup: the kit's cache, its development build and a repository's own leftovers, previewed before anything is deleted |
| [docs/test-pass.md](docs/test-pass.md) | The test pass: the repository's evidence map, the seen-in-play notes and verdict files, and what apply writes |
| [docs/installs.md](docs/installs.md) | Installs: the repository's installs.json, the install record, how gains and losses are read, and what each move does and refuses |
| [docs/art-audit.md](docs/art-audit.md) | The art audit: how images find their records, how a record's first statement sets the kind, the config, and what counts as borrowed |
| [docs/makeup.md](docs/makeup.md) | Make-up: products, kinds, what counts as a line, the history cache, and the answers |
| [docs/pins.md](docs/pins.md) | Pins: which kit version each repository records, and what a move would bring |
| [docs/picks.md](docs/picks.md) | Picks: the file, offering and settling, and the answers file |
| [docs/zeroed.md](docs/zeroed.md) | Zeroed: finding files a crash left filled with zeros, and what puts each right |
| [docs/research/rimsort-sorting.md](docs/research/rimsort-sorting.md) | RimSort's sorting studied: its tiers, rule merge and sorts, compared with ours, with proposals |
| [docs/mod-list.md](docs/mod-list.md) | Mod list: the checks, why a mod is missing, each game's lists, and the backups behind every change |
| [docs/game-files.md](docs/game-files.md) | Game files: where each part comes from, how places are guessed, and what the report holds |
| [docs/decisions.md](docs/decisions.md) | Decisions: the config, the answers file, and acting on an answer |
| [docs/claims.md](docs/claims.md) | Claims: naming a thing, the board file and its lock |
| [docs/records.md](docs/records.md) | Records: what is copied, where, and what each copy holds |
| [docs/safe-copies.md](docs/safe-copies.md) | Safe copies: the two kinds, proving a training is ours, the destinations and their marks, the list's fields |
| [docs/programs.md](docs/programs.md) | Programs: what status lists and how each is found, and what bundle makes |
| [docs/heap-reader.md](docs/heap-reader.md) | The heap reader: looking inside a running game from a snapshot, what it answers, which memory-reading library it trusts, and its limits |
| [docs/screen-notes.md](docs/screen-notes.md) | Screen notes: a note's folder, its files, and resolving one |
| [docs/gate.md](docs/gate.md) | The gate: a repository's checks from config/gate.json, and what each output parser keeps |
| `python/phobos_modkit/` | Standard-library Python package: `report.py` (every tool's reports), `cache.py` (derived data), `sampling.py` and `dotnet_diagnostics.py` (sampled call stacks and Microsoft's diagnostics tools), `query.py` (report filters), `steam/` (Workshop research; `publish/` for publishing), `release/` (changelogs, constants, history screen), `gate/` (the check runner and its output parsers), `code/` (the C# declaration scanner and index), `logs/` (game-free triage), `games/rimworld/` (the adapter, with the save schema), `games/ostranauts/` (publishing only), `games/zomboid/` (the mod list) |
| `crates/xml-index/` | Rust: streams any large XML file into SQLite, driven by a schema file; `cargo test` |
| `dotnet/` | C# tools: `PhobosModKit.Assemblies`, the assembly metadata reader (System.Reflection.Metadata; builds outside the repository) |
| `fixtures/`, `tests/` | Hand-written test data and the tests: `python -m unittest discover -s tests` |

## Licence

MIT, for Phobos-authored work in this repository; see [LICENSE](LICENSE). Games and other authors' mods keep
their own terms, and this project is not affiliated with or endorsed by any game's developer or publisher.
