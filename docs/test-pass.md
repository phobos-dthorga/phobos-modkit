# Test pass

What a repository's in-game test list is waiting for, from the game's seen-in-play notes and the owner's verdicts.

## Read this first (gotchas)

- **A seen-in-play note never passes a row.** It says a feature ran without an error, not that it looked right. A row the notes
  flag is "seen working, awaiting the owner's word" until the owner gives a verdict.
- **`apply` previews unless given `--apply`**, and then writes only inside the test list. It never removes text, except the
  "awaiting the owner's word" note on a row that has just had its verdict.
- **The repository says where its test list is**, in `config/test-evidence.json`. Without that file the tool stops and says so.

## Run it

```text
python -m phobos_modkit test-pass report --root REPO              rows waiting, rows seen working, verdicts not yet written
python -m phobos_modkit test-pass apply --root REPO               what apply would write (a preview)
python -m phobos_modkit test-pass apply --root REPO --apply       write it
```

`--seen PATH` (repeatable) and `--verdicts PATH` name other files; `--all` lists every row; `--json` gives every row's cells,
sightings, verdict and the sentence apply would add, for a program such as D'thorga Companion.

## The repository's evidence map: `config/test-evidence.json`

| Field | What it holds |
| --- | --- |
| `doc` | The test list's path in the repository: Markdown tables whose first column is `#` and last column says what passes |
| `game` | Optional: the game adapter that knows where the mod writes its notes (`rimworld`) |
| `rows` | Each row's id, and the note keys that stand as evidence for it |
| `prefixes` | Keys the mod builds at run time, by their start, with what follows |

A row's status is read from its last cell: `Passed in part` or a lower-case "passed: the owner" (part of a row) is passed in
part, `Passed` is passed, `**Failed` is failed, "Seen working by the game" is seen; the last of these in the cell decides.

## The seen-in-play notes

JSON lines a mod writes the first time each feature is seen working in a session. RimWorld: `PhobosSnapshots/SeenInPlay.jsonl`
beside the Config folder, written by phobos-rimworld's D'thorga Framework 0.118.0 and later with its setting on (or
`RIMWORLD_SEEN_IN_PLAY`, `rimworldSeenInPlayPath`).

```json
{"format":1,"time":"2026-11-17T12:00:00Z","key":"vehicles.field-refit","mod":"D'thorga Framework","version":"0.118.0","detail":"M1A2: left track"}
```

## The owner's verdicts

JSON lines, one per click, written by D'thorga Companion's Tests page: by default
`org.phobosdthorga.companion/test-verdicts/<repository folder>.jsonl` in the system's local application data (`LOCALAPPDATA` on
Windows), or `PHOBOS_TEST_VERDICTS`, or a settings file's `companionTestVerdictsPath`. The latest line for a row wins;
`cleared` takes a verdict back.

```json
{"format":1,"time":"2026-11-17T12:05:00Z","row":"127","verdict":"passed","note":"re-fitted on the M1A2"}
```

## What apply writes

| Case | Sentence added to the row's last cell |
| --- | --- |
| A verdict, passed | `**Passed: the owner, 17 Nov 2026, through D'thorga Companion: note.**` |
| A verdict, failed | `**Failed: the owner, 17 Nov 2026, through D'thorga Companion: note.**` |
| Seen, no verdict, row open or passed in part | `**Seen working by the game, 17 Nov 2026 (D'thorga Framework 0.118.0); awaiting the owner's word.**` |

A sentence already in the cell is not added again, so running apply twice changes nothing the second time.
