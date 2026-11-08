# Release chores

**Answer first.** `release` checks changelogs, keeps every copy of a version or tuning figure in step, and screens a
repository's history before it goes public. None of it contacts a network or names a game. Carried over from
phobos-ostranauts (`update-constants.py`, `audit-public-history.py`) on 8 November 2026; Workshop publishing is in
[its own guide](workshop-publishing.md).

## Read this first (gotchas)

- **`constants --set` only previews.** Add `--apply` to write. Every registered copy is checked first, so drift in
  any file stops the whole change, even one you did not ask to change.
- **The history screen is a pattern screen**, not a guarantee and not a licence audit. It names paths and object IDs,
  never contents. Screen each submodule separately, and fetch remote branches first.
- **Test fixtures trip the history screen on purpose.** A made-up `C:\Users\tester` path or a hand-written save is
  flagged like a real one; review each finding.

## Changelogs

```text
python -m phobos_modkit release changelog mods/*/CHANGELOG.md
python -m phobos_modkit release changelog CHANGELOG.md --version 1.2.0
```

The form, shared by the Phobos repositories:

```markdown
# Example changelog

Free text.

## [Unreleased]

## [1.2.0] - 2026-11-08 - Draft

### Added

- A thing, which may be wrapped
  onto the next line.

## [1.1.0] - 2026-11-01 - Released

- Older.

## Old Mod history

Merged mods' own logs, kept as written.
```

Checked: one Unreleased section before every release; headings `## [version] - YYYY-MM-DD - Draft|Released` with a
real date; no duplicate or empty entry. A heading ending in "history" after the releases closes the log, for mods
merged into this one. Unless `--plain`, every entry must also fit the store-page subset: paragraphs, dash (`-`) bullets,
`###` headings, `**bold**` and `[label](https://...)` links, with no backticks, tables, images, `<`, `>`, `|`, `#`
or square brackets in the text.

## Constants

```text
python -m phobos_modkit release constants --list
python -m phobos_modkit release constants --check
python -m phobos_modkit release constants --set Framework.version=0.13.0 --expect Framework.version=0.12.0
python -m phobos_modkit release constants --set Framework.version=0.13.0 --apply
```

The catalogue is `config/maintained-constants.json` (`--catalogue` for another). Each constant has a type (version
with 3 or 4 parts, number or integer with `min` and `max`, boolean), its value, and every target: a regular
expression with a group named `value` that must match `count` times (default 1), or a JSON pointer into a `.json` file.
`"literal": "csharp-float"` adds the `f` a C# float needs once a fraction arrives. `targetsUnder` limits where targets
may live; `.git/` and `.local/` never may. `review` lines are printed after a change: the builds and records to redo.

Writes keep each file's byte-order mark, line endings and formatting, go through temporary files, are read back, and
are undone if anything fails. Changed JSON and XML files are parsed before writing.

## History screen

```text
python -m phobos_modkit release history
```

Reads every file object reachable from any branch or tag and flags: credential patterns (GitHub, OpenAI, Anthropic
and AWS keys, private key blocks), personal machine paths (`C:\Users\...`, `/home/<name>/...`, `/Users/<name>/...`),
and refused file types (`.dll`, `.exe`, `.zip`, saves, dumps, certificates and keys). Exit 1 when anything is found.
