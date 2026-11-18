# Installs: what updating or going back would change, and the moves themselves

**Status (18 Nov 2026):** built in 1.20.0; files, builds, settings changes, test rows, build and installing several mods at once in
1.21.0. D'thorga Companion's Mods page is its first consumer; deploy.py in phobos-rimworld still does the copying of an install.

## Read this first (gotchas)

- **What you would gain or lose is read from changelogs, not from the code.** Every installed copy and backup carries the
  `CHANGELOG.md` it was installed with. An entry one copy has and the other lacks is a gain or a loss. A changelog says what
  changed, never that it works in game.
- **restore and install refuse while the game runs.** backup only reads the install, so it works while the game runs.
- **Nothing is ever deleted.** restore keeps the backup it put back, and the install it replaced becomes a new backup. Backups
  grow; the cleanup tool lists old ones, and deletes them only when the owner runs it with `--apply`.
- **A repository opts in** with `config/installs.json`. Without it, every report refuses.

## Run it

```text
python -m phobos_modkit installs status --root REPO              every mod
python -m phobos_modkit installs status --root REPO --mod NAME   one mod
python -m phobos_modkit installs backup --root REPO --mod NAME
python -m phobos_modkit installs restore --root REPO --mod NAME --backup NAME-20261118-200751
python -m phobos_modkit installs install --root REPO --mod NAME [--mod OTHER ...]
python -m phobos_modkit installs build --root REPO
```

Add `--json` for the envelope. A refusal is still an envelope, with `data.ok` false and `data.refusal` saying why, and exit 1.

## The repository's config

```json
{"schemaVersion": 1, "game": "rimworld", "mods": "mods", "backups": ".local/deploy-backups",
 "settings": ".local/install-settings.json", "sharedSources": ["src"],
 "install": ["{python}", "scripts/deploy.py", "--build", "--apply", "{mod}"]}
```

| Key | What it says |
| --- | --- |
| `game` | The adapter: `games/<game>/installs.py` says where installed mods live, how to read a mod's name and version, and the game's process names |
| `mods` | The folder holding the repository's mods, one folder each with its `CHANGELOG.md` |
| `backups` | Where backups go, one folder each named `<Mod>-YYYYMMDD-HHMMSS` |
| `settings` | Optional: a settings file the adapter reads the game's folder from |
| `sharedSources` | Optional: folders shared by every mod, whose uncommitted changes count against each mod |
| `install` | The repository's own install command; `{python}` is the running Python, `{mod}` the mod's folder name (an element that is exactly `{mod}` becomes every mod named) |
| `installOnly` | Optional: file names only an install has (patterns), left out of the file comparison; the install record always is |
| `build` | Optional: `projects` (a glob of C# projects), `modProperty` (the project property naming the mod it builds into), `shared` (root build files every project reads) and `command` (the repository's build command) |
| `settingsChanges` | Optional: a command printing, as JSON, the settings added, removed or given a new default since `{commit}`: `mod`, `key`, `label`, `what`, `before`, `after` |

## How gains and losses are read

- Each changelog is read forgivingly: `## [version]` or `## [Unreleased]` headings, `###` sections, and entries that start with
  `- `, continued on indented lines. A heading ending in "history" after the first version ends the mod's own log.
- Entries are matched by their text with spacing ignored, wherever they sit. An entry written under Unreleased and later given a
  version is in both copies, so it is neither gained nor lost.
- An entry lost and one gained with the same version, section and bold opening are paired as **reworded**: the same change,
  described again.
- Entries under **Save compatibility** are also listed apart (`saveNotes`), so a program can put them first.

## What else status compares (1.21.0)

| Field | What it says |
| --- | --- |
| `files` | Files installing would add, change or remove, counted by kind (code, Defs, patches, textures, text, sounds, About, other), with up to 60 paths. Equal size and date is equal; otherwise bytes are compared |
| `build` | Per C# project of the mod: whether its sources are newer than the assembly it built. It counts the project's folder, its `Compile Include` files from elsewhere and the `shared` files, never referenced projects, whose changes need not rebuild it |
| `installedCommit` | The install record's commit (`exact`), or for older installs the commit that first gave the mod its installed version (approximate) |
| `settings` | The settings changes since that commit for this mod, from `settingsChanges`; read once per commit, only for mods not already in step |
| `lookOut` | Test-list rows still waiting whose named version of the mod lies after the installed version and no later than the repository's (test-pass's `versionNames`) |

`build` runs the repository's build command; it writes only inside the repository, so it does not wait for the game to close.

## The install record

`InstallRecord.json` in an installed copy says where it came from: the commit, the time, and any files with uncommitted changes
under the mod's folder and `sharedSources`. The repository's install writes it (`installs.record_for` and `write_record`), so a
backup made from that install carries it too. A copy installed before records began has none, and status says nothing of its commit.

## What each move does

| Move | Does | Refuses when |
| --- | --- | --- |
| backup | Copies the installed mod to a new backup (through a `.partial` folder, renamed when complete) | Not installed; under 1 GB would be left free |
| restore | Copies the backup beside the game's mods folder, renames the install aside, renames the copy in, then moves the replaced install to a new backup. The backup is kept | The game runs; the name is not one of that mod's backups; something holds the install open; under 1 GB would be left free |
| install | Runs the repository's install command in the repository, and returns its last 40 lines | The game runs; it runs over an hour (it is then stopped, and says to check the install) |

The 1 GB margin and the hour are agent defaults.

## Limits

- Matching by text cannot tell a reworded entry from a new one unless its version, section and bold opening stay the same.
- A copy's version and name come from its own files; a hand-edited install is read as it stands.
- The install command's own safety (backing up what it replaces, refusing while the game runs) is the repository's; phobos-rimworld's
  deploy.py does both.
