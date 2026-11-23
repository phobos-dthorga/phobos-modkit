# RimWorld log triage

`rimworld-log` reads RimWorld's `Player.log`, groups its messages, compares them with the run before, and names the mods each
message points at. A 2 MB log becomes a summary of about 8 KB. It works while the game is running.

## Read this first

- **A mod named under "Points at" was involved, not necessarily at fault.** The clues are listed strongest
  first; Harmony patches on the stack are the weakest.
- **Read "One exception, several messages" before the main table.** One fault often shows as many signatures
  that differ only by a pawn's or a thing's name.
- **"Compared with" counts depend on what you did in each run.** When only one run loaded a save, the summary says
  so, because everything from play then shows as new or gone.
- **When the game hits its message limit it stops logging its own messages.** The summary warns you; anything
  after that point is missing, so restart the game and reproduce the fault early in a session.
- **The home folder is shown as `~`**, so the output can go into a bug report. Use `--no-redact` to see it.

## Examples

```text
python -m phobos_modkit rimworld-log                  Player.log against Player-prev.log
python -m phobos_modkit rimworld-log --show 1a2b3c4d  one signature in full
python -m phobos_modkit rimworld-log old.log --no-previous --json report.json
```

Run it from the `python` folder of this repository, or put that folder on `PYTHONPATH`. Game repositories that pin
this kit provide their own short command (phobos-rimworld: `python scripts/triage-log.py`).

## Reports and options

<!-- generated: options rimworld-log -->
Generated from the command's own parser by `python -m phobos_modkit command-docs --write`: change a help text in the parser, not here.

Effect: reads only.

| Option | What it does | Default |
| --- | --- | --- |
| `LOG` | (optional) the log to read (default: Player.log in the logs folder) |  |
| `--previous VALUE` | the log to compare with (default: Player-prev.log beside a Player.log) |  |
| `--no-previous` | do not compare with another log |  |
| `--show ID` | print one signature in full (an ID, or the start of one) |  |
| `--top N` | signatures to list (default 20) | `20` |
| `--levels VALUE` | levels to list, comma-separated (default FATAL,ERROR,WARN,UNKNOWN; add INFO for everything) | `FATAL,ERROR,WARN,UNKNOWN` |
| `--brief` | with `--json`, keep only the `--top` signatures of the listed levels, without their line lists: a page's worth |  |
| `--logs VALUE` | the logs folder (else RIMWORLD_LOGS_PATH, the settings file, the default) |  |
| `--game VALUE` | the RimWorld folder, for naming mods (else RIMWORLD_PATH, settings, default) |  |
| `--workshop VALUE` | the Workshop content folder (else RIMWORLD_WORKSHOP_PATH, settings, beside the game) |  |
| `--no-mods` | do not read installed mods; clues stay unnamed |  |
| `--settings VALUE` | a JSON settings file with rimworldLogsPath, rimworldPath and workshopPath |  |

- It also takes `--json` (also write the full report as JSON to FILE; - prints only JSON) and `--no-redact` (show the home folder instead of ~).
- Names in capitals are given bare, without a flag, in the order shown.
- A path left out is looked for in the order [settings](settings.md) explains: an environment variable, the repository's own settings file, the central settings file, then the default.
- [Common options](common-options.md) explains `--game`, `--workshop`, `--settings`, `--top`, `--json` and `--no-redact`, which many commands share.
<!-- end generated -->

## Inputs

Each folder comes from the option, then an environment variable (`RIMWORLD_LOGS_PATH`, `RIMWORLD_PATH`,
`RIMWORLD_WORKSHOP_PATH`), then the settings file, then Steam's usual place on Windows.

## Outputs

`--json FILE` also writes everything as JSON, in the envelope with the signatures under `data`, and `--json -` prints only JSON.
With `--brief` the JSON keeps as many of each comparison list too (with `counts` for all): about 300 KB from a 200,000-line log,
which D'thorga Companion's Logs page reads.

### What the summary holds

1. **Notices:** the save that was loaded and the mods the game marked (for example "incompatible version"),
   where the game stopped logging, engine memory warnings, and Harmony finalizers on failing stacks.
2. **Counts** by level.
3. **Signatures:** messages that differ only in numbers, IDs and codes, most severe and most frequent first,
   each with a short ID for `--show`.
4. **One exception, several messages:** signatures whose first messages share an exception trace.
5. **Compared with the previous run:** new, gone and changed signatures.

### Stack frames

Each signature's JSON carries `frames`: its first message's stack, nearest the fault first, at most 16. Each frame has `method`
(`Namespace.Type.Method`, with Harmony's `_PatchN` taken off), `file` and `line` where the trace names its source, and `assembly`
where it names a DLL; what the log does not give is empty or 0. A message with no exception trace gives the stack that logged it,
less the game's own `Verse.Log` frames. A program can look a frame's method up in its code (phobos-modkit's `connections`).

### How mods are named

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

## Limits

- Tested on logs from RimWorld 1.7.5000 (November 2026). The older 1.6 layout is read in a basic way and has not
  been checked against a real 1.6 log.
- The Linux and macOS default folders are Unity's and Steam's usual places and have not been checked.
