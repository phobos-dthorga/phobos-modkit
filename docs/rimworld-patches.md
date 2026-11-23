# RimWorld Harmony patches: who patches what, across every active mod

It answers "which mods patch this method?", "what does this mod patch?" and "where do several mods patch the same method?" for
every active mod at once, by reading their assemblies' metadata.

## Read this first

- **Assemblies are read, never run.** The reader (`dotnet/PhobosModKit.Assemblies`, C#) opens each DLL as a file through
  System.Reflection.Metadata, part of .NET itself. Nothing is loaded into a process; no mod's code runs.
- **It needs the .NET SDK** (10 or newer) the first time, to build the reader into the kit's build folder (outside the
  repository). Without it the command says so and stops.
- **Only the assemblies the game loads**: each active mod's load folders for the game's version (LoadFolders.xml and its
  IfModActive conditions, as `loading.load_folders` reads them), then their Assemblies folders. The shared Harmony copies
  (0Harmony.dll and kin) are skipped.
- **"May skip" marks a prefix returning bool**: it can stop the original method and every later prefix from running. A
  method with several of them is where one mod's change can silently undo another's.
- **What metadata cannot say, the notes do.** A target a TargetMethod works out at run time is read from that method's
  code when it names it with AccessTools (note "target read from TargetMethod's code"); an original passed in a variable
  is "worked out at run time". Patches made by a mod's own wrapper around Harmony are not seen.

## Examples

```text
cd python
python -m phobos_modkit rimworld-patches                         counts, and methods three or more mods patch
python -m phobos_modkit rimworld-patches who "Pawn.Kill"         every patch on a method, in load order
python -m phobos_modkit rimworld-patches who "VehicleStatHandler.*"   wildcards on the member or the type
python -m phobos_modkit rimworld-patches mod "Combat Extended"   what one mod patches (name or package ID)
python -m phobos_modkit rimworld-patches hotspots --top 50       methods two or more mods patch
python -m phobos_modkit rimworld-patches targets --root REPO --updates   each method REPO patches, the others on it, its last update
```

## Reports and options

<!-- generated: options rimworld-patches -->
Generated from the command's own parser by `python -m phobos_modkit command-docs --write`: change a help text in the parser, not here.

| Report | What it does | Effect |
| --- | --- | --- |
| `summary` | Counts and the most-patched methods. | reads only |
| `who` | Every patch on a method. | reads only |
| `mod` | What one mod patches. | reads only |
| `hotspots` | Methods several mods patch. | reads only |
| `targets` | Each method a repository's code patches: the other mods patching it, and, with `--updates`, what its last update changed (1.37.0). Each method a repository patches, with the other mods on it; needs the repository. | reads only |

