# Records: a copy of D'thorga Companion's own records

**Status (20 Nov 2026):** built in 1.43.0. The Companion's Settings page and Home use it from 0.22.0; from 1.55.0 the Companion
also copies by itself, every few hours while it is open (`status --every-hours`, `backup --automatic`).

## Read this first (gotchas)

- **Choose the folder first**: `recordsBackupPath` (or `PHOBOS_RECORDS_BACKUP`), on the Companion's Settings page or with
  `settings set`. A folder the owner's NAS or other backup keeps is the point: the Companion's own folder sits in the local
  application data, which Synology does not back up.
- **The Companion copies by itself** (owner, 20 Nov 2026: "every few hours when it's open, and if the schedule is missed, the
  soonest next opportunity"). It asks `status --every-hours N` and, when `due`, runs `backup --automatic`. A missed copy is
  simply due at the next look, so a closed program or a sleeping PC catches up when it next can.
- **A folder that cannot be reached is refused in words** (1.55.0): a drive not there or a NAS asleep says so, copies nothing and
  leaves no partial folder; before 1.55.0 it stopped with Python's own error.
- **Nothing is ever deleted.** Each copy is a new folder named for the local time; prune old ones by hand.
- **The window's browser cache is left out** (`EBWebView`, WebView2's, most of the folder's size). Everything else in the
  Companion's folder is copied, so a new kind of record is included without a change here.
- **Saves are not records.** A game's saves are far larger and are a separate question (D'thorga Companion's `docs/later.md`).

## Use

```text
python -m phobos_modkit records status
python -m phobos_modkit records status --every-hours 6   # also: is a copy due?
python -m phobos_modkit records backup                   # into recordsBackupPath
python -m phobos_modkit records backup --to "N:\Backups\Companion"
```

`--json` gives the envelope. `status`'s `data` holds `folder`, `folderExists`, `records` (each `name`, `path`, `files`, `bytes`),
`copies` (newest first: `name`, `time` in UTC, `files`, `bytes`), `newest`, `ageDays`, `staleDays` (7, an agent choice) and `stale`
(no copy, or the newest is at least that old), and `ageHours` (1.55.0). With `--every-hours N` it adds `everyHours` and `due`: a
folder is chosen, and there is no copy yet or the newest is N hours old or more. Each copy says whether it was `automatic`.
`backup`'s `data.copy` holds `path`, `name`, `files`, `bytes`, `time` and `automatic`.

## What is copied

| Record | From |
| --- | --- |
| Everything in the Companion's folder but the browser cache | test verdicts and decisions, the history log, "looked at" marks, screen notes, shortcuts, the central settings file |
| `elsewhere-history`, `elsewhere-test-verdicts`, `elsewhere-test-key-decisions` | where `historyPath` or the verdict settings keep them outside that folder |
| `elsewhere-settings.json` | the central settings file, when `PHOBOS_SETTINGS` names one elsewhere |

Each copy holds `backup.json`: `format`, `time`, `kit`, `files`, `bytes`, `automatic` (1.55.0) and where each record came from. It is written into
`<name>.partial` and renamed when whole. A folder inside the records themselves is refused.

## Reports and options

<!-- generated: options records -->
Generated from the command's own parser by `python -m phobos_modkit command-docs --write`: change a help text in the parser, not here.

| Report | What it does | Effect |
| --- | --- | --- |
| `status` | What would be copied, where to, and the copies already there. What would be copied, where to, and how old the newest copy is. | reads only |
| `backup` | Copies the records into a new dated folder. Copies the Companion's records into a new dated folder; deletes nothing. | writes |

| Option | Reports | What it does | Default |
| --- | --- | --- | --- |
| `--to VALUE` | all | the backup folder (default: recordsBackupPath) |  |
| `--every-hours N` | `status` | also say whether a copy is due: none yet, or the newest this old |  |
| `--automatic` | `backup` | mark the copy as made by the Companion's own timer |  |

Every report also takes `--json` (print JSON instead of Markdown) and `--no-redact` (show the home folder instead of ~).
<!-- end generated -->
