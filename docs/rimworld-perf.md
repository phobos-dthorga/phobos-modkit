# rimworld-perf: where a running RimWorld spends its time and memory

Where a running RimWorld spends its time: by mod, by method and by part of the game loop, with the runtime's garbage collection
figures beside them. It records the game from outside with Microsoft's own .NET diagnostics tools, and reads what they write.

## Read this first

- **RimWorld 1.7 or newer only.** 1.7 runs on Microsoft's CoreCLR runtime and opens the standard .NET diagnostics pipe; that is
  what lets the tools attach (seen November 2026: `coreclr.dll` in the process, `\\.\pipe\dotnet-diagnostic-<pid>` open). 1.6 and
  earlier ran on Mono, which these tools cannot record.
- **Record with the game in the state that feels slow**: the save loaded, unpaused, at the speed you play. A paused game records
  almost nothing, and the report says so.
- **Save first.** Attaching can make the game hitch for a moment, about as long as an autosave. Nothing in the game is changed.
- **The first recording installs `dotnet-trace` and `dotnet-counters`** (version 10.0.750501, Microsoft) into the kit's build
  folder with `dotnet tool install`, which needs the .NET SDK 10 or newer and fetches them from NuGet once.
- **A recording measures; it is not an in-game test.** It says where time went, never whether a feature works.

## Examples

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

Snapshots of a frozen game, and of memory:

```text
python -m phobos_modkit rimworld-perf stack --label "frozen"   3 snapshots of every thread's stack, 2 s apart (--times, --every)
python -m phobos_modkit rimworld-perf stack-report             the newest again (or name one)
python -m phobos_modkit rimworld-perf heap --label "day 40"    the managed heap by type and by mod
python -m phobos_modkit rimworld-perf heap-report              the newest again
python -m phobos_modkit rimworld-perf heap-compare             the last two heaps (or name two): who grew
```

Memory over time, and following a watch from a program:

```text
python -m phobos_modkit rimworld-perf watch --minutes 120 --label "reloads"   up to two hours; Ctrl+C ends it early
python -m phobos_modkit rimworld-perf watch --no-counters                      Windows' figures only: nothing attaches
python -m phobos_modkit rimworld-perf watch-report                             the newest again (or name one)
python -m phobos_modkit rimworld-perf watch-status --json            the running watch (else the newest) as it stands
python -m phobos_modkit rimworld-perf watch-mark "reloading now"     your words beside the running watch's figures
python -m phobos_modkit rimworld-perf watch-stop                     end the running watch early
```

## Reports and options

<!-- generated: options rimworld-perf -->
Generated from the command's own parser by `python -m phobos_modkit command-docs --write`: change a help text in the parser, not here.

| Report | What it does | Effect |
| --- | --- | --- |
| `report` | A recording: phases, who caused the time, busiest methods, garbage collection. | reads only |
| `record` | Record the running game, then report it. Attaches Microsoft's dotnet-trace and dotnet-counters to the running game; it changes nothing in it. | runs other programs |
| `index` | Index a speedscope file recorded by hand with dotnet-trace. | reads only |
| `mod` | One mod in a recording. | reads only |
| `compare` | Two recordings, as shares of the main thread and of ticking. | reads only |
| `list` | Every recording and snapshot kept. | reads only |
| `stack` | A frozen or stuck game: every thread's stack, a few times. Attaches Microsoft's dotnet-stack to the running game a few times; it changes nothing in it. | runs other programs |
| `stack-report` | Stack snapshots taken earlier. | reads only |
| `heap` | What holds the game's memory, by type and by mod (pauses the game). Attaches Microsoft's dotnet-gcdump to the running game, which forces a full garbage collection: the game pauses until it is done. | runs other programs |
| `heap-report` | A heap taken earlier. | reads only |
| `heap-compare` | Two heaps: who grew. | reads only |
| `watch` | The game's memory over time, without pausing it; Ctrl+C ends it early. Reads Windows' memory figures without pausing the game; attaches dotnet-counters once unless `--no-counters`. Ends early when watch-stop asks. | runs other programs |
| `watch-report` | A memory watch taken earlier. | reads only |
| `watch-status` | A running or kept watch as it stands, light enough to read every few seconds. Light enough to read every few seconds: the latest figures, the timeline so far, your marks, the watches kept. | reads only |
| `watch-stop` | End a running watch early, from another console or a program. Writes a stop file into the running watch's own folder in the kit's cache; the watch ends at its next look. | writes |
| `watch-mark` | Put a few words of your own beside a watch's figures. Adds the owner's words to the watch's own database in the kit's cache; nothing else. | writes |
| `look` | Inside the running game from a snapshot: every object by type and by mod. Takes a Windows snapshot of the running game (a pause of about half a second) and reads it with the game's own memory-reading library from its install folder; nothing is written to the game. | runs other programs |
| `look-kind` | One kind's objects in the running game, each described. Takes a Windows snapshot of the running game (a pause of about half a second) and reads it with the game's own memory-reading library from its install folder; nothing is written to the game. | runs other programs |
| `look-why` | Why a kind is still in memory: paths from a root to its largest objects. Takes a Windows snapshot of the running game (a pause of about half a second) and reads it with the game's own memory-reading library from its install folder; nothing is written to the game. | runs other programs |
| `look-serve` | Hold a snapshot and answer JSON requests a line at a time, for a program. Takes a Windows snapshot of the running game (a pause of about half a second) and reads it with the game's own memory-reading library from its install folder; nothing is written to the game. Holds the snapshot and answers one JSON request a line on standard input until it closes or the time limit passes; for a program's page, not a person's console. | runs other programs |

