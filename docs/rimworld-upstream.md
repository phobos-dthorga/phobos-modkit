# rimworld-upstream: did another author change what we patch?

Built in 1.23.0 (18 November 2026) at the owner's go-ahead. A mod we tie into can change a method our Harmony patch or reflection
depends on; Steam then installs it without asking. This lists those changes on purpose.

## Read this first (gotchas)

- **It matches by type and member name.** A common member name (`Tick`) in a big file can be named by a change to something else,
  and a member another type inherits is matched only on the type that declares it. Read the commit or the diff before acting.
- **updates needs two versions in the archive**: rimworld-archive's snapshot keeps a new one each time a watched file changes.
  A file updated before the first snapshot has nothing to compare. It decompiles both sides with `ilspycmd` (`--decompiler`, or
  `PHOBOS_MODKIT_ILSPYCMD`, or `ilspycmdPath` in the settings file); decompiles are cached by content.
- **pending reads the clones as they are**: bring them up to date with rimworld-sources first. The report names the clone whose
  newest commit is oldest. A commit listed may not be in the Workshop build yet; that is the point.
- It reads only: assemblies through the decompiler, which reads a file without loading it, and the clones through `git log`.

```text
python -m phobos_modkit rimworld-upstream --root REPO --clones DIR             both, for the last 30 days
python -m phobos_modkit rimworld-upstream updates --root REPO --days 90        only the archive's updates
python -m phobos_modkit rimworld-upstream updates --root REPO --file Vehicles.dll
python -m phobos_modkit rimworld-upstream pending --root REPO --clones DIR --days 14
```

## What counts as ours

Every member the C# under `src/` names on another assembly's type: the same scan rimworld-targets checks (Harmony patch attributes,
`AccessTools`, reflection by name, `nameof`), keyed by the type's own name and the member's. Each row names the first line of ours
that depends on it.

## How a change is found

- **updates**: for each archived file whose newest version was kept within `--days`, the newest two versions are decompiled and
  compared declaration by declaration (the code tool's compare, narrowed to our types). A member of ours with a new signature, a
  new body (code or values only, with the lines added and removed) or that was removed is listed. The report names every file it
  compared, so "none" is never an empty run.
- **pending**: for each confirmed repository in the source register with a clone, the C# files that declare one of our types, then
  `git log -p` since `--days` ago with git's own C# hunk headers (`diff=csharp`). A hunk counts for a member when one of its changed
  lines names it, or when its header (the member the change sits in) does, unless a changed line opens a member itself: then
  git's header names the member before it.

First run on the owner's PC (18 November 2026, 184 members, 20 clones, 60 days): 13 commits in Vanilla Expanded Framework and
Vehicle Framework, among them VF-412, the upgrade research check found by hand three days before. A spot check of one ("Progress
bar tweaks") showed a real change inside `CompAdvancedResourceProcessor.PostSpawnSetup`, which a patch of ours targets.
