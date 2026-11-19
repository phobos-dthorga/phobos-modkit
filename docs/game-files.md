# Game files: what a game writes, and what Steam records

**Status (20 Nov 2026):** built in 1.46.0, for any Steam game. D'thorga Companion's Game files page shows it from 0.22.0. Checked on
RimWorld (everything), Farming Simulator 25 (Steam's records, and from 1.58.0 its data folder) and Project Zomboid (its files; from
1.58.0 its data folder is guessed too). **1.58.0 guesses better and offers candidates**, for the Companion's Add a game from Steam.

## Read this first (gotchas)

- **Only reads.** Nothing in the game, its saves or Steam is changed. Deleting old saves or caches is a decision the owner has not
  made (D'thorga Companion's `docs/later.md`).
- **"Since you last played" is Steam's last launch.** While the game is running, that is this session's launch, so the list is
  what updated while you played. `--since` moves the line. **`--since previous` means the launch before the last** (1.51.0):
  each report remembers the launch it sees in the kit's cache (`game-files/launches-<id>.json`, the newest 30), so while the
  game runs a program can still ask what changed since the session before; until the kit has seen an earlier launch it uses
  the last one and says so (`sincePrevious` false).
- **The data folder is guessed by the game's name** in the usual homes of game data (`AppData\LocalLow`, `Documents\My Games`,
  `AppData\Local` and `Roaming`, `Documents`, the home folder), directly or one maker's folder down. **From 1.58.0 Documents is
  where Windows keeps it** (`PHOBOS_DOCUMENTS` names it; the owner's is moved into SynologyDrive), and a name may differ in the
  ways games' folders do. A guess is a guess: `--data` overrides it, and the Companion passes the game's `places` from its list.
- **`steam-games` gives each game up to three candidates** (`dataGuesses`: `path`, `score`, `reason`), surest first:

  | Score | Rule | Example on the owner's PC |
  | --- | --- | --- |
  | 100 | named for the game | `Documents\Euro Truck Simulator 2` |
  | 90 | named for the game, with more after | `RimWorld by Ludeon Studios` (85: inside a maker's folder, 5 less) |
  | 80 | named for the game, numbered differently (8 letters or more, digits aside) | `FarmingSimulator2025` for Farming Simulator 25 |
  | 70 | named for the game's last word (7 letters or more) | `Zomboid` for Project Zomboid |
  | 60 | starts with the game's first word (8 letters or more), 3 to 6 letters more | `AutomationGame` |
  | 40 | named for the game, then a side word (mods, backup, tools, server...) | `Project Zomboid (mods)` |

  Hidden folders, temporary files and mod managers' or engines' folders (Vortex, Unreal Engine...) are not looked inside: Vortex keeps
  folders named for games. Folders are read with `os.scandir` (0.4 s on the owner's PC; 15 s before, `AppData\Local` holding 80,000
  folders one level down). Agent defaults, all.
- **Steam's folder** is `steamPath` (`PHOBOS_STEAM`), else Steam's usual place on each system.

## Use

```text
python -m phobos_modkit game-files report --name RimWorld
python -m phobos_modkit game-files report --name "Project Zomboid" --data "%USERPROFILE%\Zomboid"
python -m phobos_modkit game-files report --name RimWorld --since 2026-11-18
python -m phobos_modkit game-files steam-games
```

## What the report holds

| Part | From | `--json` (`data.`) |
| --- | --- | --- |
| What changed since you last played | the game's `appmanifest_<id>.acf` (build, LastUpdated, LastPlayed, SizeOnDisk) and `workshop\appworkshop_<id>.acf` (each item's timeupdated and size); an item's title from its `About\About.xml` or `mod.info` where it has one | `game`, `changed` (`since`, `gameUpdated`, `workshop`, `workshopCount`, `workshopInstalled`; 1.51.0: `sincePrevious`, `previousLaunchAt`, `launchesSeen`) |
| Saves | the saves folder (`Saves` or `saves` in the data folder, or `--saves`); a folder holding only folders is a group, each save named "group / save" | `saves` (`list`, `count`, `bytes`, `autosaves`) |
| Screenshots | the game's own folder and Steam's (`userdata\<id>\760\remote\<appid>\screenshots`) | `screenshots` (`list`, `count`, `bytes`) |
| Space | each entry of the data folder; the install's and the Workshop items' sizes from Steam | `space` (`data`, `dataBytes`, `install`, `workshop`) |

Lists hold up to 200 entries; the counts and sizes cover everything. `places` says which folders were used.
