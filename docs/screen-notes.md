# Screen notes: what the owner flagged in D'thorga Companion

One of the three [owner queues](owner-queues.md), which says how they all work. The Companion writes the notes; agent sessions
read and resolve them.

## Read this first

- **Agent sessions read the open notes at the start of a session** in any repository the Companion shows: `python -m
  phobos_modkit screen-notes list`. Each note's picture is `picture.png` in its folder; read it to see the page as the owner saw it.
- **Resolving never deletes.** `resolve` writes `resolved.json` beside the note, saying how it was dealt with; `reopen` removes that
  file again. The owner can look back at every note.
- **The folder is not a setting.** Notes live in the Companion's own folder (`screen-notes`), where the Companion writes them;
  `PHOBOS_SCREEN_NOTES` names another folder, for tests only.

## Examples

```text
python -m phobos_modkit screen-notes list            # open notes, newest first
python -m phobos_modkit screen-notes list --all      # dealt-with notes too
python -m phobos_modkit screen-notes resolve 20261119-101500 --how "Moved the legend under the chart (Companion 0.22.1)"
python -m phobos_modkit screen-notes reopen 20261119-101500
```

## Reports and options

<!-- generated: options screen-notes -->
Generated from the command's own parser by `python -m phobos_modkit command-docs --write`: change a help text in the parser, not here.

| Report | What it does | Effect |
| --- | --- | --- |
| `list` | The open notes, newest first. | reads only |
| `resolve` | Marks a note dealt with, saying how. Writes resolved.json beside one note; nothing is deleted. | writes |
| `reopen` | Marks a dealt-with note open again. Removes one note's resolved.json, so it is open again. | writes |

| Option | Reports | What it does | Default |
| --- | --- | --- | --- |
| `--all` | `list` | the dealt-with notes too |  |
| `ID` | `resolve`, `reopen` | the note's name, as list shows it |  |
| `--how VALUE` | `resolve` | how it was dealt with, in a sentence or two. Required. |  |

- Every report also takes `--json` (print JSON instead of Markdown) and `--no-redact` (show the home folder instead of ~).
- Names in capitals are given bare, without a flag, in the order shown.
- [Common options](common-options.md) explains `--json` and `--no-redact`, which many commands share.
<!-- end generated -->

## Inputs

### A note's folder

`screen-notes/<id>/`, the id being the local time it was taken (`20261119-101500`, with `-2` and so on when two land in one
second):

| File | Written by | Holds |
| --- | --- | --- |
| `picture.png` | the Companion | the whole page, scrolled parts included, as it was when the key was pressed |
| `note.json` | the Companion | `format`, `time`, `game`, `page`, `address`, `words`, `version`, `window` |
| `resolved.json` | `screen-notes resolve` | `format`, `time`, `how` |

## Outputs

Add `--json` for the envelope: `data.notes` holds, for each note, `id`, `time` (UTC), `game`, `page`, `address` (the Companion's
`dthorga://` address of the page), `words` (may be empty), `version` (the Companion's), `window` (`width`, `height`), `picture`
(its path, or null), `folder` and `resolved` (`time`, `how`, or null); `data.open` counts the open ones.
