# Make-up: what a repository is made of

**Status (19 Nov 2026):** built in 1.39.0, at the owner's request to show "how the contents of our mods, code, etc. is consisted
of in a graphical manner". D'thorga Companion's Make-up page and its Code map's busiest code are its first consumers.

## Read this first (gotchas)

- **Only committed files count** (git's own list), so nothing ignored, private (`.local`) or half-written is measured.
- **Lines are counted in text files only.** A picture or a sound has none, so count by size or by files to see the art.
- **Lines are not effort.** A changelog line and a line of C# count the same; a generated file counts as written.
- **A product is a changelog's folder**, as `changes` names it; a C# project belongs to the product its `.csproj` ships into
  (`<ModFolder>`). Everything else is outside any product, grouped by its top folder (`docs`, `scripts`, `tests`...).
- It reads only. The day-by-day history keeps each file version's line count in the kit's cache (`makeup/`), so a second run
  reads only versions it has not seen: about 2 s for phobos-rimworld's whole history.

## Run it

```text
python -m phobos_modkit makeup now --root REPO
python -m phobos_modkit makeup growth --root REPO
python -m phobos_modkit makeup churn --root REPO --days 30
python -m phobos_modkit makeup census --root REPO
```

Add `--json` for the envelope.

## Kinds

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

## The answers (`data`)

- `now`: `files`, each `{path, product, group, kind, language, bytes, lines}` (`group` is the top folder of a file outside any
  product, `""` for the repository's own top-level files), `products`, `kinds` and `commit`.
- `growth`: `points`, one a day with commits, oldest first, each `{day, commit, kinds, products}`; each total is `[lines, bytes]`.
  Products are worked out as each day's files had them.
- `churn`: `files` changed in the last `--days` (0: every commit), each `{path, kind, commits, added, removed, last}`.
- `census`: `products`, each `{defs: {type: count}, pictures, sounds, keys}`. Defs come from `connections` (abstract ones left
  out); keys are the entries of language files under a `Keyed` folder.

## Limits

- Merges are left out of `churn`; renames count as a removal and an addition.
- Growth follows the first-parent line, the last commit of each day.
