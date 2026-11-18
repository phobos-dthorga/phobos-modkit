# rimworld-perf

Where a running RimWorld spends its time: by mod, by method and by part of the game loop, with the runtime's garbage collection
figures beside them. It records the game from outside with Microsoft's own .NET diagnostics tools, and reads what they write.

## Read this first (gotchas)

- **RimWorld 1.7 or newer only.** 1.7 runs on Microsoft's CoreCLR runtime and opens the standard .NET diagnostics pipe; that is
  what lets the tools attach (seen November 2026: `coreclr.dll` in the process, `\\.\pipe\dotnet-diagnostic-<pid>` open). 1.6 and
  earlier ran on Mono, which these tools cannot record.
- **Record with the game in the state that feels slow**: the save loaded, unpaused, at the speed you play. A paused game records
  almost nothing, and the report says so.
- **Save first.** Attaching can make the game hitch for a moment, about as long as an autosave. Nothing in the game is changed.
- **The first recording installs `dotnet-trace` and `dotnet-counters`** (version 10.0.750501, Microsoft) into the kit's build
  folder with `dotnet tool install`, which needs the .NET SDK 10 or newer and fetches them from NuGet once.
- **A recording measures; it is not an in-game test.** It says where time went, never whether a feature works.

```text
python -m phobos_modkit rimworld-perf record                       30 seconds of the running game, then its report
python -m phobos_modkit rimworld-perf record --seconds 60 --label "many wounded"
python -m phobos_modkit rimworld-perf report                       the newest recording again (or name one by ID or label)
python -m phobos_modkit rimworld-perf mod "Combat Extended"        one mod: its busiest methods and where its time went
python -m phobos_modkit rimworld-perf compare                      the last two recordings, as shares
python -m phobos_modkit rimworld-perf compare before after         two recordings by ID or label
python -m phobos_modkit rimworld-perf list                         every recording kept
python -m phobos_modkit rimworld-perf index FILE.speedscope.json --counters FILE.json   a trace recorded by hand
```

## Snapshots: a frozen game, and memory (1.22.0)

```text
python -m phobos_modkit rimworld-perf stack --label "frozen"   3 snapshots of every thread's stack, 2 s apart (--times, --every)
python -m phobos_modkit rimworld-perf stack-report             the newest again (or name one)
python -m phobos_modkit rimworld-perf heap --label "day 40"    the managed heap by type and by mod
python -m phobos_modkit rimworld-perf heap-report              the newest again
python -m phobos_modkit rimworld-perf heap-compare             the last two heaps (or name two): who grew
```

- **stack** runs Microsoft's `dotnet-stack report` a few times. It finds the thread running the game's loop (a frame from the
  named parts or `Verse.Root*`), says whether its stack moved between snapshots, and if it moved, the outer frames that never did:
  the place to look for a loop that never ends or the same slow work again and again. Then the part of the loop, the innermost mod
  on its stack (as **Caused by** above), its frames innermost first, and other threads with game or mod code on them. Each snapshot
  stops the game for a moment; on a small test program one took half a second.
- **heap** runs `dotnet-gcdump collect`, **which forces a full garbage collection, so the game pauses until it is done**, then its
  report: one row per type, with its count and the average size of one object, read here as totals. Each type belongs to its
  module's owner, as frames do. A .NET collection whose generic arguments name a mod's type (`List<Example.Dose>`) counts for that
  mod, "through" that type. **Memory counts under the type that is it**: the arrays and strings a mod's objects hold count as
  .NET's. What holds what is in the `.gcdump` file kept beside the report, for PerfView or Visual Studio.
- **On .NET 10 runtimes dotnet-gcdump warns that it can drop events on a large heap** ("non-lossy buffering requires .NET 11+"),
  so counts can come out low. The report repeats the warning; trust a difference between heaps that repeats.
- **A leak is a heap that keeps growing** across several snapshots of the same game minutes apart with the same thing on screen.
  Two can mislead; take a third.
- Snapshots are kept in the kit's cache, `rimworld-stacks/` and `rimworld-heaps/`, and listed by `list`; cleanup lists them once a
  fortnight old.

## What a recording is

