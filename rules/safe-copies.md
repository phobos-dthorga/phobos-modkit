# Rules for what cannot be made again, in every Phobos and D'thorga repository

Read before making something that cannot be made again (a training, a model trained by us, notes or art masters kept outside
git), and before starting on a new game. The tool is phobos-modkit's `safe-copies` (its guide: `docs/safe-copies.md`); the
rules for every session are in [every-session.md](every-session.md); how this folder works is in [README.md](README.md).

These rules are the owner's yes of 22 Nov 2026 to an agent's proposal ("I want all of those"), after the safe copies were built
for the RimWorld art (21 Nov 2026) and then for every game.

## List it when it is made

- **Whatever cannot be made again is listed in the same commit as the work that first makes it**: a set in the repository's
  `config/safe-copies.json`, naming the setting for where it lives, never a personal path. A training set, a model we trained, a
  picked master, a note or record kept outside git: if losing the PC would lose it, it is listed. What is committed and pushed
  is already safe, and needs no list.
- **A game's own files are listed once, for the game**: its saves, its settings and a mod manager's lists go in
  `config/safe-copies/<game>.json`, kept in phobos-modkit, with a row in its `game_folders.py` for where the game keeps them.
  **Starting on a new game adds those two, and nothing in its mod repositories.** The daily run then takes it, through the
  owner's games list.
- **Check the list before its first run**: `safe-copies plan` (with `--game` for a game's list) says what it would take and
  where each file may go. Then tell the owner what is new: the sets, their sizes, and any setting added.

## Say each kind truthfully

- **Made from a game's files or another author's** (a training on game art, a model from it) is `game-derived`: it goes only
  to a folder marked private and local, never to a repository. **A training is ours only when its manifest proves it**
  (`proven`), never because we made it.
- **The owner's private matters** (saves, settings, notes about them) are `personal`: private and local only.
- **When unsure, choose the narrower kind.** A copy kept too privately can be widened later; one pushed cannot be taken back.

## The numbers and the removals are the owner's

- **How many saves, and how many earlier copies, are the owner's choice** (`newest`, `keepEarlier`). For a new game an agent
  follows the owner's last choice and says in the list that it is a default for the owner to change.
- **Never remove a copy without the owner's word for that copy.** `let-go` removes only what the owner named or agreed to;
  nothing ever deletes at a source.
