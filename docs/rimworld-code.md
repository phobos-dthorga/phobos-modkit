# rimworld-code: another author's code, for a program

Built in 1.49.0 (19 November 2026) for D'thorga Companion, after the owner chose "Read and compare, on your press": follow one
of our Harmony patches into the method it patches, and read another author's code on screen.

## Read this first (gotchas)

- **Public source comes first.** It has the author's own names and comments. A decompile is the compiled file read back:
  no comments, and sometimes invented local names. `show` stops at the public source when it holds the name.
- **The first search indexes every place source is kept.** On the owner's machine that was 144 folders and about four
  minutes, once. The indexes live in the kit's cache (`code-index`) and are rebuilt only when a folder's files change.
- **A decompile is made only when asked** (`decompile`), into the kit's cache (`decompiled`), once per build of the assembly.
  A mod's assembly takes seconds; the game's `Assembly-CSharp.dll` about five minutes the first time. The twelve most
  recently used decompiles are kept, shared with `code compare` and `rimworld-upstream`.
- **Decompiled code stays on this machine.** It is never written into a repository, and is not ours to publish.
- **Matching is by name.** `holder` reads the game's and every active mod's assemblies through their metadata only (nothing
  is loaded or run), and a type with the same name in two assemblies is listed twice.

## Run it

```text
python -m phobos_modkit rimworld-code show Vehicles.VehicleTurret.TurretRotation --root REPO   the source, from the best copy kept
python -m phobos_modkit rimworld-code holder RimWorld.Planet.WorldPawns --root REPO          which assembly and mod declares it
python -m phobos_modkit rimworld-code decompile --assembly PATH --root REPO                  decompile it once, into the cache
```

A name may be written as Harmony, our connections graph or a person writes it: `Verse.Pawn:Kill`, `.GroundRearm.FindFallback`,
`Outer+Inner.Go`. `holder` takes a type or a member of one.

## Where source is looked for

| Order | Place | Kind |
| --- | --- | --- |
| 1 | Each folder in the source clones folder (`sourceClonesPath`, `PHOBOS_SOURCE_CLONES` or `--clones`; [rimworld-sources](rimworld-sources.md) clones there) | Public source |
| 2 | Each folder or `.cs` file in the repository's `.local/decompiled` | A decompile made by hand |
| 3 | Each finished decompile in the kit's cache, named for its assembly | A decompile made by `decompile` |

The repository's own `.local/install-settings.json` is the settings file unless `--settings` names another, so a repository's
clones folder is found without arguments. Our own `src/` is never searched: the connections graph shows it.

## What a program gets

`show` gives `data.found`: for each declaration, its `corpus`, `source` (`source` or `decompiled`), `kind`, `full` name,
`signature`, `file` (relative to the corpus), `start` and `end`, `lines` (without the decompiler's `//IL_` notes), `numbers`
(each line's own number in its file) and `more` (cut at `--lines`). `holder` gives `data.holders`: `type`, `assembly`, `path`
and `mod` (a mod's name, or "the game"). `decompile` gives `data.assembly`, `data.folder` and `data.built` (false when a
finished copy was already kept). A failure is `data.ok` false with the reason, as every other tool refuses.

All three carry the manifest surface `other-code`. `rimworld-archive list` (now with `data.files`: each kept file's owner, how
many versions, the newest and the one before) and `compare` carry `updates`, for "what did an update change?".
