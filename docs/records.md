# Records: a copy of D'thorga Companion's own records

**Status (19 Nov 2026):** built in 1.43.0. The Companion's Settings page and Home use it from 0.22.0.

## Read this first (gotchas)

- **Choose the folder first**: `recordsBackupPath` (or `PHOBOS_RECORDS_BACKUP`), on the Companion's Settings page or with
  `settings set`. A folder the owner's NAS or other backup keeps is the point: the Companion's own folder sits in the local
  application data, which Synology does not back up.
- **Nothing is ever deleted.** Each copy is a new folder named for the local time; prune old ones by hand.
- **The window's browser cache is left out** (`EBWebView`, WebView2's, most of the folder's size). Everything else in the
  Companion's folder is copied, so a new kind of record is included without a change here.
- **Saves are not records.** A game's saves are far larger and are a separate question (D'thorga Companion's `docs/later.md`).

## Use

```text
python -m phobos_modkit records status
python -m phobos_modkit records backup                   # into recordsBackupPath
python -m phobos_modkit records backup --to "N:\Backups\Companion"
```

`--json` gives the envelope. `status`'s `data` holds `folder`, `folderExists`, `records` (each `name`, `path`, `files`, `bytes`),
`copies` (newest first: `name`, `time` in UTC, `files`, `bytes`), `newest`, `ageDays`, `staleDays` (7, an agent choice) and `stale`
(no copy, or the newest is at least that old). `backup`'s `data.copy` holds `path`, `name`, `files`, `bytes` and `time`.

## What is copied

| Record | From |
| --- | --- |
| Everything in the Companion's folder but the browser cache | test verdicts and decisions, the history log, "looked at" marks, screen notes, shortcuts, the central settings file |
| `elsewhere-history`, `elsewhere-test-verdicts`, `elsewhere-test-key-decisions` | where `historyPath` or the verdict settings keep them outside that folder |
| `elsewhere-settings.json` | the central settings file, when `PHOBOS_SETTINGS` names one elsewhere |

Each copy holds `backup.json`: `format`, `time`, `kit`, `files`, `bytes` and where each record came from. It is written into
`<name>.partial` and renamed when whole. A folder inside the records themselves is refused.
