# Installs: what updating or going back would change, and the moves themselves

**Status (18 Nov 2026):** built in 1.20.0; files, builds, settings changes, test rows, build and installing several mods at once in
1.21.0. D'thorga Companion's Mods page is its first consumer; deploy.py in phobos-rimworld still does the copying of an install.

## Read this first (gotchas)

- **What you would gain or lose is read from changelogs, not from the code.** Every installed copy and backup carries the
  `CHANGELOG.md` it was installed with. An entry one copy has and the other lacks is a gain or a loss. A changelog says what
  changed, never that it works in game.
- **restore and install refuse while the game runs.** backup only reads the install, so it works while the game runs.
- **Nothing is lost, but repeats go.** restore keeps the backup it put back, and the install it replaced becomes a new backup.
  **Then the mod's repeated backups are removed** (1.64.0, the owner's call of 20 Nov 2026), as `dedupe` does: a backup the
  same as the one before it, keeping the oldest of each run, so its contents are always still there. An install command does
  the same through `installs.tidy` (phobos-rimworld's deploy.py does). Other backups grow; the cleanup tool lists old ones, and
  deletes them only when the owner runs it with `--apply`.
- **A repository opts in** with `config/installs.json`. Without it, every report refuses.

## Run it

```text
python -m phobos_modkit installs status --root REPO              every mod
python -m phobos_modkit installs status --root REPO --mod NAME   one mod
python -m phobos_modkit installs backup --root REPO --mod NAME
python -m phobos_modkit installs restore --root REPO --mod NAME --backup NAME-20261118-200751
python -m phobos_modkit installs install --root REPO --mod NAME [--mod OTHER ...]
python -m phobos_modkit installs build --root REPO
python -m phobos_modkit installs dedupe --root REPO [--mod NAME] [--identical-only]
python -m phobos_modkit installs settings --root REPO
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
| `backups` | Where backups go, one zip each named `<Mod>-YYYYMMDD-HHMMSS.zip` (1.96.0; older ones stay folders of that name until packed) |
| `settings` | Optional: a settings file the adapter reads the game's folder from |
| `sharedSources` | Optional: folders shared by every mod, whose uncommitted changes count against each mod |
| `install` | The repository's own install command; `{python}` is the running Python, `{mod}` the mod's folder name (an element that is exactly `{mod}` becomes every mod named) |
| `installOnly` | Optional: file names only an install has (patterns), left out of the file comparison; the install record always is |
| `build` | Optional: `projects` (a glob of C# projects), `modProperty` (the project property naming the mod it builds into), `shared` (root build files every project reads) and `command` (the repository's build command) |
| `settingsChanges` | Optional: a command printing, as JSON, the settings added, removed or given a new default since `{commit}`: `mod`, `key`, `label`, `what`, `before`, `after` |
| `settingsHistory` | Optional (1.40.0): a command printing, as JSON, every setting change in the repository's history, oldest first: `time`, `commit` (null for what is not committed yet), `subject`, and the fields above. `installs settings` gives it newest first, with each mod's product name; `history timeline` adds the committed ones as facts |

## How gains and losses are read

- Each changelog is read forgivingly: `## [version]` or `## [Unreleased]` headings, `###` sections, and entries that start with
  `- `, continued on indented lines. A heading ending in "history" after the first version ends the mod's own log.
- Entries are matched by their text with spacing ignored, wherever they sit. An entry written under Unreleased and later given a
  version is in both copies, so it is neither gained nor lost.
- An entry lost and one gained with the same version, section and bold opening are paired as **reworded**: the same change,
  described again.
- Entries under **Save compatibility** are also listed apart (`saveNotes`), so a program can put them first.
- **Installing from the repository sets aside what a changelog cannot call lost** (1.53.0, after the owner's screen note of 20 Nov
  2026, "Why is it showing me as taking away nine entries?"). Such entries go to `unlisted`, not `lose`, and `unlistedWhy` gives each
  version's reason: `reused`, when both copies have the version with no entry under it in common (the number now names other
  work: one session renumbered, another took it); `uncommitted`, when the install record says the copy was built with changes
  not yet committed and the version is newer than any the repository's changelog has. Either way the changelog is silent on
  whether the code went. An entry dropped from a version both copies share, and any move to a backup, stays a loss.

## What else status compares (1.21.0)

| Field | What it says |
| --- | --- |
| `files` | Files installing would add, change or remove, counted by kind (code, Defs, patches, textures, text, sounds, About, other), with up to 60 paths. Equal size and date is equal; otherwise bytes are compared. **A changed assembly whose project's own sources are unchanged since the installed commit is marked `rebuilt`** (1.26.0), and `rebuilt` counts them: it differs because it was built at another commit (.NET stamps the commit into an assembly unless told not to) or against newer code it uses. It still counts as a change, since an assembly built against older code it uses can fail against the new. **Any other changed assembly names the sources that changed** (`sources`, up to five, and `sourcesInAll`), so a reader sees why it differs when no entry says (1.27.0) |
| `build` | Per C# project of the mod: whether its sources are newer than the assembly it built. It counts the project's folder, its `Compile Include` files from elsewhere and the `shared` files, never referenced projects, whose changes need not rebuild it |
| `installedCommit` | The install record's commit (`exact`), or for older installs the commit that first gave the mod its installed version (approximate) |
| `settings` | The settings changes since that commit for this mod, from `settingsChanges`; read once per commit, only for mods not already in step |
| `state` | `up-to-date`, `behind`, `ahead` or `differs` by the changelogs, or `unlisted` when the only difference is entries set aside (1.53.0); when they agree but files differ, `rebuilt` (every changed file only rebuilt) or `unlogged` (1.26.0) |
| `lookOut` | Test-list rows still waiting whose named version of the mod lies after the installed version and no later than the repository's (test-pass's `versionNames`) |

