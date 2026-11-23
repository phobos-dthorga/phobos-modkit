# doc-tables

Tables in a repository's own docs, filled from its own files, so they cannot drift from them: its .NET projects, the methods its
C# patches with Harmony, and what each of its mods needs. Built in 1.107.0 (docs rewrite, step 3, the owner's go-ahead of
23 Nov 2026), beside [command-docs](command-docs.md), which does the same for the kit's own commands.

## Read this first (gotchas)

- **Change the files, never the table.** The next `--write` puts a table back as the files say. Everything outside the marks is
  the doc's own and is never touched.
- **A repository's gate fails when a table is out of date**, once it runs `doc-tables` as a step (phobos-rimworld: `python
  scripts/doc-tables.py`). After changing a project file, a patch or a mod's About.xml, run it with `--write` and commit the docs
  with the change.
- **It reads text, never a build.** Project files are read as XML without running MSBuild, so a value set only in
  `Directory.Build.props` or by a condition is not shown. Harmony patches are read from the C# source, so a patch whose target the
  game no longer has still shows; whether targets exist is `rimworld-targets`' and `rimworld-upstream`'s question.
- **"Not read" is said, never guessed.** A HarmonyPatch attribute in a form the reader does not know (a constant for the method's
  name, a call) is listed with its file and line, in the table and in the command's report.
- **Mod requirements need a game adapter.** RimWorld has one; a game without one gets a sentence in its table saying so, not an
  error.

## Run it

```text
python -m phobos_modkit doc-tables --root REPO            check: which tables are missing or out of date (fails when any is)
python -m phobos_modkit doc-tables --root REPO --write    write them
```

Without `--root` it reads the current folder. A consumer calls it through a thin script that passes its own root.

## The config: `config/doc-tables.json`

```json
{
  "schemaVersion": 1,
  "run": "python scripts/doc-tables.py --write",
  "tables": [
    {"doc": "docs/development/building.md", "kind": "dotnet-projects",
     "options": {"folders": ["src"], "testFolders": ["tests"], "output": "mods/{ModFolder}/{TieInFolder}"}},
    {"doc": "docs/development/building.md", "kind": "harmony-patches", "options": {"folders": ["src"]}},
    {"doc": "docs/player-guide/getting-started.md", "kind": "mod-requirements",
     "options": {"game": "rimworld", "folders": ["mods"], "names": {"brrainz.harmony": "Harmony"}}}
  ]
}
```

| Field | What it holds |
| --- | --- |
| `run` | The command the tables' first line tells a reader to run (default `python -m phobos_modkit doc-tables --write`) |
| `tables` | Each table: `doc` (relative to the repository), `kind`, `options`, and `name` when one doc holds two tables of a kind |

A table sits between `<!-- generated: table NAME -->` and `<!-- end generated -->`, NAME being its `name` or else its kind. A doc
without the marks gains the table in a section of its own at its end (`## Projects`, `## Harmony patches`, `## What each mod
needs`); move it anywhere afterwards and `--write` keeps it there. The marks, reading and writing are the same code as
command-docs' (`generated_blocks.py`), and a doc keeps its own line endings.

## The kinds

### `dotnet-projects` (any game)

Every `*.csproj` under `folders`, by name, with what it builds into, the projects and other assemblies it references, whether its
own C# uses Harmony (`using HarmonyLib` or a `[HarmonyPatch]`), and which test projects reference it or compile its files.

| Option | What it does |
| --- | --- |
| `folders` | Where the projects are (default: the whole repository) |
| `testFolders` | Where the test projects are; they are left out of the rows and named in the last column |
| `output` | A template of where a project builds to, from its own properties: `mods/{ModFolder}/{TieInFolder}`. A property the file does not set is empty; when the first one is missing, the cell says "not set". Left out, the column is too |
| `outputLabel` | The column's heading (default "Builds into") |

### `harmony-patches` (any game)

Per project under `folders`, a summary row (patched methods, patch classes that find their target by name, manual `.Patch(`
calls, attributes not read), then a folded list of each project's patched methods with their kinds and files. It reads:

- `[HarmonyPatch(typeof(T), "M")]` and `nameof(T.M)`, with `MethodType.Getter`, `Setter`, `Constructor` and the rest; argument
  types after the name choose an overload and are left out;
- attributes on the class and on its methods combined, as Harmony combines them (`[HarmonyPatch(typeof(T))]` on the class,
  `[HarmonyPatch("M")]` on the method);
- the kind from a method named `Prefix`, `Postfix`, `Transpiler` or `Finalizer`, or marked `[HarmonyPrefix]` and the like;
- a class with `TargetMethod()` or `TargetMethods()` as "by name in TargetMethod": its target is found at run time;
- manual `harmony.Patch(...)` calls, counted, never followed (`CreateClassProcessor(...).Patch()` is not one).

Comments are skipped (the kit's C# scanner, [code](code.md)). Harmony's attributes are its public API, documented by Andreas
Pardeike at [harmony.pardeike.net](https://harmony.pardeike.net/articles/annotations.html).

### `mod-requirements` (through the game's adapter)

Per mod folder under `folders`: its name, package ID, what it needs, what it loads after and before, the game versions it supports,
and the optional mods that switch on extra content of it.

| Option | What it does |
| --- | --- |
| `game` | The game whose adapter reads the mods (`rimworld`) |
| `folders` | Where the mods are (default `mods`) |
| `names` | Other authors' mods' names by package ID, for mods none of the repository's own files name; an ID not given shows as written |

**RimWorld** (`games/rimworld/mod_list.py`, `mod_requirements`): About.xml as the game reads it for the newest version the mod
supports (a `loadAfterByVersion` list for that version replaces the plain one), with `forceLoadAfter` and `forceLoadBefore`
added; the optional tie-ins are LoadFolders.xml's folders for that version with `IfModActive` (any of them), `IfModActiveAll` (all
of them) or `IfModNotActive` (none of them), grouped by what they wait for. Needs are named by their `displayName`; other mods by
the repository's own About files, then the config's `names`.

**What a next game needs**: a `mod_requirements(folder)` in its adapter (`games/<game>/mod_list.py`, the module the mod-list check
already uses), returning `(Mod, [TieIn])` from the core `mod_list` module, or None for a folder that holds no mod. Project
Zomboid's adapter reads `mod.info` already and would need only that function; until then its table says it cannot be made.

## Limits

- **The tables say what the files say.** A project's property set elsewhere, a patch whose target has gone, a mod whose About
  file is wrong: each shows as written.
- **One version of a mod's lists**: the newest it supports. A mod whose lists differ by version shows the newest version's.
- **Line numbers appear only for attributes not read**, so ordinary edits above a patch do not make a table stale; moving a patch
  to another file, or adding or removing one, does.

## Reports and options

<!-- generated: options doc-tables -->
Generated from the command's own parser by `python -m phobos_modkit command-docs --write`: change a help text in the parser, not here.

Effect: writes, with `--write`. Fails when a table is missing or out of date; with `--write`, writes only the generated tables in the docs config/doc-tables.json names.

| Option | What it does | Default |
| --- | --- | --- |
| `--root VALUE` | the repository (default: the current folder) |  |
| `--write` | write the tables that are missing or out of date; without it, only check |  |

It also takes `--json` (print JSON instead of Markdown) and `--no-redact` (show the home folder instead of ~).
<!-- end generated -->
