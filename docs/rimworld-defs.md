# RimWorld Def index

**Answer first.** `rimworld-defs` answers "which mod defines this?", "which mods patch it?" and "what does it look
like, parents and all?" across every active mod, from a SQLite index of the installed game. Indexing about 340 mods
takes about 8 seconds; later questions take about a third of a second until something changes.

## Read this first (gotchas)

- **Defs are shown as their mods wrote them.** Other mods' patches are not applied, so a Def a patch changes looks
  as its author wrote it. The `who` and `patches` reports list the patches that name it. **`patched NAME` shows it with
  every patch applied, and what the patches changed**, from a file a running game wrote (0.15.0; see below).
- **Patches are matched by the defName in their xpath.** A patch that selects Defs by class, by parent or with `*`
  is in the index (`patches --type`, `sql`) but is not listed under a Def's name.
- **A Def's type is its XML tag.** The game files a mod's subclass tags (such as `AlienRace.ThingDef_AlienRace`)
  with their base type; this index keeps them apart.
- **It rebuilds itself** when ModsConfig.xml, Steam's Workshop manifest (any Workshop update), the game's version
  file or any XML file in the game's Mods folder changes. A Workshop file edited by hand is not noticed: add
  `--rebuild`.
- **The game's files are only read.** The index lives in the kit's cache, under the system's temp folder by default.
- Checked against an install of RimWorld 1.7.5000 with 336 active mods (November 2026).

## Run it

```text
python -m phobos_modkit rimworld-defs                          summary
python -m phobos_modkit rimworld-defs who Gun_Revolver         every definition and every patch naming it
python -m phobos_modkit rimworld-defs show Gun_Revolver        its XML, then each parent up the chain
python -m phobos_modkit rimworld-defs list --type HediffDef --mod "*Medical*"
python -m phobos_modkit rimworld-defs patches --target "Meal*"
python -m phobos_modkit rimworld-defs mods --name "*Framework*"
python -m phobos_modkit rimworld-defs sql "SELECT def_type, COUNT(*) FROM def WHERE wins GROUP BY 1"
```

| Report | What it shows | Its options |
| --- | --- | --- |
| `summary` (the default) | Counts of Defs that load, are replaced, wait for MayRequire or are abstract; Def types; names more than one mod defines, with the one kept; the mods with most Defs; problems | |
| `index` | Indexes the mods again now, then the summary | |
| `mods` | Active mods in load order: package ID, source, Workshop ID, Defs, patch operations, load folders | `--name` |
| `who NAME` | Every definition of a defName or abstract Name, with its fate (kept, replaced by a later mod, abstract parent, MayRequire not met), and every patch whose xpath names it | |
| `show NAME` | The kept definition's XML as its file holds it now, then each ParentName up the chain, each cut at 80 lines unless `--lines` says otherwise (0 for all) | `--type`, `--lines` |
| `list` | Kept Defs by type, mod, name or parent; `--all` adds replaced, abstract and unloaded ones | `--type`, `--mod`, `--name`, `--parent`, `--all` |
| `patches` | Patch operations in load order, with the mods any PatchOperationFindMod around them names | `--target`, `--mod`, `--type`, `--operation` |
| `patched NAME` | The Def with every mod's patches applied (before inheritance), from a patched-Defs file a running game wrote, then a diff against the kept definition as written. A Def only a patch adds says so | `--dump`, `--type`, `--lines` |
| `sql QUERY` | Any query; the index is opened read-only | |

Every report takes `--game`, `--workshop`, `--config` (the folder with ModsConfig.xml), `--cache`, `--settings`,
`--rebuild`, `--top`, `--json` and `--no-redact`. Filters ignore case; `*` and `?` are wildcards, and `_` is an
ordinary character. The folders come from the option, then `RIMWORLD_PATH`, `RIMWORLD_WORKSHOP_PATH` and
`RIMWORLD_CONFIG_PATH`, then the settings file (`rimworldPath`, `workshopPath`, `rimworldConfigPath`), then Steam's
usual place.

## Defs with every patch applied (`patched`, 0.15.0)

The game combines every active mod's XML, applies every patch in load order, reads Defs from the result and lets it go,
so no file on disk holds a Def as patched. A mod can keep that document and write it: phobos-rimworld's D'thorga
Framework does, once, on a developer's request (its settings in dev mode, or its dev action "write patched Defs at the
next start"), to `PhobosPatchedDefs/PatchedDefs.xml` in the RimWorld user folder. The file is a `<Defs>` root with the
game version, the time and the number of active mods as attributes, and every Def node as the patches left it;
inheritance (ParentName) is not applied.

`patched NAME --dump FILE` indexes that file in the cache (again whenever it changes) and shows the Def's XML, then a
unified diff from the definition the game keeps as written (`-` lines) to the patched one (`+` lines). The file may be
named by `--dump`, `RIMWORLD_PATCHED_DEFS` or `rimworldPatchedDefsPath` in the settings file. It holds other authors'
Defs: keep it on the computer that wrote it.

## The game's rules it follows

Summarised in our own words from the RimWorld 1.7 game code (November 2026):

| Rule | Where in the game |
| --- | --- |
| Mods load in ModsConfig.xml's order; `x_steam` is the Workshop copy of a mod also installed locally | ModsConfig, ModLister |
| LoadFolders.xml: the game's version block, else the newest lower one; IfModActive (any), IfModActiveAll (all), IfModNotActive (none). Without it: the root, Common and the newest version folder not above the game's | ModContentPack |
| Two load folders with the same file path: the later-listed folder's file loads, silently | DirectXmlLoader |
| MayRequire: every listed mod active; MayRequireAnyOf: at least one. IDs compared without case or `_steam` | LoadedModManager |
| A later mod's Def replaces an earlier mod's Def of the same type and name; a second one inside one mod is skipped with an error | DefDatabase |
| `Abstract="true"` Defs (in any letter case) never load | DirectXmlToObjectNew |
| Each natural rock ThingDef (not a resource rock) makes `<rock>_Rough` unless it names a naturalTerrain, `<rock>_RoughHewn` unless it names a leaveTerrain, and `<rock>_Smooth` when either is missing; each TerrainTemplateDef makes a carpet per Structure ColorDef. The index adds these as rows marked `implied`, with `made_from` saying what from | TerrainDefGenerator_Stone, TerrainDefGenerator_Carpet |
| A Def with a Name can be a parent when its MayRequire is met; a second one with that Name in the same mod is refused. A child takes its ParentName from the latest mod at or before its own in load order, never from a later mod | XmlInheritance |

`show` follows these parent rules, so the chain it prints is the one the game uses. It does not merge the chain
into one Def; read it bottom up.

## What the index holds

| Table or view | Rows |
| --- | --- |
| `mod` | Each active mod in load order, installed or not, with its folders and counts |
| `def` | Every top-level Def element in the loaded files: type, defName, Name, ParentName, abstract, class, label, MayRequire, whether it loads (`loads`), whether the game keeps it (`wins`), and its file |
| `patch`, `patch_target` | Every patch element with an xpath, and each defName its xpath names |
| `def` rows with `implied` | Defs the game makes in code: stone floors and carpets (333 on the owner's install). Other generators (blueprints, frames, meat, corpses, techprints, mods' own) are not covered |
| `problem` | Active mods not installed, files no load folder loads because another shadows them, and unreadable XML |
| `def_view`, `patch_view` | The same with the mod's name |
| `meta` | Provenance: the game version, file stamps, the local mods' fingerprint, the kit's version |
