# Textures: does any mod need its textures encoded before the next launch?

**Status (18 Nov 2026):** built in 1.21.0. D'thorga Companion's Mods page shows it; phobos-rimworld's deploy.py uses the same todds
preset from here. Not yet run to encode by the owner.

## Read this first (gotchas)

- **A stale `.dds` shows the old picture.** The game loads a `.dds` instead of the `.png` beside it, without comparing their dates
  (RimWorld 1.7, `Verse.ModContentLoader.ShadowedByDds`, read in a decompile on 18 Nov 2026). When a mod update changes a picture
  after RimSort encoded it, the game keeps showing the old one until it is encoded again.
- **status only reads file names and dates**; about 3 seconds for 342 active mods and 35,000 pictures on the owner's PC.
- **encode writes `.dds` files into the mods' own folders, Workshop ones included** (owner, 18 Nov 2026), with RimSort's own todds
  preset, only for the mods it is named, and never while the game runs. It never deletes anything.
- **Steam dates files when it downloads them**, so a changed picture is newer than its old `.dds`: checked on 18 Nov 2026, the oldest
  file in any of the owner's 265 active Workshop mods was dated 18 Oct 2026, though many of those mods are years old, and files within
  one mod spread over weeks as updates rewrote only what changed.

## Run it

```text
python -m phobos_modkit rimworld-textures status            the mods that need attention
python -m phobos_modkit rimworld-textures status --all      every active mod
python -m phobos_modkit rimworld-textures encode --mod PACKAGE.ID [--mod ...]
```

Paths come from `--settings` (a JSON file with `rimworldPath`, `workshopPath`, `rimworldConfigPath`, `toddsPath`), the environment
(`RIMWORLD_PATH`, `RIMSORT_TODDS` and the others in `paths.py`), or the defaults. `encode` takes package IDs or folder names.

## What is counted

| Kind | Meaning | What happens in game |
| --- | --- | --- |
| Stale | A `.png` newer than its `.dds` by more than two minutes | The old picture shows |
| Never encoded | A `.png` with no `.dds` | The right picture, loaded more slowly, held in more memory |
| Left over | A `.dds` whose `.png` is gone | Still loaded under its name; usually harmless; never touched |

- Only active mods in the game's `Mods` folder and the Workshop folder; never the game's own `Data`.
- Only paths containing `Textures`, as RimSort's preset reads them; names match without regard to letter case.
- The two-minute margin keeps files a download wrote moments apart from counting (agent default).

## Encoding

`todds -f BC1 -af BC7 -on -vf -fs -ss Textures -t -p <mod folder>`: RimSort's "optimized" preset as its source has it
(RimSort/RimSort, `app/utils/todds/wrapper.py`, commit c02f2b3). `-on` re-encodes only pictures newer than their `.dds`, so a mod
in step is left alone. Each mod is checked again afterwards and the report says what is left.
