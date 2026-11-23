# Owner queues: decisions, picks and screen notes

Three lists of things waiting for the owner: questions (decisions), pictures and sounds to choose between (picks), and pages the
owner flagged as looking wrong (screen notes). They share one way of working, said once here; each command's own page has the rest.

## Read this first

- **What waits is kept beside the work.** A decision or a pick lives in the repository's own config list (`config/decisions.json`,
  `config/picks.json`), committed with the work it is about. Screen notes are the exception: D'thorga Companion writes each note
  into its own folder, where the owner made it.
- **The owner's answers are kept in D'thorga Companion's folder**, never in a repository: one JSON line each, appended to a file
  per repository. The last line for an item decides, so the owner can change their mind until an agent acts on it.
- **Act, then settle, in the same commit.** An agent acts on the answer (makes the change, exports the chosen try) and closes the
  item in the commit that acts on it, so the list holds only what still waits. The answers file stays as the record of what the
  owner chose.
- **"Something else" is always an answer**: a decision's `other`, a pick's `none`, each with the owner's words. Read the words:
  they are the owner's own choice.
- **An answer given in conversation is recorded the same way**, with the command's `answer` report, so the record stays whole.

## The three side by side

| | [Decisions](decisions.md) | [Picks](picks.md) | [Screen notes](screen-notes.md) |
| --- | --- | --- | --- |
| What waits | A question with two or more options, the agent's lean and why | A picture or sound's tries, beside the file in use | A page as the owner saw it, its picture and their words |
| Who adds it | An agent, for a choice the owner should be able to revise, or when it needs their word to go on | A repository's art tools (`picks offer`) | D'thorga Companion, when the owner presses its key |
| Where it waits | `config/decisions.json` | `config/picks.json` | `screen-notes/<id>/` in the Companion's folder |
| Where answers go | `decisions/<repository>.jsonl` in the Companion's folder (`companionDecisionsPath`, `PHOBOS_DECISIONS`) | `picks/<repository>.jsonl` (`companionPicksPath`, `PHOBOS_PICKS`) | `resolved.json` beside the note |
| Closed by | Removing it from the config in the commit that acts on it | `picks settle`, in the commit that applies it | `screen-notes resolve --how "..."`; `reopen` undoes it |
| Shown by | The Companion's Decisions page, which also answers | The Companion's Picks page, which also answers | The Companion, which writes them |

## Decisions

A question an agent puts to the owner: two or more options, the agent's lean and why, and where it came from. Ids are unique in
the file; `other` is kept for "something else". The config's fields and the answers' format are on [decisions](decisions.md).

## Picks

Tries of one picture or sound for the owner to choose between, offered by a repository's art tools whenever they make them.
An agent session or an art tool applies the answer (exports the chosen try, records it as the repository records its art), and
`picks settle` removes the pick in the same commit. The file's fields and
what `list` answers with are on [picks](picks.md).

## Screen notes

What the owner flagged as looking wrong in D'thorga Companion: the whole page as a picture, the page's address and their words.
Agent sessions read the open notes at the start of a session. Resolving never deletes: the owner can look back at every note. A
note's folder and files are on [screen notes](screen-notes.md).

## Limits

- Screen notes have no config list in a repository and no answers file: the note and its resolution are both in the Companion's
  folder, so they follow the shared way of working only in "act, then close".
- The kit keeps the lists and answers; it never acts on an answer itself. An agent does, in the repository the item belongs to.
