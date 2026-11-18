# Rules for every session, in every Phobos and D'thorga repository

These are the owner's standing rules for **every** game, mod, framework and tool repository: stated once here, in their current
form, and read at the start of every session. A repository's own `AGENTS.md` adds what is particular to it. **Where a repository
must differ from a rule here, it says so beside its own rule, with the owner's reason**; a difference with no such note is a
mistake to report, not a choice to follow. How this folder works, how a rule is changed, and what else it holds are in
[README.md](README.md).

**Keep this file short.** It is read every session, in every repository. A rule that matters only before one kind of work (art, a
release, a game's own systems) goes in a file of its own, listed in the README and read before that work.

## Commits and changelog entries

- **A change and its changelog entry go in the same commit.** The entry is how the owner reads what changed, and the commit that
  first wrote an entry is how the tools find its code (phobos-modkit's `changes`; D'thorga Companion's code viewer).
- **Commit separate changes separately, where they are separate anyway** (owner, 19 Nov 2026: of three ways to cut commits, once
  the code viewer showed that one commit writing eight entries gives the same 21 files for each of them). **Finish and commit one
  change before starting an unrelated one.** Two changes are separate when either could be shipped, or taken back, without the
  other.
- **One piece of work stays one commit**, however many entries it writes: changes that share code, or that make no sense without
  each other, are not split to look tidy. The tools name the entries a commit wrote together, so nothing is hidden.
- **Never untangle afterwards.** Two separate changes already in one working tree go in one commit, and its message says so.
  Never stage part of a file to split them: that commits something no check run ever saw, and a repository's commit guard
  refuses it.
- **A batch still shares a version.** Separate commits may write their entries under one version heading, for one install and one
  test list; the first of them carries the version's own lines.
- **Keep an entry's opening words when rewording it**, its bold opening where it has one: the tools match an entry by its opening,
  so a changed opening reads as one entry lost and another gained.

What this costs, said plainly: where a repository checks every commit (a gate, a commit guard), each separate commit needs its own
passing run. That is why the rule is "finish one before starting the next", where the run is one the change needed anyway, and not
"one commit for every entry", which the owner set aside.
