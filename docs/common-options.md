# Common options: what the options many commands share do

The options below mean the same in every command that takes them, so each command's page names them in its generated block and
links here instead of explaining them again. A few commands use one of the names for something else; their rows say so.

## Read this first

- **A path left out is looked for in one order**: the option, then an environment variable, then the settings file `--settings`
  names, then the central settings file, then the default. [Settings](settings.md) explains the order, and
  `python -m phobos_modkit settings list` shows where each value in force comes from.
- **The defaults differ between commands where the option is a number** (`--top`): each page's generated block gives the
  command's own.
- **Every report takes `--json` and `--no-redact`.** The home folder is shown as `~` unless `--no-redact` is given.

## The options

| Option | What it does | When left out |
| --- | --- | --- |
| `--root VALUE` | The repository the command works on: its `config/` files, its changelogs, its git history | Usually the current folder (each command's help says). Run from the kit's `python/` folder, the kit's own repository is `..` |
| `--game VALUE` | RimWorld's install folder | `RIMWORLD_PATH`, then `rimworldPath` in a settings file, then Steam's default: `C:\Program Files (x86)\Steam\steamapps\common\RimWorld` on Windows |
| `--workshop VALUE` | The Workshop content folder, where subscribed mods are | `RIMWORLD_WORKSHOP_PATH`, then `workshopPath` in a settings file, then `steamapps/workshop/content/294100` beside the game's folder |
| `--config VALUE` | The game's Config folder, which holds `ModsConfig.xml`, the list of active mods | `RIMWORLD_CONFIG_PATH`, then `rimworldConfigPath` in a settings file, then the `Config` folder in the game's user data (`AppData\LocalLow\Ludeon Studios\RimWorld by Ludeon Studios` on Windows) |
| `--settings VALUE` | A JSON settings file whose keys name paths (`rimworldPath`, `workshopPath`, `rimworldConfigPath`, `modkitCachePath` and the others each help lists). A repository's thin callers pass its own (phobos-rimworld's `.local/install-settings.json`) | What the command's help names; most then read only the environment and the central settings file (`PHOBOS_SETTINGS`, else `settings.json` in D'thorga Companion's folder). A settings file that is missing or unreadable is read as empty |
| `--cache VALUE` | The kit's cache folder, where indexes, fetched pages and recordings are kept | `PHOBOS_MODKIT_CACHE`, then `modkitCachePath` in a settings file, then `phobos-modkit` in the system's temporary folder |
| `--top N` | Rows per table. A table cut short says so: "Showing 30 of 1,878" | The command's own default, in its block's Default column (15 to 60 for most) |
| `--json` | Print one JSON envelope instead of Markdown: `envelope` (its format), `tool`, `kit_version`, `report` (the same report as the Markdown) and `data` (anything of the command's own, described on its page). See [manifest](manifest.md#the-envelope) | Markdown, for a person |
| `--no-redact` | Show the home folder in full instead of `~`, in Markdown and JSON alike | The home folder is shown as `~`, whichever slashes a path uses |

## Where the names mean something else

| Command | Option | What it means there |
| --- | --- | --- |
| `rimworld-log` | `--json FILE` | Also write the full report as JSON to FILE; `-` prints only JSON |
| `changes`, `history`, `repos`, `pins`, `decisions`, `picks`, `issue-links`, `feeds`, `settings` | `--root` | Repeatable: one repository each time it is given |
| `history` | `--game` | The game whose history log to read, by name |
| `safe-copies` | `--game` | A game by name: the set it belongs to, or the list `config/safe-copies/GAME.json` to read |
| `cleanup` | `--config` | A rules file other than `ROOT/config/cleanup.json` |
| `gate` | `--config` | The step list, relative to the root (default `config/gate.json`) |

## Limits

- The paths here are RimWorld's, the one game whose files the kit reads so far. A next game's adapter adds its own keys and
  environment variables to the same order ([settings](settings.md)).
