# Phobos ModKit changelog

Maintained from 7 November 2026. Versions are tags of this repository; consumers pin a commit.

## [Unreleased]

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
