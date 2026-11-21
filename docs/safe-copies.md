# Safe copies: what cannot be made again, kept apart by kind

**Status (22 Nov 2026):** built in 1.66.0; the personal kind, the notes about the owner and settings' own defaults in 1.67.0; every
game in 1.71.0. In use: phobos-rimworld's training sets and style models; this repository's own list (`config/safe-copies.json`:
Claude Code's notes about the owner, shown under D'thorga Companion's Tools game); and the lists it keeps for each game's saves and
settings (`config/safe-copies/`: RimWorld, Ostranauts, Kenshi, Project Zomboid). D'thorga Companion's Home shows each list (0.42.0).

The owner asked on 21 Nov 2026: "Should we add backup functionality for our training sets, models, etc.?" The design, and the
owner's answers, are in phobos-rimworld's `docs/development/art-backups-handoff.md`. It is called *safe copies*, never *backups*,
so it is not mixed up with the install backups of `installs` (the owner's choice).

## Read this first (gotchas)

- **Copy what cannot be made again, not what is big.** A repository lists its sets in `config/safe-copies.json`. Caches are left
  out by pattern, and base models stay with the tool that downloads and hash-checks them.
- **A game's own files have a list of their own** (1.71.0): its saves and settings belong to the game, not to one of its mod
  repositories, so any repository may keep that game's list as `config/safe-copies/<game>.json` (this kit keeps the owner's:
  RimWorld, Ostranauts, Kenshi and Project Zomboid). **A new game needs that one file**, and a row in `game_folders.py` for
  where it keeps them. Commands read it with `--game GAME`; D'thorga Companion and the daily run find every such list
  through the repositories on the owner's games list.
- **A save that is a folder is copied, kept and let go whole** (1.71.0): `units` with `newest` takes the newest few folders,
  each dated by its newest file; `unitExclude` leaves autosave folders out by name; `status` offers a save that left the
  rotation as one copy, and `let-go` removes all of it.
- **Two rules for three kinds.** `own` may go anywhere the owner chose. **`game-derived` and `personal` go only to a folder
  marked private and local, never to a repository, and never to a folder that looks synced or shared**, even one marked private
  before a sync tool arrived. `personal` (1.67.0) is the owner's own but private: notes about them, a game's settings.
- **The walk skips folders the list could never take a file from** (1.67.0), so a list that takes `projects/*/memory/**` from
  Claude Code's folder never reads its gigabytes of transcripts, logs and caches.
- **A training is ours only when proven.** A `proven` set's unit is ours only when every picture in it is listed by hash in its
  manifest, and its marker file is there. One picture that is not listed makes the whole unit game-derived. A model follows the
  training it was made from (`unitOf`); a model no training explains is game-derived.
- **Nothing at a source is ever deleted, and no copy in use.** A changed file's earlier copy moves to
  `_safe-copies/earlier/<time>/`; git keeps the repository's. A file gone from its source keeps its copy, marked gone.
- **The one thing that goes** (1.68.0, the owner's word of 22 Nov 2026): **a set that names `keepEarlier` keeps that many earlier
  copies of each file** in the plain folder, and lets the oldest beyond them go, each named in the run's record. Without
  `keepEarlier`, every earlier copy stays.
- **`newest` takes only the newest few files** a set matches, by when each was last written (a save rotation: the owner keeps
  the two newest saves up to date). A file that falls out of them keeps its copies, and is never called gone.
- **Copies of files the list no longer takes are kept until asked** (1.69.0). `status` lists them with their sizes: a file
  gone from its source, or a save that left the newest pair. `let-go` removes one, named, or `--all` of them, with their earlier
  copies and their records, and only with `--apply`. It refuses any copy the list still takes.
- **A list speaks only for its own sets** (1.71.0). Every copy records which list made it (`from`). A run marks gone, and `status`
  offers to let go, only copies of the sets its own list names, so two lists of one game (two repositories of one game, or a
  game's saves kept apart from its repository's art) never take each other's copies away. **Two lists naming the same set of one
  game are refused** until one is renamed, since they would overwrite each other's copies.
- **A push that failed stays counted** (1.69.0): `status` says how many commits the repository's copy holds that its remote has
  not had yet (`data.destinations[].unsent`), until a run sends them.
- **Restore never writes over a different file unasked**: `--overwrite` replaces files older than the copy, and
  `--overwrite-newer` newer ones too. It never writes inside the copies themselves.
- **No graphics card, no game**: disk and git only, so it can run at any time, even mid-game.
- **A failed push is reported, never lost.** The copy is committed; the next run pushes whatever the remote does not have yet.

## Use

```text
python -m phobos_modkit safe-copies plan --root REPO           what a run would copy, where each kind may go, what is refused
python -m phobos_modkit safe-copies run --root REPO            copy what changed; commit and push the repository's copy
python -m phobos_modkit safe-copies run --root REPO --set trainings --no-push
python -m phobos_modkit safe-copies status --root REPO         each set: copied, changed since, never copied
python -m phobos_modkit safe-copies run --root KIT --game kenshi    a game's own list: its saves and settings
python -m phobos_modkit safe-copies verify                     hash every copy again against its record
python -m phobos_modkit safe-copies restore --root REPO --set trainings --unit house-v1 --to D:\restored\house-v1
python -m phobos_modkit safe-copies let-go --root REPO --file rimworld/saves/PG15.rws           what would go (a preview)
python -m phobos_modkit safe-copies let-go --root REPO --all --apply                              remove every copy no longer taken
python -m phobos_modkit safe-copies mark --to K:\phobos-modkit\safe-copies\local --private-local
python -m phobos_modkit safe-copies mark --to K:\phobos-modkit\safe-copies\dthorga-safe-copies --repository
```

Exit codes: 0 done; 1 problems (a failed copy or push, a damaged copy, a warning); 2 usage; 3 refused, with the reason in
`data.refusal`. `run` prints `report: <path>` to its run record, which phobos-rimworld's night summary picks up. `--json` gives
the envelope: `status` has `data.sets` (each with `kind`, `why` and, for each destination, `state`: copied, changed since, never
copied, refused or not ready) and `data.destinations`; `plan` has `data.units` and, for each destination, what it would copy and
refuse.

## Every day, everything (1.71.0)

```text
python -m phobos_modkit safe-copies run-all --settle --verify      every list on the games list, then every copy checked
python -m phobos_modkit safe-copies schedule                        whether the daily run is set, when, and how the last went
python -m phobos_modkit safe-copies schedule --at 04:00             set or move it
python -m phobos_modkit safe-copies schedule --off                  remove it (the copies stay)
```

- **`run-all` reads the owner's games list** (`companionGamesPath`, `PHOBOS_COMPANION_GAMES`, else D'thorga Companion's own
  folder; `--games` names one) and runs, for every repository on it, its own list and every game's list it keeps. **A new game
  or repository joins by being on the list.** A refused list, or a repository not on this PC, is a row with its reason; the rest
  still run. What it did is kept for the Companion in its folder, `safe-copies/last-run-all.json`.
- **`--settle` leaves files written in the last two minutes for the next run**, and a save that is a folder waits whole: the
  daily run may start while a game is saving. A set that left a file waiting says nothing is gone that run.
- **`schedule --at` sets one Windows scheduled task of the owner's own**, "D'thorga Safe Copies": no administrator and no
  password; daily at that time, **caught up at the next sign-in when the PC was off**, never two at once, stopped after three
  hours, at low priority and with no window (`pythonw.exe`). It runs `run-all --settle --verify` with the copy of the kit and
  the Python that set it, so set it from D'thorga Companion, whose kit moves with its updates. Windows only; elsewhere, run
  `run-all` from cron.
- **No graphics card**: it reads and writes disks and pushes to GitHub, so it may run mid-game, as the owner's runs do.

## Destinations

| Setting | Environment | What it is |
| --- | --- | --- |
| `safeCopiesPath` | `PHOBOS_SAFE_COPIES` | A plain folder. Marked `--local` it takes our own files; marked `--private-local` (refused when the folder looks synced) it takes game-derived files too |
| `safeCopiesRepositoryPath` | `PHOBOS_SAFE_COPIES_REPOSITORY` | The top folder of a clone of a private git repository, marked `--repository`. Our own files only, and no file over 95 MB (GitHub's limit is 100 MB) |
| `claudeHomePath` | `CLAUDE_CONFIG_DIR` | Not a destination: Claude Code's own folder, which this repository's list reads for the notes about the owner. Defaults to `~/.claude` (1.67.0) |
| `rimsortPath`, `ostranautsDataPath`, `kenshiDataPath`, `zomboidDataPath` | `PHOBOS_RIMSORT`, `PHOBOS_OSTRANAUTS_DATA`, `PHOBOS_KENSHI_DATA`, `PHOBOS_ZOMBOID_DATA` | Not destinations: where each game (and RimSort) keeps the player's own files, read by the games' lists (1.71.0). Each defaults to where it is on Windows, so nothing needs setting |

Set them on the Companion's Settings page or with `settings set`. A destination not chosen, not reachable or not marked is skipped,
and `status` says why. **Looks synced** means one of `.SynologyWorkingDirectory`, `.git`, `.dropbox`, `.sync` or `.stfolder` is in
the folder or above it, or a folder on the way is named like a sync service's (SynologyDrive, OneDrive, Dropbox, Google Drive,
iCloud Drive, Nextcloud, ownCloud).

Each destination holds copies at `<game>/<set>/[<unit>/]<path>`, and its own record in `_safe-copies/`: `state.json` (every file's
size, source time, SHA-256, kind, set, unit and when it was copied), `runs/<time>-<game>.json` (each run: what it copied, left,
refused and why, what failed, what is gone, what rebuilds it, and git's answer), and `earlier/`. In the repository a run's record
is kept only when the run changed something, so a quiet night makes no commit.

## The list: `config/safe-copies.json`

```json
{"schemaVersion": 1, "game": "rimworld",
 "sets": [
  {"name": "lora-trainings", "root": "loraWorkPath", "units": true, "kind": "proven",
   "proof": {"marker": "dataset/own-art.json", "manifest": "manifest.json", "hashKey": "sha256",
             "files": ["**/*.png", "**/*.jpg", "**/*.jpeg", "**/*.webp"]},
   "exclude": ["**/_t_e_cache", "**/_latent_cache", "**/.aitk_size.json"],
   "localOnly": ["output/**/*_0*.safetensors", "**/optimizer.pt"]},
  {"name": "style-models", "root": "comfyUiPath", "folder": "ComfyUI/models/loras",
   "include": ["phobos-private-*.safetensors"],
   "kind": {"unitOf": "lora-trainings", "pattern": "phobos-private-{unit}.safetensors"}},
  {"name": "art-notes", "root": "@repository", "folder": ".local/art", "include": ["*.json", "*.md"], "kind": "own"}],
 "provenance": [{"name": "ai-toolkit", "root": "aiToolkitPath"}, {"name": "base models", "file": "scripts/art/models.json"}]}
```

| Field | What it says |
| --- | --- |
| `game` | The first folder of every copy |
| `name` | The set's folder in every copy: letters, digits, dots and dashes |
| `root`, `env`, `folder` | Where the set is: a settings key (read in the usual order: argument, environment, the repository's settings file, the central file, then the default the kit knows for it, such as `claudeHomePath`'s `~/.claude` or RimWorld's Config folder), or `@repository`; then a folder under it. A root not set, with no default, is a note, not a failure |
| `include`, `exclude` | Globs on the path under the set (or under each unit): `*` and `?` stay in one folder, `**` crosses folders. An excluded folder is not even walked |
| `units` | Each folder directly under the set's folder is a unit of its own: a training, proven on its own; or a save that is a folder |
| `unitExclude` | 1.71.0, with `units`: units left out by name (globs, any case), such as `autosave*` |
| `newest` | 1.68.0: only the newest this many files the set matches, by when each was last written; with `units` (1.71.0), the newest this many units, each dated by its newest file. Its copies of what falls out stay, and it never marks a file gone |
| `keepEarlier` | 1.68.0: how many earlier copies of each file the plain folder keeps; the oldest beyond them are let go, each named in the run's record. Without it, every earlier copy stays |
| `kind` | `own`, `game-derived`, `personal`, `proven`, or `{"unitOf": SET, "pattern": "...{unit}..."}` |
| `proof` | For `proven`: the marker file, the manifest (a list of entries, or `{"files": [...]}`), the field holding each hash, and the globs it covers |
| `localOnly` | Files kept in the plain folder only, never the repository: checkpoints and resume files |
| `provenance` | What rebuilds the copies, recorded with every run: a folder's git commit (`root`) or a file's hash (`file`). This repository's own commit is always recorded |

## Limits

- **A proof is only as good as its manifest.** It shows every picture is one we listed; the listing itself is the art tools'
  (`lora_experiment.py picks` writes it from the owner's picks on `art-masters`).
- **It reads files as they stand.** A file changing while it is copied is refused and tried again next run.
- **One copy per destination, plus earlier versions.** No pruning: K: grows with every changed file, and the cleanup tool does
  not list earlier copies yet.
- **It cannot take a file back out of the repository.** A training found unproven after its files were pushed is warned about
  in every run until the owner looks; removing it from git history is the owner's call.
