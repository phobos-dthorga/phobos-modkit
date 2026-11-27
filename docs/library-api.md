# Library API: what other repositories may import

**Status (23 Nov 2026, kit 1.108.1):** first written in the docs rewrite, step 4, with the owner's go-ahead, from every
`phobos_modkit` import in phobos-rimworld (`scripts/`, `scripts/art/`, `tests/`; `assets/` has none), D'thorga Companion and
phobos-ostranauts (`scripts/`). Which names are a promise is an **agent choice, open to the owner's revision**: a name is stable
when a consumer's own work (an install, an art tool) depends on it and no command gives the same answer; it is internal when a
command already does, or when only a consumer's test reaches in.

**Answer first.** 52 names are a promise: the `main` of 30 command modules, and 22 library functions and constants. 20 more names
are imported today but are internal: they may change in any release, and each has a way out below. **Changing or removing a stable
name, or a keyword argument a consumer passes to it, raises the major version** (`AGENTS.md`: "An incompatible change raises the
major version and says what consumers must change"). `tests/test_library_api.py` fails when a stable name disappears.

## Read this first (gotchas)

- **Prefer `main(argv)` to a library call.** A command's `main` takes the same words as the command line, and its `--json` gives the
  envelope ([manifest](manifest.md)); its insides may be reworked freely. Import a library name only when no command answers.
- **D'thorga Companion imports nothing.** It runs `python -m phobos_modkit <command> --json` as a process and reads the envelope
  and `manifest --json`. Its promise is the envelope's shape (`"envelope": 1`) and the manifest's (`"manifest": 1`), not any
  Python name. The only Python it imports is `gate.cli.main`, in its own `scripts/check-all.py`.
- **The kit must be on the path first.** A consumer's shim (phobos-rimworld's `scripts/_modkit.py`) adds
  `external/phobos-modkit/python` to `sys.path`; import inside the function that needs it, after the shim runs.
- **A name not on this page is internal**, even if it has no leading underscore.
- **A consumer reads the copy its pin holds.** A stable name removed in a major release reaches a consumer only when it moves its
  pin, and the changelog entry says what to change.

## Stable: command entry points

Every command module's `main(argv=None, ..., out=None)` returns an exit code (0 ok, 1 failed or refused, 2 usage) and writes to
`out` (standard output when `None`). The keyword arguments in the third column are part of the promise: consumers pass them.

| Module (`phobos_modkit.`) | Command | Keywords consumers pass | Used by |
| --- | --- | --- | --- |
| `artaudit_cli.main` | `art-audit` | `out` | rimworld `scripts/art-audit.py` |
| `changes_cli.main` | `changes` | `out` | rimworld `scripts/changes.py` |
| `cleanup_cli.main` | `cleanup` | (argv only) | rimworld `scripts/cleanup.py` |
| `code.cli.main` | `code` | `settings_file`, `out` | rimworld `scripts/query-code.py` |
| `crashdump_cli.main` | `crash-dump` | `out` | rimworld `scripts/crash-dump.py` |
| `doc_tables.main` | `doc-tables` | `out` | rimworld `scripts/doc-tables.py` |
| `gate.cli.main` | `gate` | (argv only) | rimworld and Companion `scripts/check-all.py` |
| `history_cli.main` | `history` | `out` | rimworld `scripts/history.py` |
| `installs_cli.main` | `installs` | `out` | rimworld `scripts/installs.py` |
| `release.cli.main` | `release` | (argv only) | rimworld `scripts/release.py` |
| `safe_copies.main` | `safe-copies` | `out` | rimworld `scripts/safe-copies.py` |
| `settings_cli.main` | `settings` | `out` | rimworld `scripts/settings.py` |
| `steam.publish.cli.main` | `steam-publish` | `root` | rimworld and ostranauts `scripts/workshop.py` |
| `testpass_cli.main` | `test-pass` | `out` | rimworld `scripts/test-pass.py` |
| `windows_dumps.main` | `windows-dumps` | `out` | rimworld `scripts/crash-dump.py` |
| `games.rimworld.archive_cli.main` | `rimworld-archive` | `settings_file`, `out` | rimworld `scripts/assembly-archive.py` |
| `games.rimworld.cli.main` | `rimworld-log` | `settings_file`, `out` | rimworld `scripts/triage-log.py` |
| `games.rimworld.defs_cli.main` | `rimworld-defs` | `settings_file`, `out` | rimworld `scripts/query-defs.py` |
| `games.rimworld.patches_cli.main` | `rimworld-patches` | `settings_file`, `out` | rimworld `scripts/query-patches.py` |
| `games.rimworld.perf_cli.main` | `rimworld-perf` | `settings_file`, `out` | rimworld `scripts/perf.py` |
| `games.rimworld.readiness_cli.main` | `rimworld-readiness` | `settings_file`, `out` | rimworld `scripts/version-readiness.py` |
| `games.rimworld.save_cli.main` | `rimworld-save` | `settings_file`, `out` | rimworld `scripts/query-save.py` |
| `games.rimworld.settings_cli.main` | `rimworld-settings` | `settings_file`, `out` | rimworld `scripts/mod-settings.py` |
| `games.rimworld.sources_cli.main` | `rimworld-sources` | `settings_file`, `out` | rimworld `scripts/source-repos.py` |
| `games.rimworld.startup_cli.main` | `rimworld-startup` | `settings_file`, `out` | rimworld `scripts/startup-impact.py` |
| `games.rimworld.targets_cli.main` | `rimworld-targets` | `settings_file`, `out` | rimworld `scripts/check-targets.py` |
| `games.rimworld.textures_cli.main` | `rimworld-textures` | `out` | rimworld `scripts/textures.py` |
| `games.rimworld.update_check_cli.main` | `rimworld-update-check` | `settings_file`, `out` | rimworld `scripts/update-check.py` |
| `games.rimworld.upstream_cli.main` | `rimworld-upstream` | `settings_file`, `out` | rimworld `scripts/upstream.py` |
| `games.rimworld.workshop_cli.main` | `rimworld-workshop` | `settings_file`, `out`, and its test stand-ins `post`, `pacer`, `clock` | rimworld `scripts/workshop-research.py` |

