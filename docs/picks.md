# Picks: the pictures and sounds waiting for the owner to pick one

One of the three [owner queues](owner-queues.md), which says how they all work. D'thorga Companion's Picks page reads and answers
them.

## Read this first

- **A repository's art tools offer a pick whenever they make tries for the owner to choose from** (`picks offer`, or the `offer`
  function): an id, a title, picture or sound, the file in use (if any) and each try's file. It lives in the repository's
  `config/picks.json`, committed with the tries' records. Offering the same id again replaces it, for tries made again;
  a pick of the other kind under that id (a sound where a picture waits) is refused, so each kind needs ids of its own.
- **Apply a pick, then settle it in the same commit**: export the chosen try and record it as the repository records its art, then
  `picks settle` removes the pick ([owner queues](owner-queues.md)).
- **"none" is an answer too**, usually with words: what to try next.
- **A path may be anywhere on this PC**, since tries are often made outside the repository (a working folder on another drive); a
  relative path is the repository's own. The list says whether each file is there. A program shows only the files the list names.

## Examples

```text
python -m phobos_modkit picks list --root ../phobos-rimworld
python -m phobos_modkit picks answer --root ../phobos-rimworld --id billy-kettle --pick 3
python -m phobos_modkit picks answer --root ../phobos-rimworld --id billy-kettle --pick none --words "the spout is still hidden"
python -m phobos_modkit picks offer --root ../phobos-rimworld --file pick.json
python -m phobos_modkit picks settle --root ../phobos-rimworld --id billy-kettle
```

## Reports and options

<!-- generated: options picks -->
Generated from the command's own parser by `python -m phobos_modkit command-docs --write`: change a help text in the parser, not here.

| Report | What it does | Effect |
| --- | --- | --- |
| `list` | Every pick, waiting ones first, with any answer. | reads only |
| `answer` | Records the owner's pick. Appends the owner's pick to the Companion's picks file. | writes |
| `offer` | Adds or replaces one waiting pick. Adds a waiting pick to the repository's config/picks.json. | writes |
| `settle` | Removes a pick once its answer is applied. Removes an applied pick from the repository's config/picks.json. | writes |

| Option | Reports | What it does | Default |
| --- | --- | --- | --- |
| `--root VALUE` | `list` | a repository (repeatable; default: the current folder) |  |
| `--root VALUE` | `answer` | the repository the pick belongs to. Required. |  |
| `--id VALUE` | `answer`, `settle` | the pick. Required. |  |
| `--pick VALUE` | `answer` | the chosen try's id, or 'none' (say why with `--words`). Required. |  |
| `--words VALUE` | `answer` | anything the owner added |  |
| `--root VALUE` | `offer`, `settle` | the repository. Required. |  |
| `--file VALUE` | `offer` | a JSON file holding one pick, as config/picks.json holds them. Required. |  |

- Every report also takes `--json` (print JSON instead of Markdown) and `--no-redact` (show the home folder instead of ~).
- [Common options](common-options.md) explains `--root`, `--json` and `--no-redact`, which many commands share.
<!-- end generated -->

## Inputs

### The file: `config/picks.json`

```json
{"schemaVersion": 1,
 "grounds": [{"name": "Soil", "colour": "#5C4C3A"}, {"name": "Dark stone", "colour": "#303034"}],
 "picks": [
   {"id": "billy-kettle", "title": "The billy kettle", "kind": "picture",
    "inUse": "mods/Thing/Textures/Kettle.png",
    "tries": [{"id": "3", "label": "Try 3", "path": "K:/art/cards/kettle/export/billy-kettle-3.png", "note": "4 loose specks"}],
    "context": "A redraw: the old one's spout was hidden.", "from": "assets/thing/requests/redraw.json", "asked": "2026-11-23"}]}
```

| Field | Holds |
| --- | --- |
| `grounds` | Up to six colours a game's pictures are seen on (`#RRGGBB`), offered beside the Companion's own grounds |
| `id` | Lower-case letters, digits, dots, hyphens and underscores; a try's id is never `none` |
| `kind` | `picture` (any picture or DDS texture the Companion draws) or `sound` |
| `inUse` | The file it would replace, or null for something new |
| `tries` | Up to 40: `id`, `label`, `path`, and a `note` (an edge check's figures, a seed) |
| `context`, `from`, `asked` | Why it was made, the request it came from, and when it was offered (today when left out) |

### The answers

One JSON line each, appended to `picks/<repository>.jsonl` in the Companion's folder (`companionPicksPath`, `PHOBOS_PICKS`). The
last line for a pick decides, so a pick can be changed until it is settled.

## Outputs

### What `list` answers with

Each repository's `grounds` and `picks`, waiting ones first; every path made absolute with `there` (the try's file is on this PC)
and `inUseThere`; and `answer` (`pick`, `words`, `time`) or null.
