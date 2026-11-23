# Test pass

What a repository's in-game test list is waiting for, from the game's seen-in-play notes and the owner's verdicts.

## Read this first (gotchas)

- **A seen-in-play note never passes a row.** It says a feature ran without an error, not that it looked right. A row the notes
  flag is "seen working, awaiting the owner's word" until the owner gives a verdict.
- **`apply` previews unless given `--apply`**, and then writes only inside the test list. It never removes text, except the
  "awaiting the owner's word" note on a row that has just had its verdict, or that is written again naming more parts, or that
  no note read stands for any more (1.19.1; never when no notes were read at all, so a missing notes file takes nothing back).
- **The repository says where its test list is**, in `config/test-evidence.json`. Without that file the tool stops and says so.
- **Since 1.19.0 a sighting can be weaker than it looks, and the report says so**: notes whose figures miss what the row expects,
  notes older than the row, and notes out of the order a rule demands are listed apart and do not mark a row seen.

## Run it

```text
python -m phobos_modkit test-pass report --root REPO              rows waiting, rows seen working, verdicts not yet written
python -m phobos_modkit test-pass apply --root REPO               what apply would write (a preview)
python -m phobos_modkit test-pass apply --root REPO --apply       write it
python -m phobos_modkit test-pass code --root REPO                where the code notes each row's keys (1.36.0)
```

`--seen PATH` (repeatable) and `--verdicts PATH` name other files; `--all` lists every row; `--json` gives every row's cells,
sightings, verdict and the sentence apply would add, for a program such as D'thorga Companion.

## Where the code notes each row: `code` (1.36.0)

