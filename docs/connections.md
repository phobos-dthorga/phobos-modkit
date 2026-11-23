# Connections: how a repository's code fits together

Asked for by the owner: "flow-charts and the such which show relationships between functions, classes, etc. of the code I'm
viewing". D'thorga Companion's code viewer and Code map page are its first consumers.

## Read this first

- **Every connection says whether it is exact.** C# read from a built assembly is exact: what the compiled code calls, including
  the game's and other mods' methods. Everything read by name says so: Lua (which only knows what a name means while it runs), C#
  with nothing built, and calls in Python.
- **C# is read from the assemblies the repository builds**, found by its projects: each `.csproj`'s `AssemblyName` and the newest
  `.dll` of that name in the repository, outside `obj` folders. **Build first** for exact connections; an old build gives old
  connections, and the summary says how each language was read.
- **.NET's own library is left out** (strings, lists, maths): calls into it are most of any program's calls and say nothing about
  how its parts fit together. The game's engine and other mods stay.
- **Private and build folders are never read**: `.local` (decompiled code of other authors stays there), `external`, `obj`,
  `node_modules`, `target`, `dist`, and every folder whose name starts with a dot.
- **The graph is kept in the kit's cache**, one file a repository, and read again when any file it came from changes: about 7 s
  for phobos-rimworld or phobos-ostranauts the first time, under a second after.

## Examples

```text
python -m phobos_modkit connections summary --root REPO
python -m phobos_modkit connections find --root REPO --name "*Tick*"
python -m phobos_modkit connections around --root REPO --node cs:Phobos.Framework.TopUp.Seen.Note
python -m phobos_modkit connections flow --root REPO --node cs:Phobos.Framework.TopUp.Seen.Note --depth 2
python -m phobos_modkit connections changed --root REPO --commit 3352e4da
python -m phobos_modkit connections history --root REPO --node cs:Phobos.Framework.TopUp.Seen.Note [--limit 100]
python -m phobos_modkit connections names --root REPO --file src/Mod/Sail.cs [--commit 3352e4da]
python -m phobos_modkit connections calls --root REPO --commit 5c122faf [--game rimworld]
```

Add `--json` for the envelope ([common options](common-options.md)); `--rebuild` reads every file again.

## Reports and options

<!-- generated: options connections -->
Generated from the command's own parser by `python -m phobos_modkit command-docs --write`: change a help text in the parser, not here.

| Report | What it does | Effect |
| --- | --- | --- |
| `summary` | What was read, how exactly, and how much. | reads only |
| `find` | Things by name. Things by name; needs the name. | reads only |
| `around` | Everything one connection away from one thing. Everything one connection away from one thing; needs its id. | reads only |
| `flow` | Who calls one thing and what it calls, a few steps each way. The calls around one thing, a few steps each way; needs its id. | reads only |
| `changed` | The things a commit changed. The things a commit changed; needs the commit. | reads only |
| `history` | The commits that changed one thing's lines, with the changelog entries they wrote. The commits that changed one thing, with the entries they wrote; needs its id. | reads only |
| `names` | What every name in one file is, and where it is declared. What every name in one file is and where it is declared; needs the file. | reads only |
| `calls` | What a commit did to its C# methods' calls, and the rings of calls it made or cut. What a commit did to its C# methods' calls, and rings made or cut; needs the commit. | reads only |

