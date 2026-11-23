# Changelogs

Read before writing a changelog entry. The first part was stated in phobos-rimworld, phobos-ostranauts and phobos-kenshi, and moved
here on the owner's word (23 Nov 2026: "Move all 12 now"); the second is the owner's choice of the same day in the docs rewrite
(D2: "Leave old, shorten new"). `every-session.md` holds the rules about commits: a change and its entry in one commit, and an
entry's opening kept when it is reworded.

## Every changelog

- **Leave existing entries where they are.** Never move an entry to another file, split it or merge it: this kit's `changes` and
  `history`, and D'thorga Companion's code viewer, find an entry's code from its first line, in the same file, with `git blame`.
  An entry moved elsewhere shows the commit that moved it.
- **A new entry is short** (owner, 23 Nov 2026): its bold opening, then one or two sentences on what changed and why. How to use
  a thing goes in the guide or README it changes, and how it works in the design or reference page, each linked from the entry
  when it helps.

## A mod's changelog

- **The form**: an Unreleased section, then dated entries marked **Draft** until publication is confirmed, then **Released**
  with the real date. Sections, in this order where they are used: Added, Changed, Fixed, Balance, Dependencies, Save
  compatibility, Compatibility and limits.
- **Record what a player needs**: player-visible features, fixes, balance, dependencies, effects on saves, known limits, and
  whether it is tested in game.
- **No backticks or `>` in a mod's changelog lines**: release-note tooling built from them for Workshop pages rejects them.
