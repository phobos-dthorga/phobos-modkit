# Mod list: what is wrong with a game's active mods, and why

For RimWorld and Project Zomboid: the first step of D'thorga Companion's own mod manager (the owner, 22 Nov 2026: "We actually should
have our own, third-party, mod managing", after RimSort said only "1 missing mod" for a patch whose author had taken it off the
Workshop). The Companion's Mod list page shows it.

## Read this first

- **`check` only reads**, apart from the check's own memory file. `--online` also asks Steam's public Workshop API which items
  still exist (no account, no sign-in).
- **`fix` and `undo` change nothing without `--apply`.** With it, each keeps a backup of the list as it stood first, and **refuses
  while the game or a program that rewrites the list is running** (RimSort, RimPy), because either would write over the change.
- **`undo` walks back one change at a time**: each undo marks the change it went back on, so pressing it again goes back on the
  one before. There is no redo; the list as it stood before each undo is kept as a backup.
- **`undo` refuses when the list changed after the change it would undo** (a game or a mod manager saved it since), because going
  back would throw those changes away. Name the backup with `--backup` to go back anyway.
- **Nothing here deletes a backup or forgets a mod.** Both live in D'thorga Companion's folder, `mod-list/<game>/` (setting
  `modListPath`, variable `PHOBOS_MOD_LIST`).
- **A clue is not proof.** When a missing mod was a patch between two others, the check looks inside those mods' own files for
  the other's name. A hit says one of them may now do the patch's job itself; check its page before relying on it.
- **Project Zomboid's own rules are less certain**: its process names, whether the game sorts the list itself and whether ids are
  compared with case were not confirmed (the game was not installed when it was built). Its order warnings follow each mod's own
  mod.info. With the game not installed, Workshop mods on a list are counted as "could not be looked for", never as missing.

## Examples

| Command | What it does | Effect |
| --- | --- | --- |
| `mod-list check --name GAME [--online] [--known] [--list KEY]` | Every problem, warning and note with each list, with the changes offered; `--known` adds the known problems the kit's feeds last gave (no network) | reads (online with `--online`) |
| `mod-list fix --name GAME --list KEY --remove ID [--apply]` | Takes a mod off a list; `--remove-extra ID` keeps its first entry; `--enable ID` switches it on just before the first mod that needs it | writes with `--apply` |
| `mod-list fix --name GAME --list KEY --move ID --to PLACE [--apply]` | Moves a mod to a place (1 is first); `--enable ID --to PLACE` switches one on there | writes with `--apply` |
| `mod-list write --name GAME --list KEY [--apply]` | A whole new list at once, read as JSON on standard input, `{"ids": [...], "was": [...]}`: D'thorga Companion's **Save** (1.142.0). Refused when the list changed since `was`, a mod would be listed twice, a mod switched on is not on this PC, or nothing changed; a backup first, as every change | writes with `--apply` |
| `mod-list sort --name GAME --list KEY [--full] [--apply]` | The list sorted from every rule, each move explained; `--full` rebuilds the whole order | writes with `--apply` |
| `mod-list rules --name GAME [--mod ID --after OTHER \| --before OTHER \| --top \| --bottom \| --drop N] [--apply]` | Your own rules, your RimSort rules (read only), and every rule set the sorter reads; adds or takes away one of yours | writes with `--apply` |
| `mod-list rules --name GAME --import-manager [--apply]` | Brings your rules over from the game's mod manager (RimSort), each one not kept already, with its note; once brought, RimSort's copy is no longer read until it changes there (1.144.0) | writes with `--apply` |
| `mod-list databases --name GAME [--fetch [--stale] [--only NAME]]` | The community lists the sorter and the check read, the kit's copy or the mod manager's, whichever is newer, and how old; `--fetch` fetches them from GitHub (1.144.0) | reads online with `--fetch` |
| `mod-list start --name GAME [--apply]` | Starts the game through the Steam client (`steam://rungameid/<app id>`), as pressing Play in its library or a mod manager's Run game; refused while the game runs (1.146.0) | runs a program with `--apply` |
| `mod-list since --name GAME [--list KEY]` | What the first game run after the last change made here showed: new errors, clean, or why it cannot tell | reads |
| `mod-list lists --name GAME` | Every saved list: by name, kept at game starts, each save's, RimSort's history | reads |
| `mod-list compare --name GAME --list KEY (--from SOURCE:REF \| --file PATH)` | What loading a list would switch on, off and move, and which of its mods are not on this PC, with why | reads |
| `mod-list load --name GAME --list KEY (--from SOURCE:REF \| --file PATH) [--apply]` | Loads it, leaving out mods not on this PC, after a backup | writes with `--apply` |
| `mod-list save --name GAME --list KEY --as NAME [--replace] [--apply]` / `forget --saved NAME` | Keeps the list by name; takes a saved list away | writes with `--apply` |
| `mod-list export --name GAME (--list KEY \| --from SOURCE:REF) --to PATH [--apply]` | Writes a list as the game's own file (RimWorld `.rml`) | writes with `--apply` |
| `mod-list subscribe --name GAME --item N [--item N ...] [--wait SECONDS] [--apply]` | Subscribes through the running Steam client and asks for each download; `--wait` reports Steam's progress until all are installed | writes with `--apply` |
| `mod-list unsubscribe --name GAME --list KEY --item N [...] [--apply]` | Switches those mods off (after a backup), then unsubscribes; Steam then deletes their files | writes with `--apply` |
| `mod-list undo --name GAME --list KEY [--backup FILE] [--apply]` | Goes back on the latest change made here not yet gone back on; again, on the one before | writes with `--apply` |
| `mod-list mods --name GAME` | Every mod on this PC (key, name, source, Workshop number, authors, versions, needs) and each list's entries in order, joined by key, with how many changes each list can still go back on | reads |
| `mod-list backups --name GAME` | Every backup kept, newest first | reads |
| `mod-list games` | The games whose lists it can read | reads |

