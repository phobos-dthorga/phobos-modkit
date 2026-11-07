# RimWorld log triage

**Answer first.** `rimworld-log` reads RimWorld's `Player.log`, groups its messages, compares them with the run
before, and names the mods each message points at. A 2 MB log becomes a summary of about 8 KB. It works while the
game is running.

## Read this first (gotchas)

- **A mod named under "Points at" was involved, not necessarily at fault.** The clues are listed strongest
  first; Harmony patches on the stack are the weakest.
- **Read "One exception, several messages" before the main table.** One fault often shows as many signatures
  that differ only by a pawn's or a thing's name.
- **"Compared with" counts depend on what you did in each run.** When only one run loaded a save, the summary says
  so, because everything from play then shows as new or gone.
- **When the game hits its message limit it stops logging its own messages.** The summary warns you; anything
  after that point is missing, so restart the game and reproduce the fault early in a session.
- The home folder is shown as `~`, so the output can go into a bug report. Use `--no-redact` to see it.
- Tested on logs from RimWorld 1.7.5000 (November 2026). The older 1.6 layout is read in a basic way and has not
  been checked against a real 1.6 log.

## Run it

```text
python -m phobos_modkit rimworld-log                  Player.log against Player-prev.log
python -m phobos_modkit rimworld-log --show 1a2b3c4d  one signature in full
python -m phobos_modkit rimworld-log old.log --no-previous --json report.json
```

Run it from the `python` folder of this repository, or put that folder on `PYTHONPATH`. Game repositories that pin
this kit provide their own short command (phobos-rimworld: `python scripts/triage-log.py`).

| Option | What it does |
| --- | --- |
| `LOG` | The log to read. Default: `Player.log` in the logs folder |
| `--previous FILE` / `--no-previous` | Compare with another log, or with none. Default: `Player-prev.log` beside a `Player.log` |
| `--show ID` | Print one signature in full: its first message as written, every clue, the lines it occurs on |
| `--top N` | How many signatures to list (default 20) |
| `--levels ERROR,WARN` | Which levels to list; add `INFO` for everything |
| `--json FILE` | Also write everything as JSON; `--json -` prints only JSON |
| `--logs`, `--game`, `--workshop` | Where the logs, the game and the Workshop folder are |
| `--settings FILE` | A JSON file with `rimworldLogsPath`, `rimworldPath` and `workshopPath` |
| `--no-mods` | Do not read installed mods; clues stay unnamed |
| `--no-redact` | Show the home folder instead of `~` |

Each folder comes from the option, then an environment variable (`RIMWORLD_LOGS_PATH`, `RIMWORLD_PATH`,
`RIMWORLD_WORKSHOP_PATH`), then the settings file, then Steam's usual place on Windows. The Linux and macOS
defaults are Unity's and Steam's usual places and have not been checked.

## What the summary holds

1. **Notices:** the save that was loaded and the mods the game marked (for example "incompatible version"),
   where the game stopped logging, engine memory warnings, and Harmony finalizers on failing stacks.
2. **Counts** by level.
3. **Signatures:** messages that differ only in numbers, IDs and codes, most severe and most frequent first,
   each with a short ID for `--show`.
4. **One exception, several messages:** signatures whose first messages share an exception trace.
5. **Compared with the previous run:** new, gone and changed signatures.

## How mods are named

| Clue | Where it comes from | Strength |
| --- | --- | --- |
| source | `[Source: <mod>]` lines and XML Extensions' `[<mod> - Start of stack trace]` | Names the mod outright |
| file | A path into a Workshop item (`294100\<id>\`) or the game's `Mods\<folder>\` | Strong |
| assembly | `in <Some>.dll:token` in the exception's own trace | Strong; the first one is nearest the fault |
| namespace | A type in the exception's own trace outside the game's namespaces | Good |
| caller | The first mod code on the stack that wrote a message without an exception | Fair |
| patch | `- PREFIX <harmony id>:` lines under a stack frame | Weak: involved, rarely the cause |
| finalizer | A Harmony finalizer on the stack | Weak, and it can hide where an exception began |

Clues become mod names through an index of installed mods: each mod's `About.xml` and the file names in its
`Assemblies` folders. Assemblies are never opened or run. A namespace matches a mod when it equals one of the
mod's assembly names or the last part of its package ID; a Harmony ID matches a package ID.
