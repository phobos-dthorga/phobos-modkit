# Decisions: the questions waiting for the owner

**Status (19 Nov 2026):** built in 1.45.0. D'thorga Companion's Decisions page reads and answers them from 0.22.0.

## Read this first (gotchas)

- **Add a decision whenever you make a choice the owner should be able to revise, or need their word to go on**: a question, two
  or more options, your lean and why. It lives in the repository's `config/decisions.json`, committed with the work it is about.
- **Act on an answer, then remove the decision from the config in the same commit.** The list holds only what still waits; the
  answer stays in the answers file as the record of what the owner chose.
- **Every decision may be answered "other", with words.** Read the words: they are the owner's own choice.
- **An answer given in conversation** is recorded the same way: `decisions answer --root . --id ID --option OPTION --words "..."`.

## Use

```text
python -m phobos_modkit decisions list --root ../phobos-companion --root ../phobos-rimworld
python -m phobos_modkit decisions answer --root ../phobos-companion --id page-keys --option renumber
```

`--json` gives the envelope: `data.waiting` counts the open ones; `data.repositories` holds, for each, `repository`, `root` and
`decisions`, each with `id`, `question`, `context`, `options` (`id`, `label`, `detail`), `lean`, `why`, `from`, `asked` and `answer`
(`option`, `words`, `time`, or null). `answer` answers `data.ok`, with `refusal` when refused (exit 3).

## The config

```json
{"schemaVersion": 1, "decisions": [
  {"id": "page-keys", "question": "Renumber the page keys to follow the grouped bar?",
   "context": "The bar is now grouped into Play, Code and Tools; the keys still follow the old order.",
   "options": [{"id": "renumber", "label": "Renumber them", "detail": "1 to 9 in the bar's order"},
               {"id": "keep", "label": "Keep them", "detail": "No key changes"}],
   "lean": "renumber", "why": "The number keys would match what you see",
   "from": "docs/design-record.md", "asked": "2026-11-19"}]}
```

Ids are lower-case letters, digits and hyphens, unique in the file; `other` is kept for "something else". A malformed file is
refused with its reason, never half-read.

## The answers

One JSON line each (`format`, `id`, `option`, `words`, `time` in UTC), appended to `decisions/<repository>.jsonl` in the
Companion's folder (`companionDecisionsPath`, `PHOBOS_DECISIONS`). The last line for a decision decides, so the owner can change
their mind until an agent acts on it.

## Reports and options

<!-- generated: options decisions -->
Generated from the command's own parser by `python -m phobos_modkit command-docs --write`: change a help text in the parser, not here.

| Report | What it does | Effect |
| --- | --- | --- |
| `list` | Every decision, open ones first, with any answer. | reads only |
| `answer` | Records the owner's answer. Appends the owner's answer to the Companion's decisions file. | writes |

| Option | Reports | What it does | Default |
| --- | --- | --- | --- |
| `--root VALUE` | `list` | a repository (repeatable; default: the current folder) |  |
| `--root VALUE` | `answer` | the repository the decision belongs to. Required. |  |
| `--id VALUE` | `answer` | the decision. Required. |  |
| `--option VALUE` | `answer` | the chosen option's id, or 'other' with `--words`. Required. |  |
| `--words VALUE` | `answer` | anything the owner added |  |

Every report also takes `--json` (print JSON instead of Markdown) and `--no-redact` (show the home folder instead of ~).
<!-- end generated -->
