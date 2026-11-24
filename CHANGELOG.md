# Phobos ModKit changelog

Maintained from 7 November 2026. Versions are tags of this repository; consumers pin a commit.

## [Unreleased]

## [1.123.0] - 2026-11-25

### Added

- **`look-serve` runs the live checks from the snapshot it holds** (`{"op": "checks"}`), for D'thorga Companion's Explorer page:
  the person's one snapshot answers them, with no second pause. Its data is the check data with the report under `report`.
  [The heap reader](docs/heap-reader.md).

## [1.122.0] - 2026-11-25

### Changed

- **Checks find a game's check files through the games list** when none is named and there is none in the current folder: every
  repository the games list gives the game is read, and the report names the files. D'thorga Companion runs the kit from the
  kit's own folder, so its Reports page can now offer `rimworld-save checks` with nothing typed. [Checks](docs/checks.md).

## [1.121.0] - 2026-11-25

### Added

- **test-pass reads saved histories as notes** (the owner's choice of 25 Nov 2026). Lists a mod keeps in its saves (phobos-rimworld's
  vehicle event logs and logbooks) become notes in the seen-in-play format when the evidence map names them under `saved`, judged
  beside the game's own: every occurrence, where the game's notes are once a session per thing and case. A mod's version ledger in
  the save says which version ran at each item's tick; an item older than the ledger counts as stale for any row naming a version.
  `--no-saves` leaves them out. RimWorld only, so far: [saved histories](docs/test-pass.md#saved-histories).

## [1.120.0] - 2026-11-25

### Added

- **Live checks: every check in a file answered from one snapshot of the running game** (the owner's "I especially want to do
  #4", 25 Nov 2026). `rimworld-perf look-check` takes one Windows snapshot, reads each live check's values from every object of
  its kind, lets the snapshot go and reports as save checks do; `checks_live.py` is game-free. The heap reader's new `values`
  request reads named paths from every object of a kind in one pass: through links and structs, `[]` to open a list, set, array or
  dictionary, and `#` to count one. Tested on the fixture program's real snapshot; not yet run on a game.

### Fixed

- **The heap reader shows a set's items**: .NET's HashSet names its entry fields with a capital (Next, Value), and the reader
  looked for Dictionary's lower-case ones, so `object` showed a set with none.

## [1.119.0] - 2026-11-25

### Added

- **Checks: rules written as data that say when a game's state is wrong** (the owner's choice of 25 Nov 2026, after the HEMTT
  in phobos-rimworld held 975 steel in its work store for a day before anyone noticed). A check file names what to read and a
  condition that makes it a fault, in a small language that can never run code (`checks.py`); `rimworld-save checks` runs a
  repository's save checks over a save. RimWorld's adapter adds two kinds with no rule of their own: values saved as NaN or
  infinity, and references to things the save does not hold. Run over PG20, the first save the HEMTT's pile was in, it finds it.
  How to write one: [checks](docs/checks.md).

### Changed

- **A thing another holds keeps its def, ID and stack count** in `rimworld-save thing`'s values and in checks, at the paths its
  own XML would give, read from the index; before, only a line saying it was left out.

## [1.118.0] - 2026-11-25

### Added

- **`programs status` says how a missing program is fetched** (the owner, 25 Nov 2026, for D'thorga Companion's setup check:
  "Show command, run on press"). Each row now carries the page to get it from (`url`), the command that fetches it on this
  system where one is known (`fetch`: Windows' winget for git, .NET 10 and Steam, `dotnet tool install` for ilspycmd), whether
  the program that command starts is here (`fetchHere`), what must be here first (`after`) and whether a page most people open
  needs it (`everyday`). The Markdown report lists the commands for what is missing. **The kit runs none of them.** winget's
  names were read from winget; no fetch command has been run.

### Changed

- **The .NET 10 SDK is a row of its own**, and the old ".NET 10" row is the runtime: the runtime alone runs the kit's readers,
  and only watching memory, fetching ilspycmd and building need the SDK. A PC with the runtime and no SDK read as "here" before,
  with "no SDK" in small words.

## [1.117.0] - 2026-11-24

### Added

- **`connections` reads the names that cross between a game's data files and its code** (the owner's go for D'thorga
  Companion's step 7, 24 Nov 2026). With `--game`, a translation key the code asks for, a class or a Def a data file names and a
  Def named in code become names to follow in `names` and connections in the graph, by a table of rules in the game's adapter
  (`games/<game>/data-names.json`; RimWorld's and Ostranauts' now), read by the game-free `data_names`. Every rule was counted on
  phobos-rimworld and phobos-ostranauts first, and the new `connections jumps` repeats that count on any repository. See
  [connections](docs/connections.md).

### Fixed

- **A name at its own declaration means that thing**, in `connections names` by name: a Def whose name another Def shares was
  given as either of them on its own line.

## [1.116.0] - 2026-11-24

### Added

- **`connections calls` says what a commit did to its C# methods' calls, and the rings of calls it made or cut** (the owner's go
  for D'thorga Companion's step 6, 24 Nov 2026: "proceed with steps 5 and 6"). The names reader (Roslyn) reads every method in
  the C# files the commit changed twice, before and after it, and gives each changed method's calls gone, new and kept, and calls
  that moved whole into another method. A ring is followed through our code, a virtual call on the same object into an override
  of ours, and, with `--game`, a game method a change hands on to whose own body calls back into ours: the game's real assemblies
  are read for it (`calls-of`, a new command of the assembly reader; a game's adapter offers them through
  `games.real_assemblies`, RimWorld's now), since the reference package mods build against has empty bodies. On phobos-rimworld's
  stove-bills fix it finds exactly the cut ring behind the crashes of 23 Nov 2026 (`AvailableOnNow → AvailableReport → the game's
  RecipeWorker.AvailableReport`), in about 7 s. See [connections](docs/connections.md).

## [1.115.0] - 2026-11-24

### Added

- **`connections names` reads Lua, Python and XML too, by name** (the owner's go for D'thorga Companion's step 5, 24 Nov 2026:
  "proceed with steps 5 and 6"). A word in the file that names one of the repository's things in the connections graph (in code,
  never in a comment or a string; in XML only element text and attribute values) becomes a name, with the things it may stand
  for (up to 8), its first thing's connections id and its lines, all marked by name. A dotted name is matched whole when the graph
  has it (`Lamps.shine`, a C# class a Def names). Checked on phobos-rimworld (a Def file: 39 names; a Python script: 152) and
  Project Zomboid's PhobosLib (a Lua file: 37). See [connections](docs/connections.md).

## [1.114.0] - 2026-11-24

### Added

- **`installs` counts a mod's own docs as their own kind, `docs`**: Markdown files, and a README, changelog or licence by any
  suffix, outside the game's folders. When every file installing would change is `docs`, nothing in play changes, and D'thorga
  Companion 0.80.0 can show such a mod quietly (the owner's screen notes of 24 Nov 2026: every mod said "the repository has more"
  only because its README was slimmed). They were counted as `other` before.
- **`doc_tables.settings_reader` is a stable library name** (`docs/library-api.md`, now 52): phobos-rimworld's settings history
  takes each setting's label from it, so settings named outside the Prefix_SettingThing pattern (D'thorga Radio Framework's,
  D'thorga Farming's) show their window labels.

## [1.113.3] - 2026-11-24

### Changed

- **The README is short again: what the kit is, what it needs, how a repository adds it, and the command index** (docs rewrite,
  step 7). About 600 words of its own, from 2,600: the per-tool notes and the "Run a tool" list that repeated the index go (each
  fact was already on its tool's page), and so does the Project map ([architecture](docs/architecture.md) has the module map).
  It no longer says everything but the save indexer is standard-library Python: the C# readers and `rimworld-perf`'s recorders
  need the .NET SDK too, and `programs status` says what a PC has.

## [1.113.2] - 2026-11-24

### Changed

- **One page for the owner's three queues: [owner queues](docs/owner-queues.md)** (docs rewrite, step 7; the owner's decision D7
  of 23 Nov 2026). How decisions, picks and screen notes all work, said once: what waits is kept beside the work, answers in
  D'thorga Companion's folder, act then settle in one commit; then the three side by side and a short section each.
  `decisions.md`, `picks.md` and `screen-notes.md` become short pages to the tool page template that link to it.

## [1.113.1] - 2026-11-24

### Changed

- **One template for every tool page: [writing a tool page](docs/writing-a-tool-page.md)** (docs rewrite, step 7, the owner's
  go-ahead of 24 Nov 2026). What it is for, Read this first, Examples, the generated Reports and options, Inputs, Outputs,
  Effects, Failures and exit codes, Limits; no versions in headings and no "built in" status lines, whose history is here. All
  46 tool pages are reordered to it, facts kept; topical sections become subsections of the heading they belong to.

## [1.113.0] - 2026-11-24

### Added

- **One page for the options many commands share: [common options](docs/common-options.md)** (docs rewrite, step 7, the owner's
  go-ahead of 24 Nov 2026). `--root`, `--game`, `--workshop`, `--config`, `--settings`, `--cache`, `--top`, `--json` and
  `--no-redact`, what each does and what is read when it is left out, and the commands where a name means something else. Every
  generated block now ends with a line linking there for the shared options its command takes (`commonDoc` and `common` in
  `config/command-docs.json`); the check names the page as a problem when it is missing.

## [1.112.1] - 2026-11-24

### Changed

- **The first-class design moves from `rules/` to [docs/first-class.md](docs/first-class.md)** (docs rewrite, step 7, the owner's
  go-ahead of 24 Nov 2026). It says itself it is a design, not yet rules, so `rules/` now holds rules only; the rules index drops
  its row. A file in `rules/` whose status says "not yet rules" is still counted as a design holding none.

## [1.112.0] - 2026-11-24

### Added

- **`connections changed` says where each changed thing stood at that commit** (`at`: its file and lines then), for D'thorga
  Companion to light a changed method's lines and its box together (its `docs/code-reading.md`, step 3). `file` and `line` still
  say where it stands now. See [connections](docs/connections.md).

## [1.111.0] - 2026-11-24

### Added

- **`connections names`: what every name in one C# file is, and where it is declared** (the owner's choice by card, 24 Nov 2026:
  "Roslyn for C#", for D'thorga Companion's names to follow; its `docs/code-reading.md`, step 4). A new C# tool, the names reader
  (`dotnet/PhobosModKit.Names`), reads the file's project from source with Microsoft's Roslyn, after MSBuild lists its files and
  references without building it, and every project it refers to as well, so a name declared in another of the repository's
  projects is placed in its file. For each name: its kind, its signature, its documentation id, and where it is declared, as lines
  of this repository (with those lines) or as another assembly. `--commit` reads the file as it stood then. On phobos-rimworld's
  `FieldKitchen.cs`: 350 names, 203 declared in the repository, 0 errors, about 7 s. Roslyn is the kit's second C# package, listed
  in `THIRD_PARTY_NOTICES.md`; the installer bundle carries the reader. See [connections](docs/connections.md).

## [1.110.0] - 2026-11-23

### Added

- **`mcp tools` and `mcp call`: the MCP server's three tools for a program that asks a model itself** (the owner, 23 Nov 2026:
  "go ahead with the kit's tools for the model", for D'thorga Companion's help on pages). `tools` lists them as they are handed
  to a model, with the games list's repositories; `call` answers one call a model asked for, exactly as `serve` would, with
  every check it makes: only reports that read, repositories by name, no paths, redacted. One process for each call, so the
  program needs no server running. A refusal is an answer marked as an error, in words. See [mcp](docs/mcp.md).

## [1.109.0] - 2026-11-23

### Added

- **`mcp`: the kit's reports that read, offered to AI programs over the Model Context Protocol** (the owner, 23 Nov 2026, choosing
  all three parts of D'thorga Companion's AI design, and "a small one of our own" for the server). `mcp serve` is started by an AI
  program (Claude Desktop, Claude Code, LM Studio, Gemini CLI and others) and offers three tools: `find_reports`, `describe_report`
  and `ask_report`. **It runs only reports whose manifest effect is `reads`**, checked at every call, and `reads-online` only with
  `--online`; a repository is named from the games list, never by a path; a text value that looks like a path is refused; every
  answer is redacted. It answers revision 2026-07-28 of the protocol and the older `initialize` handshake both. `mcp setup` gives
  the lines to paste into a program's settings. Standard library only, no new dependency. Checked by its tests and one real run
  over standard input and output; not yet tried from any AI program. See [mcp](docs/mcp.md).

### Changed

- **The games list is read in one place, `games_list.py`**, moved out of `safe_copies_daily`, which keeps `GAMES`, `games_file`
  and `repositories` under the same names. Each entry now also names the game that lists it.

## [1.108.1] - 2026-11-23

### Added

- **Two docs: the kit's architecture and its library API** (docs rewrite, step 4, the owner's go-ahead of 23 Nov 2026). An audit
  had found the architecture spread over `AGENTS.md` and `project-direction.md`, and no doc of what other repositories import.
  [architecture.md](docs/architecture.md), written fresh from the code: the three layers with a diagram, the module map, the five
  game adapters, the command model (manifest, report, envelope, progress, generated blocks), derived data, the Rust and C# parts
  and where they build, the paths order, tests and the gate, a checklist for a new command, and how a consumer uses the kit.
  [library-api.md](docs/library-api.md), from every `phobos_modkit` import in phobos-rimworld, D'thorga Companion and
  phobos-ostranauts: 51 names stable (30 command entry points with the keywords consumers pass, 21 library names), whose change
  raises the major version, and 20 internal names imported today, each with its way out. `tests/test_library_api.py` fails when a
  stable name or keyword disappears, or the doc stops listing one. Stable versus internal is an agent choice, for the owner to
  revise.

### Changed

- **`project-direction.md` keeps only direction**: decisions, what is out of scope, what waits and what was not adopted. Its
  layers, languages and frameworks tables moved to the architecture doc, and its "Order of work" history went (each step is in
  this changelog). `AGENTS.md` points to the architecture doc instead of repeating the layers table, and names the library API
  as what its major-version rule protects; the README and `CONTRIBUTING.md` link both docs.

## [1.108.0] - 2026-11-23

### Added

- **doc-tables: a `mod-settings` kind, a table of one mod's settings generated from its code** (docs rewrite, step 3, the owner's
  go-ahead of 23 Nov 2026: settings tables generated instead of written by hand in several places). In the order the settings
  window draws them: the label as the window shows it, what it does (its tooltip or description), its default as a player sees it
  (On or Off, an option's label, a number), and its page and section; under the table, the saved settings it did not find drawn.
  The core asks the game's adapter (`mod_settings.py`, game-free); **RimWorld's** (`games/rimworld/mod_settings.py`) reads each
  `ModSettings` class's `ExposeData` for keys and defaults, constants and enum members followed, and the window's drawing calls by
  the habit nearly every mod has (a translated label first, the setting's field among the later arguments, a translated tooltip
  after it), with labels from the mod's `Keyed` language files, pages from calls that pass a translated label beside a drawing method,
  and sections from the calls `sectionCalls` names. What it cannot resolve shows as its key and is listed in the command's report.
  **What a next game needs**: a `mod_settings(root, options)` in `games/<game>/mod_settings.py` returning a `SettingsRead`; Project
  Zomboid's would read a mod's `sandbox-options.txt`. Until then its table says so in words ([doc-tables.md](docs/doc-tables.md)).

## [1.107.0] - 2026-11-23

### Added

- **doc-tables: tables in a repository's own docs, filled from its own files** (docs rewrite, step 3, the owner's go-ahead of
  23 Nov 2026). `config/doc-tables.json` names each table's doc, kind and options; `doc-tables --write` writes it between
  `<!-- generated: table NAME -->` marks, and without `--write` it checks, for a repository's gate. Three kinds:
  `dotnet-projects` (every `.csproj`: what it builds into from its own properties, its project and assembly references, whether
  its C# uses Harmony, its test projects), `harmony-patches` (per project, the methods its `[HarmonyPatch]` attributes name, class
  and method attributes combined, with their kinds; `TargetMethod` patches and manual `.Patch(` calls counted; any attribute form
  it cannot read listed with its file and line) and `mod-requirements` (needs, load order, game versions and optional tie-ins,
  through the game's adapter: RimWorld's reads About.xml and LoadFolders.xml). **What a next game needs**: a
  `mod_requirements(folder)` in its `games/<game>/mod_list.py`; until then its table says so in words
  ([doc-tables.md](docs/doc-tables.md)).
- **command-docs and doc-tables share one block mechanism**, `generated_blocks.py`: the marks, replacing and appending a block,
  and keeping a doc's own line endings.

### Fixed

- **rimworld-perf's manifest no longer says every report attaches to the running game.** Only `record` (dotnet-trace and
  dotnet-counters), `stack` (dotnet-stack), `heap` (dotnet-gcdump), `watch` (dotnet-counters, unless `--no-counters`) and the
  `look` reports (a Windows snapshot) do, and each now says so in its own note; `report`, `index`, `mod`, `compare`, `list` and the
  other reports read files only.
- **workshop.md and rimworld-log.md drop their hand-written options tables**, which repeated their generated blocks; the few
  facts only they held (how often Workshop details are fetched, what `--json` and `--brief` give) move into the text.

## [1.106.0] - 2026-11-23

### Added

- **Every command's doc now lists all its reports and options** (docs rewrite, step 3, the owner's go-ahead of 23 Nov 2026: an
  audit found 33 of 48 commands with options their doc never named). `command-docs --write` writes a block between
  `<!-- generated: options COMMAND -->` marks in each doc, from the command's own parser: each report with its effect, each option
  once with the reports that take it, its help and its default. `config/command-docs.json` names each command's doc. The
  README's out-of-order Tools table, with its frozen "Built" versions, becomes a generated index of every command. Without
  `--write` it checks, and the gate (and CI) fail when a block is out of date ([command-docs.md](docs/command-docs.md)).
- **The manifest gives each option's `metavar`**, the placeholder its usage shows (`--set KEY=VALUE`), or null.

### Fixed

- **25 options that had no help text now have one**: the `sql` reports' `QUERY`, `rimworld-settings snapshot` and `compare`'s
  files, `steam-publish`'s mod names, `--visibility`, `--description` and `--changelog` on `pull`, `release`'s `FILES`,
  `--catalogue`, `--set` and `--expect`, and `code find`'s `PATTERN`.

## [1.105.1] - 2026-11-23

### Fixed

- **A build before preparing no longer spoils the JSON answer**: `steam-publish prepare --build` and `update` send the
  build's own output to standard error, so a program reading `--json` (D'thorga Companion's Build first and Update all
  waiting) gets one whole answer. Found building a phobos-ostranauts package through its new build command.

## [1.105.0] - 2026-11-23

### Changed