`record` finds the running `RimWorld` process (`--pid` when there are two) and runs, side by side for `--seconds`:

| Tool | What it records |
| --- | --- |
| `dotnet-trace collect --format Speedscope` | Every managed thread's call stack about once a millisecond, then converted to speedscope's JSON |
| `dotnet-counters collect --format json` | The runtime's counters once a second: time paused for garbage collection, collections by generation, memory allocated, JIT compiling, lock waits, processor and memory use |

The converted trace is indexed into SQLite (`index.sqlite`) with the owners of every module worked out against the mod list as
it is then, and the counters' averages and worst seconds. The raw `trace.nettrace` stays beside it for PerfView or Visual Studio;
the speedscope file is deleted unless `--keep-speedscope` is given, because it is large. Recordings live in the kit's cache
(`rimworld-perf/<date>-<time>-<label>/`), outside every repository; `cleanup` lists them once they are a fortnight old, saying they
cannot be made again.

## Reading the report

- **The main thread** is the thread that spent most time running managed code: RimWorld's game loop.
- **Parts of the game loop** come from `games/rimworld/perf-phases.json`: ticking (`Verse.TickManager.DoSingleTick`, the
  simulation), map and world drawing, the alerts column, the interface, sound and music, the engine's own frame drawing, and
  loading or saving. Each sample belongs to the first part whose method is
  on its stack, from the root down. Time outside them is listed by its first non-.NET method, so a missing part shows itself.
- **Caused by** is the innermost frame on the stack that belongs to a mod. A mod's code calling the game's counts for the mod;
  a Harmony prefix or postfix is its own frame and counts for the mod that wrote it. With no mod on the stack the game caused it,
  the engine's drawing included. **Work a transpiler adds inside a game method counts as the game's**, and so does a small method
  the compiler inlined into its caller.
- **One mod's code running another's** pairs the outermost mod on a stack with the innermost one. The first decides when and how
  often; the second does the work. The first recording of the owner's game (17 November 2026) needed it: Search and Rescue called
  Smart Medicine's medicine search inside a scoring loop, and the caused-by table alone named only Smart Medicine.
- **Where the thread was** is the method running when the sample was taken: the place to look for the slow line.
- **Running managed code** against **in native code or waiting**: the runtime marks each sample. Native time is the engine,
  the operating system, garbage collection or a wait; it is still time the frame took.
- **Patched game methods** are methods Harmony rewrote, with everything they call. Harmony 2 names them
  `dynamicClass.DMD<Type::Method>`; Harmony 3 on .NET names them after the original with a patch count
  (`dynamicClass.Verse.TickManager.DoSingleTick_Patch6`), and adds glue named `dynamicClass.Glue:AbiFixup<... Type:Method(...)>`.
  All three read as the original method, so a patched part of the loop is still found. Recordings indexed by an older version
  are read the same way: their frame names are split again when they load.
- **Owners**: `Assembly-CSharp` and `RimWorld` are the game; other DLLs in the install folder are the engine and Ludeon's
  libraries (Waylith, Brutal, Steamworks); `System.*` and `Microsoft.*` are .NET; Harmony and MonoMod are libraries; every active
  mod's assemblies for the game's version are that mod's, the first in load order winning when two ship one name. A module no
  rule matches is listed as unmatched.
- **Compare** uses shares of the main thread and of ticking, not milliseconds: a faster game ticks more often, so a mod's
  milliseconds per second can rise when the game speeds up.

## Limits

- Sampling sees about one stack per millisecond per thread. Totals over many seconds are reliable to a few percent; a method
  that ran for less than a millisecond in all can be missed or over-counted by chance.
- The trace counts no calls and no ticks, so it cannot give ticks per second.
- Overloads of one method are counted together (the report drops argument lists).
- The phase patterns were read from the game's code. In the first recording of the game (RimWorld 1.7.5011, 349 mods, 17 November
  2026) they matched 99.2% of the main thread; the rest sat in the program's entry point. A second recording (18 November 2026)
  matched only 66.7% until Harmony 3's names were read, then all but 2% once the alerts column, sound and the engine's frame
  drawing were named: the game's loop methods had Harmony patches that day and not the day before. The loading patterns saw
  little time there and are the least checked.
