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
| `workshop-release-notes.py`, `prepare-workshop.py` and `.ps1`, `upload-workshop.ps1`, `update-workshop.ps1`, `pull-workshop.py`, `workshop-change-notes.py` | 1 each | phobos-ostranauts | **Moved 8 Nov 2026 (0.10.0)**: `steam-publish`, with game adapters for Ostranauts and RimWorld. Differences below |
| `update-constants.py`, `audit-public-history.py` | 1 each | phobos-ostranauts | **Moved 8 Nov 2026 (0.10.0)**: `release constants`, `release history`. Differences below |
| `apicheck.ps1` | 1 | phobos-rimworld (local research tools) | C# assembly metadata reader |
| `Resolve-WrPaths.ps1`, `Resolve-WrGamePath.ps1` | 2 | the two Workers and Resources repositories | Core: path resolution; a Workers and Resources adapter |

## Stays where it is

- Art and asset generators: each is tied to one mod's look. This includes phobos-ostranauts'
  `compose-workshop-cover.py`, which also needs Pillow, outside the kit's standard-library rule.
- phobos-ostranauts' `package-documentation.py`: it packages that repository's own guide layout.
- Each repository's package checks for its Workshop content (for Ostranauts: the `dist/` package, plugin DLLs against
  compiled output, read-only data headers, sounds and translations). They are project policy, passed to
  `steam-publish` as a payload hook.

The owner-run uploader used to be listed here. On 8 November 2026 the owner asked for it to move with the rest.

## Differences from the phobos-ostranauts copies (8 Nov 2026)

Checked read-only against phobos-ostranauts that day: release notes for all 444 entries, due updates, combined change
notes, worksheets, pull findings and its 149 constants all came out the same (see
[Workshop publishing](workshop-publishing.md#checked-8-november-2026)). What changed, and what that repository's
catalogue needs to keep its behaviour when it adopts the kit:

| Area | phobos-ostranauts script | Kit | To keep the old behaviour |
| --- | --- | --- | --- |
| Uploader | PowerShell 7 (`upload-workshop.ps1`, `update-workshop.ps1`, `-Reconcile`) | Python: `steam-publish upload`, `update`, `reconcile`; same rules and receipts | Nothing; old receipts still read |
| Mod names | `Framework` meant `PhobosFramework` by prefix | Any unique ending of a catalogue name | Nothing |
| Mod metadata | `mod_info.json` read inline | Through the Ostranauts adapter, chosen by `appId` | Nothing |
| Package contents | `dist/<Mod>-P0` checked in detail | The `content` folder, or a payload hook | Pass the old checks as the hook |
| Build | `prepare-workshop.ps1 -Build` ran `build-<mod>.ps1` | The catalogue's `build` command, per mod or for all | Set each mod's `build` |
| Staging | `.local/workshop-staging/` | The kit's cache folder, outside cloud sync | `layout.staging` |
| Page and note in the item | Always under `documentation/` | Beside the content; in it only if asked | `layout.textFolder: "documentation"` |
| Changed-content rule | `src/`, `mods/`, `translations/` with a `Phobos` folder | `layout.scope`, default `mods/{mod}/` | `scope` of `src/{mod}/`, `mods/{mod}/`, `translations/{mod}/` |
| Dirty-tree exemptions | `docs/research/`, `docs/development/` fixed | `layout.dirtyExempt`, default none | Set it to those two folders |
| Candidate manifest | Format 2 | Format 3, with the page and note hashed | Prepare fresh candidates |
| Receipts | Visibility in title case (`Public`) | Lower case, as the catalogue names it; both read | Nothing |
| Changelog text | An indented line was refused | Hard-wrapped bullets and paragraphs join, as Markdown reads them; a `## <Name> history` heading after the releases closes the log | Nothing (no Ostranauts changelog changed) |
| Constants: allowed targets | Fixed: `src/`, `mods/`, `docs/`, `config/`, `README.md`, Workshop pages | `targetsUnder` in the catalogue, default anywhere but `.git/` and `.local/` | Set `targetsUnder` to the old list |
| Constants: checks | JSON and `.csproj` parsed after a change | Also `.xml`, `.props`, `.targets`; a pointer to a JSON string now edits inside its quotes (it used to fail) | Nothing |
| History screen | Windows paths; `.dll` to `.key` | Also Linux and macOS home paths, Anthropic keys and `.rws` saves | Nothing |
| Output | Custom text or JSON | The kit's report model, Markdown or `--json` | Callers that parsed the old JSON must change |
- Phobos Scope: a separate project with its own contract.
