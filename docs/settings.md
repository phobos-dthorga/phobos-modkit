# Settings: what the tools read, where each value comes from, and the central settings file

One place where the paths the tools read are listed and set, at the owner's request for "a central settings page where everything
or at least, most, of these sorts of things are managed". D'thorga Companion's Settings page is its first consumer.

## Read this first

- **One order for every path a tool reads**: an argument, then an environment variable, then the repository's own settings file,
  then **the central settings file**, then the default. A repository's own file still wins over the central one, so nothing a
  repository already sets changes when the central file is written.
- **The central file holds settings for every repository and every game**: `settings.json` in D'thorga Companion's own folder
  (`%LOCALAPPDATA%\org.phobosdthorga.companion` on Windows). The environment variable `PHOBOS_SETTINGS` names another.
- **`settings set` writes only the central file**, one setting at a time, and only a setting a tool reads, as a full path. It
  never writes a repository's file.
- **A value is read where it is used**, so a change takes effect at the next run of each tool; nothing needs restarting except a
  program that read it at its start.

## Examples

```text
python -m phobos_modkit settings list
python -m phobos_modkit settings list --root REPO
python -m phobos_modkit settings set --key historyPath --value K:\phobos-modkit\history
python -m phobos_modkit settings set --key historyPath --clear
```

## Reports and options

<!-- generated: options settings -->
Generated from the command's own parser by `python -m phobos_modkit command-docs --write`: change a help text in the parser, not here.

| Report | What it does | Effect |
| --- | --- | --- |
| `list` | Every setting, its value and where it comes from. | reads only |
| `set` | Set or clear a setting in the central file. Writes one setting into the central settings file. | writes |

| Option | Reports | What it does | Default |
| --- | --- | --- | --- |
| `--root VALUE` | all | a repository whose own settings to read (repeatable) |  |
| `--key VALUE` | `set` | the setting's name, as list gives it. Required. |  |
| `--value VALUE` | `set` | its new value: a full path |  |
| `--clear` | `set` | take it out of the central file |  |

- Every report also takes `--json` (print JSON instead of Markdown) and `--no-redact` (show the home folder instead of ~).
- [Common options](common-options.md) explains `--root`, `--json` and `--no-redact`, which many commands share.
- Only one of `--value`, `--clear` at a time (`set`).
<!-- end generated -->

## Inputs

### A repository's own settings

A repository declares the settings its own scripts read in `config/settings.json`, so they are listed and can be set centrally:

```json
{"schemaVersion": 1, "settings": [
  {"key": "artWorkPath", "env": "PHOBOS_ART_WORK", "kind": "folder", "name": "Art work files",
   "description": "Where the art tools keep their masks, parts and staging"}]}
```

`name` is optional: a few words a list shows on one line, with the description as the full sentence beside it.

Its own values live in the file its `config/installs.json` names (`settings`), else `.local/install-settings.json`. Its scripts
read a value through `phobos_modkit.paths.resolve`, which applies the order above.

## Outputs

### What list gives (`data.settings`)

| Field | What it holds |
| --- | --- |
| `key`, `env` | The setting's name in a settings file, and its environment variable |
| `name` | A few words to list it by on one line (1.95.0), or null when it has none: then show the description |
| `description`, `kind` (folder or file), `game` | What it is for; `game` is null for a setting of every game |
| `declaredBy` | `phobos-modkit`, or the repository that declares it for its own scripts |
| `value`, `layer` | The value in force, and where it comes from: `environment`, `repository`, `central` or `default` |
| `repository` | Which repository's own file sets it, when the layer is `repository` |
| `central`, `default` | The central file's value and the default, whether or not either is in force |
| `exists` | Whether the value names something on this PC |
| `overridden` | Every repository named whose own file sets it, with its value |

## Limits

- Only paths for now: a folder or a file. Other kinds of setting (numbers, choices) wait for a tool that needs one.
- A setting a repository's script reads without `paths.resolve` does not see the central file.
