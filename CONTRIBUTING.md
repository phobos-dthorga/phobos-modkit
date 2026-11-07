# Contributing

Read [AGENTS.md](AGENTS.md) and the [project direction](docs/project-direction.md) first. Keep each change to
one useful tool or one improvement, with its tests.

- **Use hand-written fixtures.** Never commit a real save, log, assembly or another author's file, or an
  excerpt of one.
- **Keep game knowledge in adapters.** Core code never names a game.
- **Never run other authors' code.** Read assemblies through their metadata only.
- **Update `CHANGELOG.md`** in the same commit as the change.

## Run the checks

You need Python 3.10 or newer and Rust from [rustup](https://rustup.rs); the toolchain version is pinned in
`rust-toolchain.toml`. Build outside the repository, so a synced or shared folder does not fill with build output:

```text
export CARGO_TARGET_DIR=~/.cache/phobos-modkit/target          (Windows: %LOCALAPPDATA%\phobos-modkit\target)
export PHOBOS_MODKIT_BUILD=$CARGO_TARGET_DIR
cargo fmt --all -- --check
cargo clippy --locked --all-targets -- -D warnings
cargo test --locked
cargo build --release --locked
PHOBOS_REQUIRE_NATIVE=1 python -W error -m unittest discover -s tests
```

Every one must pass; CI runs the same checks on Windows and Linux. Changing the version means changing
`python/phobos_modkit/__init__.py`, `Cargo.toml` and `Cargo.lock` together (`cargo update --offline --workspace`).

External contributors: fork the repository and open a pull request. By contributing you agree that your work
is released under the [MIT licence](LICENSE).
