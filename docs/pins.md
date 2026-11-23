# Pins: which version of the kit each repository uses

**Status (19 Nov 2026):** built in 1.38.0, for D'thorga Companion's cross-links (S2): see which repositories lag the kit, and by
what.

## Read this first (gotchas)

- **The pin is what the repository's HEAD records**, not what its checkout holds: an uncommitted move of the pin does not count.
- **What a move would bring is this kit's own changelog, as this checkout has it.** A kit checkout that is itself behind shows less.
- **Only pins of this kit are listed**: a submodule whose pinned commit this kit's history does not hold is left out.
- It reads only. Moving a pin is still an ordinary commit in the repository (`git -C external/phobos-modkit checkout <tag>`).

## Run it

```text
python -m phobos_modkit pins status --root ../phobos-rimworld --root ../phobos-companion
```

Add `--json` for the envelope: `data.pins` holds, for each pin, `repository`, `path`, `commit`, `version`, `kit` (this kit's
version), `behind` (how many versions newer the kit is), `ahead`, and `versions`, newest first, each `{version, heading, entries}`
with each entry's opening.

## Reports and options

<!-- generated: options pins -->
Generated from the command's own parser by `python -m phobos_modkit command-docs --write`: change a help text in the parser, not here.

| Report | What it does | Effect |
| --- | --- | --- |
| `status` | Each repository's pin of this kit, and the versions it lacks. Each repository's pin of this kit; needs the repositories. | reads only |

| Option | Reports | What it does | Default |
| --- | --- | --- | --- |
| `--root VALUE` | all | a repository (repeatable; default: the current folder) |  |

- Every report also takes `--json` (print JSON instead of Markdown) and `--no-redact` (show the home folder instead of ~).
- [Common options](common-options.md) explains `--root`, `--json` and `--no-redact`, which many commands share.
<!-- end generated -->
