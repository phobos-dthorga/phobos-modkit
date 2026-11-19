# Connections: how a repository's code fits together

**Status (19 Nov 2026):** built in 1.33.0, at the owner's request for "flow-charts and the such which show relationships between
functions, classes, etc. of the code I'm viewing". D'thorga Companion's code viewer and Code map page are its first consumers.

## Read this first (gotchas)

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
- **It only reads.** Assemblies are opened as files by the kit's assembly reader, never loaded or run.

## Run it

```text
python -m phobos_modkit connections summary --root REPO
python -m phobos_modkit connections find --root REPO --name "*Tick*"
python -m phobos_modkit connections around --root REPO --node cs:Phobos.Framework.TopUp.Seen.Note
python -m phobos_modkit connections flow --root REPO --node cs:Phobos.Framework.TopUp.Seen.Note --depth 2
python -m phobos_modkit connections changed --root REPO --commit 3352e4da
python -m phobos_modkit connections history --root REPO --node cs:Phobos.Framework.TopUp.Seen.Note [--limit 100]
```

Add `--json` for the envelope; `--rebuild` reads every file again.

## What is read, and how

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

## The answers (`data`)

- `around`: `centre`, and `groups`, each `{relation, kind, outward, count, exact, nodes}`; relations are calls and called-by, holds
  and belongs-to, builds-on and built-on-by, overrides and overridden-by, patches and patched-by, uses and used-by, imports and
  imported-by. A group lists up to 80, with `count` for all; each thing carries `connections`, how many it has itself.
- `flow`: `columns` from the furthest caller (`step` -depth) through the thing (0) to the furthest callee, and `edges` between them.
- `changed`: the things whose lines a commit changed, read from each file as it stood at that commit, with `linesChanged` and
  `inGraph` (false for a thing since removed).
- `history` (1.34.0): `node`, `file`, `lines` (first and last), and `commits`, newest first: `hash`, `time`, `subject` and `entries`,
  each `{changelog, product, text}`, the changelog entries that commit wrote; `more` when there are over 25. The lines are followed
  back through moves by git's line-range log; a thing outside the repository is refused.
- `find`: `things`; `summary`: `readers` (each language, how it was read, how much), and counts.

## Limits

- Calls made through reflection, delegates passed elsewhere, events and Harmony's own patching are only what the code shows; the
  reader cannot follow a method chosen while the game runs.
- Patches of the repository's methods by other mods are not read here; `rimworld-patches` answers that for RimWorld.
- A Def whose defName is also a word other Defs use for something else (a stat's name, say) may be counted as used.
