# crash-dump: what a Windows crash dump says

When a program dies too suddenly to log anything, Windows may leave a minidump (`.dmp`) in `%LOCALAPPDATA%\CrashDumps`. This reads
one without a debugger or symbols; `windows-dumps` asks Windows to keep full dumps of one program.

## Examples

```text
python -m phobos_modkit crash-dump                     the newest dump
python -m phobos_modkit crash-dump --program RimWorld  the newest dump of one program
python -m phobos_modkit crash-dump FILE.dmp            one dump
python -m phobos_modkit windows-dumps --program RimWorld          what Windows does now, and the lines that change it
python -m phobos_modkit windows-dumps --program RimWorld --apply  full dumps of that program only (administrator window)
python -m phobos_modkit windows-dumps --program RimWorld --off    back to Windows' default for it
```

## Reports and options

### `crash-dump`

<!-- generated: options crash-dump -->
Generated from the command's own parser by `python -m phobos_modkit command-docs --write`: change a help text in the parser, not here.

Effect: reads only.

| Option | What it does | Default |
| --- | --- | --- |
| `DUMP` | (optional) the .dmp file (default: the newest in the crash dumps folder) |  |
| `--program VALUE` | with no file named, only this program's dumps, by the start of the file name |  |
| `--folder VALUE` | the crash dumps folder (else PHOBOS_CRASH_DUMPS, else %LOCALAPPDATA%\CrashDumps) |  |
| `--no-names` | do not ask dotnet-dump to name methods, even in a full dump |  |
| `--top N` | rows per table (default 15) | `15` |

- It also takes `--json` (print JSON instead of Markdown) and `--no-redact` (show the home folder instead of ~).
- Names in capitals are given bare, without a flag, in the order shown.
- [Common options](common-options.md) explains `--top`, `--json` and `--no-redact`, which many commands share.
<!-- end generated -->

### `windows-dumps`

<!-- generated: options windows-dumps -->
Generated from the command's own parser by `python -m phobos_modkit command-docs --write`: change a help text in the parser, not here.

Effect: reads only. `--apply` and `--off` write the one registry key for the program named; they need an administrator window.

| Option | What it does | Default |
| --- | --- | --- |
| `--program VALUE` | the program's file name, with or without .exe (RimWorld). Required. |  |
| `--count N` | how many full dumps Windows keeps (default 2) | `2` |
| `--folder VALUE` | where they go (default Windows' own, %LOCALAPPDATA%\CrashDumps) |  |
| `--apply` | ask Windows for full dumps of this program (administrator window) |  |
| `--off` | remove this program's own setting (administrator window) |  |

- It also takes `--json` (print JSON instead of Markdown) and `--no-redact` (show the home folder instead of ~).
- [Common options](common-options.md) explains `--json` and `--no-redact`, which many commands share.
- Only one of `--apply`, `--off` at a time.
<!-- end generated -->

## Outputs

### What crash-dump reports

- The exception, by name and code, and the thread it happened on.
- **A call loop that ran away.** On a stack overflow the failing thread's stack is always in the dump, so a loop shows as the same return addresses at a steady spacing. It says how many times one level repeats and how many calls make up a level.
- **Whether every level holds the same objects.** The same objects mean nothing changed between calls, so the loop could never stop by itself. Objects that change mean it was walking through something, such as a chain or a tree. Saved stack pointers are left out of this comparison, since they change at every level in any loop.
- Which modules the stack's return addresses fall in.

### Full dumps: the methods by name

When the dump holds the program's full memory and the program is .NET, crash-dump asks Microsoft's `dotnet-dump` (installed into
the kit's build folder on first use, which needs the .NET SDK) which method each code address on the failing stack falls in:

- **the loop's return addresses**, for a stack overflow;
- **beyond the loop, outermost first**: the calls that led into it;
- **inside the first level**: where the stack ran out.

Only addresses in code the runtime compiled are asked about, since a game's and its mods' methods all run there. They are
words on the stack that point into code: most are return addresses, but a stale value can appear among them. `--no-names`
skips this. On a small test program's stack overflow (18 November 2026) it named `Recurse` repeating and `Main` beyond it, the same
as .NET's own error output, in about 3 seconds.

- **dotnet-dump stops at the first lookup that fails**, so the addresses are asked in order and, after a failure, the rest are
  asked again without the one that failed.
- **The stack walker itself cannot read an overflowed thread** (`clrstack` printed no frames for it), which is why the addresses
  come from the stack's memory, as for a small dump.
- **A dump .NET writes itself** (createdump, from `DOTNET_DbgEnableMiniDump`) names no failing thread and keeps the stack only in
  the full memory list; crash-dump reads the first thread, where that writer put the failing one.

## Effects

### `crash-dump`

The dump can be read while the owner of the program is doing something else: nothing is written, and no code from the dump is run.

### `windows-dumps`

Windows Error Reporting writes a dump when a program crashes if the key `HKLM\SOFTWARE\Microsoft\Windows\Windows Error
Reporting\LocalDumps` exists; a key under it named after one program sets that program alone ([Microsoft, "Collecting User-Mode
Dumps"](https://learn.microsoft.com/windows/win32/wer/collecting-user-mode-dumps)). `--apply` sets `DumpType` 2 (full) and
`DumpCount` (default 2; Windows deletes the oldest), and `DumpFolder` only when `--folder` is given. **A full dump is as large as
the memory the program used when it crashed**, so the report gives the free space. Writing to that key needs an administrator
window: without one it changes nothing and prints the PowerShell lines instead.

## Limits

The report repeats these.

- **A small dump of a .NET program cannot name the methods.** Their names live in memory the dump left out, and `dotnet-dump` needs that memory too. The addresses prove the shape of the failure, not who caused it.
- **To get the names of a stack overflow, run the program again with its error output sent to a file** (`program.exe 2> errors.txt`): .NET writes the repeating methods there when a stack overflows.
- Addresses are good only for one run. Compare the shape between crashes, never the numbers.
- The format facts follow Microsoft's published minidump structures. It reads 64-bit Windows dumps, and treats addresses from `0x7FF000000000` to `0x7FFF00000000` as code, which is where 64-bit Windows places images and nearby compiled code.
- A loop counts as one at 50 repeats or more, with at least 90% of them at one spacing. A loop shorter than that is reported as no single loop.
