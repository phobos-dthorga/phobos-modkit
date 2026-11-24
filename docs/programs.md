# Programs: what else the tools use, and the kit's tools ready-built

Written for D'thorga Companion's release audit (owner, 20 November 2026: the Companion is to be released for others): A4 (ship the
compiled tools built) and B7 (each tool says what it needs).

## Read this first

- **`programs status` only looks.** It finds each program on the PATH, in the kit's own folders or where a setting names it, and
  runs none of them. ".NET 10" is read from the folders beside `dotnet`, never by running it.
- **Each program is needed only by what it names.** A PC without Steam, ilspycmd or .NET still runs every other tool.
- **It says how a missing program is fetched, and fetches nothing** (1.118.0). Where a command is known for this system, the
  row carries it: Windows' winget for git, .NET 10 and Steam; `dotnet tool install` for ilspycmd on every system. A program
  that shows the row to a person (D'thorga Companion's setup check) runs it only on their press. Every command starts one of
  `programs.FETCHERS`, which a test holds.
- **`programs bundle` builds**: with Rust's cargo and the .NET 10 SDK, on the PC that makes an installer. It is the one way the
  kit's compiled tools reach another PC ready-built (D'thorga Companion's installer runs it).
- **A ready-built tool is found first**, before any build: in `PHOBOS_MODKIT_TOOLS`, else `tools` beside the kit's package folder.

## Examples

```text
python -m phobos_modkit programs status [--json]
python -m phobos_modkit programs bundle --out C:\full\path\tools [--json]
```

## Reports and options

<!-- generated: options programs -->
Generated from the command's own parser by `python -m phobos_modkit command-docs --write`: change a help text in the parser, not here.

| Report | What it does | Effect |
| --- | --- | --- |
| `status` | Every other program the tools use: here or not, what needs it, where to get it. Looks only: runs none of them. | reads only |
| `bundle` | Build the kit's compiled tools and copy them into one folder, for an installer. Builds the kit's compiled tools with cargo and the .NET SDK, and copies them into the folder named, for an installer. | writes |

| Option | Reports | What it does | Default |
| --- | --- | --- | --- |
| `--out VALUE` | `bundle` | the folder to fill (a full path). Required. |  |

- Every report also takes `--json` (print JSON instead of Markdown) and `--no-redact` (show the home folder instead of ~).
- [Common options](common-options.md) explains `--json` and `--no-redact`, which many commands share.
<!-- end generated -->

## Outputs

### What status lists

| Program | Needed by | Found |
| --- | --- | --- |
| git | Every repository's history | On the PATH |
| The kit's XML indexer (`xml-index`, Rust) | Reading large XML files fast, such as saves | Ready-built, else the kit's build folder (`native.tool_path`) |
| The kit's assembly reader (`PhobosModKit.Assemblies`, C#) | Reading .NET code without running it | Ready-built (`assemblies/`), else the kit's build (`assemblies.ensure_reader`) |
| .NET 10 runtime | Running the assembly, heap and names readers | `dotnet` on the PATH; versions from `shared/Microsoft.NETCore.App` beside it |
| .NET 10 SDK (a row of its own since 1.118.0) | Installing the diagnostics tools, fetching ilspycmd, building the kit's own tools | `dotnet` on the PATH; versions from `sdk` beside it |
| Microsoft's .NET diagnostics tools | Watching a running game's memory and time | The kit's own install (`dotnet_diagnostics.tool_path`) |
| ilspycmd | Another author's code from a `.dll`; comparing builds | `ilspycmdPath` or `PHOBOS_MODKIT_ILSPYCMD`, else the PATH |
| Steam | Game files, adding a game, Workshop reports | Its usual install, or `steamPath` |
| A game's own | Whatever its adapter says | `games/<game>/programs.py`, a `PROGRAMS` list of `programs.Program` (RimWorld: RimSort's todds) |

`--json` gives `data.python`, `data.system` (`windows`, `linux` or `macos`), `data.missing` and `data.programs`, each with `key`,
`name`, `game` (null for the core), `neededBy`, `get`, `here`, `where` and `how`. A lookup that fails is reported on its row, as
not here, with the reason.

Since 1.118.0 each program also has:

| Field | What it is |
| --- | --- |
| `url` | The page to get it from by hand, or null (the kit's own tools come with an installer) |
| `fetch` | The command that fetches it on this system, as a list of words, or null where none is known |
| `fetchHere` | Whether the program that command starts (`winget`, `dotnet`) is on the PATH |
| `after` | The keys of the programs that must be here first (ilspycmd and the diagnostics tools need the SDK) |
| `everyday` | True for what a page most people open needs: git and Steam |

When something a command can fetch is missing, the Markdown report adds **Commands that fetch what is missing**.

### What bundle makes

```text
<out>/xml-index.exe                       built with cargo build --release --locked
<out>/assemblies/PhobosModKit.Assemblies.exe (and its .dll, .deps.json, .runtimeconfig.json)
                                          dotnet publish, framework-dependent: needs the .NET 10 runtime where it runs
<out>/bundle.json                         format, the kit's version and every file; written last
```

A failed build leaves no `bundle.json`, so a half-made folder is never taken for a whole one. The reader is published without
debug files. About 2.5 MB in all (20 November 2026).

## Limits

- Windows is the only platform built and checked so far; the code names programs the same way elsewhere.
- **A fetch command is known for Windows only**, but for ilspycmd: Linux's package managers differ by distribution, so a row
  there gives the page alone. A next system needs one more entry in a program's `fetch` (`"linux"` or `"macos"`), no code.
- winget's package names were read from winget on 25 November 2026 (`Git.Git`, `Microsoft.DotNet.Runtime.10`,
  `Microsoft.DotNet.SDK.10`, `Valve.Steam`); no fetch command has been run by the kit or its tests.
- Whether a program works is not checked, only whether it is there: an old ilspycmd, or a Steam that won't start, still reads
  as here.
