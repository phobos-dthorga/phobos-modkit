# Shared rules: one place for what holds in every repository

**Status (19 Nov 2026):** created at the owner's request, with its first rules (commits and changelog entries). phobos-rimworld
and D'thorga Companion read it through their pinned copy of this repository. The rules waiting to move here are listed below; none
has been moved yet.

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
| [every-session.md](every-session.md) | At the start of every session | Commits and changelog entries |

`python -m phobos_modkit rules list` prints this with each file's rules counted, and `tests/test_rules.py` fails if a file here is
missing from the table.

## How a repository takes the rules up

| The repository | What it adds |
| --- | --- |
| Pins this kit at `external/phobos-modkit` | A line in its `CLAUDE.md`, `@external/phobos-modkit/rules/every-session.md`, so the file is loaded with its own rules; and a line in its `AGENTS.md` saying to read `external/phobos-modkit/rules/every-session.md` first, for a reader that does not follow imports |
| Does not pin the kit yet | Nothing until it is next worked on: then it pins the kit and adds the two lines. Until then, the owner's own instructions on their machine point every session at this folder in the kit's own checkout |
| Is this kit | `@rules/every-session.md` in its `CLAUDE.md`, and the pointer in its `AGENTS.md` |

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

## Where a rule belongs

| The rule is about | It lives in |
| --- | --- |
| How the owner and agents work, in any repository (commits, versions, honesty about testing, writing) | Here, in `every-session.md` if it applies to every session, else in a file of its own |
| One kind of work in any game (art and sound, releases, player language) | Here, in a file of its own, read before that work |
| One game's engine, mods or tools | That repository's `AGENTS.md`, or a file beside the work in it |
| What one version delivered | That repository's changelog, never a rules file |

## Waiting to move here

Found on 19 Nov 2026 by comparing the `AGENTS.md` of eight repositories: each of these is stated, in slightly different words, in
several of them. **None has been moved**: the wording of a rule is the owner's, and one wording has to be chosen from several.
Each moves on the owner's word, into the file named, and the repositories drop their copies as their pins move.

| Rule | Stated in | Would go in |
| --- | --- | --- |
| Never force-push or rewrite history; commit and push to `main` | modkit, companion, rimworld, ostranauts, kenshi, scope, log | `every-session.md` |
| Version numbers: a fix raises the last number, new functionality the middle, a rework the first | modkit, companion, rimworld, ostranauts, kenshi, log | `every-session.md` |
| Never control the owner's mouse or keyboard; never edit or delete saves | modkit, companion, rimworld, ostranauts, kenshi, scope | `every-session.md` |
| Never commit credentials, personal paths, saves, game files or other authors' files | modkit, companion, rimworld, ostranauts, kenshi, scope | `every-session.md` |
| Never invent hour estimates; working slices over speculative frameworks | modkit, companion, rimworld, ostranauts, kenshi | `every-session.md` |
| Owner choices, agent defaults and agent choices are labelled as such | modkit, companion, rimworld, ostranauts, kenshi | `every-session.md` |
| Never use Figma; diagrams are Mermaid | modkit, companion, rimworld, ostranauts, kenshi, log | `every-session.md` |
| Run the gate before a commit and chain the commit on its exit code | modkit, companion, rimworld, kenshi, log | `every-session.md` |
| Write plainly: answer first, short sentences, bold for must-dos, tables for comparisons | modkit, companion, rimworld, kenshi, log | `every-session.md` |
| Nothing counts as tested until the owner says so | companion, rimworld, kenshi | `every-session.md` |
| D'thorga is the one brand for everything new; plain names; the "dthorga" spelling on public pages | companion, rimworld (and in part modkit, kenshi, scope) | `brand.md` |
| The changelog's form: Unreleased, then dated Draft and Released entries, by section | rimworld, ostranauts, kenshi (and read by this kit's tools) | `changelogs.md` |

## Limits

- A repository that has not pinned the kit is reached only by the owner's own instructions on their machine, which another
  contributor does not have.
- The check sees that a repository reads the rules, never that a session followed them.
