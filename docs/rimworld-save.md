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
- **Grids name their Defs through the Def index** of the installed mods (see [the Def index](rimworld-defs.md)),
  built on first use. A save made with other mods may show some cells as `#number`; `--no-names` skips the mods.
- **`diff` compares by ID.** Things are matched by their ID and hediffs by their load ID, both kept for life; a
  thing destroyed and rebuilt is a different thing. World objects are matched by their ID too, and component values
  by component class, map and path; narrow the component sections with `--component`, as tick counters change in
  every save.
- **A mod's saved state is readable** through `components`: every value with text inside the game's, the world's
  and each map's components, with its path inside the component. A mod that keeps its state elsewhere (in a thing's
  comp, a Def, its own file) is not covered.
- Checked against RimWorld 1.7.5000 saves (November 2026).

## Run it

```text
python -m phobos_modkit rimworld-save                          summary of the newest save
python -m phobos_modkit rimworld-save pawns --faction player   the colony's pawns
python -m phobos_modkit rimworld-save things --def "Chunk*" --list
python -m phobos_modkit rimworld-save hediffs --pawn Abbeson
python -m phobos_modkit rimworld-save find ChunkA8061017       one thing and what holds it
python -m phobos_modkit rimworld-save schema --under savegame/game/maps/li --depth 1
python -m phobos_modkit rimworld-save grid --map 0                   every grid layer of a map, counted
python -m phobos_modkit rimworld-save grid --kind gas --render       one layer, with a text picture
python -m phobos_modkit rimworld-save grid --at 137,266              every layer at one cell, and what stands there
python -m phobos_modkit rimworld-save world --faction "Ryūmon*"     one faction's settlements and sites
python -m phobos_modkit rimworld-save components --class "*RimPacts*" --path "defendMission/*"
python -m phobos_modkit rimworld-save diff Autosave-12               what changed since an earlier save
python -m phobos_modkit rimworld-save diff PG2 --component "*RimPacts*"   the same, one mod's state only
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
| `world` | World objects counted by def and faction, or listed with ID, name, faction and tile | `--def`, `--faction`, `--name` |
| `components` | The game's, the world's and maps' components with how many values each holds, or the values inside them with their paths | `--class`, `--path`, `--value`, `--map` |
| `grid` | A map's layers counted: terrain, foundations (bridges and the like), roofs, each gas, fog, snow, pollution and deep resources; one layer in full with a text picture (north up); or every layer at one cell with the things standing there | `--map`, `--kind`, `--render`, `--gas`, `--columns`, `--at X,Z`, `--area X1,Z1,X2,Z2`, `--no-names` |
| `diff OTHER` | What changed since another save: counts, things that appeared and went by def, stacks that grew or shrank, pawns that moved, arrived or left, pawns' hediffs gained, lost, worse or better, world objects that changed faction, appeared or went, and component values that changed and lists that grew or shrank | `--faction` (`player` by default, `any`, or a faction), `--component` |
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
| `map_grid` | Each map's grids as the save holds them (base64 text), with the grid's element and owner |
| `world_object` | Every world object (settlements, sites, caravans, destroyed settlements): def, class, ID, tile, faction, name |
| `component`, `component_value` | The game's, the world's and each map's components (class, position, map), and every value with text inside one (its tag, place among same-named siblings and text); `element_path` gives its full path |
| `world_object_view`, `component_view` (views) | World objects with their faction's name and def; component values with the component's class, scope, map and the path inside the component |
| `element_path` | Every element path in the save and how often it occurs |
| `meta` | The source save's name, size and time, the schema's hash, the indexer's version |

The schema is `python/phobos_modkit/games/rimworld/save-schema.toml`. Adding a table or column there is all it
takes to index more; changing the file makes older indexes rebuild on their next use.

## How the grids are stored

Summarised in our own words from the RimWorld 1.7 game code (November 2026):

| Layer | Stored as |
| --- | --- |
| Terrain (top, under, foundation), roofs, deep resources | A 16-bit Def number per cell; 0 is none |
| Deep resource counts | A 16-bit count per cell |
| Gas | A 32-bit number per cell: blind smoke, toxic gas, rot stink and deadlife dust as one byte each (0 to 255), lowest first |
| Snow | A 16-bit fraction of full depth per cell |
| Fog, pollution | One bit per cell, lowest bit first |

Every grid is base64, of raw deflate when that is smaller (the element name then ends in "Deflate"); cells run row by
row from the south-west corner (index = z times width plus x). A Def's number is the game's StableStringHash of its
defName, modulo 65535; when two Defs of one type share a number, the later in defName order moves to the next free
one. That tie order is approximated, so names whose number moved are marked `(?)`. Terrain the game makes in code
(rough, hewn and smooth stone; carpets) is named through the Def index's game-made rows.

## How fast (7 Nov 2026, on the owner's high-end PC)

| Step | Time |
| --- | --- |
| Index PG2 (308 MB, 8.2 million elements; 84,608 things, 990 pawns, 9,110 hediffs) | 1.4 s, plus about 1 s to copy |
| Any report afterwards | about 0.6 s, mostly starting Python |
| Decode all ten grids of a 325 by 325 map | 0.02 s |
| `diff` of two indexed saves, two in-game days apart | about 4 s |
| Index PG3 (365 to 420 MB, 11.3 million elements, with 1.08 million component values; 8 Nov 2026) | 3.5 s |
| `diff` with `--component` of two such saves | about 6 s |
| The same save read once by Python's own XML reader, for comparison | 7.6 s |