| Option | Reports | What it does | Default |
| --- | --- | --- | --- |
| `--cache VALUE` | all | where recordings are kept (else PHOBOS_MODKIT_CACHE, the settings file, the temp folder) |  |
| `--game VALUE` | all | the RimWorld folder (else RIMWORLD_PATH, the settings file, Steam's default) |  |
| `--workshop VALUE` | all | the Workshop content folder (else RIMWORLD_WORKSHOP_PATH, settings, beside the game) |  |
| `--config VALUE` | all | the folder holding ModsConfig.xml (else RIMWORLD_CONFIG_PATH, settings, default) |  |
| `--settings VALUE` | all | a JSON settings file with the paths above |  |
| `--top N` | all | rows per table (default 15) | `15` |
| `RECORDING` | `report` | (optional) a recording's ID (its start is enough) or label; the newest when left out |  |
| `--seconds N` | `record` | how long to record (default 30) | `30` |
| `--label VALUE` | `record` | a few words to find the recording by, such as what was happening |  |
| `--pid N` | `record`, `stack`, `heap`, `watch`, `look`, `look-kind`, `look-why`, `look-serve` | the game's process ID, when more than one RimWorld runs |  |
| `--keep-speedscope` | `record` | keep the converted trace beside the index (large) |  |
| `FILE` | `index` | a .speedscope.json file from dotnet-trace |  |
| `--counters VALUE` | `index` | dotnet-counters' JSON file from the same time |  |
| `--label VALUE` | `index` | a few words to find the recording by |  |
| `NAME` | `mod` | a mod's name; \* and ? are wildcards |  |
| `RECORDING` | `mod` | (optional) a recording's ID or label; the newest when left out |  |
| `FIRST` | `compare` | (optional) the earlier recording; the second newest when both are left out |  |
| `SECOND` | `compare` | (optional) the later recording; the newest when both are left out |  |
| `--times N` | `stack` | how many snapshots (default 3) | `3` |
| `--every N` | `stack` | seconds between them (default 2) | `2.0` |
| `--label VALUE` | `stack` | a few words to find the snapshots by, such as what the game was doing |  |
| `--frames N` | `stack`, `stack-report` | frames of the main thread shown (default 40) | `40` |
| `SNAPSHOT` | `stack-report`, `heap-report` | (optional) its ID (its start is enough) or label; the newest when left out |  |
| `--label VALUE` | `heap` | a few words to find the heap by, such as the in-game day |  |
| `FIRST` | `heap-compare` | (optional) the earlier heap; the second newest when both are left out |  |
| `SECOND` | `heap-compare` | (optional) the later heap; the newest when both are left out |  |
| `--minutes N` | `watch` | how long to watch (default 60) | `60` |
| `--every N` | `watch` | seconds between samples (default 5) | `5` |
| `--map-every N` | `watch` | seconds between memory maps, 0 for none (default 60; Windows only) | `60` |
| `--no-counters` | `watch` | leave .NET's counters out: nothing attaches to the game at all |  |
| `--label VALUE` | `watch` | a few words to find the watch by, such as what you plan to do |  |
| `--logs VALUE` | `watch` | the folder holding Player.log (else RIMWORLD_LOGS_PATH, settings, default) |  |
| `WATCH` | `watch-report` | (optional) its ID (its start is enough) or label; the newest when left out |  |
| `WATCH` | `watch-status` | (optional) its ID or label; the one running, else the newest, when left out |  |
| `WATCH` | `watch-stop` | (optional) its ID or label; the one running when left out |  |
| `TEXT` | `watch-mark` | what you are doing or about to do, such as "reloading now" (at most 200 characters) |  |
| `--watch VALUE` | `watch-mark` | its ID or label; the one running, else the newest, when left out |  |
| `--at N` | `watch-mark` | the moment it names, in seconds since 1970; now when left out |  |
| `--label VALUE` | `look` | a few words to find it by, such as the in-game day |  |
| `TYPE` | `look-kind` | the type's full name, as look lists it (Verse.Pawn) |  |
| `--match VALUE` | `look-kind` | only objects whose description holds this text (a pawn's name, a defName) |  |
| `--largest` | `look-kind` | largest first |  |
| `--open` | `look-kind` | also show the first one with every value it holds |  |
| `TYPE` | `look-why` | the type's full name, as look lists it (System.Xml.XmlDocument) |  |
| `--sample N` | `look-why` | paths to show, each to a different object (default 3) | `3` |
| `--label VALUE` | `look-serve` | a few words to keep its overview by |  |
| `--limit-seconds N` | `look-serve` | let the snapshot go after this long (default 600: it costs memory while held) | `600` |

- Every report also takes `--json` (print JSON instead of Markdown) and `--no-redact` (show the home folder instead of ~).
- Names in capitals are given bare, without a flag, in the order shown.
- A path left out is looked for in the order [settings](settings.md) explains: an environment variable, the repository's own settings file, the central settings file, then the default.
- [Common options](common-options.md) explains `--game`, `--workshop`, `--config`, `--settings`, `--cache`, `--top`, `--json` and `--no-redact`, which many commands share.
<!-- end generated -->

## Outputs

### Reading the report

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

### Snapshots: a frozen game, and memory

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
- **On a large heap the snapshot holds only part of it.** On the owner's game (19 November 2026) dotnet-gcdump listed exactly
  10,000,003 objects and 667 MB, while the runtime's own counters had put the heap at 6 to 11.5 GB in earlier recordings, of it
  4 to 6 GB live objects and the rest gaps between them: it stops near ten million objects (Microsoft documents no such limit;
  seen, not explained). **Since 1.42.0, heap reads the runtime's own count straight after the snapshot** (dotnet-counters, a few
  seconds), and the report says in bold when the snapshot holds less than 90% of it, with shares of what it listed, never of the
  whole heap. Since 1.45.1 it compares with the runtime's live objects (its heap size less the gaps), since the heap size counts
  the gaps too (Microsoft's runtime metrics reference) and a snapshot lists objects only. Older snapshots with a count near ten million are
  flagged the same way. The report also says how long taking it took (about 20 to 30 s on the owner's game, by the owner's
  watch). For the whole heap over time, use **watch**.
- **On .NET 10 runtimes dotnet-gcdump warns that it can drop events on a large heap** ("non-lossy buffering requires .NET 11+"),
  so counts can come out low. The report repeats the warning; trust a difference between heaps that repeats.
- **A leak is a heap that keeps growing** across several snapshots of the same game minutes apart with the same thing on screen.
  Two can mislead; take a third.
- Snapshots are kept in the kit's cache, `rimworld-stacks/` and `rimworld-heaps/`, and listed by `list`; cleanup lists them once a
  fortnight old.

### Memory over time: watch

**The question it answers: does the game's memory climb steadily or in bursts, and is it .NET's or the engine's?** A heap
snapshot shows one instant and pauses the game; a watch follows the whole program for as long as asked, without pausing it.

- **Run it in a console of its own and leave it**: it ends when the minutes run out, when the game closes, or on Ctrl+C, and
  prints its report then. Everything up to that moment is kept, whichever way it ends.
- **Cost**: reading Windows' figures and the memory map does not pause or touch the game (a map of the owner's game, about
  21,000 regions, took 0.3 s of the watcher's own time). The runtime's counters attach once at the start, as `record` does, which
  can hitch the game for a moment; `--no-counters` leaves them out.
- **Every `--every` seconds (default 5)**: what the game has claimed (private bytes, Windows' commit charge) and what of it is in
  RAM, from Windows' `GetProcessMemoryInfo`; the machine's free RAM. On Linux, `/proc/<pid>/status` stands in (anonymous resident
  memory plus swap for private bytes; not yet checked against a running game there).
- **From the runtime, at the same pace** (dotnet-counters): what the collector holds from Windows, the .NET heap after its last
  collection, and the gaps inside it. **The heap's size counts its gaps** ([Microsoft's runtime metrics
  reference](https://learn.microsoft.com/dotnet/core/diagnostics/built-in-metrics-runtime)), so since 1.45.1 the report shows live
  objects as the heap less the gaps (1.42.0 called the whole heap "live"). **Claimed less the collector's is "outside .NET"**: the
  engine (textures, meshes, sound), graphics drivers, native code and .NET's own bookkeeping together.
- **Every `--map-every` seconds (default 60; Windows only)**: the memory map from `VirtualQueryEx`, as Microsoft's VMMap shows
  it: committed memory by kind (private, loaded code files, mapped files), private memory by block and by block size, and code
  and mapped files by file name (never their folder). The block whose size matches the collector's figure within 10% is named as
  .NET's heap; other blocks have addresses only, since Windows cannot say who asked for them.
- **The report**: a bold verdict (held steady; climbed mostly in jumps; or mostly a steady climb, with where it ended against
  where it began); start, end, lowest, average and highest of each figure; the largest jumps (rises of 250 MB or more within a
  minute) with what Player.log says from a minute before to a minute after (saves loaded, errors counted, the engine holding
  allocations); the figures over time as a line chart; and the first and last memory maps side by side.
- **First reading of the owner's game** (19 November 2026, `--no-counters`, 2 minutes, not a test): 26 GB claimed; one 135 GB
  reservation with 12.9 GB committed (most likely .NET's heap, unconfirmed without the counters), and about 12 GB in some 2,400
  native blocks of 1 to 64 MB. Reloading a save dropped the claim 1.6 GB, then raised it 3.4 GB within a minute, mostly in 390
  new blocks of 1 to 16 MB.
- **First watch with the counters** (19 November 2026, 15 minutes, a fresh game with one save loaded before it began, no reload
  during it): 17.4 GB claimed at the start, 18.2 GB at the end. .NET's collector held 8.3 GB throughout (heap 7.8 GB, of it about
  5.3 GB live objects and 2.5 to 3.1 GB gaps); outside .NET rose from 9.0 to 9.9 GB in two jumps a minute apart (+568 MB,
  +274 MB), all native, mostly in 20 new blocks of 16 to 64 MB.

Watches are kept in the kit's cache, `rimworld-memory/<start>-<label>/watch.sqlite` (with dotnet-counters' own file beside it),
and listed by `list`; cleanup lists them once a fortnight old.

### Following and steering a watch from a program

D'thorga Companion's Memory page uses these: the owner chose (19 November 2026) to run memory profiling from there rather than
through agents. All five commands carry the manifest surface `memory-watch`, so a program finds them without naming the game.

- **watch-status** is light enough to read every few seconds (about 0.2 s): the state (`running`, `finishing`, `ended`, or
  `cut-off` when its watcher stopped without finishing), the latest figures, the timeline so far (up to 120 points), the marks and
  the 20 newest watches. While a watch runs, .NET's figures come from dotnet-counters' own file as far as it has written it; if
  the tool holds them back until it closes, they show only at the end (not yet seen on the owner's game).
- **watch-stop** writes a `stop` file into the running watch's folder. The watch looks for it every second, ends, stops
  dotnet-counters (whose file is read up to where it was cut) and writes its report as usual. Ctrl+C in its console still works.
- **watch-mark** adds an `owner-mark` event to the watch's database, now or `--at` a moment up to a minute either side of the
  watch. It exists because two reloads asked for during watches never reached the log: **the report now says what happened
  before any figure** (the saves the log shows loaded, or that none was; the marks; the errors), and says so in bold when a mark
  naming a load or reload is not followed by a save loading within 3 minutes. The jumps table names marks beside the log's events.
- **Not built:** carrying a watch across a game restart, or starting one when the game starts (owner to decide, on the
  Companion's Decisions page).

### Looking inside

`look`, `look-kind`, `look-why` and `look-serve` read a Windows snapshot of the game with the kit's heap reader instead of
dotnet-gcdump: every object with no limit on how many, any object's values, and why something is still in memory, without forcing a
collection. See [the heap reader](heap-reader.md).

## Effects

### What a recording is

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