`GAME` is a name or id (`RimWorld`, `project-zomboid`), or give `--app-id`. A game without an adapter gets a check whose data says
`supported: false` and why, in words.

## Reports and options

<!-- generated: options mod-list -->
Generated from the command's own parser by `python -m phobos_modkit command-docs --write`: change a help text in the parser, not here.

| Report | What it does | Effect |
| --- | --- | --- |
| `check` | Every problem with the game's lists of active mods, why, and the changes offered. | reads public pages online, with `--online` |
| `fix` | One change to a list, after a backup; only with `--apply`. | writes, with `--apply` |
| `write` | Write a whole new list, read as JSON from standard input, after a backup; only with `--apply`. Reads the new list as JSON on standard input: {"ids": [...], "was": [...]}. | writes, with `--apply` |
| `undo` | Put a list back as it was before the last change made here; only with `--apply`. | writes, with `--apply` |
| `sort` | The list sorted from every rule, each move explained; written only with `--apply`. | writes, with `--apply` |
| `rules` | Your own load-order rules, and every rule set the sorter reads. | writes, with `--apply` |
| `databases` | The community lists the sorter and the check read: where from and how old. With `--fetch`, reads public files from raw.githubusercontent.com, keyless, into the kit's cache. | reads public pages online, with `--fetch` |
| `start` | Start the game through Steam, refused while it runs; only with `--apply`. Hands steam://rungameid/\<app id> to the system's opener, so the Steam client starts the game. | runs other programs, with `--apply` |
| `since` | What the first game run after the last change made here showed; only reads. | reads only |
| `lists` | Every saved list: by name, kept at game starts, each save's, and RimSort's history. | reads only |
| `compare` | What loading a list would change; only reads. | reads only |
| `load` | Load a list in place of the one the game reads, after a backup; only with `--apply`. | writes, with `--apply` |
| `save` | Keep the list as it stands, by name; only with `--apply`. | writes, with `--apply` |
| `forget` | Take away a list saved by name; only with `--apply`. | writes, with `--apply` |
| `export` | Write a list as the game's own list file; only with `--apply`. | writes, with `--apply` |
| `subscribe` | Subscribe to Workshop items through the running Steam client; only with `--apply`. | writes, with `--apply` |
| `unsubscribe` | Switch Workshop mods off, then unsubscribe through Steam; only with `--apply`. | writes, with `--apply` |
| `mods` | Every mod on this PC, and where each of the game's lists has it. | reads only |
| `backups` | Every backup kept of the game's lists, newest first. | reads only |
| `games` | The games whose lists the check can read. | reads only |