`build` runs the repository's build command; it writes only inside the repository, so it does not wait for the game to close.

## Backups kept as zips (1.96.0)

**Each backup is one zip** (the owner's choice of 23 Nov 2026, "One zip per backup", over plain folders and a store keeping each
file once). On the owner's 27 RimWorld backups: 4,254 MB as folders, about 855 MB as zips; the largest, 735 MB, became 95 MB in
7 seconds. Zip was chosen over 7z because Python reads and writes it with nothing installed, Windows opens it, and one file inside
is read without unpacking the rest; LZMA saved only 7% more.

- **`backup` writes a zip**, through a `.partial` file renamed once the zip reads back whole and holds the same files as the install.
- **`pack` turns backups kept as folders into zips**, one at a time, each checked file for file (`content_digests`, the same for a
  folder and its zip) before its folder goes. One that fails a check, or would leave under 1 GB free, stays a folder and is named.
  **Every install and go-back packs too**, after removing repeats (`installs.tidy`), so older backups turn into zips at the next
  install without anything to run.
- **Reading a zipped backup**: its name, version, changelog and install record, and the files `status` finds changed between the
  install and the repository, are copied into the kit's cache (`installs/backup-peeks/<backup>`), which is the folder `status`
  names for it, so a program can show a changed picture from it. A backup never changes, so they are copied once.
- **Going back to a zipped backup** unpacks it beside the game's mods folder, then swaps as before; the zip is kept. A zip naming
  a path outside its folder is refused.
- `content_digests` gives the full and lean digests in one reading. Their formula is unchanged, so digests kept for folders still hold.

## Repeated backups (1.40.0)

`status` marks each backup that repeats the one before it in time with `sameAs` (the oldest backup of its run, which is kept) and
`sameKind`:

| Kind | When |
| --- | --- |
| `identical` | The same file for file, the install record left out |
| `rebuilt` | The same version and every file but the assemblies the same, and none of the mod's own sources (its projects' inputs, from `build`) changed between the two commits their install records name: only a rebuild against newer code it uses tells them apart |

Only a run counts: A, A, B, A keeps the last A, since it is the newest backup from after B. `data.space` adds `duplicates` and
`duplicatesSize`. **`dedupe` deletes the repeats** (both kinds, or `--identical-only`), keeping the oldest of each run; each is
compared with the kept one again just before it goes, and the history log records `duplicates-removed`. Digests are kept in the
kit's cache (`installs/backup-digests.json`) by folder and size, so only new backups are read: the first `status` after this
reads every backup (about a minute for phobos-rimworld's 99, 5.5 GB).

**Every install and go-back removes them too** (1.64.0; the owner, 20 Nov 2026: removing repeated backups "should be part
of the normal process of install/updating mods"). `installs.tidy(where, mods)` runs `dedupe` with both kinds for the mods just
moved, and never raises, since the move has already succeeded: it returns what it removed and, if it could not finish, why.
`installs.tidy_lines` words both for a person. `restore` runs it and adds `removedRepeats` and `tidyProblem` to its data; the
repository's install command runs it itself (deploy.py in phobos-rimworld), so `install` does not run it a second time.
Removing a repeat keeps the oldest of its run, so the backup a go-back just made, or the one it put back, may be the one that
goes when an older twin holds the same files; the report says which.

## The install record

`InstallRecord.json` in an installed copy says where it came from: the commit, the time, and any files with uncommitted changes
under the mod's folder and `sharedSources`. The repository's install writes it (`installs.record_for` and `write_record`), so a
backup made from that install carries it too. A copy installed before records began has none, and status says nothing of its commit.

## What each move does

| Move | Does | Refuses when |
| --- | --- | --- |
| backup | Packs the installed mod into a new zip backup (through a `.partial` file, renamed once it reads back whole with the same files) | Not installed; under 1 GB would be left free |
| pack | Turns backups kept as folders into zips, each checked file for file before its folder goes | A check fails or under 1 GB would be left free: that backup stays a folder, named in `left` |
| restore | Copies the backup beside the game's mods folder, renames the install aside, renames the copy in, then moves the replaced install to a new backup. The backup is kept | The game runs; the name is not one of that mod's backups; something holds the install open; under 1 GB would be left free |
| install | Runs the repository's install command in the repository, and returns its last 40 lines | The game runs; it runs over an hour (it is then stopped, and says to check the install) |

The 1 GB margin and the hour are agent defaults.

## Limits

- Matching by text cannot tell a reworded entry from a new one unless its version, section and bold opening stay the same.
- A copy's version and name come from its own files; a hand-edited install is read as it stands.
- The install command's own safety (backing up what it replaces, refusing while the game runs) is the repository's; phobos-rimworld's
  deploy.py does both.
