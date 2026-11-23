# Picks: the pictures and sounds waiting for the owner to pick one

**Status (23 Nov 2026):** built in 1.83.0. D'thorga Companion's Picks page reads and answers them from 0.54.0.

## Read this first (gotchas)

- **A repository's art tools offer a pick whenever they make tries for the owner to choose from** (`picks offer`, or the `offer`
  function): an id, a title, picture or sound, the file in use (if any) and each try's file. It lives in the repository's
  `config/picks.json`, committed with the tries' records. Offering the same id again replaces it, for tries made again;
  a pick of the other kind under that id (a sound where a picture waits) is refused, so each kind needs ids of its own (1.103.1).
- **Apply a pick, then settle it in the same commit** (`picks settle`): export the chosen try, record it as the repository records
  its art, and remove the pick. The answer stays in the answers file as the record of what the owner chose.
- **"none" is an answer too**, usually with words: what to try next.
- **A path may be anywhere on this PC**, since tries are often made outside the repository (a working folder on another drive); a
  relative path is the repository's own. The list says whether each file is there. A program shows only the files the list names.
- **Answers are kept in the Companion's folder** (`picks/<repository>.jsonl`, or `companionPicksPath` / `PHOBOS_PICKS`), one JSON
  line each; the last line for a pick decides, so a pick can be changed until it is settled.

## Use

```text
python -m phobos_modkit picks list --root ../phobos-rimworld
python -m phobos_modkit picks answer --root ../phobos-rimworld --id billy-kettle --pick 3
python -m phobos_modkit picks answer --root ../phobos-rimworld --id billy-kettle --pick none --words "the spout is still hidden"
python -m phobos_modkit picks offer --root ../phobos-rimworld --file pick.json
python -m phobos_modkit picks settle --root ../phobos-rimworld --id billy-kettle
```

## The file

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

## What `list` answers with

Each repository's `grounds` and `picks`, waiting ones first; every path made absolute with `there` (the try's file is on this PC)
and `inUseThere`; and `answer` (`pick`, `words`, `time`) or null.
