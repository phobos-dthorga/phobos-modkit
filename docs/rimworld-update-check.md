# rimworld-update-check: the game or mods updated; what does it mean for ours?

**One run answers four questions after an update**, for an agent session and for D'thorga Companion's "Since you last played",
where an agent had answered them by hand with five tools.

## Read this first

- **Keep the new builds first** (`rimworld-archive snapshot`; phobos-rimworld's `refresh-mod-list.py` does it): the `temporary` and
  `updates` parts compare what the archive kept, so an update it has not kept is not seen. A full run took 1 min 46 s on the
  owner's game (366 mods), most of it decompiling new builds once; later runs reuse the decompiles.

## Examples

```text
python -m phobos_modkit rimworld-update-check --root REPO                     all four, for updates kept in the last 7 days
python -m phobos_modkit rimworld-update-check --root REPO --since 2026-11-19T10:00:00Z   updates kept since a moment
python -m phobos_modkit rimworld-update-check --root REPO --only names,xml    some of them
```

## Reports and options

<!-- generated: options rimworld-update-check -->
Generated from the command's own parser by `python -m phobos_modkit command-docs --write`: change a help text in the parser, not here.

Effect: runs other programs. Runs ilspycmd on archived assemblies and the kit's assembly reader, reading them, never loading them.

| Option | What it does | Default |
| --- | --- | --- |
| `--root VALUE` | the repository holding our C#, our mods and config/update-check.json | `.` |
| `--only VALUE` | some of names, temporary, updates, xml, by commas (default: all four) |  |
| `--since VALUE` | count updates the archive kept since this moment (ISO, UTC unless it says otherwise) |  |
| `--days N` | without `--since`: the last N days (default 7) | `7` |
| `--game VALUE` | the RimWorld folder (else RIMWORLD_PATH, the settings file, Steam's default) |  |
| `--workshop VALUE` | the Workshop content folder (else RIMWORLD_WORKSHOP_PATH, settings, beside the game) |  |
| `--config VALUE` | the folder holding ModsConfig.xml (else RIMWORLD_CONFIG_PATH, settings, default) |  |
| `--archive VALUE` | the assembly archive (else PHOBOS_ASSEMBLY_ARCHIVE, the settings file, the default) |  |
| `--decompiler VALUE` | ilspycmd (else PHOBOS_MODKIT_ILSPYCMD, ilspycmdPath in the settings file, the PATH) |  |
| `--cache VALUE` | the kit's cache folder |  |
| `--settings VALUE` | a JSON settings file |  |
| `--top N` | rows per table (default 25) | `25` |

- It also takes `--json` (print JSON instead of Markdown) and `--no-redact` (show the home folder instead of ~).
- A path left out is looked for in the order [settings](settings.md) explains: an environment variable, the repository's own settings file, the central settings file, then the default.
- [Common options](common-options.md) explains `--root`, `--game`, `--workshop`, `--config`, `--settings`, `--cache`, `--top`, `--json` and `--no-redact`, which many commands share.
<!-- end generated -->

## Inputs

### What the repository says

`config/update-check.json` in the repository named by `--root` (project policy, so it lives there):

```json
{
  "ourPackageIds": ["Author.*"],
  "targets": {"sources": ["src/**/*.cs"], "assemblies": ["mods/*/1.7/Assemblies/*.dll"], "typeLookups": ["OptionalMods.TypeNamed"]},
  "temporaryPatches": "config/temporary-patches.json"
}
```

The temporary patches file lists, under `patches`, `{"row", "patch", "mod", "file", "members": ["Type.Member"]}`: `mod` and `file`
as the archive names them (`rimworld-archive list`), and a member may end in `.*` for a whole type. An added member counts as a
change (a fix can be a new constructor).

## Outputs

### The four parts

| Part | The question | How | What it cannot say |
| --- | --- | --- | --- |
| `names` | Does every member our C# names by string still exist? | [rimworld-targets](rimworld-targets.md)' check, with the repository's own sources, fresh build and type lookups | Whether the code still behaves |
| `temporary` | Did an update touch the method a temporary patch's fault lives in? | The archive's newest two builds of the file, compared for the members listed | Whether the fault is fixed: a change is a reason to read it |
| `updates` | How big was each update, and what new types did it bring? | Every file the archive kept a new build of in the window, compared whole | What the new types do |
| `xml` | Do our XML patches still find their Defs, and the node inside? | The [Def index](rimworld-defs.md), then the patched-Defs file for what an earlier patch adds | An xpath past the simple form, or a Def selected other than by defName |

### Reading the answers

- **Temporary patches**: `changed` or `removed` means **read whether the fault is fixed** before taking the patch out; `unchanged`
  means the patch stays; `no-update` and `one-build` mean there is nothing new to compare.
- **XML patches** are checked against the Defs as written, before any patch, as the game applies them. A Def a patch adds whole
  (an Add at `Defs`) counts as defined. A node not there as written is looked for in the patched-Defs file (every patch applied),
  when one exists: found there is `patched`, a pass. `node-missing` names how many earlier patches name the Def; the file is only
  as fresh as the last time the game was asked to write it. Conditional, Test and FindMod xpaths are questions, so they are not
  checked; nor are patches inside a FindMod or MayRequire whose mod is not active.

### JSON

`--json` prints the kit's envelope; `data` holds `since`, `parts`, and per part: `names` {found, failing, notChecked, atRunTime,
assemblies}, `temporary` [rows with status and detail], `updates` [rows with added, removed, signatures, bodies, newTypes,
newTypeCount, keptAt], `xml` {checked, skipped, rows, patchedDefs}.

## Effects

It reads only: assemblies are read as metadata or decompiled, never loaded or run.

## Failures and exit codes

**Exit code** is 0 whatever is found, so a program can read the answers; 1 only when the check could not run.
