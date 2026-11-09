# crash-dump: what a Windows crash dump says

When a program dies too suddenly to log anything, Windows may leave a minidump (`.dmp`) in `%LOCALAPPDATA%\CrashDumps`. This reads one without a debugger or symbols.

```text
python -m phobos_modkit crash-dump                     the newest dump
python -m phobos_modkit crash-dump --program RimWorld  the newest dump of one program
python -m phobos_modkit crash-dump FILE.dmp            one dump
```

## What it reports

- The exception, by name and code, and the thread it happened on.
- **A call loop that ran away.** On a stack overflow the failing thread's stack is always in the dump, so a loop shows as the same return addresses at a steady spacing. It says how many times one level repeats and how many calls make up a level.
- **Whether every level holds the same objects.** The same objects mean nothing changed between calls, so the loop could never stop by itself. Objects that change mean it was walking through something, such as a chain or a tree. Saved stack pointers are left out of this comparison, since they change at every level in any loop.
- Which modules the stack's return addresses fall in.

## Limits, which the report repeats

- **A small dump of a .NET program cannot name the methods.** Their names live in memory the dump left out, and `dotnet-dump` needs that memory too. The addresses prove the shape of the failure, not who caused it.
- **To get the names of a stack overflow, run the program again with its error output sent to a file** (`program.exe 2> errors.txt`): .NET writes the repeating methods there when a stack overflows.
- Addresses are good only for one run. Compare the shape between crashes, never the numbers.
- The format facts follow Microsoft's published minidump structures. It reads 64-bit Windows dumps, and treats addresses from `0x7FF000000000` to `0x7FFF00000000` as code, which is where 64-bit Windows places images and nearby compiled code.
- A loop counts as one at 50 repeats or more, with at least 90% of them at one spacing. A loop shorter than that is reported as no single loop.

The dump can be read while the owner of the program is doing something else: nothing is written, and no code from the dump is run.
