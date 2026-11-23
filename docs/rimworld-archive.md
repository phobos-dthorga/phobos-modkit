# RimWorld archive: every version of the assemblies a project depends on

Built in 1.15.0 (18 November 2026), at the owner's request in phobos-rimworld. Steam replaces the game's and a mod's files in place,
so once an update lands the older build is gone and nothing is left to compare it with. That day the game moved from 1.7.5011 to
1.7.5013 and its assembly could not be compared; Vehicle Framework's could only because an older decompile happened to be on disk.

## Read this first

- **Run a snapshot often**, so each update finds the version before it already kept. phobos-rimworld runs one with every mod-list
  refresh. A version that comes and goes between two snapshots is never seen.
- **What it keeps:** the game's `Assembly-CSharp.dll`, and every DLL of each **active** mod the project's own mods name: in About.xml
  (`modDependencies`, `loadAfter`, `forceLoadAfter`) or in LoadFolders.xml (`IfModActive`, `IfModActiveAll`). The project's own mods
  are left out, since git keeps their history. Add others with `--mod` and `--game-file`. A tie-in named only by `MayRequire` is not
  found; add it with `--mod`.
- **Where:** its own folder, **not the kit's cache**, which defaults to a temp folder the system may clear: `--archive`, else
  `PHOBOS_ASSEMBLY_ARCHIVE`, else `assemblyArchivePath` in the settings file, else `%LOCALAPPDATA%\phobos-modkit\assembly-archive`
  (`~/.local/share/phobos-modkit/assembly-archive` elsewhere). Each distinct file is kept once, gzip-compressed.
- **Reads the game and Workshop folders as files and never writes to them.** It keeps files; it does not read them as .NET.
  `compare` decompiles with ilspycmd, which reads a file without loading or running it.
- **Never commit what it keeps.** These are the game's and other authors' files, for comparing on this machine only.

## Use

```text
cd python
python -m phobos_modkit rimworld-archive snapshot --root ..          keep what changed since the last snapshot
python -m phobos_modkit rimworld-archive list                         every file kept, most versions first
python -m phobos_modkit rimworld-archive list --file Vehicles.dll     every version of one file, oldest first
python -m phobos_modkit rimworld-archive compare Vehicles.dll         the last two versions, member by member
python -m phobos_modkit rimworld-archive compare Vehicles.dll --back 3 --to 1   two older versions against each other
python -m phobos_modkit rimworld-archive compare Vehicles.dll --show CompUpgradeTree.PrerequisitesMet   one member's diff
python -m phobos_modkit rimworld-archive get Assembly-CSharp.dll --back 1   unpack an older one; prints its path
```

`compare` hands both sides to `code compare` (see [the code index](code.md)), so its report, `--only` and `--show` are the same.
`--back` counts versions before the newest for the older side (default 1); `--to` does the same for the newer side (default 0, the
newest). A file several mods ship needs `--owner <packageId>`. Exit 0 on success, 1 when something failed, 2 for a bad command line.

## An older game build the archive never saw: DepotDownloader