`code` finds every string in the repository's C#, Lua and Python that is a key the map names, or starts with one of its `prefixes`,
and places it in the method, function or type whose lines hold it (phobos-modkit's `connections`). Its JSON gives `places`, each
`{key, prefix, file, line, thing, rows}`, and `unplaced`: keys the map names that no string in the code matches as written. Folders
named `tests` or `test` are skipped, since a test naming a key is not where the game notes it. D'thorga Companion joins rows to
code with it: a row's code, and a method's rows. It reads text, so a key in a comment counts too.

## The repository's evidence map: `config/test-evidence.json`

| Field | What it holds |
| --- | --- |
| `doc` | The test list's path in the repository: Markdown tables whose first column is `#` and last column says what passes |
| `game` | Optional: the game adapter that knows where the mod writes its notes (`rimworld`) |
| `rows` | Each row's id, and its evidence: a list (the whole row), or `{"parts": {"name": [...]}}` for a row in parts |
| `prefixes` | Keys the mod builds at run time, by their start, with what follows |
| `order` | Rules on the order of notes on one thing: `{"name", "row", "first": evidence, "then": evidence}` |
| `shared` | Keys with nothing narrowing them that stand for more than one row on purpose, with why |
| `unrowed` | Keys that need no row, with why |
| `versionNames` | How each mod is written in rows (`{"D'thorga Framework": "Framework"}`, or a list), for sightings older than the row |

**A piece of evidence** is a key, or an object narrowing it:

| Field | Meaning |
| --- | --- |
| `key` | The note's key |
| `variant` | Only notes of this case (a stage's label) |
| `detail` | Only notes whose detail fits this wildcard, ignoring case (`"*track*"`) |
| `expect` | The figures it should show: `{"W": ">= 300", "loadsA": "> 0"}`; forms `>= N`, `> N`, `<= N`, `< N`, `= N`, `A..B` |

**How a part is judged**, from its matching notes: notes older than the newest version of their mod the row names are *stale*; a
fresh note that meets every expectation counts (*expected* when the item has any, *seen* when not); fresh notes that never do are
*off*. A row is seen working when a part counts. **An order rule** is broken by a `then` note on a thing with no `first` note on the
same thing since its last `then`; notes without `on` cannot be checked and are counted. `map_problems` (and the report's "Left out")
names a key with nothing narrowing it that stands for several rows without a `shared` entry; `mapped_keys` gives every key the map
names, for a repository's own checks.

A row's status is read from its last cell: `Passed in part` or a lower-case "passed: the owner" (part of a row) is passed in
part, `Passed` is passed, `**Failed` is failed, "Seen working by the game" is seen; the last of these in the cell decides.

## The seen-in-play notes

JSON lines a mod writes the first time each feature is seen working in a session. RimWorld: `PhobosSnapshots/SeenInPlay.jsonl`
beside the Config folder, written by phobos-rimworld's D'thorga Framework 0.118.0 and later with its setting on (or
`RIMWORLD_SEEN_IN_PLAY`, `rimworldSeenInPlayPath`).

```json
{"format":1,"time":"2026-11-17T12:00:00Z","key":"vehicles.field-refit","mod":"D'thorga Framework","version":"0.118.0","detail":"M1A2: left track"}
```

Optional since 1.19.0 (D'thorga Framework 0.138.0 writes them): `on`, a stable name for what it was seen on; `kind`, what kind of
thing that is; `variant`, which case of the feature; `values`, figures by name as numbers. Readers ignore fields they do not know.

```json
{"format":1,"time":"2026-11-19T12:00:00Z","key":"vehicles.grid-hook-up","mod":"D'thorga Framework","version":"0.138.0","detail":"M2A3 Bradley: 960 W","on":"Vehicle_M2A3Bradley412","kind":"M2A3Bradley","values":{"W":960,"loadsA":30,"chargingA":4}}
```

## The owner's decisions on notes no row names

JSON lines D'thorga Companion writes beside its verdicts (`test-key-decisions/<repository folder>.jsonl`, or
`PHOBOS_TEST_KEY_DECISIONS`, or a settings file's `companionTestKeyDecisionsPath`, or `--decisions`): `key`, `decision`
(`make-row`, `no-row` or `cleared`), `time` and an optional `note`. The latest line for a key wins. "No row needed" leaves the key out
of the report; "make a row" marks it as a request for the next session that edits the test list.

## The owner's verdicts

JSON lines, one per click, written by D'thorga Companion's Tests page: by default
`org.phobosdthorga.companion/test-verdicts/<repository folder>.jsonl` in the system's local application data (`LOCALAPPDATA` on
Windows), or `PHOBOS_TEST_VERDICTS`, or a settings file's `companionTestVerdictsPath`. The latest line for a row wins;
`cleared` takes a verdict back. A verdict is `passed`, `partial` (part of the row passed, the note saying which), `failed` or
`cleared`; an optional `via` says where it was given (`companion`, the default, or `conversation`).

```json
{"format":1,"time":"2026-11-17T12:05:00Z","row":"127","verdict":"passed","note":"re-fitted on the M1A2"}
```

**A verdict the owner gives an agent in conversation** goes in on the command line, never copied into the list by hand:

```text
python -m phobos_modkit test-pass apply --root REPO --verdict "55:partial:the landing; placing by hand not seen" --apply
```

`--verdict ROW:WORD[:NOTE]` is repeatable, takes `passed`, `partial` or `failed`, is stamped with the time it is run, replaces any
verdict in the file for its row, and is written "in conversation". `report` takes it too, to preview. A badly written one is
refused with what to give.

## What apply writes

| Case | Sentence added to the row's last cell |
| --- | --- |
| A verdict, passed | `**Passed: the owner, 17 Nov 2026, through D'thorga Companion: note.**` |
| A verdict, passed in part | `**Passed in part: the owner, 17 Nov 2026, through D'thorga Companion: note.**` |
| A verdict, failed | `**Failed: the owner, 17 Nov 2026, through D'thorga Companion: note.**` |
| A verdict given in conversation | the same, with `in conversation` in place of `through D'thorga Companion` |
| Seen, no verdict, row open or passed in part | `**Seen working by the game, 17 Nov 2026 (D'thorga Framework 0.118.0); awaiting the owner's word.**` |

A sentence already in the cell is not added again, so running apply twice changes nothing the second time.

## Reports and options

<!-- generated: options test-pass -->
Generated from the command's own parser by `python -m phobos_modkit command-docs --write`: change a help text in the parser, not here.

| Report | What it does | Effect |
| --- | --- | --- |
| `report` | Rows waiting for the owner, rows seen working, verdicts not yet written. | reads only |
| `apply` | Write verdicts and seen-working notes into the test list; a preview without `--apply`. | writes, with `--apply` |
| `code` | Where the code notes each row's keys, and in which method, function or type. Where the code notes each row's keys; for a program joining rows to code. | reads only |

| Option | Reports | What it does | Default |
| --- | --- | --- | --- |
| `--root VALUE` | all | the repository (default: the current folder) |  |
| `--seen VALUE` | `report`, `apply` | a seen-in-play notes file (repeatable; default: from the config's game) |  |
| `--verdicts VALUE` | `report`, `apply` | the owner's verdicts file (default: D'thorga Companion's, for this repository) |  |
| `--decisions VALUE` | `report`, `apply` | the owner's decisions on notes no row names (default: D'thorga Companion's) |  |
| `--settings VALUE` | `report`, `apply` | a JSON settings file naming paths |  |
| `--verdict ROW:WORD[:NOTE]` | `report`, `apply` | a verdict the owner gave in conversation (WORD passed, partial or failed; repeatable) |  |
| `--all` | `report`, `apply` | list every row, not only those waiting |  |
| `--top N` | `report`, `apply` | rows per table (default 40) | `40` |
| `--apply` | `apply` | write the test list; without it, only show what would change |  |
| `--top N` | `code` | places to list (default 40) | `40` |

Every report also takes `--json` (print JSON instead of Markdown) and `--no-redact` (show the home folder instead of ~).
<!-- end generated -->
