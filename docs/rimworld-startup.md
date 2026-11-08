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