| Option | Reports | What it does | Default |
| --- | --- | --- | --- |
| `--name VALUE` | all but `games` | the game, by name or id (RimWorld, project-zomboid) |  |
| `--app-id N` | all but `games` | the game's Steam app ID, instead of its name |  |
| `--data VALUE` | all but `games` | the game's own data folder, where the tools would not find it |  |
| `--settings VALUE` | all but `games` | a JSON settings file with the games' paths |  |
| `--list KEY` | `check`, `fix`, `write`, `undo`, `sort`, `since`, `compare`, `load`, `save`, `export`, `unsubscribe` | only this list, by the key a check names |  |
| `--online` | `check` | ask Steam which Workshop items still exist |  |
| `--known` | `check` | also warn of known problems, from the known-problems feeds the kit last read (no network) |  |
| `--remove ID` | `fix` | take this mod off the list (again for several). Repeatable. |  |
| `--remove-extra ID` | `fix` | keep the first entry of this mod and take the others off |  |
| `--enable ID` | `fix` | switch this mod on: at `--to`, else just before the first mod that needs it (again for several). Repeatable. |  |
| `--move ID` | `fix` | move this mod to the place `--to` names (again for several, moved as one block). Repeatable. |  |
| `--to PLACE` | `fix` | the place a mod moved or switched on goes to, 1 first (1.73.0) |  |
| `--apply` | `fix` | make the change; without it, only say what it would be |  |
| `--apply` | `write`, `load`, `export` | write it; without it, only say what it would do |  |
| `--backup VALUE` | `undo` | this backup (its file name), instead of the latest |  |
| `--apply` | `undo` | go back; without it, only say what it would do |  |
| `--full` | `sort` | rebuild the whole order (else move only what a rule says is out of place) |  |
| `--apply` | `sort` | write the sorted list, after a backup |  |
| `--mod ID` | `rules` | the mod a new rule is about |  |
| `--after OTHER` | `rules` | it loads after this mod |  |
| `--before OTHER` | `rules` | it loads before this mod |  |
| `--top` | `rules` | it loads as near the top as its rules allow |  |
| `--bottom` | `rules` | it loads as near the bottom as its rules allow |  |
| `--drop N` | `rules` | take your rule N away (as `rules` numbers them) |  |
| `--import-manager` | `rules` | bring your rules over from the game's mod manager (RimSort), each one not kept already (1.144.0) |  |
| `--apply` | `rules` | keep the change; without it, only say what it would be |  |
| `--fetch` | `databases` | fetch them from their public GitHub repositories into the kit's cache (keyless) |  |
| `--stale` | `databases` | with `--fetch`, only the lists older than 7 days |  |
| `--only NAME` | `databases` | with `--fetch`, only this list (again for several). Repeatable. |  |
| `--apply` | `start` | ask Steam to start it; without it, only say what it would do |  |
| `--from SOURCE:REF` | `compare`, `load` | a list as `lists` names it: saved:NAME, kept:TIME, save:FILE, manager:FILE |  |
| `--last-clean` | `compare`, `load` | the newest list kept at a game start that then ran clean (1.85.0) |  |
| `--file PATH` | `compare`, `load` | a list file (the game's .rml, a save, an exported RimSort list) |  |
| `--as NAME` | `save` | the name to keep it by. Required. |  |
| `--replace` | `save` | replace a list kept by that name |  |
| `--apply` | `save` | keep it; without it, only say what it would do |  |
| `--saved NAME` | `forget` | the saved list's name, as `lists` gives its ref. Required. |  |
| `--apply` | `forget` | take it away; without it, only say what it would do |  |
| `--from SOURCE:REF` | `export` | a saved list, instead of the game's list |  |
| `--to PATH` | `export` | the file to write. Required. |  |
| `--item N` | `subscribe`, `unsubscribe` | a Workshop number (again for several). Required. Repeatable. |  |
| `--wait SECONDS` | `subscribe` | wait this long for Steam to download them, saying how far it is | `0` |
| `--apply` | `subscribe` | subscribe; without it, only say what it would do |  |
| `--apply` | `unsubscribe` | do it; without it, only say what it would do |  |

- Every report also takes `--json` (print JSON instead of Markdown) and `--no-redact` (show the home folder instead of ~).
- [Common options](common-options.md) explains `--settings`, `--top`, `--json` and `--no-redact`, which many commands share.
- Only one of `--remove`, `--remove-extra`, `--enable`, `--move` at a time (`fix`).
- Only one of `--after`, `--before`, `--top`, `--bottom`, `--drop`, `--import-manager` at a time (`rules`).
- Only one of `--from`, `--last-clean`, `--file` at a time (`compare`, `load`).
<!-- end generated -->

## Inputs

### Each game

- **RimWorld** (`games/rimworld/mod_list.py`): one list, `Config/ModsConfig.xml` (`active`). Mods from `Data` (the game and its
  expansions), `Mods` and the Workshop folder, each from `About/About.xml`. As the 1.7 game code reads them: a `...ByVersion` list
  for the running version replaces the plain one; `forceLoadAfter`/`forceLoadBefore` count as order rules; a need is not one.
  Writing changes only the `<activeMods>` block, in the file's own indentation and line endings.
- **Project Zomboid** (`games/zomboid/mod_list.py`): `mods/default.txt` (`default`) and each save's `mods.txt`
  (`save:<mode>/<save>`). Mods from `mods/`, the author's own `Workshop/<item>/Contents/mods/` and Steam's
  `workshop/content/108600/<item>/mods/`, each from the `mod.info` of the highest version folder not above the game's
  (`version.txt`). Writing changes only the `mods { }` block; `mods/reset-mods-42_00.txt` is never touched (without it the game
  empties `default.txt`).

### Saved lists

A list's **source** and **ref** name it (`--from saved:Quiet`, `save:PG18.rws`, `manager:Default/<file>.json`, `kept:<time>`).
Lists saved by name live in `mod-list/<game>/lists/`, copies kept at game starts in `mod-list/<game>/kept/`; each holds the ids
in order with the names and Workshop numbers known when it was kept, so a mod gone since can still be named. Loading leaves out
mods not on this PC and names each with why (as the check does; a list from a save knows names but no Workshop numbers, so those
say to look on the Workshop by name). **A copy kept at a game start** is made by the next read of the list after the start, when
the list then is the one the game started with (unchanged more than two minutes after the game last wrote its log) and differs
from the last copy; nothing is kept while the tools are not run, so a start followed by a change before the next read is missed.

Not confirmed, and said so: RimSort's history times are read from its files' times; Project Zomboid has no start record yet.

## Outputs

### What it checks

| Kind | Severity | When | Change offered |
| --- | --- | --- | --- |
| `missing` | problem | A list names a mod that is not on this PC | Take it off |
| `twice` | problem | A mod is on a list more than once | Keep the first |
| `needs` | problem | A mod needs one that is switched off, or not on this PC | Switch it on (when here) |
| `clash` | problem | Two mods are on that one of them says do not work together | Switch either off |
| `order` | warning | A mod loads before one it must load after, or the reverse | None here: `sort` puts it right |
| `removed` | warning | A mod on this PC that the Workshop no longer has (with `--online`) | None |
| `unsubscribed` | warning | A Workshop mod on this PC that Steam no longer keeps for you | None |
| `known` | warning | Every mod a known problem names is active, on a game version it holds for (with `--known`, from a known-problems feed) | None: its words say what to do |
| `library` | note | Several active mods carry the same library and an older copy loads first | None: load the newer above, or ask for an update |
| `version-likely` | note | Mods that do not say they work with this version but are known or likely to, and why | None |
| `replacement` | note | A missing or out-of-date mod has a continued version for this game version | Subscribe to it |
| `version` | note | A mod that does not say it works with this game version | None |
| `unchecked` | note | Mods a list names that could not be looked for (the game not installed) | None |

**Why a mod is missing**, likeliest first: taken off the Workshop or made private (Steam answers "no such item"), no longer
subscribed (not in Steam's `appworkshop_<app>.acf`), a download not finished (subscribed, files missing), a local folder gone, or
never seen here. The reason rests on the **memory**: every check records each mod on this PC (name, source, Workshop number, needs,
load-after), so a mod is still known after its files go. A mod no check ever saw has no Workshop number to ask Steam about.

### Sorting

**Where a rule comes from**, strongest first: **yours** (made here, in `rules.json`, or in RimSort), **own** (the mod's load after
and load before), **needs** (a mod loads after what it needs, as RimSort does with "use modDependencies as loadAfter"), and
**code** (a mod loads after any mod whose assembly holds the parent classes or interfaces of its own loaded code, read from the
assemblies' metadata; a call inside a method does not count), **workshop** (a mod loads after the items its Workshop page lists as
required; RimWorld: RimSort's Steam Workshop Database) and **community** (RimWorld: RimSort's Community Rules database). Strength
is used only to choose which rule of a loop to set aside (agent's order). A mod may also be asked to load **at the top** or **at
the bottom**: that is membership of the top or bottom group, as RimSort means it.

- **Fewest moves** (the default): Kahn's sort, choosing among the mods whose rules are met the one highest on the list now; done
  forwards and backwards (building from the end), keeping whichever moves fewer. A **moved** mod is one outside the longest run of
  mods whose order is kept, so a list that keeps every rule comes back unchanged.
- **Full re-sort** (`--full`): the same sort with every mod below the game's own unless a rule puts it above, each group in turn,
  and **where no rule decides, the order the list already has** (1.141.0; the owner's choice of 27 Nov 2026, "Sort first"). Before,
  such mods went in order of their names: on the owner's RimSort-sorted list that moved 135 of 387, ten UI Rethemed parts from
  about place 258 to 28, and a full re-sort had left a game unable to make a map. Now only rules and groups move a mod; the same
  list re-sorts with none moved.
- Each move lists the rules it broke where it stood, with whose they are and any note the rule carries; a mod moved only to keep a
  rule with another moved mod says so.
- **Refused**: a mod listed twice (take the extra off first). A list changed between the sort and `--apply` is refused too, since
  `--apply` sorts afresh and checks it writes the same mods.

Not confirmed, and said so: how RimSort itself reads "load at the top" (it left two such mods where this sorter lifts them), and
whether Project Zomboid has any shared community rules (none are read for it).

#### Groups

From the RimSort study (`docs/research/rimsort-sorting.md`): the game's own and its loaders first; then frameworks (the RimWorld
adapter's `known_frameworks`) and "top" mods (which no longer include the mods others' code builds on); then the rest; then
"bottom" mods. The first two groups take in every mod their members must load after, the last every mod that must load after
its members. Every rule still counts across groups. Needs make no order rule for frameworks and "top" or "bottom" mods. Each
move carries a `kind`: `rule`, `group`, `order` (full re-sort only) or `room`. A move is `group` only when the mod passes a mod of
another group, and its reason follows the links back to the member with a reason of its own.

## Effects

### Backups

`mod-list/<game>/backups/<UTC time>--<list>.list` holds the list file as it stood, byte for byte; the `.json` beside it says which
list, where, what the change was, a hash of what was written (how `undo` sees a later change), and `undone` once an undo has gone
back on it. Going back keeps the list as it then stood as a backup too ("before going back").

### The community lists, fetched by the kit (1.144.0)

So RimSort can retire (the owner's choice of 28 Nov 2026, "Own data + your rules"), the kit fetches the four lists RimSort clones
for RimWorld from the same public repositories, keyless, from raw.githubusercontent.com (outside GitHub's hourly API count), into
`<kit cache>/mod-databases/<game>/<list>/`, with `fetched.json` keeping each file's ETag so an unchanged file is not downloaded again:

| List | Repository | Files read | Licence |
| --- | --- | --- | --- |
| `community-rules` | RimSort/Community-Rules-Database | `communityRules.json` | CC0-1.0 |
| `workshop-database` | RimSort/Steam-Workshop-Database | `steamDB.json` (about 50 MB) | CC0-1.0 |
| `no-version-warning` | emipa606/NoVersionWarning | `<game version>/ModIdsToFix.xml` | MIT |
| `use-this-instead` | emipa606/UseThisInstead | `replacements.json`, fetched gzipped | MIT |

**The newer copy is read**, the kit's or RimSort's, file by file, so nothing changes while RimSort still refreshes its own. A list
older than 7 days (agent default) is called stale; `--fetch --stale` fetches only those. Measured 28 Nov 2026 on the owner's
connection: all four first fetched in about 8 s; again, all unchanged, in under 2 s. With the newer lists the owner's list still
sorted with nothing moved. A next game names its lists in its adapter's `databases` (`mod_databases.Database` rows).

### Subscribing through Steam

The tools borrow **the game's own Steam library** (`steam_api64.dll` in RimWorld's folder) and join the Steam client already
running and signed in, as the game would (`SteamAppId`), for the seconds a press takes: Steam shows the person as playing the game
meanwhile. Nothing of Steam's is shipped and no account details are held. A subscribe or unsubscribe call is waited for up to 30
s; whether it worked is read back from `GetItemState`, not assumed. **Agents never run these on the owner's account**: only the
person's own press does, so the Steamworks calls had not met a real client when 1.77.0 was made.

## Limits

- A new game is one module with `adapter()` and a row in `games/__init__.py`'s `MOD_LIST_GAMES`.