| Option | Reports | What it does | Default |
| --- | --- | --- | --- |
| `--game VALUE` | all | the RimWorld folder (else RIMWORLD_PATH, the settings file, Steam's default) |  |
| `--workshop VALUE` | all | the Workshop content folder (else RIMWORLD_WORKSHOP_PATH, settings, beside the game) |  |
| `--config VALUE` | all | the folder holding ModsConfig.xml (else RIMWORLD_CONFIG_PATH, settings, default) |  |
| `--cache VALUE` | all | where the index is kept (else PHOBOS_MODKIT_CACHE, settings, the temp folder) |  |
| `--settings VALUE` | all | a JSON settings file with rimworldPath, workshopPath, rimworldConfigPath |  |
| `--rebuild` | all | read every assembly again |  |
| `--top N` | all | rows per table (default 25) | `25` |
| `TARGET` | `who` | Type.Method, Namespace.Type.Method or Method; \* and ? are wildcards |  |
| `NAME` | `mod` | a mod's name or package ID; \* and ? are wildcards |  |
| `--root VALUE` | `targets` | the repository whose patches to look at (default: here) | `.` |
| `--updates` | `targets` | also compare the archive's newest two versions of each file (rimworld-upstream updates; decompiles on first use) |  |
| `--days N` | `targets` | `--updates`: updates in the last N days (default 30) | `30` |
| `--archive VALUE` | `targets` | `--updates`: the assembly archive (else PHOBOS_ASSEMBLY_ARCHIVE, settings, default) |  |
| `--decompiler VALUE` | `targets` | `--updates`: ilspycmd (else PHOBOS_MODKIT_ILSPYCMD, settings, the PATH) |  |

- Every report also takes `--json` (print JSON instead of Markdown) and `--no-redact` (show the home folder instead of ~).
- Names in capitals are given bare, without a flag, in the order shown.
- A path left out is looked for in the order [settings](settings.md) explains: an environment variable, the repository's own settings file, the central settings file, then the default.
- [Common options](common-options.md) explains `--root`, `--game`, `--workshop`, `--config`, `--settings`, `--cache`, `--top`, `--json` and `--no-redact`, which many commands share.
<!-- end generated -->

## Inputs

Paths resolve as the other RimWorld tools do (`--game`, `--workshop`, `--config`, or their environment variables and
settings keys; see [common options](common-options.md)).

### How patches are found

| Form | What is read |
| --- | --- |
| `[HarmonyPatch(typeof(T), "Name", ...)]` on a class | The target: type, member, `MethodType` (getter, setter, constructor...) and argument types. Methods named Prefix, Postfix, Transpiler or Finalizer, or marked `[HarmonyPrefix]` and kin, are the patches. Method-level `[HarmonyPatch]` adds to the class's, as Harmony merges them |
| `[HarmonyPatch]` with `TargetMethod()` | The method that `TargetMethod`'s code looks up through `AccessTools` (one patch per method `TargetMethods` names) |
| `harmony.Patch(original, prefix: new HarmonyMethod(...))` | From the IL: the first method looked up with `AccessTools.Method`, `PropertyGetter` and kin (or `Type.GetMethod`) since the last `Patch` call is the original; a method passed to `new HarmonyMethod` is a patch. `AccessTools.TypeByName("X")` names the type of a lookup that follows |
| `[HarmonyPriority(n)]` | Shown beside the patch |

Harmony's names (the attributes, `Harmony.Patch`, `HarmonyMethod`, `AccessTools`) are the public facts used, from
Andreas Pardeike's Harmony documentation; types are matched by name, so a mod's own copy of HarmonyLib counts too.

## Outputs

### A repository's patch targets (`targets`)

`targets` lists each method a repository's code patches, from its `connections` graph (exact, from the built assemblies), with
every other active mod patching the same method (the repository's own assemblies left out, by name) and how many of those patches
may skip the original. With `--updates` it adds rimworld-upstream's comparison of the newest two versions the assembly archive kept
of each file in the last `--days` (30): a new signature, a new body or a removed member, matched by type and member name. Its JSON
`data.targets` holds `{node, target, name, assembly, ours, mods, skippers, changed}`; `node` is the target's `connections` id. Each
`changed` entry gives `mod`, `file`, `versions`, `change` and, from 1.51.0, `newestKept`: when the archive first kept the newer
build, as an ISO time, so a program can tell an update since the last launch from an older one.
D'thorga Companion's Code map shows it as badges on the methods.

## Effects

Results are kept in the kit's cache (`rimworld-patches/patches.sqlite`); only DLLs whose size or time changed are read again, and
everything is read again when the kit's version changes. On the owner's 254 active mods: 5,356 patches in 333 assemblies, read in
6 seconds; a query then takes about 3 seconds (most of it finding the active mods).

## Limits

- Read from the IL, a call-made patch is a best reading, not a proof: a mod that keeps its originals in a list and loops
  over them shows "worked out at run time". The patch class and method are always right.
- Transpilers are listed but what they change is not read.
- Patches the game applies itself, and ones made by other frameworks' attributes (a framework that scans for its own
  attribute and calls Harmony), are not seen.
- The game's own assembly is not read: it patches nothing.
