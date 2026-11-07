# Phobos ModKit changelog

Maintained from 7 November 2026. Versions are tags of this repository; consumers pin a commit.

## [Unreleased]

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
