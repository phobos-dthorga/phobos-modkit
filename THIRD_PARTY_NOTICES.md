# Third-party notices

No third-party code is copied into this repository. The Rust tools download these crates from crates.io when
they are built, at the versions `Cargo.lock` pins; their licences are as their authors publish them. Nothing
from any game is included.

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