Every other command's `main` follows the same pattern, but is not listed until a consumer calls it.

## Stable: library names

| Name (`phobos_modkit.`) | Signature | What it does | Used by |
| --- | --- | --- | --- |
| `paths.resolve` | `(key, env_var, default, explicit=None, environ=None, settings_file=None)` | The path for one setting by the one order: argument, environment, the repository's settings file, the central settings file, default; `None` when nothing names one and `default` is `None` | rimworld `scripts/deploy.py` (`local_path`, which every script's paths go through) |
| `paths.central_settings_file` | `(environ=None)` | The central settings file: `PHOBOS_SETTINGS`, else `settings.json` in D'thorga Companion's data folder; it may not exist | rimworld `scripts/art/art_paths.py` |
| `paths.read_settings_file` | `(path)` | A settings file's values as a dict; `{}` when missing or unreadable | rimworld `scripts/art/art_paths.py` |
| `cache.folder` | `(namespace, explicit=None, environ=None, settings_file=None)` | One tool's folder in the kit's cache (`<cache root>/<namespace>`), not created until written | rimworld `scripts/art/edge_check.py`, `scripts/mod-settings.py`, `scripts/reference-site.py` |
| `progress.Progress` | `(environ=None, stream=None)`, then called as `progress(label=None, step=None, of=None, detail=None)` | Writes progress lines to standard error when `PHOBOS_MODKIT_PROGRESS=1`; silent otherwise; thread-safe | rimworld `scripts/deploy.py`, `scripts/reference-site.py` |
| `build_lock.held` | `(root, purpose, name='build', wait_s=900, stale_s=3600, log=None, ...)`, a context manager | Holds the repository's build lock while the block runs; waits for another build, then gives up | rimworld `scripts/deploy.py` |
| `build_lock.BuildBusy` | exception, `(path, holder, waited_s)` | Another build held the lock longer than this one would wait | rimworld `scripts/deploy.py` |
| `installs.load_config` | `(root)` | The repository's `config/installs.json` | rimworld `scripts/deploy.py` |
| `installs.record_for` | `(root, config, mod, version, now=None)` | What an install record says: where the copy came from and when | rimworld `scripts/deploy.py` |
| `installs.write_record` | `(target, record, settings=None, environ=None)` | Writes the record into the installed copy and notes the install in the history log (Companion's Timeline reads both) | rimworld `scripts/deploy.py` |
| `installs.place` | `(root, settings=None, environ=None)` | A `Place`: the repository, its installs config, the game's adapter, the installed-mods folder and the backups folder | rimworld `scripts/deploy.py` |
| `installs.tidy` | `(where, mods, progress=None)` | Removes repeated backups of the mods named, keeping the oldest of each run; returns `(removed, problem)` | rimworld `scripts/deploy.py` |
| `installs.tidy_lines` | `(done, problem)` | A person's lines for what `tidy` did | rimworld `scripts/deploy.py` |
| `games.rimworld.installs.identity` | `(folder)` | `(name, version)` from a mod's `About/About.xml`; empty strings for what it does not say | rimworld `scripts/deploy.py` |
| `games.rimworld.paths.config_path` | `(explicit=None, environ=None, settings_file=None)` | The folder holding `ModsConfig.xml` (setting `rimworldConfigPath`) | rimworld `scripts/query-defs.py`, `scripts/vehicle-bindings.py` |
| `games.rimworld.textures.DEFAULT_TODDS` | constant, a `Path` | RimSort's todds encoder where RimSort installs it on Windows | rimworld `scripts/deploy.py` |
| `games.rimworld.textures.default_todds(environ=None)` | function, a `Path` | Where todds is with no setting naming it (1.145.0): the PATH, then on its own, then RimSort's copy | rimworld `scripts/deploy.py` |
| `games.rimworld.textures.RIMSORT_OPTIMIZED` | constant, a tuple of arguments | RimSort's own todds preset, so our encoding matches RimSort's | rimworld `scripts/deploy.py` |
| `games.rimworld.textures.trim_folder` | `(folder, min_kept=4)` | Shortens the mip chain of every encoded texture under a `Textures` folder in a mod folder | rimworld `scripts/deploy.py` |
| `artaudit.record_home` | `(path, mirrors=None)` | Where a new record for a repository-relative file is written: under the first mirror that matches, else beside it | rimworld `scripts/art/art_paths.py` |
| `doc_tables.settings_reader` | `(game)` | The game adapter's `mod_settings(root, options)`, which reads one mod's settings from its code (key, label, description, default, page, section), or `None` when the game has no reader (1.114.0) | rimworld `scripts/mod-settings.py` (the labels in the settings history) |
| `artaudit.mirrors_of` | `(root)` | The `records.mirrors` of the repository's `config/art-audit.json`; none without a config; a broken config raises | rimworld `scripts/art/art_paths.py` |
| `picks.offer` | `(root, item, grounds=None)` | Adds one waiting pick to `config/picks.json`, or replaces the one with its id; refuses a pick of the other kind under the same id | rimworld `scripts/art/art_picks.py` |

Why these are stable (agent choice): each writes or finds something another program reads back the same way (an install record,
an encoded texture, a record's place, a pick, a setting), and calling a command for it would mean a process per file or per mod
inside an install. `progress.run_streaming(command, cwd=None, env=None, timeout=None, progress=None, popen=None)` is offered to
repositories in [manifest](manifest.md) but nobody imports it yet; it is not listed.

## Internal: imported today, not promised

| Name (`phobos_modkit.`) | Used by | Way out |
| --- | --- | --- |
| `testpass.load_config`, `parse_rows`, `parse_mapping` | rimworld `scripts/deploy.py` (`test_rows_text`, the rows file the Framework's test-moment message reads) | `test-pass report --json` gives `data.rows[]` with `evidence_keys`, but not each key's case and detail wildcard that the rows file holds. **Until a report carries them, this import stays**; a `test-pass rows --json` report would end it (not built) |
| `testpass.mapped_keys`, `map_problems`, `parse_mapping` | rimworld `tests/test_test_evidence.py` | A consumer test of its own evidence map; `test-pass report --json` for what the kit checks |
| `artaudit.load_config`, `audit`, `kinds_of`, `accepted_of`, `NO_RECORD`, `NOT_OURS` | rimworld `tests/test_art_audit.py` | `artaudit_cli.main(['report', '--root', ROOT, '--json'])` and read `data.images[]` and `data.uses[]` |
| `cleanup.load_rules`, `rule_items`, `DAY` | rimworld `tests/test_cleanup.py` | `cleanup_cli.main(['--root', ROOT, '--json'])` and read `data.items[]` and `data.groups[]` |
| `source_clones.existing`, `drive`, `short_of_space`, `BUDGET_BYTES` | rimworld `scripts/source-repos.py` (`watch_line`) | `rimworld-sources` already reports the clones, the budget and the drive's free space in its "Source clones" section; the one-line summary could come from its `--json` |
| `code.scan.declarations`, `ATTRIBUTES` | rimworld `scripts/reference-site.py` | `code outline` over an indexed folder answers per type, but the script parses signatures and single files. **Candidate to become stable** if the owner agrees: the scanner is the kit's own C# reader, and a process per file would be slow |

20 names in all. **phobos-rimworld imports every one of them**; D'thorga Companion and phobos-ostranauts import only stable entry
points. Within phobos-rimworld, `tests/test_art_audit.py` reaches in furthest (six names).

## How a name changes

- **Adding a stable name** is new functionality (the middle number): add it here and to `STABLE` in `tests/test_library_api.py`
  in the same commit.
- **Changing or removing one**, or a keyword argument in the entry-point table, raises the first number, and the changelog says
  what each consumer must change. Moving a name from stable to internal counts as removing it.
- **Internal names change freely.** A release that changes one should still say so in its entry when a consumer is known to import
  it, and the consumer moves to the way out when it next touches that script.

## Limits

- Found by searching for `phobos_modkit` in the consumers' Python on 23 Nov 2026. phobos-kenshi and phobos-log import nothing;
  Phobos Scope had no local checkout to search. A repository that pins the kit later may import more: add it here when it does.
- The test checks that each name exists and that each entry point accepts the keywords listed; it does not check behaviour.