| Option | Reports | What it does | Default |
| --- | --- | --- | --- |
| `--root VALUE` | all | the repository (default: the current folder) |  |
| `--rebuild` | all | read every file again, whatever the cache holds |  |
| `--top N` | all | rows per table (default 60) | `60` |
| `--name VALUE` | `find` | a name or pattern (\* and ?). Required. |  |
| `--kind VALUE` | `find` | only this kind (repeatable): method, class, def... |  |
| `--outside` | `find` | also the game's and other mods' things the code uses |  |
| `--node VALUE` | `around`, `flow`, `history` | a thing's id, as find gives it (cs:..., def:..., lua:..., py:...). Required. |  |
| `--depth N` | `flow` | steps each way (default 2). One of `1`, `2`, `3`. | `2` |
| `--commit VALUE` | `changed`, `calls` | the commit. Required. |  |
| `--limit N` | `history` | commits to give, newest first (default 25, at most 500) | `25` |
| `--file VALUE` | `names` | the file (C#, Lua, Python or XML), relative to the repository. Required. |  |
| `--commit VALUE` | `names` | read the file as it stood at this commit (other files as they stand now) |  |
| `--game VALUE` | `calls` | the game the repository's mods are for (rimworld), to follow a ring through its own code |  |

- Every report also takes `--json` (print JSON instead of Markdown) and `--no-redact` (show the home folder instead of ~).
- [Common options](common-options.md) explains `--root`, `--game`, `--top`, `--json` and `--no-redact`, which many commands share.
<!-- end generated -->

## Inputs

### What is read, and how

| Language | Things | Connections | How exact |
| --- | --- | --- | --- |
| C#, built | types, methods, properties, events, fields (placed in the source by the kit's C# scanner) | calls; uses (fields); holds; builds on (base type, interfaces); overrides; patches (Harmony, from the same reader as `rimworld-patches`) | Exact, from the assembly's metadata and method bodies. Code the compiler made for a lambda, a local function, an iterator or an async method counts as the method that wrote it. Overloads share one thing, as the source names them. An override of an outside type's method is by name |
| C#, source only | types and members | holds; calls where a body names a method only one or two types declare | By name |
| XML Defs | each Def (`def:ThingDef/Name`), abstract ones by their `Name` | builds on (`ParentName`); uses a Def (a value that is its defName); uses a C# class (a `Class` attribute, or an element whose name ends in `Class`) | Parents exact; a defName unique in the repository counts as exact |
| Lua | each file, and its functions (`function A.b(`, `function A:b(`, `local function b(`, `b = function(`) | holds; calls (a name followed by `(`, comments and strings blanked); imports (`require`) | By name |
| Python | modules, classes, functions, methods (Python's own parser) | holds; builds on (bases in the repository); imports; calls | Shape exact; calls by name |

A thing's id starts with its language: `cs:Namespace.Type.Member`, `def:DefType/Name`, `lua:Name` (or `lua:file:path:Name` for a
local function, `lua:file:path` for a file), `py:module.name`. Things outside the repository (the game, other mods) are in the graph
as `external`, with the assembly that holds them where the reader knows it.

### Names in one C# file (`names`)

**For following a name to where it is declared** (D'thorga Companion, `docs/code-reading.md` step 4; the owner's choice by card
of 24 Nov 2026: "Roslyn for C#"). It reads differently from the rest of this tool:

- **From source, with Microsoft's Roslyn**, through the kit's names reader (`dotnet/PhobosModKit.Names`), built on first use
  with the .NET SDK; nothing needs building first. It never loads or runs an assembly, an analyser or a source generator.
- **MSBuild lists the project's files and references** (`dotnet msbuild -getItem`, `BuildProjectReferences=false`), and those
  of every project it refers to, so a name declared in another of the repository's projects is placed in its file. A project
  never restored is restored first, which fetches its packages and builds nothing.
- **At a commit, only that file is read as it stood**; every other file as it stands now, and `limits` says so.
- **About 3 to 7 s a file** on phobos-rimworld's vehicles part (two projects, 355 files): MSBuild's listing about half of it.
  Nothing is cached yet.
- **Lua, Python and XML by name** (1.115.0; Companion's `docs/code-reading.md` step 5): a word in the file (in code, never a
  comment or a string; in XML only element text and attribute values) that names one of this repository's things in the graph,
  a dotted name whole when the graph has it (`Lamps.shine`, or a C# class a Def names) and otherwise each part. Each such name
  lists the things it may stand for; the file is read as it stood at `--commit`, the things as they stand now. Checked on
  phobos-rimworld (a Def file, a Python script) and Project Zomboid's PhobosLib (Lua).

### What a commit did to its calls (`calls`, 1.116.0)

**For a change's calls gone and added, and the rings of calls it made or cut** (Companion's `docs/code-reading.md` step 6; the
owner's go of 24 Nov 2026). C# only, through the names reader:

- **Read twice, from source**: every method in the C# files the commit changed (at most 12 files), as they stood before the commit
  and after it, each a build of its own with those files swapped in; every other file as it stands now, and `limits` says so.
  A method of ours the changed methods call through `base`, or override, is read one level deep for its calls.
- **Calls gone, new and kept** for each method whose calls changed, a method added or removed, and calls that moved whole from
  one of its methods to another (`movedTo`, `movedFrom`).
- **Rings**: a loop of calls holding a method the commit changed, followed through our code, through a virtual call on the same
  object landing in an override of ours (a call through `base` never does), and through a game method a changed method hands on
  to (through `base`, or virtually on the same object) whose body calls back into an override of ours. **That last needs the
  game's own assemblies**: a mod builds against a reference package whose method bodies are empty, so `--game` names the game and
  its adapter finds its install (`games.real_assemblies`; RimWorld's reads the settings, then Steam's default folder). The
  assembly reader's `calls-of` reads only the methods wanted. Without a game, or one with no such reader yet, `limits` says the
  game's code was not read. **A next game adds one row to `games.REAL_ASSEMBLY_GAMES` and a `real_assemblies(environ)`.**
- On phobos-rimworld's stove-bills fix (`5c122faf`, Framework 0.273.2) with `--game rimworld`: 3 methods' calls changed; 6 calls
  moved from `AvailableReport` into the new `Check`; and one ring cut, `AvailableOnNow → AvailableReport → RecipeWorker.AvailableReport
  (the game's) → AvailableOnNow`, the loop behind the crashes of 23 Nov 2026. About 7 s; reading the game's `Assembly-CSharp` for
  two methods about 2 s of it.
- A ring is not always a fault: it is shown for a person to judge.

## Outputs

The answers (`data`):

- `around`: `centre`, and `groups`, each `{relation, kind, outward, count, exact, nodes}`; relations are calls and called-by, holds
  and belongs-to, builds-on and built-on-by, overrides and overridden-by, patches and patched-by, uses and used-by, imports and
  imported-by. A group lists up to 80, with `count` for all; each thing carries `connections`, how many it has itself.
- `flow`: `columns` from the furthest caller (`step` -depth) through the thing (0) to the furthest callee, and `edges` between them.
- `changed`: the things whose lines a commit changed, read from each file as it stood at that commit, with `linesChanged`,
  `inGraph` (false for a thing since removed) and, since 1.112.0, `at`: `{file, line, end}`, where the thing stood at that commit,
  for a viewer to light its lines in the commit's changes (its `file` and `line` are where it stands now).
- `history`: `node`, `file`, `lines` (first and last), and `commits`, newest first: `hash`, `time`, `subject` and `entries`,
  each `{changelog, product, text}`, the changelog entries that commit wrote; `more` when there are over 25. The lines are followed
  back through moves by git's line-range log; a thing outside the repository is refused.
- `find`: `things`; `summary`: `readers` (each language, how it was read, how much), and counts.
- `names`: `file`, `project`, `projects` (it and every project it refers to), `names`, `snippets`, `errors`,
  `missingReferences`, `seconds`, `commit` and `limits`. Each name is `{line, column, length, text, kind, display, id, here,
  declared}`: `line` counts from 1 and `column` from 0; `kind` is class, struct, interface, enum, delegate, record, method,
  constructor, property, field, constant, enum member, event, parameter, local, type parameter or namespace; `display` its
  signature (`Boat.Float(int)`); `id` the documentation id (`M:NamesFixture.Core.Boat.Float(System.Int32)`); `here` true where
  the name is its own declaration; `declared` either `{file, line, end}` in this repository or `{assembly}`. `snippets` holds
  each of this repository's declarations the file names (not parameters or locals) by `file:line`: `{file, start, end, lines,
  cut}`, at most 60 lines, its comment above it included. Read by name (a Lua, Python or XML file), the answer has `exact: false`
  and each name also `node` (the first thing's connections id), `exact: false`, `candidates` (up to 8 things, `{id, name, kind,
  file, line, end}`) and `more` (how many beyond them); `declared` is the first candidate's place.
- `calls` (1.116.0): `commit` `{hash, subject}`, `files` (`{before, after}` paths, null where a file did not exist), `methods`,
  `rings`, `game`, `gameRead` (the game's assemblies read), `seconds` and `limits`. Each method is `{key, id, node, display, file,
  line, end, status, gone, new, kept}`, `status` changed, added or removed, with `movedTo` and `movedFrom` (`{key, display,
  calls}`) where calls moved whole; each call `{key, display, viaBase}` and either `{file, line, node}` (ours) or `{assembly}`.
  `rings` holds `made`, `cut` and `standing`, each a list of rings, each ring its steps in order `{key, display, outside}`
  (`outside` for a game method), from its first changed method; the last step calls the first.

## Effects

- **It only reads.** Assemblies are opened as files by the kit's assembly reader, never loaded or run.

## Limits

- Calls made through reflection, delegates passed elsewhere, events and Harmony's own patching are only what the code shows; the
  reader cannot follow a method chosen while the game runs.
- Patches of the repository's methods by other mods are not read here; `rimworld-patches` answers that for RimWorld.
- A Def whose defName is also a word other Defs use for something else (a stat's name, say) may be counted as used.