For a game version that came and went before the archive kept it, Steam can still serve the old build. Valve took that option out
of the Steam client in January 2020; **DepotDownloader** ([SteamRE/DepotDownloader](https://github.com/SteamRE/DepotDownloader),
open source, GPL-2.0) is the usual way now. **Only the owner runs it**: it logs in to Steam with the owner's account, which this kit
and its agents never do.

1. **Install it:** `winget install --exact --id SteamRE.DepotDownloader`.
2. **Find the build:** on [SteamDB](https://steamdb.info/app/294100/depots/), RimWorld is app 294100. Open the depot for your
   system (its Windows content depot; check the ID there) and its manifest history, and copy the manifest ID dated just before the
   build you have now. Whether SteamDB shows the history without signing in is not confirmed.
3. **Fetch only the assembly**, not the whole game. Make a text file `files.txt` holding the one line `Assembly-CSharp.dll`, then:

   ```text
   DepotDownloader -app 294100 -depot <depot ID> -manifest <manifest ID> -username <your Steam name> -remember-password -filelist files.txt -dir <an empty folder>
   ```

   It asks for your password and any Steam Guard code in its own window. Old builds can download slowly. **Never point `-dir` at the
   game's own folder.**
4. **Compare it:** `python -m phobos_modkit code compare <that folder>\Assembly-CSharp.dll <the newer one>`, where the newer one is the
   game's own file or `rimworld-archive get Assembly-CSharp.dll --back 0`.

Workshop items are a different matter: Steam keeps the current file of an item, and whether DepotDownloader can still fetch an
older one is not confirmed. For a mod with public source, its own repository's history is the better record.

## Limits

- Only what passes through a snapshot is kept; nothing prunes the archive yet. It reports its size each time.
- A file's version text is the owner's own (`Version.txt` for the game, `modVersion` for a mod) and may be blank; the first-seen
  time and the hash always tell versions apart.
- Going back to an older build counts as a new version (stored once), so `--back 1` is always the version before the newest.

## Reports and options

<!-- generated: options rimworld-archive -->
Generated from the command's own parser by `python -m phobos_modkit command-docs --write`: change a help text in the parser, not here.

| Report | What it does | Effect |
| --- | --- | --- |
| `snapshot` | Keep each watched file whose content changed since the last snapshot. Writes only to the archive folder, never to the game or Workshop. | writes |
| `list` | What the archive holds. | reads only |
| `compare` | What changed between two kept versions, member by member. Unpacks both sides inside the archive folder and runs ilspycmd, which reads a file without loading or running it. | runs other programs |
| `get` | Unpack a kept version and print where it is. Unpacks a kept file inside the archive folder. | writes |

| Option | Reports | What it does | Default |
| --- | --- | --- | --- |
| `--archive VALUE` | all | the archive folder (else PHOBOS_ASSEMBLY_ARCHIVE, assemblyArchivePath in settings, %LOCALAPPDATA%\phobos-modkit\assembly-archive) |  |
| `--settings VALUE` | all | a JSON settings file with rimworldPath, workshopPath, rimworldConfigPath, assemblyArchivePath |  |
| `--top N` | all | rows per table (default 60) | `60` |
| `--root VALUE` | `snapshot` | the project whose mods' tie-ins decide what to watch (default: here) | `.` |
| `--mod PACKAGE_ID` | `snapshot` | watch this active mod too; may repeat |  |
| `--game-file NAME` | `snapshot` | a game assembly to watch beside Assembly-CSharp.dll; may repeat |  |
| `--game VALUE` | `snapshot` | the RimWorld folder (else RIMWORLD_PATH, the settings file, Steam's default) |  |
| `--workshop VALUE` | `snapshot` | the Workshop content folder (else RIMWORLD_WORKSHOP_PATH, settings, beside the game) |  |
| `--config VALUE` | `snapshot` | the folder holding ModsConfig.xml (else RIMWORLD_CONFIG_PATH, settings, default) |  |
| `--if-installed` | `snapshot` | with no game on this machine, say so and pass (for CI) |  |
| `--file VALUE` | `list` | every version of one file (its name, any case) |  |
| `FILE` | `compare`, `get` | the file's name, as the mod or game ships it |  |
| `--owner VALUE` | `compare`, `get` | the package ID that ships it, when several do |  |
| `--back N` | `compare`, `get` | how many versions before the newest (default 1) | `1` |
| `--to BACK` | `compare` | the newer side, versions before the newest (default 0) | `0` |
| `--only PATTERN` | `compare` | only declarations whose full name matches; repeatable |  |
| `--show NAME` | `compare` | the changes in one declaration, as a diff |  |
| `--decompiler VALUE` | `compare` | ilspycmd (else PHOBOS_MODKIT_ILSPYCMD, settings, the PATH) |  |

- Every report also takes `--json` (print JSON instead of Markdown) and `--no-redact` (show the home folder instead of ~).
- Names in capitals are given bare, without a flag, in the order shown.
- A path left out is looked for in the order [settings](settings.md) explains: an environment variable, the repository's own settings file, the central settings file, then the default.
- [Common options](common-options.md) explains `--root`, `--game`, `--workshop`, `--config`, `--settings`, `--top`, `--json` and `--no-redact`, which many commands share.
<!-- end generated -->
