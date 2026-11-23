# Third-party notices

No third-party code is copied into this repository. The Rust tools download these crates from crates.io when
they are built, at the versions `Cargo.lock` pins; their licences are as their authors publish them. Nothing
from any game is included.

## Tools installed at run time, not shipped

rimworld-perf installs Microsoft's [dotnet-trace](https://www.nuget.org/packages/dotnet-trace) and
[dotnet-counters](https://www.nuget.org/packages/dotnet-counters) (MIT, part of [dotnet/diagnostics](https://github.com/dotnet/diagnostics))
with `dotnet tool install` into the kit's build folder on first use, and runs them. Nothing of theirs is in this repository.

## The heap reader's package (dotnet/PhobosModKit.Heap)

The kit's one C# package reference (owner's yes, 20 November 2026), restored from NuGet when the reader is built; nothing of it is
in this repository, and an installer's bundle carries the built files.

| Package | Licence | Why it is used |
| --- | --- | --- |
| [Microsoft.Diagnostics.Runtime](https://www.nuget.org/packages/Microsoft.Diagnostics.Runtime) 4.2.751201 (ClrMD, [microsoft/clrmd](https://github.com/microsoft/clrmd)) | MIT | Reads a running .NET program's memory from a snapshot, through the program's own memory-reading library |
| [Microsoft.CodeAnalysis.CSharp](https://www.nuget.org/packages/Microsoft.CodeAnalysis.CSharp) 5.0.0, with Microsoft.CodeAnalysis.Common 5.0.0 (Roslyn, [dotnet/roslyn](https://github.com/dotnet/roslyn)) | MIT | The names reader (1.111.0, read 24 November 2026): reads a C# project's source and says what each name in a file is and where it is declared. Only `dotnet/PhobosModKit.Names` refers to it |

ClrMD brings Microsoft's own packages with it, for fetching symbols and logging: Azure.Core, Azure.Identity, Microsoft.Identity.Client
and its extensions, Microsoft.IdentityModel.Abstractions, Microsoft.Diagnostics.NETCore.Client, Microsoft.Security.AntiSSRF,
System.ClientModel, System.Memory.Data, System.Security.Cryptography.ProtectedData and the Microsoft.Extensions abstractions
(`dotnet list package --include-transitive`, 20 November 2026). Their NuGet pages give the MIT licence; each was not checked
one by one.

## Direct dependencies of xml-index

| Crate | Licence | Why it is used |
| --- | --- | --- |
| [quick-xml](https://crates.io/crates/quick-xml) | MIT | Fast streaming XML reading, so a 300 MB save is read in about a second |
| [rusqlite](https://crates.io/crates/rusqlite) | MIT | Writes the SQLite index |
| [libsqlite3-sys](https://crates.io/crates/libsqlite3-sys), with SQLite bundled | MIT; [SQLite](https://www.sqlite.org/copyright.html) is in the public domain | Builds SQLite into the program, so nothing needs installing |
| [serde](https://crates.io/crates/serde) | MIT OR Apache-2.0 | Reads the schema file into typed structures |
| [toml](https://crates.io/crates/toml) | MIT OR Apache-2.0 | The schema file's format |

## Their dependencies

Checked with `cargo metadata` on 7 November 2026; all permit use and redistribution.

| Licence | Crates |
| --- | --- |
| MIT OR Apache-2.0 | ahash, bitflags, cc, cfg-if, equivalent, fallible-iterator, fallible-streaming-iterator, find-msvc-tools, hashbrown, hashlink, indexmap, once_cell, pkg-config, proc-macro2, quote, serde_core, serde_derive, serde_spanned, shlex, smallvec, syn, toml_datetime, toml_edit, toml_write, vcpkg, version_check |
| MIT | winnow |
| Unlicense OR MIT | memchr |
| (MIT OR Apache-2.0) AND Unicode-3.0 | unicode-ident |
| BSD-2-Clause OR Apache-2.0 OR MIT | zerocopy, zerocopy-derive |
