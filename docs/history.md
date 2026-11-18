# History: what happened to a game's products over time, and any changelog as it stood

**Status (19 Nov 2026):** built in 1.30.0. D'thorga Companion's Timeline page is its first consumer. Installs, go-backs, backups,
builds and encoded textures are recorded from 19 Nov 2026 on; earlier ones were not recovered (owner's choice).

## Read this first (gotchas)

- **No changelog is lost to time.** git holds every version of every changelog, back to each repository's first commit, so the
  timeline can show any changelog as it stood at any moment, marked by what has happened to each entry since. Nothing new is asked
  of a changelog.
- **Two sources, kept apart.** What the repository did comes from git. What happened on this PC (installed, went back, backed up,
  built, textures encoded) git cannot know, so the tools write it down as it happens, in **the history log**: one JSON line a fact,
  one file a game, in D'thorga Companion's own folder by default (`historyPath`; owner's choice, 19 Nov 2026).
- **The first read of a repository takes a few seconds** (about 4 s for phobos-rimworld's 400 commits). The facts are cached in the
  kit's cache folder, and later reads take only new commits (under a second).
- **It only reads.** Writing to the history log is done by the commands that do the work (installs, rimworld-textures), never by
  this one, and a log that cannot be written never undoes the work it records.
- **Any game, any repository with a changelog.** The core names no game: a game reaches the log only as the name a caller passes.

## Run it

```text
python -m phobos_modkit history timeline --root REPO --game rimworld
python -m phobos_modkit history timeline --root REPO1 --root REPO2 --since 2026-11-01
python -m phobos_modkit history at --root REPO --changelog mods/Thing/CHANGELOG.md --when 2026-11-12T15:00
python -m phobos_modkit history at --root REPO --changelog mods/Thing/CHANGELOG.md --commit 401c6a93
```

Add `--json` for the envelope. With `--game`, the timeline joins the game's history log, keeping only its facts about the
repositories named. `changes entry --commit HASH --changelog PATH` shows the code behind any fact from git (docs/changes.md).

## The facts

Every fact has `kind`, `time` (UTC), `source` (`git` or `log`) and `product`; facts from git add `repository`, `commit`,
`subject` and `changelog`, and most add `version`.

| Kind | From | When |
| --- | --- | --- |
| `product-started` | git | A changelog first appears; `count`, `versions`, `newest` |
| `version-written` | git | A version heading appears; `entries` (up to 8), `count`, `summary`, `heading` |
| `entries-added`, `entries-removed` | git | Entries appear in or leave a version that was already there |
| `entries-reworded` | git | An entry keeps its opening but changes its words; each with `was` and `now` |
| `version-removed` | git | A version heading leaves the changelog |
| `version-released` | git | A version's heading goes from Draft to Released |
| `product-renamed` | git | The changelog's title names another product; `was`, `now` |
| `product-ended` | git | The changelog is removed; `mergedInto` names the product whose changelog took in its history (a `## <name> history` heading added by the same commit), or null |
| `installed`, `went-back`, `backed-up` | log | Written by `installs` (an install through deploy writes `installed` too); `mod`, `version`, `commit`, `backup` |
| `built` | log | Written by `installs build`; `ok`, `exitCode` |
| `encoded` | log | Written by `rimworld-textures encode`; `ok`, `count`, `mods` |

An entry is matched across commits as `installs` matches one across copies: by version and its first words, so a rewording keeps
its identity and a moved entry is neither gained nor lost.

## A changelog as it stood (`history at`)

`data` holds `product`, `commit` (hash, time, author, subject), `stillThere` (whether the repository still has the file), and
`versions`, each with its `entries`. Each entry carries `since`: **kept**, **reworded** (with `now`, its words today) or
**removed**; `since` at the top counts the entries added, reworded and removed since. A removed changelog (a mod merged into
another) can still be read at any commit that had it.

## The history log

`historyPath` (environment `PHOBOS_HISTORY`) names the folder; the file is `<game>.jsonl`. Its default is the `history` folder in
D'thorga Companion's own folder (`%LOCALAPPDATA%\org.phobosdthorga.companion` on Windows). It can be set for every repository in
the central settings file (docs/settings.md). Each line is `{"format": 1, "time", "kind", "game", ...}`; a line that cannot be
read is skipped. The tests point it into a folder of their own, so a test never writes the owner's log.

## Limits

- A fact from git is dated by its commit's author time, not by when it reached the owner's PC.
- Two entries with the same version and first 28 characters cannot be told apart.
- An entry moved from one version to another reads as removed from one and added to the other.
- Installs and the rest before 19 Nov 2026 are not on the timeline: the backups hold copies, but not when they were installed.
