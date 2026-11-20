# The heap reader: looking inside a running game (1.65.0)

**Read this first:**

- **It only reads.** It takes a Windows snapshot of the game, which pauses it for about half a second (431 to 470 ms on a RimWorld
  1.7 colony of 27 million objects, November 2026), then reads the snapshot while the game runs on. Nothing is written to the game.
- **Ask before every snapshot of someone's running game**, and ask them to save first, as for every tool that attaches to a game.
- **A snapshot does not sweep the heap first**, so its counts include garbage the collector has not reclaimed yet. `why` tells the
  two apart: a kind nothing holds is garbage, not a leak.
- **Addresses are good only within one snapshot.** The collector moves objects, so a command line that lists objects opens the first
  one in the same run (`--open`), and a program holds one snapshot (`serve`) while it follows links.
- **A held snapshot costs memory while the game runs on**: Windows copies each page the game changes after it. `serve` lets it go
  after ten minutes (the owner's choice, 20 November 2026), when its input closes, or on `{"op": "release"}`.
- **Windows only**, and only for a game on .NET (CoreCLR) whose install ships its memory-reading library (`mscordaccore.dll`).

## What it answers

| Request | Answer |
| --- | --- |
| `overview` | Every type: its count, bytes and module; free space between objects; every object read, with no limit on how many |
| `kind` | One type's objects, each described in a few words, largest first on request, filtered by a word; `open` opens the first in full |
| `object` | One object with every value it holds: numbers, text, enums by name, structs opened, links to other objects described; .NET's lists, dictionaries and sets opened as their items |
| `holders` | The objects that point to it, and through which field or array slot; whether it is a root; the static field that holds it |
| `path` | One path from a root down to it, starting at the static field on the way when there is one |
| `why` | Paths from roots to a kind's largest objects (up to 2,000 checked), each to a different one; or that nothing holds them |

## Using it

RimWorld's commands are part of [rimworld-perf](rimworld-perf.md):

```text
python -m phobos_modkit rimworld-perf look --label "day 40"        every object by type and by mod; kept beside the gcdump heaps
python -m phobos_modkit rimworld-perf look-kind Verse.Pawn --open   one kind's objects, each described, and the first in full
python -m phobos_modkit rimworld-perf look-why System.Xml.XmlDocument   why a kind is still in memory
python -m phobos_modkit rimworld-perf look-serve                    hold a snapshot; one JSON request a line on standard input
```

`look` keeps its overview as a heap in `rimworld-heaps/`, so `heap-report` reads it again and `heap-compare` sets it beside another
`look` or a gcdump heap (mind that a gcdump forces a collection first and a snapshot does not). `look-serve` is for a program's page
(the manifest's `look-inside` surface): its first line says whether the snapshot was taken, each request may carry an `id` its
answer repeats, and an overview's answer gains who each type belongs to.

## How it works

```mermaid
flowchart LR
  P[Python: heap_reader] -->|run or serve| R[PhobosModKit.Heap]
  R -->|PssCaptureSnapshot| S[Snapshot of the game]
  R -->|loads| D[The game's own mscordaccore.dll]
  D --> S
  R -->|JSON lines| P
```

- **The reader** is `dotnet/PhobosModKit.Heap`, built into the kit's build folder on first use like the assembly reader
  (`dotnet_tools`), or brought ready-built by an installer (`programs bundle`). It uses Microsoft's ClrMD
  ([dotnet/clrmd](https://github.com/microsoft/clrmd), MIT), the kit's one C# package (owner's yes, 20 November 2026).
- **Which memory-reading library it loads.** A program's .NET runtime ships one library that knows its memory layout. The caller
  (a game's adapter) names the install it trusts; the reader refuses a program whose `coreclr.dll` is anywhere else, and loads only
  the library beside it. RimWorld 1.7 ships its own build of .NET (Waylith, Ludeon's engine), whose library is not signed by
  Microsoft, so the signature check is off and the folder check is what stands in for it. This loads the game's own runtime code
  into the reader; it is the one exception to "never execute other authors' code" (`AGENTS.md`, owner's yes, 20 November 2026), and
  never extends to a mod's file.
- **How objects are described** is the game adapter's: a list of field paths (`def.defName`, `nameInt.nickInt`), of which the
  first two the reader finds are shown. RimWorld's are in `games/rimworld/look.py`.
- **Progress** comes as the kit's progress lines on standard error when `PHOBOS_MODKIT_PROGRESS` is set: walking every object takes
  about 12 to 18 s on a large colony; a path from the roots can take a few minutes, and gives up after five.

## Limits

- Structs are opened two levels deep; text is cut at 4,000 characters, descriptions at 120.
- A field Waylith adds at run time (its field injection) shows only where the runtime's own metadata lists it; not yet checked on
  every type.
- Memory outside .NET's heap (textures, the engine's own) is not in a snapshot's answers: rimworld-perf's `watch` sees it.
- **The first real use** (20 November 2026, the owner's colony): 453 MB of XML in 9.8 million objects was live, held through every
  mod's `ModContentPack.patches`, which the game clears after loading and Vanilla Expanded Framework's settings code reads again
  (each read makes the game load every patch file again, and keep it). A finding for phobos-rimworld, recorded there.
