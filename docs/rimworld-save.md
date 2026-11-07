# RimWorld save index

**Answer first.** `rimworld-save` answers questions about a RimWorld save (pawns, hediffs, where a thing is, what a
map holds) from a SQLite index instead of the 300 MB file. The first question indexes a frozen copy of the save in
about a second and a half; later questions take well under a second until the save changes.

## Read this first (gotchas)

- **Build the indexer once:** add `--build-indexer` to any command. It is a Rust program (Rust comes from
  [rustup](https://rustup.rs)), built into `%LOCALAPPDATA%\phobos-modkit\target` on Windows or
  `~/.cache/phobos-modkit/target` elsewhere, never into a repository that might be cloud-synced.
  `PHOBOS_MODKIT_BUILD` chooses another folder; a `cargo build --release` in this repository is found too.
- **The save is only ever read.** Each index is built from a copy, deleted straight afterwards, because the game
  may write the save while it is being read. If the save changes during the copy, the command says so; run it again.
- **Indexes hold data from your saves**, so they live under the system's temp folder by default, which cloud-sync
  tools usually leave alone. Choose another place with `--cache`, `PHOBOS_MODKIT_CACHE` or `modkitCachePath`.
- **Options go after the report's name**: `rimworld-save pawns --save PG1`, not `rimworld-save --save PG1 pawns`.
- **Patches and mods are not applied.** The index holds what the save file says, nothing more: a def's name, never
  its label, and a body part's index, never its name.
- Checked against RimWorld 1.7.5000 saves (November 2026).

## Run it

```text
python -m phobos_modkit rimworld-save                          summary of the newest save
python -m phobos_modkit rimworld-save pawns --faction player   the colony's pawns
python -m phobos_modkit rimworld-save things --def "Chunk*" --list
python -m phobos_modkit rimworld-save hediffs --pawn Abbeson
python -m phobos_modkit rimworld-save find ChunkA8061017       one thing and what holds it
python -m phobos_modkit rimworld-save schema --under savegame/game/maps/li --depth 1
python -m phobos_modkit rimworld-save sql "SELECT def, COUNT(*) FROM thing GROUP BY def"
```

| Report | What it shows | Its options |
| --- | --- | --- |
| `summary` (the default) | Version, scenario, days since the colony began, maps, where things are, the player's pawns by race, the commonest things | |
| `index` | Indexes the save again now, then the summary | |
| `schema` | Element paths in the save with how often each occurs, to find where something is saved | `--under PATH`, `--depth N` |
| `things` | Things counted by def, or listed one per row | `--def`, `--class`, `--map`, `--place`, `--held` or `--loose`, `--list` |
| `pawns` | Name, ID, race, kind, faction, place, map and position, age, health state, how many hediffs | `--faction` (`player` or a name), `--name`, `--kind`, `--place` |
| `hediffs` | Hediffs counted by def, or one pawn's in full with body part, severity, age and source | `--pawn`, `--def` |
| `find ID` | A thing by its ID, with every thing holding it out to the map or world | |
| `sql QUERY` | Any query; the index is opened read-only, so nothing can change it | |

Every report takes `--save NAME` (default: the newest save), `--saves`, `--cache`, `--index FILE` (read an index
directly), `--rebuild`, `--top N`, `--json` and `--no-redact`. Filters ignore case; `*` and `?` are wildcards, and
`_` is an ordinary character.

## What the index holds

| Table or view | Rows |
| --- | --- |
| `game` | The save's version, ticks, starting year, scenario and play time |
| `mods` (view of `mod_id`, `mod_name`, `mod_steam_id`) | The save's mod list, in load order |
| `faction` | Every faction's load ID, def and name; things name it as `Faction_<load ID>` |
| `map` | Each map's position, generator, size and world object |
| `thing` | Every thing on a map, held by another thing, or a world pawn: def, ID, class, stuff, stack, hit points, quality, forbidden, map, position, faction, the thing holding it |
| `pawn` | The pawn part of a thing (same `id`): kind, gender, name parts, health state, biological age, backstories |
| `hediff`, `trait`, `skill` | Each belongs to a pawn by its `id` |
| `thing_place` (view) | For each thing, the outermost thing holding it, whether it is held, its place and map |
| `pawn_view` (view) | Pawns with display name, race, faction name, place, map, position and age in years |
| `element_path` | Every element path in the save and how often it occurs |
| `meta` | The source save's name, size and time, the schema's hash, the indexer's version |

The schema is `python/phobos_modkit/games/rimworld/save-schema.toml`. Adding a table or column there is all it
takes to index more; changing the file makes older indexes rebuild on their next use.

## How fast (7 Nov 2026, on the owner's high-end PC)

| Step | Time |
| --- | --- |
| Index PG2 (308 MB, 8.2 million elements; 84,608 things, 990 pawns, 9,110 hediffs) | 1.4 s, plus about 1 s to copy |
| Any report afterwards | about 0.6 s, mostly starting Python |
| The same save read once by Python's own XML reader, for comparison | 7.6 s |
