# Screen notes: what the owner flagged in D'thorga Companion

**Status (19 Nov 2026):** built in 1.41.0. The Companion writes the notes from 0.22.0.

## Read this first (gotchas)

- **Agent sessions read the open notes at the start of a session** in any repository the Companion shows: `python -m
  phobos_modkit screen-notes list`. Each note's picture is `picture.png` in its folder; read it to see the page as the owner saw it.
- **Resolving never deletes.** `resolve` writes `resolved.json` beside the note, saying how it was dealt with; `reopen` removes that
  file again. The owner can look back at every note.
- **The folder is not a setting.** Notes live in the Companion's own folder (`screen-notes`), where the Companion writes them;
  `PHOBOS_SCREEN_NOTES` names another folder, for tests only.

## Use

```text
python -m phobos_modkit screen-notes list            # open notes, newest first
python -m phobos_modkit screen-notes list --all      # dealt-with notes too
python -m phobos_modkit screen-notes resolve 20261119-101500 --how "Moved the legend under the chart (Companion 0.22.1)"
python -m phobos_modkit screen-notes reopen 20261119-101500
```

Add `--json` for the envelope: `data.notes` holds, for each note, `id`, `time` (UTC), `game`, `page`, `address` (the Companion's
`dthorga://` address of the page), `words` (may be empty), `version` (the Companion's), `window` (`width`, `height`), `picture`
(its path, or null), `folder` and `resolved` (`time`, `how`, or null); `data.open` counts the open ones.

## A note's folder

`screen-notes/<id>/`, the id being the local time it was taken (`20261119-101500`, with `-2` and so on when two land in one
second):

| File | Written by | Holds |
| --- | --- | --- |
| `picture.png` | the Companion | the whole page, scrolled parts included, as it was when the key was pressed |
| `note.json` | the Companion | `format`, `time`, `game`, `page`, `address`, `words`, `version`, `window` |
| `resolved.json` | `screen-notes resolve` | `format`, `time`, `how` |
