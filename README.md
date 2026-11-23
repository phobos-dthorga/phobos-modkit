# Phobos ModKit

Out-of-game tools for game modders: read logs, saves, mod data and Steam Workshop pages, and answer the usual
questions in a short summary instead of a long read. One shared home for code that the
[Phobos](https://github.com/phobos-dthorga) game repositories had each been copying.

## Read this first (gotchas)

- **`python -m phobos_modkit manifest` lists every command** with what it reads and changes, and the [Tools](#tools) table
  below says what each is for and links its doc, which ends with every report and option it takes. The first were RimWorld log triage, the save index, the Def index,
  Workshop research and publishing, release chores, the gate, mod settings, the code index, Harmony patches, startup sessions,
  the version readiness scan and the target check. See [log triage](docs/rimworld-log.md),
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
  their own console or by their own press in D'thorga Companion. It sends through the Steam client already running and signed
  in (`--via steam`, the default since 1.98.0), or through SteamCMD (`--via steamcmd`), which asks for the login in its own
  prompt; either way the tool never sees a password, and new items are always created Private. Agents, tests and CI never run a real upload.
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
python -m phobos_modkit command-docs --write  each doc's reports and options, and this README's command index
```

## Tools

One row per command, generated from the manifest; each doc ends with every report and option its command takes. The first
tools were proposed on 7 Nov 2026 in phobos-rimworld's
[analysis tooling record](https://github.com/phobos-dthorga/phobos-rimworld/blob/main/docs/development/analysis-tooling.md).

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
| [docs/repos.md](docs/repos.md) | Repos: what each light means, when GitHub is asked, the shared allowance, and the JSON |
| [docs/feeds.md](docs/feeds.md) | Feeds: the folder and its index, kinds and their checks, reading with the last good copy, and the nightly workflow |
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
| [docs/command-docs.md](docs/command-docs.md) | Command docs: the generated block of reports and options in each doc, and the README's command index |
| [docs/gate.md](docs/gate.md) | The gate: a repository's checks from config/gate.json, and what each output parser keeps |
| `python/phobos_modkit/` | Standard-library Python package: `report.py` (every tool's reports), `cache.py` (derived data), `sampling.py` and `dotnet_diagnostics.py` (sampled call stacks and Microsoft's diagnostics tools), `query.py` (report filters), `steam/` (Workshop research; `publish/` for publishing), `release/` (changelogs, constants, history screen), `gate/` (the check runner and its output parsers), `code/` (the C# declaration scanner and index), `logs/` (game-free triage), `games/rimworld/` (the adapter, with the save schema), `games/zomboid/` (the mod list and publishing), `games/ostranauts/`, `games/kenshi/` and `games/wrsr/` (publishing only: each a `workshop.json`) |
| `crates/xml-index/` | Rust: streams any large XML file into SQLite, driven by a schema file; `cargo test` |
| `dotnet/` | C# tools: `PhobosModKit.Assemblies`, the assembly metadata reader (System.Reflection.Metadata; builds outside the repository) |
| `fixtures/`, `tests/` | Hand-written test data and the tests: `python -m unittest discover -s tests` |

## Licence

MIT, for Phobos-authored work in this repository; see [LICENSE](LICENSE). Games and other authors' mods keep
their own terms, and this project is not affiliated with or endorsed by any game's developer or publisher.
