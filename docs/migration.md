# Migration: copied scripts and where they go (7 Nov 2026)

**Answer first.** The Phobos game repositories carry several copies of the same scripts, and most copies have
drifted apart. Each one moves here when its repository next touches it; nothing moves in a sweep.

**Rules for each move**

- Keep the best-tested copy's behaviour, and list what the other copies did differently.
- Game-specific rules stay behind in the game repository as data the shared code reads.
- The game repository's old script becomes a thin caller, then goes once nothing calls it.

## Copies found

Found on 7 Nov 2026 in the owner's local clones; where copies are called identical or different, file checksums were compared.

| Script | Copies | Where | Destination |
| --- | --- | --- | --- |
| `check-doc-links.py` | 3: two identical, one larger | phobos-rimworld, phobos-ostranauts, a private Kenshi repository | Core: documents |
| `check-mod-layout.py` | 3, all different | phobos-rimworld, phobos-ostranauts, a private Kenshi repository | Core: a layout checker; each game's rules stay as data |
| `deploy.py` | 2, different | phobos-rimworld, a private Kenshi repository | Core: the install pattern; game paths through adapters |
| `generate_changelog.py` | 6: five identical | every Project Zomboid repository | Core: changelog tooling |
| `generate_manifest.py`, `bump-version.sh` | several | Project Zomboid repositories | Core: version tooling, with Ostranauts' constants updater |
| `package_mod.py`, `package_set.py`, `validate_mod.py` | 3 or 4 each, different | FS25 repositories | Core packaging; FS25's checks become an adapter |
| `triage_log.py`, `measure_log.py` | 1 each | FS25_PhobosLib, FS25_BgaExtensions | Core log triage plus an FS25 adapter |
| `pull-workshop.py`, `workshop-release-notes.py`, `update-constants.py` | 1 each | phobos-ostranauts | Core: Steam and release tooling. `phobos_modkit.steam.workshop` now reads item details the same way, so `pull-workshop.py` can call it when next touched |
| `apicheck.ps1` | 1 | phobos-rimworld (local research tools) | C# assembly metadata reader |
| `Resolve-WrPaths.ps1`, `Resolve-WrGamePath.ps1` | 2 | the two Workers and Resources repositories | Core: path resolution; a Workers and Resources adapter |

## Stays where it is

- Owner-run Steam upload scripts (`upload-workshop.ps1` and its kin): they handle the owner's own login and
  stay with the repository that publishes.
- Art and asset generators: each is tied to one mod's look.
- Phobos Scope: a separate project with its own contract.
