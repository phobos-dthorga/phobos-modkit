# rimworld-startup

How long RimWorld takes to start, which mods cost the most, and what changed between launches. It reads the sessions the
[Loading Progress](https://steamcommunity.com/sharedfiles/filedetails/?id=3535481557) mod by ilyvion writes as `StartupImpactSessions/`
beside the game's `Config` folder. **Without that mod there is nothing to read.** It reads only.

```text
python -m phobos_modkit rimworld-startup                         every recorded launch, the costliest mods, the slowest stages
python -m phobos_modkit rimworld-startup compare                 the last two launches
python -m phobos_modkit rimworld-startup compare A B             two launches, by the start of their IDs
python -m phobos_modkit rimworld-startup mod "Combat Extended"   one mod across the launches, and where its time went
```

## Reading it

- **Start-up time varies a lot between launches with the same mods** (what the disk has cached, what else is running). The summary
  gives the range and median over the launches with the newest mod list; trust a difference only when it repeats.
- **A mod's cost is its measured load work on and off the main thread**, as Loading Progress attributes it. It is not everything the
  mod adds to the game: most of a start-up is shared work that no mod is charged for.
- **"Mod list" in the launches table** is the change from the launch before: `same`, or how many mods were added and removed.
- Loading Progress keeps only its last launches, so the history is short.

## Reports and options

<!-- generated: options rimworld-startup -->
Generated from the command's own parser by `python -m phobos_modkit command-docs --write`: change a help text in the parser, not here.

| Report | What it does | Effect |
| --- | --- | --- |
| `summary` | Every launch, the costliest mods and the slowest stages. | reads only |
| `compare` | What changed between two launches. | reads only |
| `mod` | One mod across the launches. | reads only |

| Option | Reports | What it does | Default |
| --- | --- | --- | --- |
| `--sessions VALUE` | all | the StartupImpactSessions folder (else beside the game's Config folder) |  |
| `--config VALUE` | all | the game's Config folder (else RIMWORLD_CONFIG_PATH, the settings file, the default) |  |
| `--settings VALUE` | all | a JSON settings file with rimworldConfigPath |  |
| `--top N` | all | rows per table (default 15) | `15` |
| `FIRST` | `compare` | (optional) the earlier launch, by the start of its ID |  |
| `SECOND` | `compare` | (optional) the later launch, by the start of its ID |  |
| `NAME` | `mod` | a mod's name or package ID; \* and ? are wildcards |  |

- Every report also takes `--json` (print JSON instead of Markdown) and `--no-redact` (show the home folder instead of ~).
- Names in capitals are given bare, without a flag, in the order shown.
- A path left out is looked for in the order [settings](settings.md) explains: an environment variable, the repository's own settings file, the central settings file, then the default.
<!-- end generated -->
