# RimWorld Harmony patches: who patches what, across every active mod

Built in 0.14.0 (9 November 2026): tool 4 of the plan, the assembly metadata reader, at the owner's request. It answers
"which mods patch this method?", "what does this mod patch?" and "where do several mods patch the same method?" for
every active mod at once, by reading their assemblies' metadata. On the owner's 254 active mods: 5,356 patches in 333
assemblies, read in 6 seconds; a query then takes about 3 seconds (most of it finding the active mods).

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

## Use

```text
cd python
python -m phobos_modkit rimworld-patches                         counts, and methods three or more mods patch
python -m phobos_modkit rimworld-patches who "Pawn.Kill"         every patch on a method, in load order
python -m phobos_modkit rimworld-patches who "VehicleStatHandler.*"   wildcards on the member or the type
python -m phobos_modkit rimworld-patches mod "Combat Extended"   what one mod patches (name or package ID)
python -m phobos_modkit rimworld-patches hotspots --top 50       methods two or more mods patch
```

Paths resolve as the other RimWorld tools do (`--game`, `--workshop`, `--config`, or their environment variables and
settings keys). Results are kept in the kit's cache (`rimworld-patches/patches.sqlite`); only DLLs whose size or time
changed are read again, and everything is read again when the kit's version changes.

## How patches are found

| Form | What is read |
| --- | --- |
| `[HarmonyPatch(typeof(T), "Name", ...)]` on a class | The target: type, member, `MethodType` (getter, setter, constructor...) and argument types. Methods named Prefix, Postfix, Transpiler or Finalizer, or marked `[HarmonyPrefix]` and kin, are the patches. Method-level `[HarmonyPatch]` adds to the class's, as Harmony merges them |
| `[HarmonyPatch]` with `TargetMethod()` | The method that `TargetMethod`'s code looks up through `AccessTools` (one patch per method `TargetMethods` names) |
| `harmony.Patch(original, prefix: new HarmonyMethod(...))` | From the IL: the first method looked up with `AccessTools.Method`, `PropertyGetter` and kin (or `Type.GetMethod`) since the last `Patch` call is the original; a method passed to `new HarmonyMethod` is a patch. `AccessTools.TypeByName("X")` names the type of a lookup that follows |
| `[HarmonyPriority(n)]` | Shown beside the patch |

Harmony's names (the attributes, `Harmony.Patch`, `HarmonyMethod`, `AccessTools`) are the public facts used, from
Andreas Pardeike's Harmony documentation; types are matched by name, so a mod's own copy of HarmonyLib counts too.

## Limits

- Read from the IL, a call-made patch is a best reading, not a proof: a mod that keeps its originals in a list and loops
  over them shows "worked out at run time". The patch class and method are always right.
- Transpilers are listed but what they change is not read.
- Patches the game applies itself, and ones made by other frameworks' attributes (a framework that scans for its own
  attribute and calls Harmony), are not seen.
- The game's own assembly is not read: it patches nothing.
