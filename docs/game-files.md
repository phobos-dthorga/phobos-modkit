# Game files: what a game writes, and what Steam records

**Status (19 Nov 2026):** built in 1.46.0, for any Steam game. D'thorga Companion's Game files page shows it from 0.22.0. Checked on
RimWorld (everything), Farming Simulator 25 (Steam's records; its data folder is not guessed) and Project Zomboid (its files, given
`--data`; it is not installed through Steam at the moment).

## Read this first (gotchas)

- **Only reads.** Nothing in the game, its saves or Steam is changed. Deleting old saves or caches is a decision the owner has not
  made (D'thorga Companion's `docs/later.md`).
- **"Since you last played" is Steam's last launch.** While the game is running, that is this session's launch, so the list is
  what updated while you played. `--since` moves the line.
- **The data folder is guessed by the game's name** in the usual homes of game data (`AppData\LocalLow`, `Documents\My Games`,
  `AppData\Local` and `Roaming`, `Documents`, the home folder), directly or one maker's folder down. A game whose folder is named
  otherwise (Project Zomboid's `Zomboid`, Farming Simulator 25's `FarmingSimulator2025`) needs `--data`; the Companion passes it
  from the game's `places` in its list.
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
| What changed since you last played | the game's `appmanifest_<id>.acf` (build, LastUpdated, LastPlayed, SizeOnDisk) and `workshop\appworkshop_<id>.acf` (each item's timeupdated and size); an item's title from its `About\About.xml` or `mod.info` where it has one | `game`, `changed` (`since`, `gameUpdated`, `workshop`, `workshopCount`, `workshopInstalled`) |
| Saves | the saves folder (`Saves` or `saves` in the data folder, or `--saves`); a folder holding only folders is a group, each save named "group / save" | `saves` (`list`, `count`, `bytes`, `autosaves`) |
| Screenshots | the game's own folder and Steam's (`userdata\<id>\760\remote\<appid>\screenshots`) | `screenshots` (`list`, `count`, `bytes`) |
| Space | each entry of the data folder; the install's and the Workshop items' sizes from Steam | `space` (`data`, `dataBytes`, `install`, `workshop`) |

Lists hold up to 200 entries; the counts and sizes cover everything. `places` says which folders were used.