- **The twelve rules every repository repeated now live here** (the owner's word of 23 Nov 2026 in the docs rewrite, D4: "Move all
  12 now"; each wording chosen by the moving agent from the repositories' own, for the owner to revise). Ten join
  `rules/every-session.md` (working slices and no hour estimates; nothing tested until the owner says so; never the mouse,
  keyboard or saves; choices labelled; writing plainly with Mermaid, never Figma; commit to `main`, never force-push; version
  numbers; the gate before every commit; what is never committed). Two get files of their own, read before the work:
  `rules/brand.md` (D'thorga, plain names, the "dthorga" spelling) and `rules/changelogs.md` (a mod's changelog form, and the
  owner's choice D2 of the same day: existing entries are never moved, new entries are short). This repository's `AGENTS.md`
  drops its copies, and `every-session.md`'s reasoning about commit costs moves to `rules/README.md`, so the file read every
  session holds rules only. **Consumers drop their own copies when their pin moves to this version.**

## [1.104.0] - 2026-11-23

### Added

- **Records can be kept out of the folders a repository ships** (the owner's choice of 23 Nov 2026, docs rewrite D6: phobos-rimworld's
  deploy copied about 492 `*.record.md` notes beside their images and sounds into the game's Mods folder). The art audit's config
  takes `records.mirrors`, mapping a leading folder to where its records are kept (`{"mods": "assets/records"}`), and looks for an
  image's record beside it first, then in the same place under the mirror, so a record not yet moved still pairs. A tool that writes
  records asks `artaudit.record_home(path, artaudit.mirrors_of(root))` where a new one goes. Without `mirrors`, nothing changes
  ([art-audit.md](docs/art-audit.md)).

## [1.103.2] - 2026-11-23

### Fixed

- **The README's facts match the kit again** (the owner's docs rewrite, step 1, 23 Nov 2026). It said "Ten tools are built"
  where 48 commands are, and that the uploader goes through SteamCMD, where the Steam client has been the default since 1.98.0;
  its project map now names the Kenshi and Workers & Resources publishing data. `project-direction.md` no longer draws a
  `games/fs25` that never existed, and says why the game adapter contract still waits now that five games have adapters.

## [1.103.1] - 2026-11-23

### Fixed

- **A pick is never replaced by one of the other kind.** `picks offer` refuses a sound under a waiting picture's id (or the
  reverse), saying so: phobos-rimworld's night 12 made a picture and a sound both named `n12-exhaust-brake`, and the sound's offer
  replaced the picture, which never reached the owner's Picks page. A repository's art tools give each kind its own ids.
- **Writing the picks file is tried again while another program holds it**, as the kit's other writers are: one refused swap
  ("Access is denied", the Companion or a sync reading the file that moment) stopped a run of offers part-way.

## [1.103.0] - 2026-11-23

### Added

- **One build at a time in a repository** (the owner's report of 23 Nov 2026, and "Build the lock in phobos-modkit": an install's build
  failed because another session's gate was building the same projects into the same folders at the same moment). `build_lock.held`
  holds a repository's build lock, in the kit's cache; a second build waits, saying who holds it and since when, and goes on, or after
  15 minutes gives up naming the holder; a lock older than an hour is broken. The gate's steps may say `"holds": "build"`, so their
  lane runs inside the lock and a wait shows as a warning. Consumers add `holds` to their build steps and take the lock in their own
  install scripts ([gate.md](docs/gate.md), "The build lock").

### Fixed

- **The tests' isolated environment points the kit's cache into the test's own folder too.** The gate runs the tests on two Pythons
  side by side, and installs' backup peeks, unpacked into the one shared cache, could be deleted by one run under the other, failing
  `test_status_reads_a_zipped_backup_and_copies_out_a_changed_picture_to_compare` now and then.

## [1.102.0] - 2026-11-23

### Added

- **A catalogue can name its own payload hook** (`layout.payloadHook`, `"scripts/file.py:function"` inside the repository), so a
  repository whose package is built (phobos-ostranauts: its dist package, plugin assemblies, read-only data headers) gives the
  same package to every runner, D'thorga Companion's Publish page included, not only to its own wrapper. A wrapper's hook still
  wins.

## [1.101.1] - 2026-11-23

### Fixed

- **A short mod name picks the mod it names**: `Framework` is PhobosFramework, not also PhobosRadioFramework (the prefix every
  mod shares is taken off first). Found on phobos-rimworld's real catalogue.
- **The upload plan says "Required items"**, not "to set on Steam afterwards": the Steam client route sets them itself, and
  SteamCMD's reminder still follows its upload.

## [1.101.0] - 2026-11-23

### Added

- **Every steam-publish answer a program reads carries JSON data** (asked for by D'thorga Companion's Publish page): a refusal
  says `ok: false` and why; `upload` and `update` with `--json` give their lines, the receipt, the item, its status and whether
  the sender said it went up, instead of loose lines; `prepare`, `pull` and `notes` give the candidate and manifest, the rows
  and files written, and the notes' state. Receipts keep the sender's word as `senderOk`. Guide: `docs/workshop-publishing.md`.

## [1.100.0] - 2026-11-23

### Added

- **Workshop publishing for Project Zomboid, Kenshi and Workers & Resources** (the owner's choice of 23 Nov 2026), each a game
  file of data in `games/<game>/workshop.json`, with its format facts and sources. Project Zomboid builds the item as the game's
  own uploader does (the mod under `Contents/mods/<mod>/`, the cover's rules checked, refused files named, `Workshop ID` and
  `Mod ID` lines ending the page) from a repository holding one mod; Kenshi and Workers & Resources take each mod's version from
  the catalogue, as their files keep no release number, and keep the game's own record of the item number in step. Read against
  the owner's own PZ, Kenshi and Workers & Resources repositories; **none has published through it yet**.
- **Each mod's own Required items** are read from its metadata (RimWorld: every `<modDependencies>` entry with a Workshop link,
  named by its `displayName`) or listed in its catalogue entry (`requiredItems`), beside the project-wide ones.
- **More the game file can say as data**: a field from the catalogue (`catalogue:<key>`), the highest version folder's metadata
  (`"pick": "highest"`), `$KEY value` lines and quoted values, an item number kept in an XML element or before an `$END` line,
  the cover's rules and refused file endings as blockers, and a footer for the page. A catalogue's layout may hold one mod at the
  repository's top (`"mod": "."`), put the content under a folder of the item, and take the cover from elsewhere.

### Fixed

- **A cover path naming the mod (`{mod}`) is filled in**, and mod names may hold single spaces, as Kenshi's do.
- **Version control never ships**: `.git` is always left out of an item's content.

## [1.99.0] - 2026-11-23

### Added

- **`steam-publish page`**, for D'thorga Companion's Workshop page editor: a mod's page with **every problem at once**, its
  size against the budget and a starter for a page not written yet; `--check` checks a text from standard input or a file,
  and `--write` saves it only when it has no problems.
- **`steam-publish show`**: one mod's card, read-only: the change note exactly as Steam would get it next, its tags and
  Required items, blockers, sizes, whether an update is due, and every upload's receipt, newest first.
- **`status` and `pending` give their rows as JSON data**, beside the report. Guide: `docs/workshop-publishing.md`, "For a
  program's Publish page".

## [1.98.0] - 2026-11-23

### Added

- **Workshop uploads through the running Steam client** (the owner's choice of 23 Nov 2026 for D'thorga Companion's Publish
  page: "Both, chosen per upload"). `steam-publish upload` and `update` take `--via steam` (now the default) or `--via steamcmd`.
  The Steam client route uses the game's own Steam library and the client already signed in, so nothing is typed and no
  password is ever used; it sets the item's tags and Required items, which SteamCMD cannot, and reports Steam's own progress
  as progress lines. A new item's number is recorded the moment Steam gives it. RimWorld 1.7's library exports every function
  it uses; **it has not yet sent anything to Steam**. Guide: `docs/workshop-publishing.md`, "Uploading".
- **`--new-console`** runs SteamCMD in a console window of its own, so a program can start it and still never see the login.
- **A manifest effect for the owner's press, `owner-press`**: a program may run it only on the person's own press and yes;
  never an agent, a test or CI. `upload` and `update` move to it from `owner-only`, and this repository's Steam rule says so.

### Changed

- **`steam-publish upload` sends through the Steam client unless `--via steamcmd` is given.** SteamCMD's options work as
  before with it; receipts name the route as `via`, and list the tags.

## [1.97.0] - 2026-11-23

### Changed

- **Workshop publishing reads each game from a data file** (the owner, 23 Nov 2026: "The Steam Workshop uploader should be
  genericized as far as is possible"; first step of D'thorga Companion's Publish page). `games/<game>/workshop.json` says where a
  game's mods keep their title, version, cover, tags and Workshop ID file, in XML, JSON or key=value form, found in any letter
  case; `steam/publish/game_data.py` reads it, and the core names no game. RimWorld's and Ostranauts' Python adapters became game
  files: the titles and versions of all 18 mods in phobos-rimworld and phobos-ostranauts read the same as before.
- **A catalogue can describe its own game** in a `game` block of the same shape, for a game nobody has written a file for; with
  `"format": "catalogue"` the title, version and tags come from each mod's catalogue entry, and the folder goes up as it is.
- **Every candidate records the tags its item is given** (RimWorld: Mod and each supported version). The manifest's format is 4,
  so candidates prepared before this are refused: prepare a fresh one. Guide: `docs/workshop-publishing.md`, "Games, as data".

## [1.96.0] - 2026-11-23

### Added

- **Install backups are kept as zips** (the owner's choice of 23 Nov 2026, "One zip per backup"). `installs backup` writes one zip,
  checked file for file; **`installs pack`** turns backups kept as folders into zips, each checked before its folder goes; and the
  tidying after every install and go-back packs too, so older backups turn into zips at the next install. On the owner's
  RimWorld backups: 4,254 MB as folders, about 855 MB as zips; the largest, 735 MB, became 95 MB in 7 seconds.
- **A zipped backup reads as a folder did**: `status` names its name, version and changelog, its size on disk, and a folder in the
  kit's cache holding the files that changed, so a program can compare a picture with it. Going back unpacks it; repeated zipped
  backups are found and removed as repeated folders were. Guide: `docs/installs.md`.

### Changed

- **The go-back answer lists `packed` apart from `removedRepeats`.**

## [1.95.0] - 2026-11-23

### Added

- **`settings list` gives each setting a few words to list it by**, `name` (D'thorga Companion 0.66.0 shows the settings one line
  each, the owner's choice of 23 Nov 2026). Every setting the kit reads has one; a repository's own `config/settings.json` may give
  one too, and without it `name` is null and the description stands. Guide: `docs/settings.md`.

## [1.94.0] - 2026-11-23

The fourth slice of going online (D'thorga Companion's `docs/online.md`, O4: report links; the owner's choice of the Logs page).

### Added

- **`issue-links`: where a fault in a mod is reported, and the new-issue form filled in.** `where` says for each mod a fault names
  whether it is ours (installed from one of a listed repository's own mod folders, on GitHub), theirs (its public source
  confirmed in a source register) or unknown; `new` builds the address of GitHub's new-issue form with a title, text and label,
  putting a text too long for an address on the clipboard instead; `issues` lists a repository's issues, open and closed, those
  naming every word of the fault first, keyless. **Nothing is ever posted.** Guide: `docs/issue-links.md`.

### Fixed

- **A feed's `index.json` is written with plain line ends** on Windows too, so git no longer warns of changing them.

## [1.93.0] - 2026-11-23

The third slice of going online (D'thorga Companion's `docs/online.md`, O2: known problems, the owner's choice of "public, facts
and links").

### Added

- **Known problems, a feed kind**: mods that go wrong together, each with the mods that must all be active, what goes wrong,
  what to do, the day it was checked and what it was checked against, and optionally the game versions it holds for, the author's
  report and the day it was fixed. `feeds` checks every entry before it is used or published. Guide: `docs/feeds.md`.
- **`mod-list check --known`** warns of each known problem the list has (every mod it names active, on a game version it holds
  for, not marked fixed), from the last good copies the kit keeps, with no network. Without a feed read yet, it says so.
- **`feeds read --root REPO --from published`** reads a repository's own `feeds/` folder on its default branch, as `--from
  results` (the default) reads its nightly results.

## [1.92.0] - 2026-11-23

### Added

- **`feeds read --root REPO`**: a repository on this PC, read for its nightly results on the GitHub repository its `origin` names
  (`--results`, default `companion-results`), so D'thorga Companion names repositories by folder, as everywhere else. One not on
  GitHub is listed apart (`data.offGithub`), and a feed with no files now keeps its line in the report (`missing`). The first
  nightly run on GitHub (phobos-rimworld, 23 Nov 2026) found 16 commits in 24 fresh clones in 56 seconds.

## [1.91.1] - 2026-11-23

### Fixed

- **The nightly workflow starts on GitHub**: 1.90.1's named the `runner` context in the job's `env`, which GitHub refuses before
  a run begins (phobos-rimworld's first try, 23 Nov 2026). The folders are now named in the first step. `kit-ref` is required, as
  the `job.workflow_sha` fallback could not be checked (`actionlint` 1.7.12 does not know it yet); the workflow passes
  `actionlint`, which the feed guide now asks for before every push of a workflow.

## [1.91.0] - 2026-11-23

After the owner's full re-sort preview with 1.88.0 (23 Nov 2026: "Thoughts?"): the five "moved into their group" mods on their
list were already in their group. The owner chose all three fixes on a question card.

### Changed

- **A move counts as into its group only when the mod passes a mod of another group** (`kind` `group`); one that only changes
  places inside its group is a names move (`order`), or in fewest moves a room move. A mod no group claims that passes a group's
  mod is a group move too, with its reason. On the owner's list a full re-sort's 134 moves are now all names moves; fewest moves
  still finds none.
- **A group move's reason follows the links back to the member that has its own reason**, up to four links: "Deserters: Combat
  Extended loads after it, and Vanilla Expanded Framework after Combat Extended (Vanilla Expanded Framework: it is a known
  framework)". Each group keeps its own links, so a chain never runs through another group.

## [1.90.1] - 2026-11-23

### Fixed

- **The nightly workflow runs the kit at its own version**, not the calling repository's pin of it: the caller passes `kit-ref`
  (the tag it calls the workflow at), else the commit GitHub says the workflow came from. phobos-rimworld pins kit 1.83.0, which
  has neither `feeds` nor `--clone-into`, so 1.90.0's workflow would have failed there. The caller no longer needs submodules.

## [1.90.0] - 2026-11-23

The second slice of going online (D'thorga Companion's `docs/online.md`, S3 and S5, for O3's nightly watch).

### Added

- **`feeds`: small files of data a repository publishes for D'thorga Companion.** `index --write` writes a feed folder's index
  (each file's kind, size and SHA-256), `check` says whether the index still matches its files and each file passes its kind's
  check (for a gate), and `read` fetches feeds keyless from GitHub's raw files, using a file only when its size, hash and kind
  check pass, and **otherwise keeping the last good copy**, which is also what it gives when GitHub can't be reached. Kinds in
  format 1: `upstream-watch` (checked here), `theme` and `guide` (checked by the program that uses them). Guide: `docs/feeds.md`.
- **A reusable nightly workflow**, `.github/workflows/nightly-feed.yml`: a game repository calls it on a schedule with the kit
  command that writes its feed; it publishes to a results branch (`companion-results`) **only when the answer changed**, never
  force-pushing, with the run's own token for that job alone.
- **`rimworld-upstream pending --clone-into DIR`** makes or updates lean clones straight from the source register, with no GitHub
  API call, and **`--feed FILE`** writes the findings as an `upstream-watch` feed file, left untouched when only its time would
  change. **`--json` now carries every finding as data**, each pending one with a link to its commit on GitHub. First real run
  (the owner's clones, 30 days): 14 findings in 23 clones.

## [1.89.0] - 2026-11-23

The first slice of going online (D'thorga Companion's `docs/online.md`, O4's gate lights; the owner's go-ahead and answers of
23 Nov 2026).

### Added

- **`repos status`: where each repository stands with its remote.** For each repository named: its branch, commits not pushed,
  tracked files changed, and with `--online` whether GitHub's checks passed for its last push (passed, failed and which, running,
  no run yet for the last push, no checks), and each nightly run's last result, marked late after two days (GitHub switches a
  schedule off after 60 days without activity). One keyless call a repository, and one more only where its own workflow files hold
  a schedule. `--automatic` (a look nobody pressed for) asks again only when the pushed commit moved, a run was going five minutes
  ago, or a day has passed. Game-free; manifest surface `repo-status`. Guide: `docs/repos.md`.
- **One hourly GitHub allowance for every tool.** The GitHub reader keeps the calls left this hour from each answer, so every tool
  sees the same figure; it stops asking at none, and an automatic look stops at 15, keeping them for a press.
- **The last answer when GitHub cannot be asked.** A reader made to keep it gives its last answer with its age, instead of failing,
  when GitHub cannot be reached or the allowance is spent. Used by `repos status`; `rimworld-sources` is unchanged.

### Changed

- **A stale cached GitHub answer is asked for again with its ETag**, and "not modified" keeps the cached one. **Measured: for a
  keyless client GitHub still counts it as a call** (two such answers and one new one took the allowance from 57 to 54), so it
  saves the download, not the call.

## [1.88.0] - 2026-11-23

After the owner's first full re-sort preview with 1.86.0 (23 Nov 2026): all 146 moves on their list were group or name-order
moves, with no rule broken, and the owner chose on a question card to drop the one group rule RimSort does not have.

### Changed

- **A mod others' code builds on no longer joins the frameworks' group** in a full re-sort (the owner's choice): its code rules
  still order each pair, but it is not pulled up, so the groups are RimSort's tiers and no more. On the owner's list 1.86.0 lifted
  Vanilla Vehicles Expanded 198 places, Dubs Bad Hygiene 62, Rimefeller 149 and D'thorga Framework 310 this way. Now a full
  re-sort of that list moves 134 mods (5 into their group, 129 only to put names in order, none for a rule), with Vanilla
  Expanded Framework 13th, Combat Extended 18th and Vehicle Framework 21st; fewest moves still finds none. 1.87.0 is unused
  (another session's claim, released).
- **Each group move names its own reason**: "a known framework", "loads at the top (whose rule)", "a loader that goes with the
  game's own", or which member loads after it ("Vanilla Expanded Framework loads after it"), instead of every reason a group has.
- **A mod whose place number stays the same is not listed as moved**, though the mods around it moved (Adaptive Storage Framework,
  "12 → 12", on the owner's list).

## [1.86.0] - 2026-11-23

The sorter after the RimSort study (`docs/research/rimsort-sorting.md`; the owner's choices on question cards of 23 Nov 2026:
groups as RimSort's tiers, needs as RimSort reads them, Workshop requirements weakest, "top" and "bottom" as RimSort means them,
and a full re-sort's moves told apart by kind).

### Changed

- **Mods sort in groups, as RimSort's tiers**: the game's own and its loaders (Harmony, Prepatcher, Visual Exceptions); then
  frameworks (a list kept as the RimWorld adapter's data, from the facts RimSort lists) and "load at the top" mods, joined in a
  full re-sort by the mods others' code builds on; then the rest; then "load at the bottom" mods. **Each of the first two takes
  in every mod its members must load after, and the last every mod that must load after its members**: what both earlier full
  re-sorts lacked (Vanilla Backgrounds Expanded must load before Vanilla Expanded Framework, and held it back). Unlike RimSort,
  every rule still counts across groups: the group is only the first thing chosen by. On the owner's list a full re-sort moves
  146 mods (204 before) with Vanilla Expanded Framework 20th, Combat Extended 25th and Vehicle Framework 33rd.
- **"Load at the top" and "at the bottom" mean the group**, as in RimSort, not "as high (or low) as its rules allow". Fewest moves
  no longer lifts a top mod past others in its group: on the owner's list it now finds no moves (XML Extensions and Vehicle
  Framework were flagged by every earlier sort).
- **Needs make no order rule for frameworks and "top" or "bottom" mods**, as RimSort: their needs usually mean "install this".
- **Workshop requirements are the weakest rule source**, below the community rules: RimSort does not sort by them at all.
- **Each move says what kind it is** (`kind`): a rule asks for it, its group places it, or (in a full re-sort) names put in order;
  for the Companion to show the rule moves and fold the rest.

### Removed

- **"Libraries first, the most used first" (1.84.0)**, which counted any mod others load after: it lifted big content mods such as
  Vanilla Vehicles Expanded 214 places, and narrowed, let the frameworks sink again. The groups replace it. (Not wholly: in a
  full re-sort a mod others' code builds on still joined the frameworks' group, lifting Vanilla Vehicles Expanded 198 places;
  1.88.0 ends that.)

### Docs

- **RimSort's sorting studied** (`docs/research/rimsort-sorting.md`; the owner, 23 Nov 2026: study it "before any further
  changes"): its four tiers, each pulling in what its mods depend on (what our full re-sort lacked), its rule merge, its sorts and
  its handling of loops, compared with ours, with proposals. Read from its public GPL-3.0 source and summarised, nothing copied.

## [1.85.0] - 2026-11-23

Helpers for the player in the mod manager (the owner, 23 Nov 2026: "Is there anything more we can do, especially to help the
player?"; their choices on a question card: all four offered). Each came in its own commit.

### Added

- **mod-list check names libraries carried in several copies, where an older copy loads first**: when two or more active mods
  carry their own copy of the same assembly and the one loaded first (load order decides: RimWorld loads every copy, with no check
  for a name already loaded) is older than another, a note names both mods and both versions. A note, not a warning: such copies
  are often stubs that do nothing until their own mod runs, and whether a newer copy's mods need what it adds cannot be read from
  outside. The assembly reader's `refs` now also gives each assembly's version. On the owner's list: one, 0MultiplayerAPI, carried
  by 16 mods (0.5.0.0 from Adaptive Storage Framework first, 0.6.0.0 from Exosuit Framework).
- **Version notes name only the mods really in doubt**: a mod that does not say it works with the game's version, but has a folder
  for it (or a LoadFolders section), a Workshop page naming it (RimSort's Steam Workshop Database), or a place on the community's
  No Version Warning list, joins one note saying why each is likely to work. On the owner's list none yet: the Workshop database
  copy predates 1.7, and the No Version Warning list names one mod for 1.7.
- **A continued version is offered** for a mod that is missing, or does not say it works with the game's version, when the
  community's Use This Instead list (2,846 rules, MIT, read where RimSort keeps it) names a continuation that does: a note with
  the continuation's name, author and Workshop number. None on the owner's list, which already uses the continuations.
- **Did my change break it? `mod-list since`**, and the check's data (`since`, `last_run`): after a change made here, the first
  game run that started after it is compared with the run before, which ended before it, and the error signatures new since are
  named with the mods their clues point at. New since is not the same as caused by, and the words say so. Only like with like is
  compared: a run that loaded a save against one that did (on 23 Nov 2026 a two-minute run that loaded nothing made 76 errors from
  loading a save look new). When the list was changed since by something else (the game, RimSort, by hand), it says so rather
  than judge the wrong change. Each run is judged once, when the game has closed, and kept in `runs.json`; 3 s on the owner's
  logs. `mod_runs.py`; the RimWorld adapter's `runs()` and `run_report()` read Player.log and Player-prev.log with the kit's log
  reader.
- **Ran clean**: the copy of the list kept at a game start is marked with that run's verdict (`ran` in `lists`), and
  `compare` / `load --last-clean` take the newest one that ran clean.
- **No errors from it**: a mod that does not say it works with the game's version, but was on the list and named by no error in
  the newest run, counts as likely to work. On the owner's list the version notes go from 98 to 5.
## [1.84.0] - 2026-11-23

From the owner's log of 23 Nov 2026: after a full re-sort, I Am Mother's compat code failed to load ("ReflectionTypeLoadException
... PipeSystem") and a save's mechs went missing. The full re-sort had put Vanilla Expanded Framework 176 places lower (15 to 191),
with Vehicle Framework, Combat Extended, Fortified Features Framework and HugsLib likewise, below mods that build on them without
saying so. The owner's choices on question cards: libraries first, and rules read from the mods' assemblies.

### Added

- **The sorter reads what each mod's code builds on** (a new rule source, **code**, ranked under yours only): where a type in one
  of a mod's loaded assemblies (compat folders by LoadFolders.xml included) has a parent class or an interface from another mod's
  assembly, the mod loads after that one, since the game needs a type's parents the moment it reads it. A reference used only
  inside a method does not count: Combat Extended calls into Dubs Rimatomics from far above it without fault. On the owner's
  list: 139 such rules, 3 s the first read and under a second after (answers kept per file version in the kit's cache); I Am
  Mother loads after Vanilla Expanded Framework. **mod-list check** flags a mod loading before what its code builds on as a
  problem. The kit's assembly reader gains `refs` (each assembly's name, what it references, and what its types inherit from),
  shared as `assembly_refs.read_references`.

### Changed

- **A full re-sort puts libraries first**: after the game's own, a mod others load after goes as early as its rules allow, the
  most used first, then the rest by name. On the owner's list Vanilla Expanded Framework comes 17th, Vehicle Framework 18th and
  HugsLib 21st, where the 1.79.0 full re-sort put them 191st, 192nd and 181st. Fewest moves is unchanged.
## [1.83.0] - 2026-11-23

The picks page (the owner, 23 Nov 2026: "Go ahead and build the picks page", after answering its design's questions: a file each
repository keeps, a pick kept as an answer).

### Added

- **picks**: the pictures and sounds waiting for the owner to pick one (`docs/picks.md`). A repository's art tools offer a pick
  (`picks offer`) into its `config/picks.json`: a title, picture or sound, the file in use and each try's file, anywhere on this PC,
  with the grounds its game's pictures are seen on. `picks list` names every pick, waiting ones first, each file checked;
  `picks answer` keeps the owner's pick (a try, or none with words) in the Companion's folder, one line each, the last deciding;
  `picks settle` removes a pick once applied. Game-free; the manifest's `picks` surface finds it.
## [1.82.0] - 2026-11-23

Pictures and sounds beyond the code viewer (the owner, 23 Nov 2026: "Can we introduce these new features anywhere else?", choosing
on question cards the Mods page, repositories with no changelog, the Mod list's previews, screenshots and encoded textures). Each
tool now names the files a program can show; none of them decodes anything.

### Added

- **changes commits**: a repository's newest commits, newest first (`--top`, `--skip`), each with how many files it changed and
  how many of them aren't text, and the count of every commit. For a repository with no changelog, where no entry leads to its code:
  Workers & Resources' buildings repository lists 45 commits, one of them changing 142 textures and models.
- **changes entry --commit no longer needs --changelog**: it names the entries the commit wrote only when given one.
- **installs: each copy names its folder** (`folder` on the installed copy, the repository's and each backup), so a program can
  show a changed picture or sound from two copies.
- **mod-list mods: each mod's own picture** (`preview`): RimWorld's `About/Preview.png` (399 of the owner's 407 mods have one);
  Project Zomboid's `poster` from the `mod.info` the game reads, beside it (checked with made-up files only: the game is not
  installed here).
- **rimworld-textures pairs --mod NAME**: each of a mod's pictures beside the encoded texture the game loads in its place, with its
  state (fresh, stale, missing, left over) and sizes, and `flipped`, since RimSort's preset stores the texture upside down (checked
  on the owner's armour kits: turned over, it matches its picture). Found by the manifest's `texture-pairs` surface. 563 pairs for
  D'thorga Vehicles.
## [1.81.0] - 2026-11-23

### Added

- **zeroed: files a crash left filled with zero bytes** (`python -m phobos_modkit zeroed check`; `docs/zeroed.md`; the owner,
  23 Nov 2026, after a crash left two of the kit's files and a test assembly as zeros). Looks through every repository on D'thorga
  Companion's games list (`.git` included), the kit's build folder and the Companion's own folder, opening only files written in
  the last three days (`--days N`, `--all`), and names each zero-filled file with its kind and what puts it right: tracked (git's
  last commit has it: `zeroed restore --apply` writes it back), committed zeros, untracked, git's own store (`git fsck`), built (a
  full rebuild) or Companion data. Nothing is deleted. On the owner's PC: 24 folders, none found, 5.8 s with the folders cached
  and about two minutes straight after a restart.
## [1.80.0] - 2026-11-23

### Added

- **A cleanup rule can name its folder by a path setting: `{setting:KEY}`** (the owner's go, 23 Nov 2026). It is read as every
  path is: the repository's local settings file that `--settings` names, then the central settings file. A rule whose setting is
  unset is skipped, as one naming an unset environment variable is. phobos-rimworld's art tools moved their working files to a
  folder chosen by a setting (`artWorkPath`, on another drive), which no rule could name until now, so their staging folders and
  the owner's review cards were never offered for clearing.

## [1.79.1] - 2026-11-23

### Fixed

- **Tests no longer write into the home folder.** The tests' shared environment (`isolated_environ`) now points D'thorga
  Companion's own data folder into the test's folder too (`LOCALAPPDATA`, `XDG_DATA_HOME`). Without them `paths.companion_data`
  fell back to `~/.local/share`, so safe-copies' run-all test wrote its record there, and two runs at once collided (the gate
  failed once on 23 Nov 2026 with "being used by another process"). A full test run now leaves that folder untouched.
- **The kit's C# tools are built into a folder of their own for each kit version** (`<build>/dotnet/tool/<tool>/<version>`).
  Repositories pin different versions of the kit, and with one shared folder each rebuilt the assembly reader over the other's
  whenever their versions differed, so a run could find it half written (Windows: "not compatible with the version of Windows")
  or built from other source; on 23 Nov 2026 phobos-rimworld's pinned 1.75.0 and the kit's own tests did so in turns and eight
  reader tests failed. Each version now keeps its own build (about 250 KB each; older ones are left in place, never deleted
  here). This and the entry above are one commit: both were in the tree when the gate first failed.

## [1.79.0] - 2026-11-23

### Added

- **The sorter reads the Workshop's required items** (the owner, 23 Nov 2026: "add RimSort's Workshop database as a source"): a
  mod loads after each item its Workshop page lists as required, which catches needs a mod never wrote into its own files.
  RimWorld reads RimSort's Steam Workshop Database (`steamDB.json`, CC0) where RimSort keeps it, never copied; about 50 MB and
  57,679 items, read once per file version (0.6 s the first sort, 0.2 s after). A new rule source, **workshop**, ranks between a
  mod's needs and the community rules when a loop is broken (agent's order). On the owner's list it adds 19 rules the mods' own
  files do not state; the list already kept all of them.
## [1.78.0] - 2026-11-22

Pictures and sounds in the code behind an entry (the owner, 22 Nov 2026: "We should support the ability to display multimedia in
parts like this", of D'thorga Companion's code viewer, which could only say a changed picture "isn't text").

### Added

- **changes entry names what each file that isn't text is, and its size before and after**: `media` (picture, texture, sound,
  video, model, font, document, archive, program or other, by extension; null for text) and `sizeBefore` and `sizeAfter` in bytes,
  read from git's trees in one call a hundred files (`docs/changes.md`). A program can then draw a picture, play a sound or name a
  model and its sizes, where before it had only `binary`. Checked on two games' repositories: phobos-rimworld's truck armour kits
  (30 pictures) and phobos-ostranauts' washer pump (4 sounds, removed).
## [1.77.0] - 2026-11-22

Subscribing through Steam, step 5 of the mod manager (the owner, 22 Nov 2026: "Start step 5, subscribing through Steam"). The
owner's choices on question cards: through the running Steam client, at once, with the game's own Steam library; unsubscribing
asks first and switches the mod off; downloads shown until done.

### Added

- **mod-list subscribe and unsubscribe** (`steam/client.py`): through the Steam client already running and signed in on this PC,
  as RimSort does, by borrowing the game's own Steam library (RimWorld's `steam_api64.dll`; Project Zomboid's once installed) for
  the few seconds a press takes, so nothing of Steam's is shipped and no credentials are held. While it runs, Steam shows the person
  as playing the game. `subscribe --item N ... [--wait SECONDS] --apply` subscribes, asks for each download at once, and with
  `--wait` says how far Steam is until every item is installed; its answer names the mod each number installed. `unsubscribe --list
  KEY --item N ... --apply` first switches those mods off (after a backup, refused while the game or RimSort runs), then
  unsubscribes, after which Steam deletes their files. Whether each worked is read back from Steam's own item state. Not yet
  tested against a real Steam client: agents never subscribe on the owner's account, so the first real use is the owner's own press.
## [1.76.0] - 2026-11-22

Saved lists, step 4 of the mod manager (the owner, 22 Nov 2026: "Start step 4, saved lists"). The owner's choices on question
cards: lists from each save, RimSort's history and files as well as lists saved by name; loading shows the difference, then a yes;
mods not on this PC are left out, named with why, and offered in Steam; a copy kept at each game start.

### Added

- **mod-list lists, compare and load** (`mod_lists.py`): every list on offer, by source: **saved** by name, **kept** at game
  starts, each **save**'s own record of its mods (RimWorld: the `.rws` header, read no further than `</meta>`; saves are never
  changed) and a mod manager's **history** (RimWorld: RimSort's, read where it keeps it), or a **file** (`--file`: the game's own
  `.rml`, a save, an exported RimSort list or RimSort's JSON). `compare` says what loading one would switch on, switch off and
  move, and which mods it names are not on this PC, each with why; `load --apply` writes the rest after a backup, refused while
  the game or RimSort runs, and `undo` takes it back. 0.2 s for the owner's 46 saves and 100 RimSort lists.
- **mod-list save, forget and export**: keep the list as it stands by name (`--as NAME`, `--replace`), take a saved list away,
  and write any list as the game's own `.rml`, which the game's mod menu loads too.
- **A copy kept at each game start**: every read of the list (`check`, `mods`) keeps a copy of the list the game last started
  with when it differs from the last copy kept. RimWorld's start is its log's `Started:` line, else the time its Logs folder was
  last written; a list changed more than two minutes after the game last wrote its log is not what it started with, so nothing is
  kept. Kept copies are never deleted here. Project Zomboid has no start record yet, so it keeps none.

### Changed

- A save records a Steam number only for the game's expansions (Workshop mods get 0), so those are never taken for Workshop items;
  a missing mod a list cannot place says to look for it on the Workshop by its name.
- The RimWorld adapter's running check can be handed in (`adapter.running`), so tests never depend on the owner's game.
## [1.75.0] - 2026-11-22

A rule for every session: ask the owner to install a tool

### Added

- **Ask the owner to install a tool rather than work round its absence** (`rules/every-session.md`, "Tools the owner can install"; the
  owner, 22 Nov 2026: "I honestly don't mind installing more tools; just let me know!", then "add that as a rule"). Say what it is, what
  it gains and its licence; installing stays the owner's.

## [1.74.0] - 2026-11-22

The sorter's side of the mod manager (the owner, 22 Nov 2026: step 3, "our own sorter", and moving mods "more freely"). The
owner's choices on question cards: both sorts, chosen at the press; the owner's RimSort rules read as they are, plus new ones kept
here.

### Added

- **mod-list sort: the list sorted from every rule, each move explained** (`mod-list sort --name GAME --list KEY [--full]
  [--apply]`; `mod_sort.py`). Rules from each mod's own files, from what mods need, from the community rules a game's managers
  share (RimWorld: RimSort's Community Rules database, read where RimSort keeps it, never copied) and from the owner's own rules.
  **The fewest moves** keeps the list's order and moves only what a rule says is out of place, trying a forward and a backward pass
  and keeping whichever moves fewer; **`--full`** rebuilds the order, the game's own first and then by name where no rule decides.
  "Load at the top" never goes above the game's own. **A loop of rules is not a refusal**: its weakest rule (community, then needs,
  then a mod's own, then yours) is set aside and named. Each move says from where to where and why, with whose rule. Written with
  `--apply` after a backup, like every change, and taken back by `undo`. 0.2 s on the owner's 378 active mods, where it finds
  2 moves on a list RimSort sorted: two "load at the top" rules RimSort reads more loosely.
- **mod-list rules**: the owner's own load-order rules kept here (`rules.json` in the game's mod-list folder; `--mod ID --after
  OTHER`, `--before`, `--top`, `--bottom`, `--drop N`, each only with `--apply`), the owner's RimSort rules read as they are, and
  every rule set the sorter reads, with where it is. The RimWorld adapter's `rule_sets()` reads RimSort's files (variable
  `PHOBOS_RIMSORT` names another folder).
- **Several mods at once**: `fix` takes `--move`, `--enable` and `--remove` more than once; moved or switched on together, they go
  to `--to` as one block, in the order the list had them.
## [1.73.0] - 2026-11-22

The list editor's side of the mod manager (the owner, 22 Nov 2026: switching mods on and off and moving them in D'thorga
Companion, each change saved at once).

### Added

- **mod-list mods**: every mod on this PC (key, name, source, Workshop number, authors, versions, needs) and each list's entries
  in order, joined by the key the game compares, with how many changes each list can still go back on. 1.2 s on the owner's
  RimWorld (407 mods).
- **mod-list fix --move ID --to PLACE** moves a mod to a place (1 is first), and **--enable ID --to PLACE** switches one on there.
  Every change now answers with the list as it then stands (`ids`, `keys`).

### Changed

- **undo walks back one change at a time**: each undo marks the change it went back on (`undone` in its record), so pressing it
  again goes back on the one before. Before, a second undo went back on the same change again.
- **Moving and switching off no longer read every mod's files**: only switching on needs to know what is on this PC.
- The RimWorld adapter reads ModsConfig.xml afresh each time a list is asked for, so an undo answers with the list as restored.

## [1.72.0] - 2026-11-22

The first step of D'thorga Companion's own mod manager (the owner, 22 Nov 2026: "We actually should have our own, third-party, mod
managing", after RimSort said only "1 missing mod" for a patch whose author had taken it off the Workshop, without naming it).

### Added

- **mod-list: what is wrong with a game's list of active mods, and why** (`python -m phobos_modkit mod-list check --name GAME
  [--online]`; `docs/mod-list.md`). Missing mods with the likeliest reason they went (taken off the Workshop, no longer subscribed,
  a download not finished, a local folder gone, never seen here), who needs them, and a clue when one of the mods a missing patch
  joined now names the other in its own files; needs switched off or not on this PC; order and clashes as the game itself reads
  them; a mod listed twice; early warnings (a mod the Workshop no longer has, or Steam no longer keeps for you); and mods that do
  not say they work with this game version. **RimWorld** (ModsConfig.xml, the 1.7 game's own rules: a version list replaces the
  plain one, force rules count, needs are not order rules) and **Project Zomboid** (mods/default.txt and each save's mods.txt;
  mod.info by version folder); any other game is told in words that it is not read yet. Checked on the owner's RimWorld (407 mods,
  1.5 s, 9 s with Steam) and Project Zomboid lists (the game not installed: its Workshop mods are counted as "could not be looked
  for", never as missing).
- **mod-list fix, undo and backups**: one change at a time (`--remove`, `--remove-extra`, `--enable`), only with `--apply`, each
  after a byte-for-byte backup of the list; refused while the game or RimSort runs. `undo` refuses when something else changed
  the list since. Both writers give back the owner's real files byte for byte when nothing changes. Recorded in the history log.
- **The check's memory of every mod it has seen**, so a mod is still known after its files go. Backups and memory live in
  D'thorga Companion's folder (new setting `modListPath`, `PHOBOS_MOD_LIST`); nothing deletes either.
- The manifest's `surface` gains `mod-list`.

## [1.71.0] - 2026-11-22

Safe copies for every game (the owner, 22 Nov 2026: "we should be trying to genericize as much as possible too so whatever is
achievable can work across as many individual games and their mods from the get go, or with lesser follow-up at the very least").

### Added

- **rules: every game from the start** (`every-session.md`; the owner's words of 22 Nov 2026, above): a tool, check or Companion
  page is written game-free and what one game needs is data; what cannot be generic yet says what a next game would need.
- **rules/safe-copies.md: what cannot be made again** (the owner's yes of 22 Nov 2026): listed in the same commit as the work that
  first makes it; a game's own files listed once, for the game, so a new game adds two small things and nothing in its mod
  repositories; each kind said truthfully, the narrower when unsure; the numbers and every removal the owner's.
- **safe-copies: a game's own list, kept by any repository** (`config/safe-copies/<game>.json`, read with `--game`). A game's
  saves and settings are the game's, not one mod repository's, so a new game needs one file. This kit keeps the owner's:
  **RimWorld's** saves, Config folder and RimSort lists, moved here from phobos-rimworld with the same set names so their copies
  stay as they are, and, new, **Ostranauts'** saves and settings, **Kenshi's** saves and **Project Zomboid's** saves and settings.
  Their numbers follow the owner's RimWorld choices (the newest two saves, autosaves left out, five earlier copies, K: only), an
  agent default each list says it is.
- **safe-copies: a save that is a folder** is copied, kept and let go whole: `units` with `newest` takes the newest folders, each
  dated by its newest file, `unitExclude` leaves autosave folders out by name, and `status` offers a save that left the rotation
  as one copy with its file count, never thousands of rows.
- **safe-copies: fresh files wait for the next run** when a run asks (`settle`, for the daily run in this version): a file written
  in the last two minutes is left, and a save that is a folder waits whole, so a game saving mid-run is never half copied.
- **safe-copies run-all: every list on the games list, in one run** (`--settle`, `--verify`): each repository's own list and every
  game's list it keeps, so a new game or repository joins by being on the owner's games list. A refused list or a missing
  repository is a row with its reason, and the rest still run; what it did is kept for D'thorga Companion
  (`safe-copies/last-run-all.json`). The games list is the new setting `companionGamesPath` (`PHOBOS_COMPANION_GAMES`, as the
  Companion reads it).
- **safe-copies schedule: the daily run** (the owner's word of 22 Nov 2026), one Windows scheduled task of the owner's own,
  "D'thorga Safe Copies": `--at HH:MM` sets or moves it, `--off` removes it, and on its own it says how it stands and how the
  last run went. Caught up at the next sign-in when the PC was off, never two at once, low priority, no window, no administrator.
- **Settings for where games keep the player's own files** (`game_folders.py`, one row per folder, each with its Windows
  default): `rimsortPath` (declared by phobos-rimworld until now), `ostranautsDataPath`, `kenshiDataPath`, `zomboidDataPath`.

### Fixed

- **safe-copies: a list speaks only for its own sets.** A run marked gone, and `status` offered to let go, every copy of its game
  it had not taken itself, so two lists of one game (Farming Simulator's or Project Zomboid's several repositories, or a game's
  saves kept apart from its art) would have taken each other's copies away. Each copy now records which list made it (`from`;
  one recorded before learns it at the next run), a list speaks only for the sets it names, and two lists naming the same set of
  one game are refused, with both names, until one is renamed.

## [1.70.2] - 2026-11-22

### Fixed

- **Two runs starting together after a kit update build a C# tool once.** Both found the heap reader (or the assembly reader)
  built by the last version and ran `dotnet build` into the same folder at once, and one failed on a file the other held; the
  gate's two Python lanes did so after each version change. The build now takes a lock beside the tool's folder, and a run
  that waited finds the tool built and goes on. The heap-reader test builds its made-up program under the same lock.

### Changed

- **One lock file for the whole kit** (`file_lock.py`): the claims board and safe copies' destinations each had their own copy
  of the same loop; both now hold the shared one, with the same waits and the same words when busy.

## [1.70.1] - 2026-11-22

### Fixed

- **safe-copies restore brings back one file a set lists on its own**, such as one installed style model, when the unit names it
  as status does. It looked only for a folder of that name, so D'thorga Companion's Restore on a model's row found nothing.

## [1.70.0] - 2026-11-22

The owner's word for reports to other authors (22 Nov 2026).

### Added

- **rules/reports.md: how a fault in another author's work is reported, in every game** (owner, 22 Nov 2026: "We'll make this
  the handling of issue reports to all third-party authors, moving forward", after Vehicle Framework's issue #390). Find it with
  the tools and look for an existing report first; a plain draft in the owner's private tracker, ready to paste (the title apart,
  code in fenced blocks, angle brackets in backticks); the owner posts; check how it shows, then mark it posted everywhere.
  Listed in the rules index and in every-session.md's table of files to read before some kinds of work.

## [1.69.0] - 2026-11-22

The owner's go for the safe copies' follow-ups (22 Nov 2026).

### Added

- **safe-copies status says when the repository's copy holds commits not sent yet** (`unsent`), and keeps saying so until a run
  sends them; before this, a failed push was said only once, by the run it failed in.
- **safe-copies status lists copies of files the list no longer takes** (`keptOnly`): a file gone from its source, or a save that
  left the newest pair, each with its size and its earlier copies'.
- **safe-copies let-go removes them, on request**: one named with `--file`, or `--all`; a preview unless `--apply`. It removes the
  copy, its earlier copies and its record from the plain folder only, and refuses any copy the list still takes.

### Changed

- AGENTS.md: let-go joins what safe copies may remove, each copy named and only with --apply.

## [1.68.0] - 2026-11-22

The owner's go for safe copies of their RimWorld saves (22 Nov 2026): the newest pair of their rotation, five earlier versions of
each, on a private, local folder only. Corruption has taken their saves before, and the game's folder is not synced.

### Added

- **safe-copies: `newest`**, for a set that takes only the newest few files it matches, by when each was last written (a save
  rotation). A file that falls out of them keeps its copies and is never called gone.
- **safe-copies: `keepEarlier`**, the first thing the tool lets go, by the owner's word: a set keeps that many earlier copies of
  each file in the plain folder, and the oldest beyond them are deleted from the destination's own `_safe-copies/earlier`, each
  named in the run's record and its report. Nothing at a source, no copy in use, and nothing of a set without it.

### Changed

- AGENTS.md, the README and the guide say exactly what may now go, in place of "never deletes".

## [1.67.0] - 2026-11-22

The owner's go for the next step of safe copies (22 Nov 2026): the notes Claude Code keeps about them, and their game settings,
copied to a private, local folder only.

### Added

- **safe-copies: a personal kind**, for the owner's own files that stay private: notes about them, a game's settings. It follows
  the game-derived rule: a folder marked private and local only, never a repository, and never a folder that looks synced.
- **This repository's own list, config/safe-copies.json**: Claude Code's notes about the owner from every project
  (`projects/*/memory`) and their global instructions (`CLAUDE.md`), personal, under the game id `tools`.
- **A set's root falls back to the default the kit knows for its setting**, so RimWorld's Config folder and the new
  claudeHomePath (CLAUDE_CONFIG_DIR, default `~/.claude`) need no value set by hand.

### Changed

- **The walk skips folders the list could never take a file from**: a list taking `projects/*/memory/**` from Claude Code's folder
  no longer reads its transcripts, logs and caches, and no longer notes their links. phobos-rimworld's plan went from about a
  second to under one, with the same 1,587 files.

## [1.66.0] - 2026-11-21

The owner asked for copies of "our training sets, models, etc." (21 Nov 2026), after the first style model of our own art took
158 minutes of the graphics card to train, and chose the name, the places and the rules for files made from a game's own.

### Added

- **safe-copies: copies of what cannot be made again, kept apart by kind** (docs/safe-copies.md). A repository lists its sets in
  config/safe-copies.json; `plan` says what a run would copy and where each kind may go, `run` copies what changed, `status` says
  what is copied, changed since or never copied, `verify` hashes every copy again, `restore` copies a set back into a folder the
  owner names, and `mark` marks a destination on the owner's word. Nothing is ever deleted, at the source or in a copy.
- **Files made from a game's own never reach a shared place.** They go only to a plain folder marked private and local, which is
  refused when it looks synced (a Synology, OneDrive or Dropbox folder, or a git clone, there or above), and never to a repository.
- **A training is ours only when proven**: every picture listed by hash in its manifest, beside its marker. One unlisted picture
  makes the whole training game-derived; a model follows the training it was made from, and a model no training explains is
  game-derived. Checkpoints and resume files stay in the plain folder only.
- **The repository's copy is committed and pushed after each run**; a quiet run makes no commit, and a failed push is reported and
  sent with the next run. Every run records what rebuilds its copies (each tool's commit, a file's hash) and adds a line to the
  history log.
- Settings safeCopiesPath and safeCopiesRepositoryPath (the Settings page lists them).
- AGENTS.md: safe copies join the list of tools that write, and what they may write where.

## [1.65.1] - 2026-11-21

A program reading look-serve reads one JSON line first; with the game not running it got the error as Markdown instead.

### Fixed

- rimworld-perf look-serve says that the game is not running, or that no snapshot could be taken, in its first line's own shape
  ({"ready": false, "error": ...}), as it already did for a refused snapshot.

## [1.65.0] - 2026-11-21

The owner asked for debugging tools in D'thorga Companion that attach to a game and show "variables in memory" and the
relationships between things, and chose looking inside a snapshot of the running game first (20 Nov 2026).

### Added

- **The heap reader looks inside a running .NET game** (docs/heap-reader.md): a Windows snapshot, a pause of about half a second
  (431 to 470 ms on the owner's colony), then every object by type, one kind's objects each described, any object with every value
  it holds (enums by name, structs opened, lists and dictionaries as their items), what holds it, and paths from a root that say
  why it is still in memory, or that nothing holds it. No limit on objects: 27.4 million read in 17.6 s. Read-only.
- dotnet/PhobosModKit.Heap, the reader, on Microsoft's ClrMD 4.2.751201 (MIT): the kit's one C# package, by the owner's yes.
  It loads only the memory-reading library beside the running program's own coreclr.dll in the install the caller names;
  RimWorld 1.7's (Waylith) is not signed by Microsoft, so that folder check stands in for the signature check.
- heap_reader: run_requests for a command line (one snapshot, then let go), Session for a program (held, at most ten minutes, the
  owner's choice), and the reports.
- rimworld-perf look (every object by type and by mod, kept beside the gcdump heaps so heap-report and heap-compare read it),
  look-kind (with --open, --match, --largest), look-why, and look-serve, which holds a snapshot and answers one JSON request a
  line for D'thorga Companion; manifest surface look-inside.
- programs lists the heap reader, and bundle carries it ready-built in heap/.

### Changed

- dotnet_tools: how the kit's C# tools are built, published and found, once; the assembly reader uses it, with the same names
  as before.
- A heap report from a snapshot says what a snapshot is: no collection forced, garbage included, how long the game paused, the
  free space; it no longer points to a gcdump file it does not have.
- AGENTS.md: two written exceptions, the owner's of 20 Nov 2026: ClrMD as the one C# package, and loading a game's own
  memory-reading library (never a mod's file); reading a game's memory is reading, asked for before every snapshot.

### First real use

- On the owner's colony, 453 MB of XML (9.8 million objects, 10,499 documents) was live: every mod's patch list, which the game
  clears after loading, read again by Vanilla Expanded Framework's settings code, so the game loads every patch file again and
  keeps it. Recorded in phobos-rimworld.

## [1.64.0] - 2026-11-20

### Changed

- **Going back to a backup removes the mod's repeated backups** (the owner, 20 Nov 2026: removing them "should be part of the
  normal process of install/updating mods"). installs restore runs the same removal as dedupe, both kinds, for the mod it moved,
  keeping the oldest of each run, and says which it removed; its data adds removedRepeats and tidyProblem. A failure there is
  reported and the go-back still stands.

### Added

- installs.tidy and installs.tidy_lines: the removal for a repository's own install command to run after an install, never
  raising, with its lines for a person. phobos-rimworld's deploy.py runs it (docs/installs.md).

## [1.63.0] - 2026-11-20

### Changed

- rules/designs.md gains a second rule, the owner's for every mod and game (20 Nov 2026): a behaviour that puts the player's
  things or people at risk has its own setting to switch it off, on by default unless its risk is high or higher, then off; the
  design record grades the risk and says why. A new rule raises the middle number.

## [1.62.0] - 2026-11-20

For D'thorga Companion's release audit (the owner, 20 November 2026: the Companion is to be released for others): A4, ship the
kit's compiled tools built, and B7, each tool says what it needs.

### Added

- programs status: every other program the tools use (git, the kit's XML indexer and assembly reader, .NET 10, Microsoft's
  diagnostics tools, ilspycmd, Steam, and a game's own through its adapter: RimSort's todds for RimWorld), whether each is on this
  PC and how it was found, what needs it, and where to get it. It only looks, and runs none of them (docs/programs.md).
- programs bundle --out FOLDER: builds the XML indexer and the assembly reader (published to need only the .NET 10 runtime) and
  copies them into one folder, stamped last with bundle.json, for an installer to carry.

### Changed

- The XML indexer and the assembly reader are found ready-built first, in PHOBOS_MODKIT_TOOLS or a tools folder beside the kit's
  package folder, before any build: a PC that installs them needs neither Rust nor the .NET SDK.

## [1.61.1] - 2026-11-20

### Fixed

- rimworld-update-check's manifest gives it the update-check surface, so D'thorga Companion finds it by role, and calls its effect
  runs (it decompiles new builds with ilspycmd, as rimworld-archive compare does), so a program runs it on a person's press. It no
  longer offers a question of its own: it needs a repository, which a page of reports does not give.

## [1.61.0] - 2026-11-20

For D'thorga Companion's Since you last played: the checks an agent ran by hand after the updates of 18-20 November 2026 (the
owner's request, by question card: "All four").

### Added

- rimworld-update-check: the game or mods updated; what does it mean for ours? One run, four parts: whether every member our C#
  names still exists (rimworld-targets' check), whether an update touched the members a temporary patch's fault lives in
  (the repository's config/temporary-patches.json), how big each kept update was with the new types it brought, and whether our
  XML patches still find their Defs and, for a simple xpath, the node inside, as written, then in the patched-Defs file. The
  repository says what is ours in config/update-check.json. On the owner's game it found every one of 622 targets and 371 Def
  names, and flagged VFE Factory's belt tick for row 12 (docs/rimworld-update-check.md).

### Changed

- rimworld-targets' check is a function (targets_cli.check) the new command shares; its report is unchanged.

## [1.60.0] - 2026-11-20

A shared rule for licences (the owner's decisions of 20 November 2026, by question card).

### Added

- rules/licences.md: code, data and documents stay MIT; our own art and sound are CC BY 4.0, credited to House D'thorga; the names
  D'thorga and House D'thorga, the mods' and tools' names and their preview images are kept out of both grants, so a fork or
  reupload uses its own name. It gives the two paragraphs every repository's LICENSE adds, read before writing a LICENSE, starting
  a repository or preparing a mod's first public page.

### Changed

- This repository's LICENSE carries the two paragraphs. Nothing it granted before is withdrawn.

## [1.59.0] - 2026-11-20

For D'thorga Companion's screenshot gallery on the Timeline (docs/later.md, item 5, agreed by the owner on 19 November 2026).

### Added

- game-files screenshots: only one game's screenshots, from the same folders the report reads (its own and Steam's), up to 2,000
  newest first with the counts covering all. It does not size the data folder or the saves, so it answers at once (0.3 s for the
  owner's 330 RimWorld screenshots).

## [1.58.0] - 2026-11-20

For D'thorga Companion's Add a game from Steam (docs/later.md, item 5, agreed by the owner on 19 November 2026; built overnight on
their go-ahead of 20 November).

### Added

- game-files steam-games gives each game up to three candidates for its data folder (dataGuesses: path, score, reason), surest
  first, read in one look at the usual homes.

### Fixed

- The data folder is found where Windows keeps Documents (the owner's is moved into SynologyDrive, so Documents\My Games was never
  looked in), or PHOBOS_DOCUMENTS. Names that differ the way games' folders do now match: FarmingSimulator2025 for Farming
  Simulator 25, Zomboid for Project Zomboid, AutomationGame for Automation. A folder for the game's mods or backups ranks below the
  game's own, and mod managers' copies (Vortex) are not looked inside.
- Looking for a data folder takes 0.4 s instead of 15 s on the owner's PC: folders are read with os.scandir, and temporary files
  are not looked inside.

## [1.57.1] - 2026-11-20

The owner, on D'thorga Companion's code viewer (20 November 2026): "It doesn't seem to be showing the full extent of the code
that was/is involved? I've had this feeling for sometime now." For an entry not yet committed it showed 25 files and 104 lines
of D'thorga Farming's first build, which was 113 files and 5,432 lines.

### Fixed

- changes entry, for an entry in no commit yet, now shows every new file git has not been told of, added whole, beside the edits
  to files it tracks. They were left out, and a new feature is mostly new files. Files .gitignore leaves out are skipped; a new
  file over 2 MB, or with a NUL byte near its start, is listed as binary.

## [1.57.0] - 2026-11-20

The owner (20 November 2026): the Waylith fix in 1.54.0 is truly effective only once D'thorga Companion's own install and encode steps
carry it. Its install runs the repository's deploy, and its encode runs this kit, but its texture check read names and dates only, so a
mod whose textures Waylith unpacks looked in step and was never offered encoding. A first check of the owner's 358 active mods found
4,770 such textures in 116 mods, about 7.75 GiB of what Graphics Settings' profiler counts.

### Added

- rimworld-textures status counts, for each mod, the encoded textures Waylith unpacks that encode would shorten (unpacked, unpackedPaths;
  totals unpackedMods and unpacked), in their own section and in the title. Those left whole are not counted, since encode cannot help.
- Each .dds header is read once and its verdict remembered in the kit's cache (rimworld-textures/dds-headers.sqlite) by path, size and
  date; only new or changed files are read again, and the file is rewritten only when something changed. The JSON says how many were
  read this run (headersReadNow). On the owner's PC the first run took about 9 seconds, later ones about 0.3 seconds more than before.
- textures.HeaderCache and textures.classify; check_folder takes headers to count them.

### Compatibility and limits

- A mod with only unpacked textures now counts as needing encoding (Freshness.needs_encoding), so a program offering encode from it
  offers it for those mods too.

## [1.56.0] - 2026-11-20

A new shared rule, at the owner's word (20 November 2026): a new behaviour in any game or mod says what outside the thing itself
notices it. A review of the RimWorld vehicles had found them detailed within each vehicle, with almost nothing reaching the rest
of the game.

### Added

- rules/designs.md, read before designing or building a new behaviour: the three questions every new behaviour answers (what it
  lets the player do, what it stops them doing, how it changes the way they do things; the owner's rule of 8 November 2026, moved
  here from phobos-rimworld so the four stand together) and the new fourth (what outside the thing itself notices; nothing is
  allowed as a stated choice, never by accident). every-session.md's table and the rules index name it.

## [1.55.0] - 2026-11-20

For D'thorga Companion's automatic records backup (the owner, 20 November 2026: "every few hours when it's open, and if the
schedule is missed, the soonest next opportunity should then arise"). The owner had found backups not working: no folder had
ever been saved, and nothing ran by itself.

### Added

- records status --every-hours N adds due (a folder is chosen, and there is no copy yet or the newest is N hours old or more)
  and everyHours; every status adds ageHours. records backup --automatic marks the copy as made by the Companion's own timer, in
  its backup.json and in each copy status lists.

### Fixed

- A backup folder that cannot be reached or written to (a drive not there, a NAS asleep) is refused in words, copying nothing and
  leaving no partial folder, instead of stopping with Python's own error.

## [1.54.0] - 2026-11-20

The owner asked (20 November 2026) why D'thorga Vehicles held 2.0 GB of textures in Graphics Settings' memory profiler, more than
mods with larger art. The game was running on Waylith, which unpacks a compressed texture to plain pixels, at four times the memory,
when any mip level four or more pixels tall has a height that is not a multiple of four: 255 of the mod's 459 textures, 1.9 of its
2.0 GiB. The owner chose to shorten the mip chains when encoding.

### Added

- rimworld-textures encode shortens the mip chain of every .dds in the named mods that Waylith would unpack, those todds left alone
  included: the chain is cut just before the first such level, the header's mip count lowered and the smaller levels dropped; the
  full-size picture is untouched. A texture that would keep fewer than four levels is left whole (agent default: it would shimmer when
  zoomed out). Only block-compressed 2D files whose size the header fully explains are changed. The report and its JSON give, for each
  mod, mip chains shortened, left whole and any that could not be written; a failure to write one makes the run fail.
- textures.trim_folder, trim_mips, read_layout and kept_mips, for phobos-rimworld's deploy to use after its own todds run.

### Compatibility and limits

- Not yet seen in game. Predicted from the installed files: D'thorga Vehicles from 2.0 to about 0.6 GiB in the profiler, with the
  Osprey's 24 nacelle frames (heights 654 to 1156) still unpacked. Unity's own loader reads a shorter chain as it reads any other.

## [1.53.0] - 2026-11-20

The owner's screen note on D'thorga Companion's Mods page (20 November 2026): "Why is it showing me as taking away nine
entries?" Two sessions had both numbered their work Framework 0.184.0; the one installed was renumbered, and its nine entries
read as a loss though their code was still in the repository.

### Added

- installs status sets aside, from what installing from the repository would lose, the entries a changelog cannot call lost:
  a version number used twice (both copies have it, with no entry in common) and uncommitted work the repository's changelog
  does not hold now (the install record says the copy was built with uncommitted changes, under a version newer than any in the
  repository). The update's JSON adds unlisted and unlistedWhy (reused or uncommitted, by version); the state is unlisted when
  nothing else differs, and the Markdown says why for each version. An entry dropped from a version both share, and any move to
  a backup, is still a loss.

## [1.52.0] - 2026-11-20

The owner asked (20 November 2026) for one command to read what a vehicle has saved, after a fault on a dirt bike could be
traced only by reading the save by hand: the index held each thing's def, place and health, but none of what its comps
wrote.

### Added

- rimworld-save thing ID: one thing's saved data in full, every value its comps and mods wrote with its path inside the
  thing, dictionaries paired as name[key], list items numbered. The things it holds are listed and left out unless --held;
  --path and --value narrow it. It reads only that thing's bytes from the save (a 200 KB vehicle in a 340 MB save in a
  moment), and refuses once the save has been saved again since it was indexed.
- xml-index: a column may hold an element's byte offsets in the input (offset = "start" or "end"); a UTF-8 byte-order
  mark is counted, as RimWorld's saves begin with one. The save schema records them for every thing, so older indexes
  are rebuilt on their next use.

## [1.51.0] - 2026-11-20

For D'thorga Companion's "Since you last played" line on the Mods page (the owner's go-ahead, 20 November 2026): what updated since the session before, and whether those updates changed a method our mods patch.

### Added

- game-files report --since previous: the launch before the last. Steam records only the latest launch, so while a game runs "since you last played" meant since this launch; each report now remembers the launch it sees in the kit's cache (the newest 30 per game), and until it has seen an earlier one it uses the last and says so. The report's changed part adds sincePrevious, previousLaunchAt and launchesSeen.
- rimworld-patches targets --updates gives each change's newestKept: when the assembly archive first kept the newer build, as an ISO time, so a program can tell an update since the last launch from an older one.
- rimworld-archive snapshot carries the manifest surface updates, so a program can offer to keep new builds before comparing them.

## [1.50.0] - 2026-11-20

The owner asked (20 November 2026) for an ongoing cleanup in D'thorga Companion, with their yes before anything goes; the listing found 33.7 GB, 29 GB of it the kit's development build, beside install backups they may want to keep.

### Added

- cleanup --group, repeatable: only the groups named are listed or deleted, so a program can let its user keep some, such as install backups. The git file-watcher daemons are a group of their own then, stopped only when named.
- cleanup's JSON gives each group's items, bytes and reason (data.groups) and how many git file-watcher daemons run (data.daemons).

## [1.49.0] - 2026-11-19

The owner chose (19 November 2026) that D'thorga Companion should read and compare other authors' code on their press: follow one of our patches into the method it patches, and see what an update changed. The tools could already do both from a console, but only phobos-rimworld's own script knew where the source clones and decompiles were kept.

### Added

- rimworld-code show: a type's or member's source from the best copy kept, public clones first, then the repository's own decompiles, then the kit's. Each line comes with its own number, and the decompiler's IL notes are left out. The first search indexes every place once (about four minutes on the owner's machine), then answers in under a second.
- rimworld-code holder: which of the game's and active mods' assemblies declares a type, and which mod ships it, read through metadata alone (about five seconds).
- rimworld-code decompile: decompiles one assembly into the kit's cache on request, once per build, shared with code compare and rimworld-upstream.
- rimworld-archive list gives each kept file as data (owner, versions kept, the newest and the one before), so a program can offer a comparison wherever there are two.
- Manifest surfaces other-code (rimworld-code's three reports) and updates (rimworld-archive list and compare).

## [1.48.0] - 2026-11-19

The owner found the top of D'thorga Companion's atlas cluttered (19 November 2026): every save report opened with one long sentence naming the save, how it was read and a count of every kind of element in it, and the atlas added another for the world seed.

### Added

- A report may carry facts: short labelled values saying where it came from, such as the save it read. JSON gives them as a list of label and value under report.facts (an empty list when a report has none); Markdown prints them as one line before the opening. Redaction reaches them as it does every other text.

### Changed

- **rimworld-save reports open with facts instead of the "Index of" sentence**: Save, Read (now, from a frozen copy, in how many seconds; or from the index already built) and, when built just now, how many elements the index holds. The count of each kind of element moved to the JSON data, as elements.
- The atlas gives the world seed and the number of surface tiles as facts; its note on how tile positions are worked out stays as the opening line.

## [1.47.0] - 2026-11-19

The owner chose (19 November 2026) to run memory profiling from D'thorga Companion rather than through agents, and two reloads asked for during watches never reached the log; a program could not stop a watch, follow it, or put the owner's intentions beside its figures.

### Added

- rimworld-perf watch-status: a running or kept watch as it stands, in about 0.2 s, light enough for a program to read every few seconds: its state (running, finishing, ended, or cut off when its watcher stopped without finishing), the latest figures, the timeline so far, the marks and the watches kept. .NET's figures come from dotnet-counters' own file as far as it has been written.
- rimworld-perf watch-stop ends a running watch early from another console or a program: it writes a stop file the watch looks for every second, and the watch then stops dotnet-counters too and writes its report as usual.
- rimworld-perf watch-mark puts your own words beside a watch's figures ("reloading now"), now or at a moment up to a minute either side of it.
- The manifest surface memory-watch on watch, watch-report, watch-status, watch-stop and watch-mark, so a program finds them without naming the game.

### Changed

- **A watch's report says what happened before any figure**: the saves the log shows loaded, or in bold that none was; your marks; the errors logged; and, in bold, a mark naming a load or reload that no save loading followed within 3 minutes. The jumps table names your marks beside the log's events.
- rimworld-perf's --json answers a failure (the game not running, a watch not found) with ok false and the reason in data, as every other tool refuses, so a program can say it in words.
- watch-report with no name reads the watch still running, if one is, before a newer one; a report of a running watch says so instead of "it ended because".

## [1.46.0] - 2026-11-19

The owner asked (19 November 2026) what the games themselves write that D'thorga Companion could show, made general so a new game needs little setting up, and said yes to the views proposed.

### Added

- game-files report, for any Steam game: what changed since you last played (the build, and every Workshop item Steam updated since its last launch, named from the item's own files where they name it), the saves newest first with autosaves marked, the screenshots (the game's own and Steam's), and where the data folder's space goes beside the install's and the Workshop's. About a second for RimWorld. Checked on RimWorld, Farming Simulator 25 and Project Zomboid.
- game-files steam-games: every game Steam has installed, from its library records.
- steamPath (PHOBOS_STEAM), Steam's own folder, listed with every other setting.

### Fixed

- claims could lose a claim when many sessions took one at once on Windows (seen once in a gate run, 11 of 12): Windows can answer a lock being let go, or a file a virus scanner holds for a moment, with a refusal rather than "busy", and the claim was dropped. Those are now waited out. The cause is likely but was not reproduced; the test now runs 24 sessions at once and names any error.
## [1.45.1] - 2026-11-19

The first memory watch with the runtime's counters (19 November 2026) showed the .NET heap labelled wrongly: its size counts the gaps between objects.

### Fixed

- rimworld-perf watch called the runtime's whole heap "live". Its size counts the gaps between objects too (Microsoft's runtime metrics reference), so the report now shows the heap with its gaps, then live objects and gaps apart, and its closing line says how .NET's share splits.
- rimworld-perf heap compares its snapshot with the runtime's live objects (the heap less its gaps), since a snapshot lists objects only; it had compared with the heap and gaps together, so a snapshot looked more partial than it was.
## [1.45.0] - 2026-11-19

The owner said yes (19 November 2026) to a Decisions page in D'thorga Companion, gathering the choices agents made for them to revise.

### Added

- decisions list: each repository's open questions from its config/decisions.json, with their options, the agent's lean and why, open ones first, and the owner's answer where given.
- decisions answer records the owner's answer (an option, or other with words), one line appended to a file per repository in the Companion's folder; the last answer decides. Agents act on an answer and remove the decision from the config in the same commit.
- companionDecisionsPath (PHOBOS_DECISIONS), the folder for those answers, listed with every other setting.
## [1.44.0] - 2026-11-19

The owner said yes (19 November 2026) to a claims board, so agent sessions sharing the machine stop asking each other in messages which version number is free.

### Added

- claims list, take and release: one board where a session holds a version number, a test row or a file, refused while another session holds the same thing (compared ignoring case and spacing). A claim over a day old is shown as old, and --force takes it over. Changes hold a lock file and write the board whole, so sessions taking at once lose nothing.
- claimsPath (PHOBOS_CLAIMS), the board's file, listed with every other setting.
- A shared rule in rules/every-session.md: take a claim before using anything another session may want, release it once committed, and ask a claim's holder rather than pick around it.

### Fixed

- records backup and screen-notes resolve and reopen now answer a refusal in JSON (ok false, with the reason) when asked for JSON, as every other command does, instead of plain text a program could not read.
## [1.43.0] - 2026-11-19

The owner said yes (19 November 2026) to backing up D'thorga Companion's own records, which sit in a folder their NAS does not back up.

### Added

- records status: what would be copied (everything in the Companion's folder but the window's browser cache, and any record a setting keeps elsewhere), the backup folder, the copies already there, and whether the newest is at least a week old.
- records backup copies them into a new folder named for the local time, written whole, with a backup.json saying what it holds. It never deletes.
- recordsBackupPath (PHOBOS_RECORDS_BACKUP), the folder the copies go into, listed with every other setting.
## [1.42.0] - 2026-11-19

The owner asked (19 November 2026) to take memory profiles of the running game and see where it goes, after RimWorld's use climbed from about 12.5 GB to 17.5 GB and more.

### Added

- rimworld-perf watch: the game's memory over minutes or hours without pausing it. Every few seconds, what it claimed and what is in RAM (Windows' own figures), and .NET's heap and collector (dotnet-counters, attached once; --no-counters leaves them out); every minute, the memory map by kind, block and block size, and code and mapped files by name. Ctrl+C, the game closing or the time running out ends it, keeping everything.
- Its report says whether memory held steady, climbed in jumps or climbed steadily; the start, end, lowest, average and highest of each figure; .NET's share and the rest; the largest jumps with the saves loaded and errors logged around each; the figures over time as a chart; and which blocks grew, naming the one that is .NET's heap. watch-report shows a kept watch again; list shows them.
- process_memory: a program's memory figures and memory map, read from outside on Windows (figures on Linux too); nothing in the program is read or paused.

### Fixed

- rimworld-perf heap no longer presents a partial snapshot as the whole heap. dotnet-gcdump stopped at 10,000,003 objects and 667 MB on a heap the runtime had counted at 6 GB and more; heap now reads the runtime's own count straight after, and says in bold when the snapshot holds less than 90% of it. Older snapshots near ten million objects are flagged too.
- The heap report's shares are of what the tool listed, so they no longer add up to more than 100%. It also says how long taking the snapshot took, which is about how long the game was paused.
## [1.41.0] - 2026-11-19

The owner said yes (19 November 2026) to a "something's off" key in D'thorga Companion whose notes agent sessions read at the start.

### Added

- screen-notes list: what the owner flagged in the Companion, newest first, each with its page, address, words, the Companion's version and the path of its picture; --all adds the dealt-with ones.
- screen-notes resolve ID --how WORDS marks a note dealt with, writing resolved.json beside it; reopen undoes that. Nothing is ever deleted.
## [1.40.0] - 2026-11-19

The owner asked (19 November 2026) for repeated backups to be removable, for new settings to be followed alongside the timeline, and for paging further back in D'thorga Companion.

### Added

- installs status marks backups that repeat the one before them: identical (the same file for file) or rebuilt (the same version and files but the assemblies, with none of the mod's own sources changed between their commits). installs dedupe removes them, keeping the oldest of each run, after checking each again. Digests are kept in the cache, so only new backups are read.
- installs settings: every setting the repository's mods ever added, removed or gave a new default, newest first, from the repository's own settingsHistory command in installs.json.
- history timeline adds those settings changes as facts (setting-added, setting-removed, setting-default) on each mod's lane.
- changes list --versions 0 gives every version, and connections history --limit gives more than 25 commits (up to 500), so a program can page further back.
## [1.39.0] - 2026-11-19

The owner asked (19 November 2026) to show "how the contents of our mods, code, etc. is consisted of in a graphical manner", for D'thorga Companion.

### Added

- makeup now: every committed file by product (a changelog's folder; a C# project by its ModFolder), kind (code, tests, data, words, pictures, sounds, build, other), language, lines and size. 0.3 s for phobos-rimworld.
- makeup growth: the same totalled by kind and by product, one point a day since the first commit; each file version's lines are kept in the kit's cache, so a run reads only new versions (about 2 s for phobos-rimworld's whole history).
- makeup churn: the files commits changed lately, how often, lines added and removed, and when last.
- makeup census: each product's Defs by type, pictures, sounds and text keys.
## [1.38.0] - 2026-11-19

For D'thorga Companion's cross-links (19 November 2026, docs/cross-links.md there, S2): pins as installs.

### Added

- pins status: which version of this kit each repository pins (the commit its HEAD records), how many versions newer this kit is, and what moving the pin would bring, version by version, from this kit's changelog.

### Fixed

- The connections tests' .NET fixture no longer fails the gate now and then: the gate runs the tests under two Pythons at once, and the second build could find the first's DLL still open. It now waits and builds again.
## [1.37.1] - 2026-11-19

### Fixed

- The manifest marks rimworld-patches targets as a patch-targets reader (surface patch-targets), so a program can find it for any game whose tools have one without naming the game.
## [1.37.0] - 2026-11-19

For D'thorga Companion's cross-links (19 November 2026, docs/cross-links.md there, L5): risk where it sits.

### Added

- rimworld-patches targets: each method a repository's code patches (from its connections graph), with every other active mod patching the same method and how many of their patches may skip the original; with --updates, what the archive's newest update of that file changed in it (rimworld-upstream's comparison: new signature, new body or removed). About 5 s on the owner's list.
## [1.36.0] - 2026-11-19

For D'thorga Companion's cross-links (19 November 2026, docs/cross-links.md there, L3): test rows joined to code.

### Added

- test-pass code: where the code notes each test row's keys, as strings in C#, Lua or Python (a key built at run time by its prefix), each placed in the method, function or type that holds it, with the rows it stands for; and the keys no code writes as the map names them. Folders named tests are skipped.
## [1.35.0] - 2026-11-19

For D'thorga Companion's cross-links (19 November 2026, docs/cross-links.md there, L1): the game's log as a page, its stack lines leading to code.

### Added

- rimworld-log: each signature's JSON names its stack frames (method, source file and line where the log gives them, assembly), nearest the fault first; a message without an exception gives the stack that logged it.
- rimworld-log --brief: with --json, only the top signatures of the listed levels, without their line lists, and as many of each comparison list with counts for all: a page's worth (about 300 KB instead of 4 MB from a 200,000-line log).
- The manifest marks rimworld-log as a log reader (surface log), so a program can offer a log page for any game whose tools have one.
## [1.34.0] - 2026-11-19

For D'thorga Companion's cross-links (19 November 2026, docs/cross-links.md there, L2): a thing's own history.

### Added

- connections history: the commits that changed one thing's lines (a method, class, Def or function), newest first, followed back as the lines moved (git's line-range log), each with the changelog entries that commit wrote: why the thing changed. At most 25 commits, saying when there are more.
## [1.33.0] - 2026-11-19

The owner asked for it (19 November 2026): "flow-charts and the such which show relationships between functions, classes, etc. of the code I'm viewing", with exact C# from built code, for C#, XML Defs, Lua and Python, in D'thorga Companion's code viewer and a page of its own.

### Added

- connections: how a repository's code fits together, as one graph for every language: summary, find, around (everything one connection away, grouped: calls and called by, holds and belongs to, builds on, overrides, patches, uses, imports), flow (the calls a few steps each way) and changed (the things a commit's lines changed, read from each file as it stood). Every connection says whether it is exact. Kept in the kit's cache and read again when a file it came from changes: about 7 s the first time for phobos-rimworld or phobos-ostranauts, under a second after.
- The assembly reader reads which methods call which (calls): exact from an assembly's metadata and method bodies, across the game and other mods, with the calls a method's lambdas, local functions, iterators and async parts make counted as its own. C# connections come from it, placed in the source by the code scanner; where nothing is built, from the source by name.
- XML Defs (parents exact; Defs and C# classes used), Lua (by name: functions, calls, require) and Python (Python's own parser; calls by name).

### Changed

- The assembly reader's build and run helpers moved from the RimWorld adapter to a module of their own (assemblies), so a tool that is not RimWorld's can use them; rimworld-patches and rimworld-targets use them as before.
## [1.32.0] - 2026-11-19

For D'thorga Companion's shared-code audit (19 November 2026, docs/shared-code-audit.md there, X1): its Home page read changelogs with a parser of its own beside this kit's.

### Added

- changes pending: what each changelog has not released yet (entries with no version, and the newest Draft version with its date and how many older drafts), for one or more repositories in one run. It reads the files only, never git: about 0.35 s for three repositories, quick enough for a program's first page.

### Changed

- changes list reads each changelog it has just found straight from disk, instead of walking the repository again for each one: about 0.95 s instead of 1.65 s for phobos-rimworld.
## [1.31.0] - 2026-11-19

From the owner's first look at D'thorga Companion's Timeline (19 November 2026): "I'm unable to view the applicable changes to the code, as you can in normal views".

### Added

- history at gives each entry the commit that wrote it, as the changelog stood then (its first 12 characters, or null), so a program can offer the code behind any entry of an old changelog, as changes list does for today's.
- changes.entry_commits reads a changelog as it stood at a commit when given one (at).
## [1.30.0] - 2026-11-19

The owner asked for it (19 November 2026): "a timeline ... that records/shows how updates were applied, changed, removed, etc. over time ... I like coming back and reading the CHANGELOGs from a particular update-in-moment but I can't because it is now lost to time", with the history kept in D'thorga Companion's own folder and "a central settings page where everything or at least, most, of these sorts of things are managed".

### Added

- history timeline: every fact about a game's products over time, newest first. From git, back to each repository's first commit: a changelog started, a version written, released or removed, entries added, reworded or removed, a product renamed, a product ended and the product it was merged into. From this PC's history log: installed, went back, backed up, built, textures encoded. Facts from git are cached, so only new commits are read after the first time (about 4 s, then under a second, for phobos-rimworld).
- history at: any changelog as it stood at a commit or a moment, each entry marked kept, reworded (with its words now) or removed, and a count of what was added since. A removed changelog can still be read.
- The history log: one JSON line a fact, one file a game, in the history folder of D'thorga Companion's own folder (historyPath, PHOBOS_HISTORY). installs writes installed, backed up, went back and built; an install through a repository's deploy writes installed through the install record; rimworld-textures encode writes encoded. Recorded from 19 November 2026 on; earlier installs were not recovered (owner's choice).
- The central settings file: settings.json in D'thorga Companion's own folder (PHOBOS_SETTINGS names another), read after a repository's own settings file and before the default, for every path the tools read.
- settings list: every setting the tools read, its value, and whether it comes from the environment, a repository's own file, the central file or the default; a repository declares its own scripts' settings in config/settings.json. settings set writes one into the central file, or clears it.
- changes entry --commit: one commit's code with every entry it wrote, for a fact on the timeline.
- rules/first-class.md, a design for the owner to edit and not yet rules: the six properties that make a thing first-class (an identity not a label, an address, a history, the same shape in every game, one shape in tools and window, rules can be about it), eleven citizens with how far each is today, and principles such as "identity is origin and continuity, never the label". The timeline is built on the first five.
- rules list marks a file whose status says it is not yet rules as "a design to edit", and counts no rules in it.

### Changed

- paths.where says which layer a value comes from; paths.companion_data and changes.product_name moved to where every tool can use them.
- The tests point the history log and the central settings file into a folder of their own. Found while building it: two test runs had written stand-in installs into the owner's real history log; those lines were removed before anything else read them.
## [1.29.0] - 2026-11-19

The owner asked for it (19 November 2026), after D'thorga Companion read every mod as changed because .NET stamped the git commit into each assembly.

### Added

- A shared rule, in rules/builds.md: the same code builds to the same bytes, whatever the commit, the clock or the folder. Nothing that changes from build to build goes into what is built; the commit belongs in the install record, the changelog or the tag. For .NET, Deterministic and IncludeSourceRevisionInInformationalVersion set to false in Directory.Build.props, and how to check.
- rules/every-session.md says which file to read before which kind of work, starting with builds.md.

### Changed

- The kit's own .NET helpers follow the rule: dotnet/Directory.Build.props no longer lets the SDK stamp the commit.

## [1.28.0] - 2026-11-19

### Fixed

- An entry that many versions repeat word for word, such as "Not yet tested in game.", was given the commit that first ever wrote that line, in every version. Seen on the owner's Changes page the same day: 0.142.0 and 0.141.0 each split off their last entry into a group of its own. Each entry's commit now comes from git blame, by version and first line, with the history pass kept for entries no longer in the changelog.

## [1.27.0] - 2026-11-19

### Added

- installs status names, for a changed assembly that was not only rebuilt, the sources that changed since the installed commit (sources, up to five, and sourcesInAll). Found the same day: turning off .NET's commit stamp in phobos-rimworld's shared build file changed every mod's build inputs, so every assembly read as changed with nothing to say why; now each names Directory.Build.props.

## [1.26.0] - 2026-11-19

From the owner's look at the Companion's Mods page (19 November 2026): "It seems to see changes in DLLs, across the board, where there might not be any", and a tidier page with fewer repeated buttons.

### Added

- changes.entry_commits: every entry a changelog ever held, with the commit that first added its first line, from one pass over its history (about 0.4 s for seven changelogs). changes list and installs status give each entry its commit, so a program can offer one "show the code" for all the entries one commit wrote; changes entry takes its commit from the same pass, so both always agree.
- installs status marks a changed assembly as rebuilt when its project's own sources (its folder, its compiled includes, the shared build files) have not changed since the installed commit, committed or not, with no new source files. Found on the owner's PC: .NET stamps the current git commit into every assembly it builds, so every commit anywhere changed every rebuilt assembly by about 100 bytes. A rebuilt assembly still counts as a change.
- Two states for a mod whose changelogs agree but whose files differ: rebuilt (every changed file only rebuilt) and unlogged (something else changed that no entry describes). A mod in this case read as up to date before.

### Changed

- installs status says what it is doing while it matches entries to their commits.

## [1.25.1] - 2026-11-19

### Changed

- rules/README.md says to name the shared rules' path in backticks, never as a Markdown link: on GitHub a pinned kit's folder is a pointer to this repository, and a link into it leads nowhere. Found when phobos-rimworld's link check refused the first such link. No rule changed.

## [1.25.0] - 2026-11-19

Asked for by the owner (19 November 2026), on choosing how commits are cut for the Companion's code viewer: "a central point from which global rules for all mods can be read and modified", as a folder in this repository to be used as the root for such rules from now on.

### Added

- rules/: the rules every Phobos and D'thorga repository shares. rules/every-session.md is read at the start of every session; rules/README.md says what the folder holds, how a repository takes the rules up, how a rule is changed and where a rule belongs.
- The first shared rules, on commits and changelog entries (the owner's choice): a change and its entry go in one commit; separate changes are committed separately where they are separate anyway, one finished before the next is started; one piece of work stays one commit; nothing is untangled afterwards by staging part of a file; a batch may share a version; an entry keeps its opening words when reworded.
- rules list prints the rule files with when each is read and how many rules it holds. rules check --root REPO says whether a repository reads them (the import in its CLAUDE.md, the pointer in its AGENTS.md, the file its pin holds) and fails when one is missing, for a repository's gate.
- This repository reads its own rules: a CLAUDE.md that imports AGENTS.md and rules/every-session.md.

### Compatibility

- Twelve rules repeated across the repositories are listed in rules/README.md as waiting to move; none was moved. A new or changed rule raises this repository's middle version number from now on, a rewording the last.

## [1.24.1] - 2026-11-19

### Added

- installs status gives each mod's changelog as a path in the repository (changelog), so a program can ask changes for the code behind any entry it lists.

## [1.24.0] - 2026-11-19

Asked for by the owner for D'thorga Companion (19 November 2026): progress bars with status updates wherever they fit, and a code viewer showing the code behind any changelog entry, for every game they mod and not only RimWorld.

### Added

- Progress lines: with PHOBOS_MODKIT_PROGRESS=1 a command writes one JSON line a step to standard error (label, step and of when it can count, detail for a line of the work's own output). Standard output is untouched, and without the variable nothing changes. installs (status, backup, restore, build, install), rimworld-textures (status, encode), rimworld-save and changes speak them.
- progress.run_streaming runs a repository's own command, passes its progress lines on and turns its ordinary output into details, so a build or an install can report each project and mod as it goes. installs build and install use it.
- changes list: every changelog in a repository with its newest versions and their entries. changes entry: the code behind one entry, as the commit that first wrote it into its changelog (found with git log -S) and that commit's diff, file by file with line numbers, code first; an entry in no commit yet shows the uncommitted changes. It names the other entries the same commit wrote. No game in it: checked on RimWorld, Ostranauts, Project Zomboid and Kenshi repositories.
- The manifest's surface gains changes; installs.parse_changelog keeps each version's heading text (headings).

### Compatibility

- Nothing changes for a caller that does not set the variable. A changelog needs no new markup for changes to read it.

## [1.23.0] - 2026-11-18

The third tool the owner wanted that day (18 November 2026): a watch on the mods we tie into, so a change to a method we patch is found on purpose rather than by chance. Vehicle Framework's upgrade research check (VF-412) had been noticed by hand; this finds it, and twelve more like it, in 34 seconds.

### Added

- rimworld-upstream: every member our C# names on another author's type (the scan rimworld-targets checks), against two sources. updates compares the newest two versions rimworld-archive kept of each file updated in the last --days, member by member, through the code tool's compare, and lists those it changed, gave a new signature or removed. pending reads the source clones rimworld-sources made and lists commits since --days ago whose hunks change one of those members, a warning before the Workshop build carries them. Both name the line of ours that depends on the member.

### Changed

- The commit guard's guide says what it cannot pass: a commit that stages only part of a file, since the gate checked the whole file.

## [1.22.0] - 2026-11-18

The owner's go-ahead for two of the tools proposed that day (18 November 2026): readers for a game that hangs, holds too much memory or crashes, and a guard that refuses a commit the gate has not passed. A gate piped through tail had once lost its exit code and let a broken commit in.

### Added

- rimworld-perf stack: a few snapshots of every thread's stack in the running game (Microsoft's dotnet-stack), a moment apart. It finds the thread running the game's loop, says whether it moved between snapshots and which frames never did, names the part of the loop and the innermost mod on its stack, and lists other threads with game or mod code on them. stack-report reads them again.
- rimworld-perf heap: what the game's managed heap holds, by type and by the mod each type belongs to (Microsoft's dotnet-gcdump, which forces a full garbage collection first). A .NET collection whose generic arguments name a mod's type counts for that mod. heap-report reads one again; heap-compare sets two side by side, who grew and which types. The .gcdump file is kept for PerfView or Visual Studio.
- crash-dump names the methods in a dump that holds the full memory of a .NET program: the loop's return addresses, the calls beyond it and those where the stack ran out, through Microsoft's dotnet-dump, with each method's assembly. --no-names skips it. Checked on a stack overflow of a small test program: it named the same method and caller as .NET's own error output.
- windows-dumps: whether Windows keeps full crash dumps of one program, the PowerShell lines that ask it to, and --apply or --off to do it from an administrator window. Only that program's own key is written.
- The gate's commit guard: a full passing run (no --only or --skip) notes, in the repository's .git folder, the content of every changed file it saw unchanged from start to end; gate --verify-staged, run from a pre-commit hook, refuses a commit whose staged files no single passing run saw exactly so. A failing run, a narrowed run or an edit after the pass is refused; another session's failing run leaves an earlier pass standing.
- dotnet_diagnostics installs and runs dotnet-stack, dotnet-gcdump and dotnet-dump beside dotnet-trace and dotnet-counters, each at the pinned version and only when first needed; dotnet_snapshots reads their text.

### Fixed

- crash-dump read the wrong bytes as the stack in a dump .NET writes itself (createdump): its thread record points to no stack, which is kept in the full memory list instead. It now looks there, and a stack overflow's loop is found.
- A test of installs status could fail by timing: two files of the same size written in the same clock tick were taken for the same file. The test now gives them different times.

### Changed

- The kit's rules allow one more writer, for Windows' crash dump setting only: windows-dumps --apply and --off write the one LocalDumps key of the program named, on request, from an administrator window.

## [1.21.0] - 2026-11-18

The owner's four asks for D'thorga Companion's Mods page (18 November 2026): compile as needed, refresh after, see before and after ahead of a compile, and know whether textures need encoding before the next launch, Workshop mods included. Their picks: check and fix textures, a build button plus installing everything that changed, all four before-and-after extras, and a "before you play" strip.

### Added

- rimworld-textures status: every active mod's encoded textures against its pictures. Stale (the game would show the old picture, since it loads a .dds instead of the .png beside it without comparing dates), never encoded, and left over. About 3 seconds for 342 mods.
- rimworld-textures encode: RimSort's own todds preset on the named mods, Workshop ones included (owner's choice), refused while the game runs; each mod is checked again afterwards. The preset moved here from phobos-rimworld's deploy.py, so both use one copy.
- installs status, for each mod: the files installing would add, change or remove, by kind; whether its C# projects need a build; the installed commit (the record's, or the one that first set its version); its settings changes since then, from the repository's own command; and the test rows the install would bring.
- installs build runs the repository's build command, which writes only inside the repository, so it does not wait for the game to close. installs install takes --mod more than once, for one run and one restart.
- installs.json keys: installOnly, build (projects, modProperty, shared, command) and settingsChanges.

### Changed

- The kit's rules allow one more writer, for textures only: encode writes .dds files into the mod folders it is named, never deletes, and never runs while the game does.
- The status summary says "1 mod", not "1 mods".

### Compatibility

- installs install's JSON names its mods under mods (a list) instead of mod.

## [1.20.0] - 2026-11-18

Asked for by the owner for D'thorga Companion (18 November 2026): a part of it for updating, going back and backups, starting with a live view of what each change to the changelogs would give them or take away. This is the install helper the kit's rules have named since 1.0.0, and the first step of moving deploy.py's install pattern here (docs/migration.md).

### Added

- installs status: each of a repository's mods, its installed copy, the repository's copy and every backup, with what moving to the repository or to each backup gains, loses or rewords, read from the changelog each copy carries. An entry is matched by its text wherever it sits, so one that moved from Unreleased into a version is neither gained nor lost. Entries under Save compatibility are listed apart. Backups' sizes, free space on both drives and whether the game is running come with it.
- installs backup copies an installed mod into the backups folder. installs restore puts a backup back: the replaced install becomes a backup first and the backup is kept, the swap is two renames on the game's drive, and it refuses while the game runs or while something holds the folder open. installs install runs the repository's own install command. Each refuses rather than leave a drive with less than 1 GB free.
- The install record (InstallRecord.json): the commit, the time and any uncommitted files a copy was installed from, written by the repository's install and read by status. installs.record_for and write_record make it.
- A repository opts in with config/installs.json (docs/installs.md). RimWorld's adapter: games/rimworld/installs.py.

### Compatibility

- Read-only unless backup, restore or install is asked for; manifest effects say which (writes, runs). Backups use deploy.py's names, so cleanup's install-backup rule still covers them.

## [1.19.1] - 2026-11-18

Found on the first run against phobos-rimworld's test list: four rows still said "seen working" from notes that, judged by the new evidence, no longer stand for them (an engine stop on a thrown-track row, a 0 W grid draw, a warning from before its row changed).

### Fixed

- apply takes back its own "seen working, awaiting the owner's word" sentence when no note read stands for the row any more. Never when the row has a verdict, and never when no notes were read at all, so a missing or moved notes file takes nothing back.
- The report says "1 kind", not "1 kinds".

## [1.19.0] - 2026-11-18

Asked for by the owner in phobos-rimworld (18 November 2026, its design record "Seen-in-play checks"): two faults sat in the seen-in-play notes and only a reading by eye found them, a grid hook-up noted at 0 W on a row expecting about a kilowatt, and a refusal with no warning before it.

### Added

- test-pass reads optional note fields: what a note was seen on (on), its kind, its case (variant) and its figures (values). Every note is kept, not only the last of each key.
- Evidence that judges: a row in named parts; a piece of evidence narrowed by a case or a wildcard on the detail; expected figures (>= N, > N, <= N, < N, = N, A..B). A part whose notes never show the figures is listed as seen but off, and does not mark its row seen.
- Order rules: a note that must come before another on the same thing, such as a warning before a refusal. Each break is listed with the thing and the time.
- Sightings older than the row: versionNames says how each mod is written in the rows, and a note from an older version than the newest the row names is listed apart.
- How widely a row was seen: the kinds of thing its notes came from.
- The owner's decisions on notes no row names, read from D'thorga Companion's folder (test-key-decisions, or --decisions): no row needed leaves a key out, make a row lists it as a request.
- testpass.map_problems: a key with nothing narrowing it that stands for several rows without a shared entry. testpass.mapped_keys: every key the map names, in any form.
- --json: each row's parts with their state, figures and staleness, its kinds, the versions it names and its order problems; and the whole map's order problems, notes no row names and map problems.

### Changed

- apply's seen sentence names the parts seen ("2 of 3 parts (wet brakes, air filter)"), and is written again when more parts are seen.

### Compatibility

- Every existing evidence map, note and verdict reads as before: a list of keys is one part, and a note without the new fields is a sighting with no figures, which cannot meet an expectation or be checked for order.

## [1.18.0] - 2026-11-18

The owner's first clones (19 repositories, 59 MB on K:) showed five that hold built files only: Dubs Bad Hygiene, Rimatomics, Rimefeller, Medical System Expansion 2 and Frontline Workshop.

### Added

- rimworld-sources --clone-into: each clone's C# file count, read from the repository's file list, and a note when there is none: decompile for code, and read its history for what changed and when.

## [1.17.0] - 2026-11-18

Asked for by the owner in phobos-rimworld (18 November 2026): clone the confirmed repositories, watch what they cost as they grow, and ask before anything is deleted.

### Added

- rimworld-sources --clone-into DIR: a lean clone of each confirmed repository (whole history, but only source and project files checked out and fetched), --update-clones to move them forward without ever discarding work, and a report of each clone's size, their total against a budget and the drive's free space. When the drive is short (under 10 GB or 3% free, both adjustable) no new clone is made; when it is short or the budget is passed, the report asks for a decision and lists the choices. The tool never deletes.
- source_clones: the game-free clones and the storage watch behind it.

### Fixed

- rimworld-sources: a register entry missing a field no longer stops the report.

## [1.16.0] - 2026-11-18

Asked for by the owner in phobos-rimworld (18 November 2026), beside its new rule to read a mod's public repository before decompiling it.

### Added

- rimworld-sources: where the public source of each mod a project ties into lives. Candidates come from the mod's About.xml, then its Workshop page, then a GitHub search by name, cheapest first; one counts only when an About.xml in the repository names the mod's package ID, so links to another mod (the Harmony mod's, most often) are ruled out by the check. With --write it keeps a register in the project (config/source-repos.json) that later runs reuse. On the owner's 54 tied mods: 19 confirmed, 22 with only unconfirmed candidates, 13 with none.
- github: a keyless, paced client with a week's cache in the kit's cache folder, for repository facts, file lists, raw files and searches. It stops at GitHub's limit for clients that do not log in and says when to run again.

### Changed

- rimworld-archive: the tie-ins it watches come from one function the source finder shares.

## [1.15.0] - 2026-11-18

Asked for by the owner in phobos-rimworld (18 November 2026): that day's game update could not be compared with the build before it, because Steam had replaced the file and nothing had kept it.

### Added

- rimworld-archive: keeps every version of the game's Assembly-CSharp.dll and of each active mod a project's own mods name (About.xml dependencies and load order, LoadFolders.xml IfModActive), each distinct file once and compressed, with an SQLite index of owner, file, version text and first-seen time. Reports snapshot, list, get and compare; compare hands two kept versions to code compare. Its folder is its own (PHOBOS_ASSEMBLY_ARCHIVE, assemblyArchivePath, else the user's local application data), never the cache, which defaults to a temp folder.
- The guide (docs/rimworld-archive.md) says how the owner can fetch a game build the archive never saw with SteamRE's DepotDownloader, which logs in with the owner's account and is never run by the kit.

## [1.14.0] - 2026-11-18

A tooling round asked for by the owner in phobos-rimworld (18 November 2026), for three gaps met that day: a part-pass written into the test list by hand, a profile that could not find the game loop, and a scratch script for heights.

### Added

- test-pass: a `partial` verdict, written "Passed in part", for a row of which only some has been seen; and `--verdict ROW:WORD[:NOTE]` on report and apply, for a verdict the owner gives an agent in conversation, written "in conversation" and replacing the file's for its row. Verdict lines may say `via`.
- rimworld-save terrain: how high the land stands and how rough it is; land heights and hilliness across the world, the player's places with their height, the steps between neighbouring land tiles, and with --near the heights in rings round a place.
- rimworld-perf: the alerts column, sound and music, and the engine's own frame drawing are named parts of the loop.

### Fixed

- rimworld-perf: Harmony 3's names for rewritten methods (`Type.Method_PatchN` and its `Glue:AbiFixup` glue) read as the original method, so a patched game loop is found. The owner's recording of 18 November 2026 had put two thirds of the main thread outside every named part; it now names all but 2%. Recordings already indexed are read the new way.

## [1.13.1] - 2026-11-17

The first recording of the owner's game (3 minutes, many wounded) put 95.6% of ticking down to Smart Medicine, when Search and Rescue was calling it in a scoring loop; the headline named the mod doing the work, not the one deciding how often.

### Fixed

- rimworld-perf report: a new table, one mod's code running another's, pairs the outermost mod on each stack with the innermost, so a mod that calls another in a loop is named beside it.
- The phase list and the guide say what the first recording of the game confirmed: the named parts matched 99.2% of the main thread, and every mod assembly with time was matched to its mod.

## [1.13.0] - 2026-11-17

In phobos-rimworld (17 November 2026) a slow game with many wounded pawns could only be answered by reading code, because nothing measured the running game. RimWorld 1.7 turned out to run on Microsoft's CoreCLR with its diagnostics pipe open, so Microsoft's own tools can record it from outside; the owner asked for a tool built on that.

### Added

- rimworld-perf record: attaches dotnet-trace and dotnet-counters (10.0.750501, installed into the kit's build folder on first use) to the running game for --seconds, indexes the trace with the owners of every module against the mod list of the day, and reports it. --label, --pid, --keep-speedscope.
- rimworld-perf report: the main thread by part of the game loop (ticking, drawing, interface, loading), who caused the time (the innermost mod on the stack), mods' busiest methods, where the thread was when sampled, game methods other mods patched, garbage collection and runtime counters, other busy threads, and time outside the named parts.
- rimworld-perf mod, compare (as shares of the main thread and of ticking), list, and index for a trace recorded by hand.
- The core reader of sampled stacks (sampling.py) and the diagnostics tools' runner (dotnet_diagnostics.py), with no game in them.
- A cache policy may give its own reason for the age rule (aged); rimworld-perf's says a recording cannot be made again.

### Changed

- AGENTS.md: in-game instrumentation stays Phobos Scope's; sampling a game from outside belongs here.

## [1.12.0] - 2026-11-17

In phobos-rimworld (17 November 2026) a one-off audit of stand-in art took two throwaway scripts and a hand check of every "mixed" result; the owner asked for it as a reusable tool.

### Added

- art-audit report: every shipped image paired with its records (its own name, the name before each underscore, or its folder's name) and classed by the record's first statement of how it was made, using the repository's patterns; images drawn in code, without a record, or with a record no rule recognises; generated images whose record calls them a stand-in; and pictures used by a Def that belong to another thing or are not ours, open or accepted with a reason. --mod, --kind, --all, --json.
- art-audit check: exits 1 when an image has no record, for a repository's gate.
- The RimWorld adapter's art part: the names a texture answers to (facings, masks, folders), and every use in Defs (with list-item parts and ParentName inheritance), patch operations and C# literals.
- A repository's config/art-audit.json describes its images, records, kinds and accepted borrowings; docs/art-audit.md describes it.

## [1.11.0] - 2026-11-17

In phobos-rimworld (17 November 2026), a Workshop report gave an update date some hours old for a mod updated minutes before, while its first line said nothing was reused from the cache. Details, reused for a day, were never counted. The owner asked for it fixed. This entry followed the tagged commit, which went up without it.

### Added

- --details-max-age H for steam-workshop and rimworld-workshop: how long fetched details (update date, version tags, subscribers) stay fresh. Default 1 hour, since details cost one request per 100 items; --max-age (default 24) now covers comments and collections only.

### Fixed

- The first line of a report names what came from the cache: items' details with the age of the oldest, and comment pages or collections, and says --refresh gives the newest. It used to count reused comments only, so a report built on old details looked freshly fetched.

## [1.10.0] - 2026-11-17

A crash in phobos-rimworld (17 November 2026) was fixed with a patch whose target is named as a "Type:Member" string, and its parameters had to be checked against Combat Extended by hand: the target check read neither. The owner asked for the gap closed.

### Added

- rimworld-targets reads Harmony's "Namespace.Type:Member" names in AccessTools lookups, and types found by name with a fixed name (AccessTools.TypeByName, Type.GetType, the game's GenTypes.GetTypeInAnyAssembly, and a project's own lookups given with --type-lookup), directly or through a variable every assignment in its file sets to the same type. String constants count, joined with +, from the file itself or as Class.Name from any file scanned.
- A patch class's TargetMethod whose body names one member gives the class that target, so its parameters are checked too.
- Patch parameters Harmony matches by name with the original's (every name in a prefix, postfix or finalizer but Harmony's own) are checked against the original's parameter names; a name the original lacks fails, with the names it has. The assembly reader's member listing now gives each method's parameterNames.

### Fixed

- A typeof that a call follows, as in typeof(X<>).MakeGenericType(...), is no longer read as the type X.

## [1.9.0] - 2026-11-17

The owner sees in-game tests pass but the news rarely reaches the test list, and asked for the checklist to live in D'thorga Companion (phobos-rimworld, 17 November 2026).

### Added

- test-pass report: a repository's in-game test list (named by its config/test-evidence.json), the rows waiting for the owner, the rows the game has seen working, and verdicts not yet written; --json gives every row's cells, sightings and verdict for a program to show. test-pass apply writes each verdict into its row, and "seen working, awaiting the owner's word" for a row the notes flag that has no verdict; a preview without --apply, and it writes only inside the test list.
- The seen-in-play notes file and the owner's verdicts file, both JSON lines, described in docs/test-pass.md. A note never passes a row; only a verdict does. Verdicts default to D'thorga Companion's own folder, one file per repository.
- rimworld paths: seen_in_play_path, where D'thorga Framework 0.118.0 writes its notes (PhobosSnapshots/SeenInPlay.jsonl beside the Config folder).

## [1.8.0] - 2026-11-11

The owner asked for a cleanup of every temporary file the RimWorld work had left, and for the tool to live here (phobos-rimworld, 11 November 2026).

### Added

- cleanup: lists what the kit's tools and a repository's builds and tests left behind, with sizes and the reason each may go, and deletes it only with --apply. It covers the kit's cache (a file a tool says is stale, anything unchanged for 14 days, frozen copies a stopped run left), the kit's development build (never the release programs the tools run, and never while cargo or rustc runs), the folders and patterns a repository names in config/cleanup.json, and git's file-watcher daemons. docs/cleanup.md describes the rules file.
- A command may declare CACHE_POLICIES for its cache folders: a stale test, or a reason to keep the folder. rimworld-save's index is stale once its save has been saved again or has gone; the Workshop cache is always kept, its pages being slow to fetch.

## [1.7.0] - 2026-11-10

The owner asked for the atlas in D'thorga Companion: the whole world map, with biomes, settlements, pollution, climate and terrain views, roads and rivers (phobos-rimworld, 10 November 2026).

### Added

- rimworld-save atlas: every surface tile of a save's world as a globe a program can draw, with its biome, elevation, temperature, rainfall, hills, swampiness, pollution, named region and landscape features; settlements and other world objects grouped by how their faction stands with the player; roads, rivers and the game's region labels. Tables list biomes, places with latitude and longitude, named regions, and roads and rivers.
- A globe block in the report model: tile positions, each tile's neighbours in order round it, layers of one value per tile, places, lines, tags and labels, with arrays as base64 in JSON. docs/manifest.md describes it.
- The save index holds the surface layer's per-tile arrays, the world's named regions, and how each faction stands with the others.
- The manifest's surface field names a report that is mostly a picture (globe for the atlas), so a program can give it a page of its own.
- Biome colours and road and river widths in a data file (atlas-palette.json), agent-authored for the owner to revise.

### Changed

- The planet model keeps each tile's neighbours in order round it as well, and gives a tile's outline, longitude and latitude as the game reckons them. Its cache rebuilds once.

### Fixed

- The planet model kept each tile's neighbours in an order of its own, not the game's. Saves name a road's or river's other end by its place in that list, so the model would have put every road and river piece on the wrong neighbour; no report read them before the atlas. Now in the game's order: on the owner's save, river pieces join into 233 river systems and road pieces into 33 networks, where the wrong order scattered them into thousands of scraps. The planet's cache rebuilds once.

### Notes

- The planet's orientation is settled from the game's code: it builds the world from the same icosahedron and never rotates it, so no in-game reading is needed.

## [1.6.0] - 2026-11-10

The owner said yes to naming the half of mood a save leaves out, to suggested fixes labelled as advice, and to colonists, slaves and prisoners together (10 November 2026).

### Added

- rimworld-save mood reads the colony mood file D'thorga Framework writes at each save, when its tick count and world seed match the save: every thought as the game counted it, bedrooms, pain, cold and beliefs included, with each pawn's own break thresholds. A file from another save, or of another shape, is said and set aside. --mood-file names one; --no-mood-file ignores it.
- Where to start: the costliest causes a player can do something about, each with a suggestion. Needs running low and one pawn's thoughts carry advice too. The suggestions are ours, kept in a data file anyone can add to, and always labelled as advice.
- The save index records the world's seed.

## [1.5.1] - 2026-11-10

### Fixed

- rimworld-save mood: the charts of what hurts and helps most have titles of their own, instead of repeating their section's heading (seen in D'thorga Companion).

## [1.5.0] - 2026-11-10

The owner's colony showed "Extreme break risk x29" and they asked to see where it was lacking mood-wise, in D'thorga Companion (phobos-rimworld, 10 November 2026). They also asked for graphs.

### Added

- rimworld-save mood: each pawn's mood against its own break thresholds, the remembered events that cost the colony most and help it most, needs running low, and addictions and drug needs. --pawn gives one pawn in full; --who narrows it to colonists, slaves or prisoners.
- It counts remembered events by the game's own rules (stage, strength, fading, stacking, trait cancelling) from the Defs as patched where a patched-Defs file exists, else as written, and says plainly that situational thoughts are not in a save. What they cost comes as one figure, mood minus the remembered events.
- The save index gains need and memory tables, and each pawn's prisoner or slave status.
- A chart block in the report model: bars or lines, with series and reference lines that carry a meaning (risk, success and so on), never a colour. Markdown shows text bars; JSON carries the chart for a program to draw.
- The patched-Defs file is found by default where D'thorga Framework writes it, beside the Config folder.

### Fixed

- A need whose level is 0 is left out of the save by the game; the mood report reads that as 0, not as unknown.

## [1.4.0] - 2026-11-09

A game died with a stack overflow and nothing in its log, and reading its crash dump took a debugger, a downloaded tool and a hand-written script (phobos-rimworld, 9 November 2026).

### Added

- crash-dump: reads a Windows minidump with no debugger or symbols. It names the exception and the thread, finds a call loop that ran away (how big one level is, how often it repeats, and whether every level held the same objects), and says which modules the stack points at.
- It says what a small dump cannot tell, and for a .NET stack overflow how to get the method names next time.

## [1.3.0] - 2026-11-09

What changed between two builds of an assembly could not be answered well by the metadata tools tried: one read nearly every method of a small rebuild as changed, and could not read a game's main assembly at all (phobos-rimworld, 9 November 2026).

### Added

- code compare OLD NEW: what changed between two builds, declaration by declaration. Each side is a .dll, an indexed corpus, or a folder of C#. It lists what was added and removed, new signatures, and new bodies with lines changed, marking a change that touches only strings or numbers as values only; a new type is one row. --only narrows it by name and --show prints one declaration's changes as a diff.
- A .dll is decompiled once with ilspycmd, named by --decompiler, PHOBOS_MODKIT_ILSPYCMD, ilspycmdPath or the PATH, and kept in the kit's cache by its bytes and --reference folders; the 12 most recently used are kept. ilspycmd reads the file without loading or running it.
- A side with no declarations is an error, never a list of removals, and two sides with nothing in common are called out.

## [1.2.0] - 2026-11-09

Which vehicle types other mods already provide could not be answered without reading a Steam collection, and Steam's item pages refuse automated fetches while its keyless APIs do not (phobos-rimworld, 9 November 2026).

### Added

- steam-workshop and rimworld-workshop collection: a Steam collection's items by ID or URL, in the collection's order, with each item's update date, declared versions, whether it declares the game's version, and the opening of its description with the BBCode stripped; --grep keeps the items whose title or description match (* and ? wildcards). One request per 100 collections and one per 100 items; no comments are fetched. A collection Steam does not return is named as such.
- The cache keeps each item's description (column description) and each collection's members (table collection), so sql can ask across them. Caches made before this version gain the column on first use.


A program showing the kit's reports needs to sort numbers as numbers, and to name a report as a person would ask for it (owner, 9 November 2026).

### Added

- Every table in a report's JSON now has values: the number each cell sorts by, so 12.5% sorts as a number. A column that isn't all numbers in one unit has none.
- A report in the manifest can carry a question: the report as a person would ask for it. The RimWorld reports that need nothing typed have theirs.

## [1.0.0] - 2026-11-09

A desktop program over the tools needs to read every command the same way, and to know what each one does before it runs it (owner, 9 November 2026).

### Changed

- **Incompatible: every command's --json now prints one envelope**: envelope, tool, kit_version, report and data. What consumers must change: the report that was at the top level (release, gate, code, steam-publish, rimworld-patches, rimworld-readiness, rimworld-settings, rimworld-startup, rimworld-targets) is now under report; the save, index and built fields of rimworld-save and rimworld-defs are now under data; rimworld-log's JSON is now under data, beside its summary report. Nothing in phobos-rimworld reads this output.
- The command table moved to commands.py, and the dispatcher imports each command's module by name.

### Added

- manifest: every command, its reports and options read from its own parser, and what each report reads or changes (reads, reads-online, writes, runs, owner-only). See docs/manifest.md.

## [0.19.0] - 2026-11-09

Why a world tile is polluted could not be answered from a save without reading the file by hand (owner, 9 November 2026).

### Added

- rimworld-save planet: pollution on the world map from the save's planet layer, by band and as patches of touching tiles with what stands on or nearest each, rings of tiles around a named place or tile (--near, --hops), what changed against another save (--compare), and every save of the same world by in-game day (--history, read straight from the saves without indexing them).
- The save index holds the planet's pollution layer (table planet_grid).
- A planet's tile centres and neighbours are rebuilt from a model of its shape and cached by subdivision count; a world generated with less than full coverage is reported as such and its tiles are not placed.

## [0.18.0] - 2026-11-09

The compiler checks typeof and nameof; nothing checked the names C# holds in strings (owner, 9 November 2026).

### Added

- rimworld-targets: every Harmony patch and reflected lookup in a source tree, and the parameters Harmony fills at run time, checked against the game's and active mods' assemblies as metadata. Exit 1 when a name no longer matches.
- The assembly reader's members command: the fields, methods and properties of named types and their base types.

## [0.17.0] - 2026-11-08

Two tools from the planned list (owner, 8 November 2026).

### Added

- rimworld-startup: every recorded launch from Loading Progress's StartupImpact sessions, the costliest mods and slowest stages over the launches with the newest mod list, a comparison of any two launches, and one mod across them.
- rimworld-readiness: per active mod, the versions its About.xml and Steam tags declare, its Harmony transpilers, and byte scans for Prepatcher and asset bundles, riskiest first, with what changed since the last run. It says what a mod declares and how closely it depends on the game, not whether it works.

## [0.16.0] - 2026-11-08

The patched view becomes the first place to look (owner, 8 November 2026), so it has to say when it cannot be trusted.

### Added

- rimworld-defs patched says when the file may be out of date: a different count of active mods or game version, a mod list or Workshop manifest saved after it, or XML changed after it in the game's Mods folder, naming those folders.
- rimworld-defs who and show take --dump and add one line pointing at the patched report when the file exists.

### Fixed

- The Workshop publishing and release history tests set core.fsmonitor false in their test repositories. They had passed it only on their own git calls, so the plain git status in the code under test started a watcher for each test repository that never exited, and one could hang the test run.

### Changed

- README: the opening list names all ten built tools and says the Harmony patch reader needs the .NET SDK.

## [0.15.0] - 2026-11-09

The resolved-Defs half of the plan's shared frameworks, at the owner's go-ahead (9 November 2026): a Def with every
patch applied, which no file on disk holds.

### Added

- rimworld-defs patched NAME: the Def with every mod's XML patches applied (before inheritance), from a patched-Defs file a running game wrote, and a diff against the kept definition as written. A Def only a patch adds, and one the patches leave alone, each say so. The file is indexed in the cache by streaming, again whenever it changes, and is named by --dump, RIMWORLD_PATCHED_DEFS or the rimworldPatchedDefsPath setting.
- docs/rimworld-defs.md: what such a file holds and how phobos-rimworld's D'thorga Framework writes one; 2 tests on a hand-written file.

## [0.14.0] - 2026-11-09

The plan's tool 4, the assembly metadata reader, at the owner's request (9 November 2026). On the owner's 254 active mods:
5,356 Harmony patches in 333 assemblies, read in 6 seconds.

### Added

- rimworld-patches: which active mods patch a method (who, with wildcards on the member and type), what one mod patches (mod), and methods several mods patch (hotspots), each patch with its kind, its patch method, its priority, and whether a prefix returning bool may stop the original. Only the assemblies the game loads are read (each active mod's load folders for the game's version), and only ones that changed since last time.
- PhobosModKit.Assemblies (C#, dotnet/): reads assemblies through System.Reflection.Metadata, never loading them. Finds [HarmonyPatch] classes (merged as Harmony merges class and method attributes, with MethodType, argument types and HarmonyPriority), the targets a TargetMethod's code names through AccessTools, and harmony.Patch calls read from the IL. Its build goes to the kit's build folder, outside the repository.
- docs/rimworld-patches.md; a made-up mod assembly in C# source (fixtures/dotnet/PatchFixture) and 4 tests that build and read it.

### Changed

- CI installs .NET 10 so the reader's tests run, as the Rust tools' do.

## [0.13.1] - 2026-11-09

### Fixed

- code outline: line numbers print plainly (8765, not 8,765), as a file:line reads them.

## [0.13.0] - 2026-11-09

At the owner's request (9 November 2026) for tools that keep agent sessions lean: research into a mod's code used to
mean agents searching hundreds of thousands of decompiled lines. On the owner's 54 trees (about 330,000 declarations)
the first index took 34 seconds; a query then takes under a second.

### Added

- code: indexes C# source trees (decompiled assemblies kept on the researcher's machine, a project's own source) into the cache, and answers find (declarations by name, with wildcards and kinds), outline (a type's members with their lines), show (a member's source by bare, dotted or full name, numbered, every overload, decompiler notes hidden) and refs (every line using a name, grouped by the member holding it). Indexes rebuild when a tree's files change.
- The scanner blanks comments and every kind of string first (verbatim, interpolated with quotes nested in their holes, raw) and reads attributes with braces, default parameters with casts, tuple types, expression bodies and file-scoped namespaces; on the owner's trees it misses about two declarations in 100,000.
- docs/code.md; 6 tests on made-up C#.

## [0.12.0] - 2026-11-09

At the owner's request (9 November 2026) for a tool that captures the settings they play with, to help work out what
causes an error. Run on the owner's Config folder: 154 settings files, 118 of them for active mods, 36 left by mods no
longer active (among them five of phobos-rimworld's, merged on 7 November).

### Added

- rimworld-settings: which mod each settings file belongs to and whether it is active; the values of chosen mods (name, package ID or folder, with wildcards); files left by removed, merged or renamed mods; snapshot and compare. A defaults file from the mod's own source shows each value beside its default, the keys left at default, keys no longer read, and defaults that disagree between a field's starting value and the one a missing key loads as.
- docs/rimworld-settings.md: why a file lists only what the player changed (RimWorld writes nothing for a value at its default), and how files are matched to mods (class names may hold underscores, as Vanilla Expanded Framework's do).
- 7 tests on a made-up install.

## [0.11.0] - 2026-11-09

At the owner's request (9 November 2026) for tools that keep agent sessions lean: one command for every check before a
commit, printing only what failed.

### Added

- gate: runs a repository's checks from its config/gate.json in stages and lanes (steps sharing a lane in order, lanes side by side), repeats a step for every file a glob finds, skips a step whose program is missing and says so, stops later stages when one fails, and keeps a failed step's full output in the cache. Parsers for MSBuild, dotnet test, unittest and cargo keep the errors, failed tests and counts and drop the rest; a passing run prints three lines.
- This repository's own config/gate.json, the list of checks in AGENTS.md.
- docs/gate.md; 11 tests on hand-written tool output and a made-up repository.

## [0.10.1] - 2026-11-09

### Fixed

- release changelog and steam-publish notes: a # inside a line is text again (C#, issue #12); only a line that starts with # is refused, as a stray Markdown heading. phobos-rimworld's changelogs failed on "C# assembly".
- A formatting refusal now names what it found (a backtick, a pipe, # at the start, a numbered list), instead of only quoting the line.

## [0.10.0] - 2026-11-08

At the owner's request (8 November 2026): phobos-ostranauts' Steam Workshop and release tools, made generic and
moved here. Read-only checks against phobos-ostranauts gave the same results as its own scripts: release notes for
444 changelog entries byte for byte, due updates, combined change notes, change-note worksheets, pull findings and
149 constants. Not yet used for a real upload from the kit.

### Added

- steam-publish notes: each changelog entry as a Steam change note in BBCode, written beside the Workshop page; checks the page's title, version and publication status lines, its size and its text; --base refuses content changed without changelog and page edits.
- steam-publish status, pending, prepare and verify: publication order, blockers and sizes; which items have a newer version than the one uploaded; a hashed candidate staged offline in the kit's cache, with a change note covering every version since the last upload, cut to Steam's limit.
- steam-publish upload and update, run by the owner only: SteamCMD takes the login in its own prompt, so the tool never sees a password. New items are created Private; going public needs committed work and --confirm-public; a receipt is written before SteamCMD starts; an update with nothing new does nothing; a create with no returned ID must be reconciled before another. update builds, prepares and updates every due item, dependencies first.
- steam-publish reconcile, pull and change-notes: settle an uncertain upload; bring an item's live visibility, page and release date back from Steam's public API; worksheets for tidying an item's Change Notes tab by hand.
- Game adapters for publishing: RimWorld reads About.xml and keeps About/PublishedFileId.txt in step with the catalogue, and reminds the owner that SteamCMD sets no tags (a Ludeon forum report, not checked against Valve's documentation); Ostranauts reads mod_info.json. A repository may pass its own package checks as a payload hook.
- release changelog: checks changelogs in the Phobos form, including whether every entry fits the store-page text.
- release constants: keeps every registered copy of a version or figure in step, checking all of them before writing any, with read-back and rollback.
- release history: screens every file in a repository's history for credentials, personal paths and refused file types before it goes public.
- Shared modules: phobos_modkit.files (link refusal, tree reads, atomic writes), phobos_modkit.steam.bbcode and phobos_modkit.steam.vdf. The Workshop item model keeps an item's description in memory (not cached).
- 33 tests on made-up repositories, with stand-ins for SteamCMD and Steam's API.

### Changed

- AGENTS.md, README and project direction: the owner-run uploader is the one exception to the read-only Steam rule. Agents, tests and CI never run a real upload.
- Hard-wrapped bullets and paragraphs in a changelog now join, as Markdown reads them, and a heading ending in history after the releases closes the log (mods merged into another keep their old logs there). The Ostranauts scripts refused indented lines.

### Fixed

- Constants: a JSON pointer to a string value now edits inside its quotes; the Ostranauts copy captured the quotes and could not match a string.

### Compatibility and limits

- Moving phobos-ostranauts onto the kit needs layout entries in its catalogue and its package checks as a payload hook; docs/migration.md lists every difference. phobos-rimworld adopts publishing when its first mod reaches its public beta gate.
- Not moved: the Workshop cover composer (Ostranauts' art, and it needs Pillow) and Ostranauts' documentation packager.

## [0.9.0] - 2026-11-09

### Added

- rimworld-defs show --lines N: how many XML lines each Def and parent shows before it is cut (default 80, as before; 0 shows every line). A long VehicleDef's parts list was cut off at 80 lines with no way to see the rest (phobos-rimworld, 9 November 2026). The cut line now names the option.

## [0.8.0] - 2026-11-08

### Added

- rimworld-save world --id: one world object's values in full, such as an aircraft's flight path and destination or a site's parts. The save schema gains the world_object_value table and world_object_value_view.

### Changed

- The save schema changed, so indexes rebuild on their next use (about 70,000 more rows on the owner's save).

## [0.7.0] - 2026-11-08

### Added

- rimworld-save world: world objects (settlements, sites, caravans) counted by def and faction, or listed with ID, name, faction and tile.
- rimworld-save components: the game's, the world's and each map's components with their value counts, or every value with text inside them with its path in the component, so a mod's saved state (a diplomacy mod's wars and battles, for example) can be read without opening the save.
- rimworld-save diff now lists world objects that changed faction, appeared or went (by ID), component values that changed and component lists that grew or shrank; --component narrows those sections to matching component classes.
- The RimWorld save schema gains the world_object, component and component_value tables and the world_object_view and component_view views. 3 new tests and a larger fixture save.

### Changed

- The save schema changed, so indexes rebuild on their next use. An index is larger and slower to build: about 1.1 million more rows and 3.5 s instead of about 2 s on the owner's 11-million-element save.

### Compatibility and limits

- Component values are matched between saves by class, map position and path, so items of a list are compared only by count. State a mod keeps outside components is not covered.

### Changed

- AGENTS.md now holds the rules learned while building the first tools: run every check before a commit and gate the commit on their exit codes; a version bump changes the package, Cargo.toml and Cargo.lock together, and pushed tags are never moved; set CARGO_TARGET_DIR outside the repository when developing; a tool's first change in a consumer adds that consumer's AGENTS.md rule; report filters go through phobos_modkit.query. CONTRIBUTING.md says how to run the checks. Documents only; no tool changed.

## [0.6.0] - 2026-11-07

### Added

- rimworld-save grid: a map's layers counted (terrain, foundations, roofs, each gas, fog, snow, pollution, deep resources), one layer in full with a text picture, or every layer at one cell with the things standing there; --area limits the counts to a rectangle. Grids are decoded as the 1.7 game code writes them, and Defs are named through the Def index; a 325 by 325 map's ten grids decode in 0.02 s.
- rimworld-save diff: what changed since another save, matched by thing ID and hediff load ID: counts, things that appeared and went by def, stacks that grew or shrank, pawns that moved, arrived or left, and pawns' hediffs gained, lost, worse or better (the player's by default).
- The Def index now adds the Defs the game makes in code for stone floors and carpets, with their source (333 on the owner's install), so terrain on the owner's maps is named for 98 to 99 percent of cells instead of 70. show says such a Def has no XML of its own.
- xml-index: a column can hold an element's own tag or its parent's (tag = "self" or "parent"). The RimWorld schema gains a map_grid table.
- 19 Python tests for grids, hashing, comparison and game-made Defs, and 3 Rust tests.

### Changed

- The save index's schema and the Def index's format changed, so both rebuild on their next use.

### Compatibility and limits

- A Def's number follows the game's short-hash rule; when names tie, the game's string order is approximated and such names are marked (?). Defs from other generators (blueprints, frames, meat, corpses, techprints, mods' own) are not named.
- Sand depth, temperatures and terrain colours are not decoded yet.

## [0.5.0] - 2026-11-07

### Added

- Workshop research (python -m phobos_modkit steam-workshop and rimworld-workshop): report, details, comments and sql over a SQLite cache of Steam's public item details (batched 100 at a time) and each item's newest comments. Per item it gives the update date, declared versions, subscribers, comments in the last 90 days, the uploader's last reply and the newest comments that mention problems. Comment requests go 8 s apart and back off 150 s once after HTTP 429, then stop and say so; anything fetched in the last 24 hours is reused; --offline never contacts Steam.
- rimworld-workshop takes mods by name (with wildcards), package ID, Workshop ID or URL, flags comments that mention the game's version from ModsConfig.xml, and adds a versions report: every active Workshop mod that does not declare the game's version (about 10 s for 320 mods).
- 20 tests with a fake Steam and hand-written fixtures in Steam's markup.

### Compatibility and limits

- Items whose uploader's profile is private show no comments to visitors who are not signed in; the report names them with Steam's reason. Only the uploader's own replies are recognised, not other team members'.
- Checked against Steam on 7 November 2026.

## [0.4.0] - 2026-11-07

### Added

- RimWorld Def index (python -m phobos_modkit rimworld-defs): summary, mods, who, show, list, patches and sql reports over a SQLite index of every active mod's Defs and patch operations. It follows the game's load rules (ModsConfig order and the _steam suffix, LoadFolders.xml with IfModActive, IfModActiveAll and IfModNotActive, version-folder fallback, shadowed files, MayRequire and MayRequireAnyOf, abstract Defs) and marks which definition the game keeps when mods share a name: the later mod's, and the first inside one mod, as the 1.7 game code does. show prints a Def's XML with each parent up the chain, choosing parents as the game's XmlInheritance does: the same Name from the latest mod at or before the child's, with its MayRequire met.
- The index rebuilds itself when ModsConfig.xml, the Workshop manifest, the game's version file or any XML file in the game's Mods folder changes. 336 active mods (42,418 Defs, 15,208 patch operations) index in about 8 s; reports take about 0.3 s.
- phobos_modkit.query: the report filters (LIKE patterns with literal underscores, the WHERE builder, counts and capped rows), moved out of the save index so both tools share them. Config-folder setting rimworldConfigPath (RIMWORLD_CONFIG_PATH).
- 23 tests on a synthetic install covering every load rule and the parent rule.

### Compatibility and limits

- Defs are shown as written: other mods' patches are not applied. Patches are found under a Def's name only when their xpath names its defName. Subclass Def tags are kept apart from their base type.
- A Workshop file edited by hand, without Steam, is not noticed until --rebuild.

## [0.3.0] - 2026-11-07

### Added

- A shared report model (phobos_modkit.report): every tool builds a Report of paragraphs, bullets, tables and code blocks, rendered as Markdown or JSON, with redaction applied to every piece of text and table cut-offs stated. Log triage and the save index now use it; their Markdown is unchanged byte for byte (checked on the fixtures, the owner's live log with all 1,560 signature details, and 12 save reports on a real index).
- A shared derived-data cache (phobos_modkit.cache): the cache folder, provenance stamps and hashes, a staleness check over a SQLite meta table, frozen copies of files another program may be writing, and removal of read-only files. The save index now uses it.
- The convention that all derived data is SQLite with a meta table of provenance, written into AGENTS.md and the project direction, so later tools can be joined in one query.
- 23 tests for the report model and the cache.

### Changed

- rimworld-save --json now prints the shared report shape: each section holds typed blocks (text, bullets, table, code), so a table's headers are at sections[n].blocks[m].headers. Log triage's --json data export is unchanged.

### Fixed

- The version test added in 0.2.2 could not be loaded, so the v0.2.2 tag's test run fails. Tests only: the tools in v0.2.2 are unchanged and build and run correctly.
- The save index's command tests now find the indexer in its build folder outside the repository.

## [0.2.2] - 2026-11-07

### Fixed

- Cargo.lock now matches the crate's version. In 0.2.1 it still named 0.2.0, so every build with --locked (CI and --build-indexer) refused to start; **do not build v0.2.1**. A test now checks that the Python package, Cargo.toml and Cargo.lock name one version.

## [0.2.1] - 2026-11-07

### Fixed

- The Rust tools now build outside the repository by default (%LOCALAPPDATA%\phobos-modkit\target on Windows, ~/.cache/phobos-modkit/target elsewhere; PHOBOS_MODKIT_BUILD overrides it). A Rust build folder runs to hundreds of megabytes, and a repository or submodule in a cloud-synced folder would upload it. A build in the repository's own target folder is still found.

## [0.2.0] - 2026-11-07

### Added

- xml-index, a Rust program that reads a large XML file once and writes a SQLite index, driven by a schema file: tables from element-path patterns, columns from child text, attributes, sibling positions and enclosing rows, typed values, indexes and views, plus a census of every element path. A 308 MB RimWorld save (8.2 million elements) indexes in 1.4 s.
- RimWorld save index (python -m phobos_modkit rimworld-save): summary, schema, things, pawns, hediffs, find and sql reports over an index of a save, in Markdown or JSON. The RimWorld schema covers the game header, mods, factions, maps, things (with what holds each), pawns, hediffs, traits and skills, with views for where each thing is and for pawns' names and factions.
- Each index is built from a frozen copy of the save, deleted afterwards, and rebuilt when the save or the schema changes. Indexes live under the system's temp folder by default, away from cloud-synced folders.
- A shared Markdown table helper, the kit's cache-folder setting (modkitCachePath, PHOBOS_MODKIT_CACHE) and RimWorld's Saves-folder setting (rimworldSavesPath, RIMWORLD_SAVES_PATH).
- A hand-written fixture save, 6 Rust integration tests of the RimWorld schema, 19 Rust unit tests and 26 more Python tests; CI now checks Rust formatting and lints, runs the Rust tests and runs the Python tests with the program built.

### Dependencies

- The Rust build downloads quick-xml, rusqlite with SQLite bundled, serde and toml from crates.io; licences are in THIRD_PARTY_NOTICES.md.

### Compatibility and limits

- Checked against RimWorld 1.7.5000 saves. Mods' patches are not applied; the index holds def names, not labels, and body-part indexes, not part names.
- Comparing two saves and reading map grids (terrain, roofs, gas) are not built yet.

## [0.1.1] - 2026-11-07

### Fixed

- RimWorld log triage: when a save is loaded again with the same mods, its notice says so in one sentence instead of listing the same marked mods again (seen with three loads of one save in one session).

## [0.1.0] - 2026-11-07

### Added

- RimWorld log triage (python -m phobos_modkit rimworld-log). It groups a Player.log's messages into signatures, compares them with the previous run, groups signatures that share one exception, and names the mods each points at from clues in the log (source lines, file paths, assemblies and namespaces in traces, the calling code, Harmony patches). It also reports the save loaded and the mods the game marked, where the game stopped logging, engine memory warnings and Harmony finalizers. Output is a short Markdown summary or full JSON; one signature can be shown in full. The home folder is redacted by default.
- A game-free log core (signatures, grouping, comparison, clusters, rendering), a path resolver shared by every tool, and an installed-mod index for RimWorld that reads only About.xml and assembly file names.
- Hand-written fixtures, 71 tests run on Python 3.10, 3.12 and 3.14, and continuous integration on Windows and Linux.

### Compatibility and limits

- Checked against RimWorld 1.7.5000 logs (November 2026). The 1.6 layout is read in a basic way and has not been checked against a real 1.6 log.
- The Linux and macOS default folders are the usual Unity and Steam places and have not been checked.

## [0.0.0] - 2026-11-07

### Added

- The repository's design documents: the README, contributor rules, the project direction (three layers,
  languages, how consumers use it) and the migration list of scripts copied across the Phobos repositories.
  No tools yet.
