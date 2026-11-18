# Settings: what the tools read, where each value comes from, and the central settings file

**Status (19 Nov 2026):** built in 1.30.0, at the owner's request for "a central settings page where everything or at least, most,
of these sorts of things are managed". D'thorga Companion's Settings page is its first consumer.

## Read this first (gotchas)

- **One order for every path a tool reads**: an argument, then an environment variable, then the repository's own settings file,
  then **the central settings file**, then the default. A repository's own file still wins over the central one, so nothing a
  repository already sets changes when the central file is written.
- **The central file holds settings for every repository and every game**: `settings.json` in D'thorga Companion's own folder
  (`%LOCALAPPDATA%\org.phobosdthorga.companion` on Windows). The environment variable `PHOBOS_SETTINGS` names another.
- **`settings set` writes only the central file**, one setting at a time, and only a setting a tool reads, as a full path. It
  never writes a repository's file.
- **A value is read where it is used**, so a change takes effect at the next run of each tool; nothing needs restarting except a
  program that read it at its start.

## Run it

```text
python -m phobos_modkit settings list
python -m phobos_modkit settings list --root REPO
python -m phobos_modkit settings set --key historyPath --value K:\phobos-modkit\history
python -m phobos_modkit settings set --key historyPath --clear
```

## What list gives (`data.settings`)

| Field | What it holds |
| --- | --- |
| `key`, `env` | The setting's name in a settings file, and its environment variable |
| `description`, `kind` (folder or file), `game` | What it is for; `game` is null for a setting of every game |
| `declaredBy` | `phobos-modkit`, or the repository that declares it for its own scripts |
| `value`, `layer` | The value in force, and where it comes from: `environment`, `repository`, `central` or `default` |
| `repository` | Which repository's own file sets it, when the layer is `repository` |
| `central`, `default` | The central file's value and the default, whether or not either is in force |
| `exists` | Whether the value names something on this PC |
| `overridden` | Every repository named whose own file sets it, with its value |

## A repository's own settings

A repository declares the settings its own scripts read in `config/settings.json`, so they are listed and can be set centrally:

```json
{"schemaVersion": 1, "settings": [
  {"key": "artWorkPath", "env": "PHOBOS_ART_WORK", "kind": "folder",
   "description": "Where the art tools keep their masks, parts and staging"}]}
```

Its own values live in the file its `config/installs.json` names (`settings`), else `.local/install-settings.json`. Its scripts
read a value through `phobos_modkit.paths.resolve`, which applies the order above.

## Limits

- Only paths for now: a folder or a file. Other kinds of setting (numbers, choices) wait for a tool that needs one.
- A setting a repository's script reads without `paths.resolve` does not see the central file.
