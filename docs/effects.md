# effects: what a repository's data declares, and whether anything reads it

**Read this first.** It reads a repository's data files and code, and changes nothing. It answers one question: is every name a
thing declares as an effect read by something? It never shows that the reading does what a description promises: that is for a
person, or a test in play. A repository opts in by writing `config/effects.json`; without one, the command says so and fails.

    python -m phobos_modkit effects check --root REPO    fails on a declared effect nothing reads that the table has not accepted
    python -m phobos_modkit effects list --root REPO     the same, with the accepted ones and their reasons

## Why

A game's data often declares a thing's effects by name: a vehicle fitting grants `HouseBattery`, moves a system's
`batteryAmpHours`, goes on a `HouseBatteryTray`. The name does nothing until something reads it. In phobos-rimworld on 27 Nov 2026
the owner asked whether the house battery was "appropriately modelled", and an audit of every fitting followed; this command is that
audit kept as a check, so a fitting that promises what nothing models fails a repository's gate instead of waiting for a player.

## The table

`config/effects.json` in the repository. Nothing about any game is in this kit: the table names the game's things.

| Key | What it holds |
| --- | --- |
| `description` | One line shown under the report's title |
| `data`, `skip` | Globs, from the repository's root, of the XML data files to read and those to leave out |
| `code` | Globs of the code files whose quoted strings count as readers |
| `kinds` | The data elements that declare effects: `element` (its tag), `id` (the child naming each entry), `label`, `effects` |
| `accepted` | Known findings, each `entry`, `value` and `why`: listed by `list`, passed by `check` |

Each effect has a `path` from the entry to the elements whose text is the declared name (`grants/li`: every list item of
`grants`), a word for it (`what`), and its `readers`:

| Reader | Counts when |
| --- | --- |
| `tags` | A data element of one of these tags holds the same text (a `needsGrant` naming the grant) |
| `tagEndings` | A data element whose tag ends so holds it (`Node`: a `strawChopperNode` naming an upgrade node) |
| `anyTag` | Any data element holds it |
| `code` | The name appears as a whole quoted string in code (`"HouseBattery"`); a string put together (`"Engine" + i`) does not |
| `built` | The name matches this regular expression, for names the code puts together at run time |

An effect may be `unless` a child of the element above its last step (an upgrade node with upgrades of its own declares its effect
there, so only nodes without one are checked), and may need `definedBy` `tagNamed`: an element named after it somewhere (a figure
declared as `<batteryAmpHours>`), else it is "defined nowhere".

**A declaring element never reads anything.** Two fittings that grant the same name do not read each other's.

## What fails

`check` fails on a finding the table has not accepted, and on an accepted entry that no longer finds anything (take it out). The
JSON's `data.waiting` counts both, which D'thorga Companion shows beside its Reports page.

## Limits

- Comments are never read; XML that will not parse is listed and skipped.
- Readers are counted by name, never by meaning: a reading in the wrong place, or one that does nothing, still counts.
- Only XML data, for now. A game whose data is Lua or JSON needs a reader for that form: a next game's need, said here so it is
  small and known.

## Reports and options

<!-- generated: options effects -->
Generated from the command's own parser by `python -m phobos_modkit command-docs --write`: change a help text in the parser, not here.

| Report | What it does | Effect |
| --- | --- | --- |
| `check` | Every declared effect nothing reads; fails on one not accepted. Fails on a declared effect nothing reads that the repository's table has not accepted. | reads only |
| `list` | The same, with the accepted ones and what was read. | reads only |

| Option | Reports | What it does | Default |
| --- | --- | --- | --- |
| `--root VALUE` | all | the repository (default: the current folder) |  |
| `--config VALUE` | all | the table (default: config/effects.json in the repository) |  |

- Every report also takes `--json` (print JSON instead of Markdown) and `--no-redact` (show the home folder instead of ~).
- [Common options](common-options.md) explains `--root`, `--config`, `--json` and `--no-redact`, which many commands share.
<!-- end generated -->
