# Make-up: what a repository is made of

Asked for by the owner, to show "how the contents of our mods, code, etc. is consisted of in a graphical manner". D'thorga
Companion's Make-up page and its Code map's busiest code are its first consumers.

## Read this first

- **Only committed files count** (git's own list), so nothing ignored, private (`.local`) or half-written is measured.
- **Lines are counted in text files only.** A picture or a sound has none, so count by size or by files to see the art.
- **Lines are not effort.** A changelog line and a line of C# count the same; a generated file counts as written.
- **A product is a changelog's folder**, as `changes` names it; a C# project belongs to the product its `.csproj` ships into
  (`<ModFolder>`). Everything else is outside any product, grouped by its top folder (`docs`, `scripts`, `tests`...).

## Examples

```text
python -m phobos_modkit makeup now --root REPO
python -m phobos_modkit makeup growth --root REPO
python -m phobos_modkit makeup churn --root REPO --days 30
python -m phobos_modkit makeup census --root REPO
```

Add `--json` for the envelope ([common options](common-options.md)).

## Reports and options

<!-- generated: options makeup -->
Generated from the command's own parser by `python -m phobos_modkit command-docs --write`: change a help text in the parser, not here.

| Report | What it does | Effect |
| --- | --- | --- |
| `now` | Every committed file by product, kind, language, lines and size. Every committed file by product and kind; needs the repository. | reads only |
| `growth` | Totals by kind and product, one point a day since the first commit. Totals one point a day; needs the repository. | reads only |
| `churn` | The files commits changed lately. The files commits changed lately; needs the repository. | reads only |
| `census` | Each product's Defs by type, pictures, sounds and text keys. What each product holds for players; needs the repository. | reads only |

| Option | Reports | What it does | Default |
| --- | --- | --- | --- |
| `--root VALUE` | all | the repository (default: here) | `.` |
| `--top N` | all | rows per table (default 25) | `25` |
| `--days N` | `churn` | how far back (default 30; 0 for every commit) | `30` |

- Every report also takes `--json` (print JSON instead of Markdown) and `--no-redact` (show the home folder instead of ~).
- [Common options](common-options.md) explains `--root`, `--top`, `--json` and `--no-redact`, which many commands share.
<!-- end generated -->

## Inputs

### Kinds

| Kind | What |
| --- | --- |
| code | C#, Lua, Python, TypeScript, JavaScript, Svelte, Rust, C/C++, shaders, scripts |
| tests | code or data under a folder named `tests`, `test`, `__tests__` or `spec` |
| data | XML, JSON, TOML, YAML, CSV and the like (Defs, configuration) |
| words | Markdown and plain text, and data files under a `Languages`, `Translate`, `Localization` or `locales` folder |
| pictures | PNG, JPEG, DDS, PSD, SVG, GIF, WebP, TGA and the like |
| sounds | OGG, WAV, MP3, FLAC, Opus |
| build | project, solution and lock files, `.gitignore` and the like |
| other | everything else |

## Outputs

### Size as installed (`now`, 1.127.0)

The owner's answer on D'thorga Companion's Decisions page, "Add it". For a repository with `config/installs.json`, `now` measures
each mod folder under its `mods` where its game's adapter installs it (encoded textures and all) beside its folder in the
repository: `data.installed` is `{problem, folder, mods: [{mod, found, bytes, files, repositoryBytes}]}`, largest first, and the
report adds a **Size as installed** table. It is null for a repository with no installs.json, and `problem` says why when the
installed mods can't be found (no game folder in the settings, no adapter for the game). It only reads. Checked on
phobos-rimworld (Phobos Vehicles: 786 MB installed, 60 MB in the repository); phobos-ostranauts keeps no installs.json yet, so it
says nothing there.

The answers (`data`):

- `now`: `files`, each `{path, product, group, kind, language, bytes, lines}` (`group` is the top folder of a file outside any
  product, `""` for the repository's own top-level files), `products`, `kinds` and `commit`.
- `growth`: `points`, one a day with commits, oldest first, each `{day, commit, kinds, products}`; each total is `[lines, bytes]`.
  Products are worked out as each day's files had them.
- `churn`: `files` changed in the last `--days` (0: every commit), each `{path, kind, commits, added, removed, last}`.
- `census`: `products`, each `{defs: {type: count}, pictures, sounds, keys}`. Defs come from `connections` (abstract ones left
  out); keys are the entries of language files under a `Keyed` folder.

## Effects

- It reads only. The day-by-day history keeps each file version's line count in the kit's cache (`makeup/`), so a second run
  reads only versions it has not seen: about 2 s for phobos-rimworld's whole history.

## Limits

- Merges are left out of `churn`; renames count as a removal and an addition.
- Growth follows the first-parent line, the last commit of each day.
