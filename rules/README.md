# Shared rules: one place for what holds in every repository

**Status (19 Nov 2026):** created at the owner's request, with its first rules (commits and changelog entries), and a second file
the same day (builds: the same code builds to the same bytes). phobos-rimworld and D'thorga Companion read it through their pinned
copy of this repository. On 20 Nov 2026 a third file followed (designs: the four questions a new behaviour answers), its first
three questions moved here from phobos-rimworld with the fourth. On 23 Nov 2026 the twelve rules that had been waiting moved here
on the owner's word ("Move all 12 now"): ten into `every-session.md`, and two files of their own, `brand.md` and `changelogs.md`.

## Read this first (gotchas)

- **This folder is the root for rules that hold across every game** (owner, 19 Nov 2026: "a central point from which global rules
  for all mods can be read and modified"). A rule about one game, one mod or one tool stays in that repository's `AGENTS.md`.
- **A repository reads the copy its pin holds**, so a rule changed here reaches a repository when its pin next moves. That is on
  purpose: a repository's rules never change under a session without a commit in that repository saying so.
- **Rules are the owner's.** An agent may propose a rule, or move one here, only on the owner's word, and labels who decided it and
  when, as every rule here is.
- **`every-session.md` is read in every session of every repository**, so it stays short. Everything else here is read before the
  work it governs.

## What is here

| File | Read | Covers |
| --- | --- | --- |
| [every-session.md](every-session.md) | At the start of every session | Working with the owner (slices, testing, mouse and saves, labels, plain writing); git, versions, the gate and what is never committed; every game from the start; commits and changelog entries; claims when sharing the machine with other sessions; which file to read before which work |
| [builds.md](builds.md) | Before setting up or changing how code is built | The same code builds to the same bytes |
| [brand.md](brand.md) | Before naming anything players or the public see, or writing a public page | D'thorga the one brand; plain names; older names change on return, display names only; the "dthorga" spelling on public pages |
| [changelogs.md](changelogs.md) | Before writing a changelog entry | Existing entries never moved; new entries short; a mod's changelog form, what it records, no backticks |
| [designs.md](designs.md) | Before designing or building a new behaviour | The four questions a new behaviour answers: what it lets, stops and changes, and what outside it notices; and a riskier behaviour's own setting, off by default when its risk is high |
| [licences.md](licences.md) | Before writing or changing a `LICENSE`, starting a repository, or preparing a mod's first public page | Code MIT, our art and sound CC BY 4.0, our names kept out of both grants, and the paragraphs a `LICENSE` carries |
| [reports.md](reports.md) | Before drafting a report of another author's fault, and when the owner says one is posted | Find it with the tools and look for an existing report; a plain draft in the owner's private tracker, ready to paste; the owner posts; check how it shows, then mark it posted everywhere |
| [safe-copies.md](safe-copies.md) | Before making something that cannot be made again, and before starting on a new game | List it when it is made, in the same commit; a game's own files once, for the game; each kind said truthfully, the narrower when unsure; the numbers and every removal the owner's |
| [first-class.md](first-class.md) | Before adding a new kind of thing to the tools or the Companion | A design to edit, not yet rules: the things every tool and page treats as real, and what makes them first-class |

`python -m phobos_modkit rules list` prints this with each file's rules counted, and `tests/test_rules.py` fails if a file here is
missing from the table.

## How a repository takes the rules up

| The repository | What it adds |
| --- | --- |
| Pins this kit at `external/phobos-modkit` | A line in its `CLAUDE.md`, `@external/phobos-modkit/rules/every-session.md`, so the file is loaded with its own rules; and a line in its `AGENTS.md` saying to read `external/phobos-modkit/rules/every-session.md` first, for a reader that does not follow imports |
| Does not pin the kit yet | Nothing until it is next worked on: then it pins the kit and adds the two lines. Until then, the owner's own instructions on their machine point every session at this folder in the kit's own checkout |
| Is this kit | `@rules/every-session.md` in its `CLAUDE.md`, and the pointer in its `AGENTS.md` |

**Name the path in backticks, never as a Markdown link** (learnt on the first day, 19 Nov 2026): on GitHub a pinned kit's folder
is a pointer to this repository, so a link into it leads nowhere, and a repository's own link check rightly refuses it. For a
person reading on GitHub, link to this repository instead:
`https://github.com/phobos-dthorga/phobos-modkit/blob/main/rules/every-session.md`.

**`python -m phobos_modkit rules check --root REPO` says whether a repository has both lines**, and fails when one is missing. Add
it to the repository's gate (`config/gate.json`), so a repository cannot stop reading the rules without a check saying so:

```json
{"name": "shared rules", "cwd": "external/phobos-modkit/python",
 "run": ["{python}", "-m", "phobos_modkit", "rules", "check", "--root", "../../.."]}
```

## How a rule is changed

1. **The owner decides.** The rule is written here in their words where they gave them, with "(owner, date)" and the reason.
2. Edit the file in this repository, add it to the table above if it is new, and record the change in `CHANGELOG.md`: **a new or
   changed rule raises the middle version number; a rewording that changes no behaviour raises the last.**
3. Run this repository's gate, commit, tag and push, as for any change here.
4. Move each repository's pin when it is next worked on, or at once when the owner wants the rule in force everywhere now. A
   repository whose own `AGENTS.md` repeated the rule drops its copy in the same commit, so a rule is never stated twice.

## Why the commit rules are as they are

Moved from `every-session.md` on 23 Nov 2026, which keeps only the rules. What this costs, said plainly: where a repository checks every commit (a gate, a commit guard), each separate commit needs its own
passing run. That is why the rule is "finish one before starting the next", where the run is one the change needed anyway, and not
"one commit for every entry", which the owner set aside.

## Where a rule belongs

| The rule is about | It lives in |
| --- | --- |
| How the owner and agents work, in any repository (commits, versions, honesty about testing, writing) | Here, in `every-session.md` if it applies to every session, else in a file of its own |
| One kind of work in any game (art and sound, releases, player language) | Here, in a file of its own, read before that work |
| One game's engine, mods or tools | That repository's `AGENTS.md`, or a file beside the work in it |
| What one version delivered | That repository's changelog, never a rules file |

## Moved here on 23 Nov 2026

Found on 19 Nov 2026 by comparing the `AGENTS.md` of eight repositories: each of these was stated, in slightly different words, in
several of them. **All twelve moved on the owner's word of 23 Nov 2026** ("Move all 12 now", in the docs rewrite), each in one
wording the moving agent chose from theirs, for the owner to revise. Each repository drops its copies as its pin moves: phobos-rimworld
and D'thorga Companion the same day; the others when next worked on.

| Rule | Was stated in | Now in |
| --- | --- | --- |
| Never force-push or rewrite history; commit and push to `main` | modkit, companion, rimworld, ostranauts, kenshi, scope, log | [every-session.md](every-session.md) |
| Version numbers: a fix raises the last number, new functionality the middle, a rework the first | modkit, companion, rimworld, ostranauts, kenshi, log | [every-session.md](every-session.md) |
| Never control the owner's mouse or keyboard; never edit or delete saves | modkit, companion, rimworld, ostranauts, kenshi, scope | [every-session.md](every-session.md) |
| Never commit credentials, personal paths, saves, game files or other authors' files | modkit, companion, rimworld, ostranauts, kenshi, scope | [every-session.md](every-session.md) |
| Never invent hour estimates; working slices over speculative frameworks | modkit, companion, rimworld, ostranauts, kenshi | [every-session.md](every-session.md) |
| Owner choices, agent defaults and agent choices are labelled as such | modkit, companion, rimworld, ostranauts, kenshi | [every-session.md](every-session.md) |
| Never use Figma; diagrams are Mermaid | modkit, companion, rimworld, ostranauts, kenshi, log | [every-session.md](every-session.md) |
| Run the gate before a commit and chain the commit on its exit code | modkit, companion, rimworld, kenshi, log | [every-session.md](every-session.md) |
| Write plainly: answer first, short sentences, bold for must-dos, tables for comparisons | modkit, companion, rimworld, kenshi, log | [every-session.md](every-session.md) |
| Nothing counts as tested until the owner says so | companion, rimworld, kenshi | [every-session.md](every-session.md) |
| D'thorga is the one brand for everything new; plain names; the "dthorga" spelling on public pages | companion, rimworld (and in part modkit, kenshi, scope) | [brand.md](brand.md) |
| The changelog's form: Unreleased, then dated Draft and Released entries, by section | rimworld, ostranauts, kenshi (and read by this kit's tools) | [changelogs.md](changelogs.md) |

## Limits

- A repository that has not pinned the kit is reached only by the owner's own instructions on their machine, which another
  contributor does not have.
- The check sees that a repository reads the rules, never that a session followed them.

## Reports and options

<!-- generated: options rules -->
Generated from the command's own parser by `python -m phobos_modkit command-docs --write`: change a help text in the parser, not here.

| Report | What it does | Effect |
| --- | --- | --- |
| `list` | The shared rule files, when each is read and what it covers. | reads only |
| `check` | Whether a repository reads the shared rules. Fails when the repository's CLAUDE.md or AGENTS.md does not read the shared rules. | reads only |

| Option | Reports | What it does | Default |
| --- | --- | --- | --- |
| `--root VALUE` | `check` | the repository (default: the current folder) |  |

Every report also takes `--json` (print JSON instead of Markdown) and `--no-redact` (show the home folder instead of ~).
<!-- end generated -->
