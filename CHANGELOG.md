# Phobos ModKit changelog

Maintained from 7 November 2026. Versions are tags of this repository; consumers pin a commit.

## [Unreleased]

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
