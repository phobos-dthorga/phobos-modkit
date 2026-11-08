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
