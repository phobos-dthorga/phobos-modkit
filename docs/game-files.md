# Game files: what a game writes, and what Steam records

For any Steam game. D'thorga Companion's Game files page shows it, and its Add a game from Steam takes the data-folder
candidates `steam-games` offers.

## Read this first

- **Only reads.** Nothing in the game, its saves or Steam is changed. Deleting old saves or caches is a decision the owner has not
  made (D'thorga Companion's `docs/later.md`).
- **"Since you last played" is Steam's last launch.** While the game is running, that is this session's launch, so the list is
  what updated while you played. `--since` moves the line. **`--since previous` means the launch before the last**:
  each report remembers the launch it sees in the kit's cache (`game-files/launches-<id>.json`, the newest 30), so while the
  game runs a program can still ask what changed since the session before; until the kit has seen an earlier launch it uses
  the last one and says so (`sincePrevious` false).
- **The data folder is guessed by the game's name**, and a guess is a guess: `--data` overrides it, and the Companion passes the
  game's `places` from its list. [How the data folder is guessed](#how-the-data-folder-is-guessed) gives the rules.

## Examples

```text
python -m phobos_modkit game-files report --name RimWorld
python -m phobos_modkit game-files report --name "Project Zomboid" --data "%USERPROFILE%\Zomboid"
python -m phobos_modkit game-files report --name RimWorld --since 2026-11-18
python -m phobos_modkit game-files steam-games
python -m phobos_modkit game-files screenshots --name RimWorld
```

## Reports and options

<!-- generated: options game-files -->
Generated from the command's own parser by `python -m phobos_modkit command-docs --write`: change a help text in the parser, not here.

| Report | What it does | Effect |
| --- | --- | --- |
| `report` | What changed since you last played, saves, screenshots and space, for one game. What changed since you last played, saves, screenshots and space, for one game. | reads only |
| `steam-games` | Every game Steam has installed on this PC. Every game Steam has installed on this PC. | reads only |
| `screenshots` | Only one game's screenshots, quickly: the same folders as the report. Only one game's screenshots, quickly, for a gallery. | reads only |

| Option | Reports | What it does | Default |
| --- | --- | --- | --- |
| `--name VALUE` | `report`, `screenshots` | the game's name, as Steam shows it. Required. |  |
| `--app-id N` | `report`, `screenshots` | its Steam app ID, when its name is not enough |  |
| `--data VALUE` | `report`, `screenshots` | its data folder (default: guessed from its name) |  |
| `--saves VALUE` | `report` | its saves folder (default: inside the data folder) |  |
| `--screenshots VALUE` | `report`, `screenshots` | its own screenshots folder (default: inside the data folder) |  |
| `--since VALUE` | `report` | list Workshop items updated since this time (default: the last launch); 'previous' for the launch before the last, as far as the kit has seen (1.51.0: while the game runs) |  |

- Every report also takes `--json` (print JSON instead of Markdown) and `--no-redact` (show the home folder instead of ~).
- [Common options](common-options.md) explains `--json` and `--no-redact`, which many commands share.
<!-- end generated -->

## Inputs

### How the data folder is guessed

The data folder is looked for by the game's name in the usual homes of game data (`AppData\LocalLow`, `Documents\My Games`,
`AppData\Local` and `Roaming`, `Documents`, the home folder), directly or one maker's folder down. **Documents is where Windows
keeps it** (`PHOBOS_DOCUMENTS` names it; the owner's is moved into SynologyDrive), and a name may differ in the ways games'
folders do.

**`steam-games` gives each game up to three candidates** (`dataGuesses`: `path`, `score`, `reason`), surest first:

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

### Steam's folder

`steamPath` (`PHOBOS_STEAM`), else Steam's usual place on each system.

## Outputs

### What the report holds

| Part | From | `--json` (`data.`) |
| --- | --- | --- |
| What changed since you last played | the game's `appmanifest_<id>.acf` (build, LastUpdated, LastPlayed, SizeOnDisk) and `workshop\appworkshop_<id>.acf` (each item's timeupdated and size); an item's title from its `About\About.xml` or `mod.info` where it has one | `game`, `changed` (`since`, `gameUpdated`, `workshop`, `workshopCount`, `workshopInstalled`, `sincePrevious`, `previousLaunchAt`, `launchesSeen`) |
| Saves | the saves folder (`Saves` or `saves` in the data folder, or `--saves`); a folder holding only folders is a group, each save named "group / save" | `saves` (`list`, `count`, `bytes`, `autosaves`) |
| Screenshots | the game's own folder and Steam's (`userdata\<id>\760\remote\<appid>\screenshots`) | `screenshots` (`list`, `count`, `bytes`) |
| Space | each entry of the data folder; the install's and the Workshop items' sizes from Steam | `space` (`data`, `dataBytes`, `install`, `workshop`) |

Lists hold up to 200 entries; the counts and sizes cover everything. `places` says which folders were used.

### What screenshots holds

**`screenshots` lists only the pictures**, from the same folders the report reads, without sizing the data folder or the
saves: 0.3 s for the owner's 330 RimWorld screenshots, where the report walks gigabytes. `data` holds `folders`, `list` (up to 2,000,
newest first: `path`, `name`, `bytes`, `taken`, `source`), `count` and `bytes`. D'thorga Companion's screenshot gallery reads it.

## Limits

- Checked on RimWorld (everything), Farming Simulator 25 (Steam's records, and its data folder) and Project Zomboid (its files,
  and its data folder guessed).
