# Rules for every session, in every Phobos and D'thorga repository

These are the owner's standing rules for **every** game, mod, framework and tool repository: stated once here, in their current
form, and read at the start of every session. A repository's own `AGENTS.md` adds what is particular to it. **Where a repository
must differ from a rule here, it says so beside its own rule, with the owner's reason**; a difference with no such note is a
mistake to report, not a choice to follow. How this folder works, how a rule is changed, and what else it holds are in
[README.md](README.md).

**Keep this file short.** It is read every session, in every repository. A rule that matters only before one kind of work (art, a
release, a game's own systems) goes in a file of its own, listed in the README and read before that work.

## Before some kinds of work

Read the file named before doing the work, even when no file of that kind is open yet.

| Before | Read |
| --- | --- |
| Setting up or changing how a repository builds code, or adding a project or a build script | [builds.md](builds.md) |
| Naming anything players or the public see, or writing a public page (a README's opening, a Workshop description) | [brand.md](brand.md) |
| Writing a changelog entry | [changelogs.md](changelogs.md) |
| Designing or building a new behaviour for a game or mod | [designs.md](designs.md) |
| Writing or changing a `LICENSE`, starting a repository, or preparing a mod's first public page | [licences.md](licences.md) |
| Drafting a report of another author's fault, or hearing from the owner that one is posted | [reports.md](reports.md) |
| Making something that cannot be made again (a training, a model, notes or masters kept outside git), or starting on a new game | [safe-copies.md](safe-copies.md) |

## Working with the owner

Moved here from every repository's `AGENTS.md` on the owner's word (23 Nov 2026: "Move all 12 now"); the wording is chosen from
theirs by the agent that moved them, for the owner to revise.

- **Practical working slices over speculative frameworks, and never invent hour estimates.** Explain what works, what was
  checked and what remains uncertain.
- **Nothing counts as tested until the owner says so.** A build, a unit test, a run on a fixture or a browser audit is never a
  test in the game or on screen; write "not yet tested in game" (or "on screen") where it matters.
- **Never control the owner's mouse or keyboard**; give instructions for interactive steps. **Never edit, replace or delete the
  owner's saves**; read-only copies for diagnosis are fine, and are deleted afterwards.
- **Owner choices, agent defaults and agent choices are labelled as such** in design records, so the owner can revise them.
- **Write plainly**: answer first, short sentences, **bold** for must-dos, tables for comparisons. Diagrams are Mermaid in the
  Markdown; never use Figma.

## Git, versions and checks

- **Commit and push directly to `main`**, with no pull requests unless the owner asks. **Never force-push or rewrite history.**
  Several sessions may share a tree: commit explicit paths, and leave others' uncommitted work alone.
- **Versions**: a fix raises the last number, new functionality the middle, an incompatible change or a total rework the first.
  A release mixing a fix and a feature takes the middle.
- **Run the repository's gate before every commit and chain the commit on its exit code** (`gate && git commit ...`), never on
  reading its output, and never pass `--no-verify`. Each repository's `AGENTS.md` names its gate.
- **Never commit** credentials, personal paths, saves, logs, game files or assemblies, decompiled code, or other authors' mod
  files.

## Every game from the start

- **Build for every game from the start** (owner, 22 Nov 2026: "we should be trying to genericize as much as possible too so
  whatever is achievable can work across as many individual games and their mods from the get go, or with lesser follow-up at the
  very least"). A tool, a check or a Companion page is written game-free, in phobos-modkit or D'thorga Companion, and what one game
  needs is data: a row, a setting, or a small file. Code goes in one game's repository only when it is about that game's engine,
  and code shared by one game's mods goes in that game's own library.
- **What cannot be generic yet says what a next game would need**, in its design record or changelog entry, so the follow-up is
  small and known rather than found later.

## Tools the owner can install

- **Ask the owner to install a tool rather than work round its absence** (owner, 22 Nov 2026: "I honestly don't mind installing more
  tools; just let me know!", and "add that as a rule"). When a library, program or model would make the work clearly better or simpler
  (numpy for picture checks, a converter, a profiler), say what it is, what it gains and its licence, and ask; a workaround is for when
  the owner says no, or until it is installed. Installing still goes through the owner: agents never install system-wide by themselves.

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

## Sharing the machine with other sessions

- **Take a claim before using anything another session may also want** (owner's go-ahead, 19 Nov 2026, for the claims board in
  D'thorga Companion): a version number, a test row, a file being reworked. `python -m phobos_modkit claims list` shows who holds
  what; `claims take "phobos-modkit 1.44.0" --by <your session's name>` takes it, and is refused while another session holds it.
  **Release it once committed** (`claims release ... --by ...`, or `--all`). The Companion's Home shows the board.
- **A refused claim is a question for its holder**, sent as a message, never a reason to pick around it silently. A claim more than
  a day old is shown as old; take it over with `--force` only once its session has ended or agreed.
