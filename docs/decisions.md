# Decisions: the questions waiting for the owner

One of the three [owner queues](owner-queues.md), which says how they all work. D'thorga Companion's Decisions page reads and
answers them.

## Read this first

- **Add a decision whenever you make a choice the owner should be able to revise, or need their word to go on**: a question, two
  or more options, your lean and why, in the repository's `config/decisions.json`, committed with the work it is about.
- **Act on an answer, then remove the decision from the config in the same commit** ([owner queues](owner-queues.md)).
- **Every decision may be answered "other", with words.** Read the words: they are the owner's own choice.
- **An answer given in conversation** is recorded the same way: `decisions answer --root . --id ID --option OPTION --words "..."`.

## Examples

```text
python -m phobos_modkit decisions list --root ../phobos-companion --root ../phobos-rimworld
python -m phobos_modkit decisions answer --root ../phobos-companion --id page-keys --option renumber
```

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

- Every report also takes `--json` (print JSON instead of Markdown) and `--no-redact` (show the home folder instead of ~).
- [Common options](common-options.md) explains `--root`, `--json` and `--no-redact`, which many commands share.
<!-- end generated -->

## Inputs

### The config: `config/decisions.json`

```json
{"schemaVersion": 1, "decisions": [
  {"id": "page-keys", "question": "Renumber the page keys to follow the grouped bar?",
   "context": "The bar is now grouped into Play, Code and Tools; the keys still follow the old order.",
   "options": [{"id": "renumber", "label": "Renumber them", "detail": "1 to 9 in the bar's order"},
               {"id": "keep", "label": "Keep them", "detail": "No key changes"}],
   "lean": "renumber", "why": "The number keys would match what you see",
   "from": "docs/design-record.md", "asked": "2026-11-19"}]}
```

Ids are lower-case letters, digits and hyphens, unique in the file; `other` is kept for "something else".

### The answers

One JSON line each (`format`, `id`, `option`, `words`, `time` in UTC), appended to `decisions/<repository>.jsonl` in the
Companion's folder (`companionDecisionsPath`, `PHOBOS_DECISIONS`). The last line for a decision decides.

## Outputs

`--json` gives the envelope: `data.waiting` counts the open ones; `data.repositories` holds, for each, `repository`, `root` and
`decisions`, each with `id`, `question`, `context`, `options` (`id`, `label`, `detail`), `lean`, `why`, `from`, `asked` and `answer`
(`option`, `words`, `time`, or null). `answer` answers `data.ok`, with `refusal` when refused.

## Failures and exit codes

- A malformed config is refused with its reason, never half-read.
- `answer` exits 3 when it is refused, with `data.refusal` saying why.
