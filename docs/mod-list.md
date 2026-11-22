# Mod list: what is wrong with a game's active mods, and why

**Status (22 Nov 2026):** built in 1.72.0 for RimWorld and Project Zomboid; 1.73.0 adds the list editor's side (`mods`, moving, switching on at a place, and an undo that walks back one change at a time); 1.74.0 the sorter (`sort`), the owner's own rules (`rules`) and changes to several mods at once; 1.76.0 saved lists (`lists`, `compare`, `load`, `save`, `forget`, `export`) and a copy kept at each game start; 1.77.0 subscribing and unsubscribing through Steam. It is the first step of D'thorga Companion's own mod
manager (the owner, 22 Nov 2026: "We actually should have our own, third-party, mod managing", after RimSort said only "1 missing
mod" for a patch whose author had taken it off the Workshop). The Companion's Mod list page shows it from 0.45.0.

## Read this first (gotchas)

- **`check` only reads**, apart from the check's own memory file. `--online` also asks Steam's public Workshop API which items
  still exist (no account, no sign-in).
- **`fix` and `undo` change nothing without `--apply`.** With it, each keeps a backup of the list as it stood first, and **refuses
  while the game or a program that rewrites the list is running** (RimSort, RimPy), because either would write over the change.
- **`undo` walks back one change at a time** (1.73.0): each undo marks the change it went back on, so pressing it again goes back on the one before. There is no redo; the list as it stood before each undo is kept as a backup.
- **`undo` refuses when the list changed after the change it would undo** (a game or a mod manager saved it since), because going
  back would throw those changes away. Name the backup with `--backup` to go back anyway.
- **Nothing here deletes a backup or forgets a mod.** Both live in D'thorga Companion's folder, `mod-list/<game>/` (setting
  `modListPath`, variable `PHOBOS_MOD_LIST`).
- **A clue is not proof.** When a missing mod was a patch between two others, the check looks inside those mods' own files for
  the other's name. A hit says one of them may now do the patch's job itself; check its page before relying on it.
- **Project Zomboid's own rules are less certain**: its process names, whether the game sorts the list itself and whether ids are
  compared with case were not confirmed (the game was not installed when it was built). Its order warnings follow each mod's own
  mod.info. With the game not installed, Workshop mods on a list are counted as "could not be looked for", never as missing.

## Commands

| Command | What it does | Effect |
| --- | --- | --- |
| `mod-list check --name GAME [--online] [--list KEY]` | Every problem, warning and note with each list, with the changes offered | reads (online with `--online`) |
| `mod-list fix --name GAME --list KEY --remove ID [--apply]` | Takes a mod off a list; `--remove-extra ID` keeps its first entry; `--enable ID` switches it on just before the first mod that needs it | writes with `--apply` |
| `mod-list fix --name GAME --list KEY --move ID --to PLACE [--apply]` | Moves a mod to a place (1 is first); `--enable ID --to PLACE` switches one on there (1.73.0) | writes with `--apply` |
| `mod-list sort --name GAME --list KEY [--full] [--apply]` | The list sorted from every rule, each move explained; `--full` rebuilds the whole order (1.74.0) | writes with `--apply` |
| `mod-list rules --name GAME [--mod ID --after OTHER \| --before OTHER \| --top \| --bottom \| --drop N] [--apply]` | Your own rules, your RimSort rules (read only), and every rule set the sorter reads; adds or takes away one of yours (1.74.0) | writes with `--apply` |
| `mod-list since --name GAME [--list KEY]` | What the first game run after the last change made here showed: new errors, clean, or why it cannot tell (1.85.0) | reads |
| `mod-list lists --name GAME` | Every saved list: by name, kept at game starts, each save's, RimSort's history (1.76.0) | reads |
| `mod-list compare --name GAME --list KEY (--from SOURCE:REF \| --file PATH)` | What loading a list would switch on, off and move, and which of its mods are not on this PC, with why | reads |
| `mod-list load --name GAME --list KEY (--from SOURCE:REF \| --file PATH) [--apply]` | Loads it, leaving out mods not on this PC, after a backup | writes with `--apply` |
| `mod-list save --name GAME --list KEY --as NAME [--replace] [--apply]` / `forget --saved NAME` | Keeps the list by name; takes a saved list away | writes with `--apply` |
| `mod-list export --name GAME (--list KEY \| --from SOURCE:REF) --to PATH [--apply]` | Writes a list as the game's own file (RimWorld `.rml`) | writes with `--apply` |
| `mod-list subscribe --name GAME --item N [--item N ...] [--wait SECONDS] [--apply]` | Subscribes through the running Steam client and asks for each download; `--wait` reports Steam's progress until all are installed (1.77.0) | writes with `--apply` |
| `mod-list unsubscribe --name GAME --list KEY --item N [...] [--apply]` | Switches those mods off (after a backup), then unsubscribes; Steam then deletes their files | writes with `--apply` |
| `mod-list undo --name GAME --list KEY [--backup FILE] [--apply]` | Goes back on the latest change made here not yet gone back on; again, on the one before | writes with `--apply` |
| `mod-list mods --name GAME` | Every mod on this PC (key, name, source, Workshop number, authors, versions, needs) and each list's entries in order, joined by key, with how many changes each list can still go back on (1.73.0) | reads |
| `mod-list backups --name GAME` | Every backup kept, newest first | reads |
| `mod-list games` | The games whose lists it can read | reads |

`GAME` is a name or id (`RimWorld`, `project-zomboid`), or give `--app-id`. A game without an adapter gets a check whose data says
`supported: false` and why, in words.

## What it checks

| Kind | Severity | When | Change offered |
| --- | --- | --- | --- |
| `missing` | problem | A list names a mod that is not on this PC | Take it off |
| `twice` | problem | A mod is on a list more than once | Keep the first |
| `needs` | problem | A mod needs one that is switched off, or not on this PC | Switch it on (when here) |
| `clash` | problem | Two mods are on that one of them says do not work together | Switch either off |
| `order` | warning | A mod loads before one it must load after, or the reverse | None here: `sort` puts it right |
| `removed` | warning | A mod on this PC that the Workshop no longer has (with `--online`) | None |
| `unsubscribed` | warning | A Workshop mod on this PC that Steam no longer keeps for you | None |
| `library` | note | Several active mods carry the same library and an older copy loads first (1.85.0) | None: load the newer above, or ask for an update |
| `version-likely` | note | Mods that do not say they work with this version but are known or likely to, and why (1.85.0) | None |
| `replacement` | note | A missing or out-of-date mod has a continued version for this game version (1.85.0) | Subscribe to it |
| `version` | note | A mod that does not say it works with this game version | None |
| `unchecked` | note | Mods a list names that could not be looked for (the game not installed) | None |

**Why a mod is missing**, likeliest first: taken off the Workshop or made private (Steam answers "no such item"), no longer
subscribed (not in Steam's `appworkshop_<app>.acf`), a download not finished (subscribed, files missing), a local folder gone, or
never seen here. The reason rests on the **memory**: every check records each mod on this PC (name, source, Workshop number, needs,
load-after), so a mod is still known after its files go. A mod no check ever saw has no Workshop number to ask Steam about.

## Each game

- **RimWorld** (`games/rimworld/mod_list.py`): one list, `Config/ModsConfig.xml` (`active`). Mods from `Data` (the game and its
  expansions), `Mods` and the Workshop folder, each from `About/About.xml`. As the 1.7 game code reads them: a `...ByVersion` list
  for the running version replaces the plain one; `forceLoadAfter`/`forceLoadBefore` count as order rules; a need is not one.
  Writing changes only the `<activeMods>` block, in the file's own indentation and line endings.
- **Project Zomboid** (`games/zomboid/mod_list.py`): `mods/default.txt` (`default`) and each save's `mods.txt`
  (`save:<mode>/<save>`). Mods from `mods/`, the author's own `Workshop/<item>/Contents/mods/` and Steam's
  `workshop/content/108600/<item>/mods/`, each from the `mod.info` of the highest version folder not above the game's
  (`version.txt`). Writing changes only the `mods { }` block; `mods/reset-mods-42_00.txt` is never touched (without it the game
  empties `default.txt`).

A new game is one module with `adapter()` and a row in `games/__init__.py`'s `MOD_LIST_GAMES`.

## Sorting (1.74.0)

**Where a rule comes from**, strongest first: **yours** (made here, in `rules.json`, or in RimSort), **own** (the mod's load after
and load before), **needs** (a mod loads after what it needs, as RimSort does with "use modDependencies as loadAfter"), and
**code** (1.84.0: a mod loads after any mod whose assembly holds the parent classes or interfaces of its own loaded code, read from the assemblies' metadata; a call inside a method does not count), **workshop** (1.79.0: a mod loads after the items its Workshop page lists as required; RimWorld: RimSort's Steam Workshop Database) and **community** (RimWorld: RimSort's Community Rules database). Strength is used only to choose which rule of a loop to set aside
(agent's order). A mod may also be asked to load **at the top** (as early as its rules allow, never above the game's own unless a
rule puts it there, as Harmony's does) or **at the bottom**.

- **Fewest moves** (the default): Kahn's sort, choosing among the mods whose rules are met the one highest on the list now; done
  forwards and backwards (building from the end), keeping whichever moves fewer. A **moved** mod is one outside the longest run of
  mods whose order is kept, so a list that keeps every rule comes back unchanged.
- **Full re-sort** (`--full`): the same sort with every mod below the game's own unless a rule puts it above; from 1.84.0 a mod others load after comes next, the most used first (libraries first), then the rest by name.
- Each move lists the rules it broke where it stood, with whose they are and any note the rule carries; a mod moved only to keep a
  rule with another moved mod says so.
- **Refused**: a mod listed twice (take the extra off first). A list changed between the sort and `--apply` is refused too, since
  `--apply` sorts afresh and checks it writes the same mods.

Not confirmed, and said so: how RimSort itself reads "load at the top" (it left two such mods where this sorter lifts them), and
whether Project Zomboid has any shared community rules (none are read for it).

## Saved lists (1.76.0)

A list's **source** and **ref** name it (`--from saved:Quiet`, `save:PG18.rws`, `manager:Default/<file>.json`, `kept:<time>`).
Lists saved by name live in `mod-list/<game>/lists/`, copies kept at game starts in `mod-list/<game>/kept/`; each holds the ids
in order with the names and Workshop numbers known when it was kept, so a mod gone since can still be named. Loading leaves out
mods not on this PC and names each with why (as the check does; a list from a save knows names but no Workshop numbers, so those
say to look on the Workshop by name). **A copy kept at a game start** is made by the next read of the list after the start, when
the list then is the one the game started with (unchanged more than two minutes after the game last wrote its log) and differs
from the last copy; nothing is kept while the tools are not run, so a start followed by a change before the next read is missed.

Not confirmed, and said so: RimSort's history times are read from its files' times; Project Zomboid has no start record yet.

## Subscribing through Steam (1.77.0)

The tools borrow **the game's own Steam library** (`steam_api64.dll` in RimWorld's folder) and join the Steam client already
running and signed in, as the game would (`SteamAppId`), for the seconds a press takes: Steam shows the person as playing the game
meanwhile. Nothing of Steam's is shipped and no account details are held. A subscribe or unsubscribe call is waited for up to 30
s; whether it worked is read back from `GetItemState`, not assumed. **Agents never run these on the owner's account**: only the
person's own press does, so the Steamworks calls had not met a real client when 1.77.0 was made.

## Backups

`mod-list/<game>/backups/<UTC time>--<list>.list` holds the list file as it stood, byte for byte; the `.json` beside it says which
list, where, what the change was, a hash of what was written (how `undo` sees a later change), and from 1.73.0 `undone` once an undo has gone back on it. Going back keeps the list as it
then stood as a backup too ("before going back").
