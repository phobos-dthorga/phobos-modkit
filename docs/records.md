# Records: a copy of D'thorga Companion's own records

The Companion's Settings page and Home use it, and the Companion also copies by itself, every few hours while it is open
(`status --every-hours`, `backup --automatic`).

## Read this first

- **Choose the folder first**: `recordsBackupPath` (or `PHOBOS_RECORDS_BACKUP`), on the Companion's Settings page or with
  `settings set`. A folder the owner's NAS or other backup keeps is the point: the Companion's own folder sits in the local
  application data, which Synology does not back up.
- **The Companion copies by itself** (owner, 20 Nov 2026: "every few hours when it's open, and if the schedule is missed, the
  soonest next opportunity"). It asks `status --every-hours N` and, when `due`, runs `backup --automatic`. A missed copy is
  simply due at the next look, so a closed program or a sleeping PC catches up when it next can.
- **Each file is kept once, compressed** (1.149.0; the owner's choice by card, 28 Nov 2026: "Store-once"). The backup folder holds
  `store/` and one small `<local time>.json` per copy, listing its files. 24 copies as plain folders measured 155 MB; kept once,
  about 10.5 MB, as the screen-note pictures and logs repeat in every copy.
- **To look inside a copy, write it out**: `records restore --copy NAME --into FOLDER`, into an empty folder of its own. It never
  writes into the Companion's folder or the backup folder: putting records back is done by hand, with the Companion closed.
- **The kit never deletes a copy.** Prune one by deleting its `.json`; `records tidy --apply` then lets go of the kept files no copy
  names (never one kept in the last day, in case a backup is writing its list at that moment).
- **Copies made before 1.149.0 are plain folders.** `records pack` says which; `pack --apply` keeps each in the store and removes its
  folder only once every file reads back the same (the owner's choice by card, 28 Nov 2026: "Convert, checked first").
- **The window's browser cache is left out** (`EBWebView`, WebView2's, most of the folder's size), **and so are the kept answers**
  (`answers`, 1.147.2: each slow page's last reading, which the Companion reads again by itself). Everything else in the
  Companion's folder is copied, so a new kind of record is included without a change here.
- **Saves are not records.** A game's saves are far larger and are a separate question (D'thorga Companion's `docs/later.md`).

## Examples

```text
python -m phobos_modkit records status
python -m phobos_modkit records status --every-hours 6   # also: is a copy due?
python -m phobos_modkit records backup                   # into recordsBackupPath
python -m phobos_modkit records backup --to "N:\Backups\Companion"
python -m phobos_modkit records restore --copy 20261128-030818 --into "C:\Temp\records-look"
python -m phobos_modkit records pack                     # which copies are still plain folders; --apply packs them
python -m phobos_modkit records tidy                     # kept files no copy names; --apply lets them go
```

## Reports and options

<!-- generated: options records -->
Generated from the command's own parser by `python -m phobos_modkit command-docs --write`: change a help text in the parser, not here.

| Report | What it does | Effect |
| --- | --- | --- |
| `status` | What would be copied, where to, and the copies already there. What would be copied, where to, and how old the newest copy is. | reads only |
| `backup` | Keeps the records in the store as a new dated copy. Keeps the Companion's records in the store as a new dated copy; deletes nothing. | writes |
| `restore` | Writes one copy out, plain, into an empty folder. Writes one copy out into an empty folder the owner names; never into the Companion's folder or the backup folder. | writes |
| `pack` | Turns copies made as plain folders into store copies, each checked before its folder goes. With `--apply`, keeps each folder copy in the store and removes the folder only once every file reads back the same; without, only says. | writes |
| `tidy` | Lets go of kept files no copy names any more. With `--apply`, lets go of kept files no copy names, never one kept in the last day; without, only says. | writes |

| Option | Reports | What it does | Default |
| --- | --- | --- | --- |
| `--to VALUE` | all | the backup folder (default: recordsBackupPath) |  |
| `--every-hours N` | `status` | also say whether a copy is due: none yet, or the newest this old |  |
| `--automatic` | `backup` | mark the copy as made by the Companion's own timer |  |
| `--copy VALUE` | `restore` | the copy's name, as status lists it. Required. |  |
| `--into VALUE` | `restore` | an empty folder, or one not there yet, to write it into. Required. |  |
| `--apply` | `pack`, `tidy` | do it; without this, only say what would be done |  |

- Every report also takes `--json` (print JSON instead of Markdown) and `--no-redact` (show the home folder instead of ~).
- [Common options](common-options.md) explains `--json` and `--no-redact`, which many commands share.
<!-- end generated -->

## Inputs

### What is copied

| Record | From |
| --- | --- |
| Everything in the Companion's folder but the browser cache | test verdicts and decisions, the history log, "looked at" marks, screen notes, shortcuts, the central settings file |
| `elsewhere-history`, `elsewhere-test-verdicts`, `elsewhere-test-key-decisions` | where `historyPath` or the verdict settings keep them outside that folder |
| `elsewhere-settings.json` | the central settings file, when `PHOBOS_SETTINGS` names one elsewhere |

## Outputs

### Each copy

Each copy is `<name>.json`: `format` (2), `time`, `kit`, `files`, `bytes`, `automatic`, where each record came from, and `entries`,
one per file: `path` in the copy, `sha256`, `bytes` and `mtimeNs`. Each file's bytes are in `store/objects/<first two>/<sha256>.zst`
(`packed.Store`), written whole and read back before the list names it; the list is written as `<name>.json.partial` and renamed when
whole. A copy packed from a folder adds `packedFrom` and `packedBy`. Before 1.149.0 a copy was a folder holding `backup.json` (format 1)
beside the files.

### The JSON envelope

`--json` gives the envelope ([common options](common-options.md)). `status`'s `data` holds `folder`, `folderExists`, `records`
(each `name`, `path`, `files`, `bytes`), `copies` (newest first: `name`, `time` in UTC, `files`, `bytes`, `form`: `store` or
`folder`), `store` (`files`, `bytes` on disk), `folderCopies`, `newest`, `ageDays`,
`staleDays` (7, an agent choice) and `stale` (no copy, or the newest is at least that old), and `ageHours`. With
`--every-hours N` it adds `everyHours` and `due`: a folder is chosen, and there is no copy yet or the newest is N hours old or
more. Each copy says whether it was `automatic`. `backup`'s `data.copy` holds `path` (its list), `name`, `files`, `bytes`, `time`,
`automatic` and `form`. `restore`'s `data.restore` holds `name`, `into`, `files`, `bytes`; `pack`'s `data.pack` each folder copy's
`name`, `files`, `bytes`, `packed` and any `refusal`, and the store's size; `tidy`'s `data.tidy` `loose`, `looseBytes`, `removed`,
`removedBytes`.

## Failures and exit codes

- **A folder that cannot be reached is refused in words**: a drive not there or a NAS asleep says so, copies nothing and leaves no
  partial folder (before 1.55.0 it stopped with Python's own error).
- **A folder inside the records themselves is refused.**
