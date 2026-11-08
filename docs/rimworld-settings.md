# RimWorld mod settings

Built in 0.12.0 (9 November 2026), at the owner's request for a tool that captures the settings they play with, to
help work out what causes an error. It reads the game's Config folder and says which mod each settings file belongs
to, whether that mod is active, and what the file holds. It reads only.

## Read this first

- **A file lists only what the player changed.** RimWorld writes a value only when it differs from the default the
  mod's code names, and a key missing on load takes that default (Verse.Scribe_Values.Look, read in the 1.7 game code).
  "Every value is at its default" is a real answer, not a failure to read. A list (Scribe_Collections) is written even
  when empty, so it shows as "(empty)".
- **Defaults come from the mod's own source, not from here.** Pass a defaults file (`--defaults`) to see each value
  beside its default, the keys left at default, keys the mod no longer reads, and defaults that disagree between the
  field's starting value and the one a missing key loads as. phobos-rimworld writes its own from its C# source.
- **Files outlive their mods.** The game never deletes a settings file: a mod removed, merged or renamed leaves one.
  They do no harm; the summary lists them so they are not mistaken for live settings.
- **Other settings systems are only counted**: HugsLib's folder and Mod Settings Framework's files are not this format.

## Use

```text
cd python
python -m phobos_modkit rimworld-settings                          counts, the mods with most values, files left behind
python -m phobos_modkit rimworld-settings --mod "dubwise.*"        the values of matching mods (name, package ID or folder)
python -m phobos_modkit rimworld-settings --mod X --defaults F     each value beside its default
python -m phobos_modkit rimworld-settings --list                   every mod with settings and every file left, uncut
python -m phobos_modkit rimworld-settings snapshot before.json     every value now, as JSON
python -m phobos_modkit rimworld-settings compare before.json      what changed since then (or between two snapshots)
```

Paths resolve as the other RimWorld tools do: `--config`, then `RIMWORLD_CONFIG_PATH`, then `rimworldConfigPath` in a
`--settings` file, then the platform default; the game and Workshop folders (to name the mods) likewise. Without the
game folder the files are still read, but none can be matched to a mod.

## How a file is matched to a mod

The game names a file `Mod_<folder>_<class>.xml` (Verse.LoadedModManager): `<folder>` is the folder the mod loaded from
(a Workshop item's number, or a local folder's name) and `<class>` its Mod class. Class names may hold underscores, so
the tool splits at the longest installed folder name the file starts with, and only falls back to the last underscore
for a folder no installed mod has. One mod may own several files, one per Mod class (Vanilla Expanded Framework has
three). Active means listed in ModsConfig.xml and resolved as the game resolves it (`loading.resolve_active`).

## The defaults file

```json
{"schemaVersion": 1, "classes": {
  "Phobos.Example.ExampleSettings": {
    "PhobosEx_Mode": {"default": "Operator", "initial": "Operator", "field": "displayMode"}
  }
}}
```

Keyed by the settings class the file names (`<ModSettings Class="...">`); each saved key has `default` (what a missing
key loads as: the third argument of `Scribe_Values.Look`, or the type's default) and optionally `initial` (the field's
starting value, which a player with no settings file gets). Booleans compare without case, numbers as numbers.

## Limits

- Values are shown as written. An enum is its name; a list of plain items is one value, "[3] a; b; c", cut after eight.
- The saved date is the file's modification time, in UTC.
- A settings file whose name the game sanitised (a folder name with characters Windows refuses) may not match its mod.
