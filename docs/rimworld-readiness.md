# rimworld-readiness

Which active mods are ready for a game version, and which would be likeliest to break if they are not. **It says what a mod declares
and how closely it depends on the game; it does not test whether a mod works.**

```text
python -m phobos_modkit rimworld-readiness                       against the version the game is on now
python -m phobos_modkit rimworld-readiness --game-version 1.8    against another version
python -m phobos_modkit rimworld-readiness --all                 every mod that does not declare it, uncut
python -m phobos_modkit rimworld-readiness --no-save             do not remember this run
```

It reads only: `About.xml`, assemblies opened as files and never loaded or run, and the Steam tags already in the Workshop cache. Run
`rimworld-workshop versions` first to refresh those. The first run builds the same C# metadata reader as `rimworld-patches` and needs the
.NET SDK.

## What each column means

| Column | Read from | What it suggests |
| --- | --- | --- |
| About.xml | The mod's `supportedVersions` | What the author says it runs on |
| Steam tags | The Workshop item's version tags | The same, on Steam; the two can differ |
| Transpilers | The Harmony patch index | It rewrites the game's own instructions, so a new build of the game can break it most easily |
| Prepatcher | A byte scan of its assemblies for the name | It alters types as they load. A byte scan finds the name, and does not prove the mod uses it |
| Asset bundles | An `AssetBundles` folder with a file in it, or a `.bundle` file | Bundles are tied to the engine that built them |

**Riskiest first** is an authored weighting (a transpiler 3, Prepatcher 5, asset bundles 2), to put the likeliest trouble at the top. It is
not a measurement. Each run remembers its result in the kit's cache, per version, and says what changed since the last.

## Reports and options

<!-- generated: options rimworld-readiness -->
Generated from the command's own parser by `python -m phobos_modkit command-docs --write`: change a help text in the parser, not here.

Effect: reads only.

| Option | What it does | Default |
| --- | --- | --- |
| `--game-version VALUE` | the version to check against, like 1.8 (default: the one the game is on) |  |
| `--game VALUE` | the RimWorld folder (else RIMWORLD_PATH, the settings file, Steam's default) |  |
| `--workshop VALUE` | the Workshop content folder (else RIMWORLD_WORKSHOP_PATH, settings, beside the game) |  |
| `--config VALUE` | the folder holding ModsConfig.xml (else RIMWORLD_CONFIG_PATH, settings, default) |  |
| `--cache VALUE` | where indexes are kept (else PHOBOS_MODKIT_CACHE, settings, the temp folder) |  |
| `--settings VALUE` | a JSON settings file with rimworldPath, workshopPath, rimworldConfigPath |  |
| `--top N` | rows per table (default 25) | `25` |
| `--all` | list every mod that does not declare the version |  |
| `--no-save` | do not remember this run |  |

- It also takes `--json` (print JSON instead of Markdown) and `--no-redact` (show the home folder instead of ~).
- A path left out is looked for in the order [settings](settings.md) explains: an environment variable, the repository's own settings file, the central settings file, then the default.
<!-- end generated -->
