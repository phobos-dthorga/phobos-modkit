# feeds: small files of data a repository publishes for D'thorga Companion

Built in 1.90.0 (23 November 2026) for D'thorga Companion's going online (phobos-companion `docs/online.md`, S3 and S5), at the
owner's go-ahead. Game-free: a game's knowledge reaches a feed through the kind of file it writes.

## Read this first (gotchas)

- **A feed is a folder with an `index.json`**: the feed's name and title, when it changed, and each file's kind, path, size and
  SHA-256. People write theirs in a repository's `feeds/` folder on its default branch; a nightly run writes its own at the top of
  a results branch (`companion-results`).
- **A file is used only when its size and hash match the index and its kind's check passes.** Otherwise the last good copy is
  kept, and the report says what failed. An unknown kind is skipped, never used.
- **An unchanged answer changes nothing**: `write_file` leaves a file that says the same but for its `volatile` fields (a time it
  was checked), and `index --write` keeps the old `updated` when no file changed, so a nightly run that found nothing new commits
  nothing (the owner's choice: written only when the result changes).
- **Reading is keyless, from GitHub's raw files**, outside the API's 60 calls an hour, and cached for six hours. GitHub keeps its
  own copy of a raw file for a few minutes after a push, so a feed read straight after its commit may still be the one before.

## Use

```text
cd python
python -m phobos_modkit feeds index --folder DIR --name phobos-rimworld --write      write the folder's index
python -m phobos_modkit feeds check --folder DIR                                     for a gate: does the index match?
python -m phobos_modkit feeds read --source phobos-dthorga/phobos-rimworld@companion-results:
python -m phobos_modkit feeds read --root ../../phobos-rimworld --root ..           each one's nightly results, by folder
```

A source is `OWNER/REPO`, then `@BRANCH` (default `HEAD`) and `:FOLDER` (default `feeds`; empty for the top of the branch).
**`--root`** (1.92.0) names a repository on this PC instead: its nightly results (`--results`, default `companion-results`) on
the GitHub repository its `origin` remote names. A repository not on GitHub is listed under `data.offGithub`; one with no results
branch reads as `missing`, which is normal for a repository with no nightly run.

**First nightly run on GitHub (23 Nov 2026, phobos-rimworld, 30 days):** 16 findings in 24 fresh clones in 56 seconds, read back
keyless from `companion-results`.

## Kinds, format 1

| Kind | Where | Checked by |
| --- | --- | --- |
| `upstream-watch` | A JSON file naming its kind: `game`, `checked`, `days`, `findings` (each with `mod`, `commit`, `member`, and `date`, `subject`, `ours`, `repository`, `link` to the commit on GitHub), `clonesRead`, `skipped` | This kit |
| `known-problems` (1.93.0) | A JSON file naming its kind: `game`, `problems` (each with an `id`, its `game`, the `mods` that must all be active, each with `id` and `name`, `what` goes wrong, what to `do`, the day it was `checked`; optionally `gameVersions`, `versions` in words, a `link` to the author's report, and `fixed`, the day it was fixed, after which it is no longer shown) | This kit; `mod-list check --known` reads it |
| `theme` | A JSON file in a `theme` folder | The program that uses it (D'thorga Companion's theme checks) |
| `guide` | A Markdown file in a `guide` folder | The program that uses it (the Companion's Guide checks) |

`sort-rules` comes in a later version, with its own check.

**Known problems are public statements about other authors' mods** (the owner's choice, 23 Nov 2026: "public, facts and links"),
so each one is checked as a report would be before it is published (phobos-modkit `rules/reports.md`): against the author's
newest public source, or the Workshop build where there is none, and its `versions` says what it was checked against and what
was not. Plain facts and what to do; no blame. A repository publishes its own in `feeds/` on its default branch; `feeds read
--root REPO --from published` reads it, and `mod-list check --known` uses the last good copy the kit keeps, with no network.

## The nightly watch

`.github/workflows/nightly-feed.yml` is a reusable workflow: a game repository calls it on a schedule with the kit command that
writes its feed files into `$FEED`. It checks out the results branch (or starts it), runs the command from the kit's `python`
folder, writes and checks the index, and commits and pushes **only when something changed**, never force-pushing. The caller
grants `contents: write` to that job alone; nothing holds a credential. The file's header shows a caller.

**The kit runs at the workflow's own version** (1.90.1), not the caller's pin of it: the caller passes `kit-ref`, the same tag it
calls the workflow at (`uses: …/nightly-feed.yml@v1.91.1` with `kit-ref: v1.91.1`); it is required from 1.91.1. So a
repository whose submodule pins an older kit (phobos-rimworld pinned 1.83.0 on 23 Nov 2026) still gets the nightly tools it calls
for. **Check a workflow with `actionlint` before pushing** (it is on the owner's PC): 1.90.1's named the `runner` context in a
job's `env`, which GitHub refuses before the run starts, and actionlint does not yet know GitHub's newer `job.workflow_sha`, so
that fallback was dropped.

For RimWorld the command is `rimworld-upstream pending --clone-into DIR --feed "$FEED/upstream-watch.json"`: it makes lean clones
straight from the source register (no GitHub API call) and writes its findings as an `upstream-watch` file.

**First real run (23 Nov 2026, the owner's existing clones, 30 days):** 14 findings in 23 clones, among them Vehicle Framework's
VF-412 and VF-414 and Combat Extended's loadout changes, each with a link to its commit.

## The JSON

`read`: `data.feeds[]`, each with `source`, `repository`, `ref`, `path`, `state` (`read`, `missing`, `unreachable`, `refused`),
`feed`, `title`, `updated`, `stale` and `asOf`, and `files[]` with `path`, `kind`, `state` (`new`, `same`, `kept`, `failed`,
`refused`), `why`, `content` (parsed JSON, or the text of a guide entry) and `keptAt` for a kept copy.

## Reports and options

<!-- generated: options feeds -->
Generated from the command's own parser by `python -m phobos_modkit command-docs --write`: change a help text in the parser, not here.

| Report | What it does | Effect |
| --- | --- | --- |
| `index` | The index of a feed folder; written with `--write`. | writes, with `--write` |
| `check` | Whether a feed folder's index matches its files, and each file its kind. | reads only |
| `read` | Each feed from GitHub's raw files, checked, with the last good copy kept. GitHub's raw files, keyless; keeps checked copies in the kit's cache. | reads public pages online |

| Option | Reports | What it does | Default |
| --- | --- | --- | --- |
| `--folder VALUE` | `index`, `check` | the feed folder. Required. |  |
| `--name VALUE` | `index` | the feed's short name (the repository's, usually). Required. |  |
| `--title VALUE` | `index` | the feed's title for people (default: its name) |  |
| `--write` | `index` | write index.json into the folder |  |
| `--source VALUE` | `read` | OWNER/REPO[@REF][:PATH] (repeatable) |  |
| `--root VALUE` | `read` | a repository on this PC: its nightly results, found from its own GitHub remote (repeatable) |  |
| `--results VALUE` | `read` | with `--root`, the results branch (default companion-results) | `companion-results` |
| `--from VALUE` | `read` | with `--root`: the nightly results branch (default), or the feeds/ folder people publish on the default branch. One of `published`, `results`. | `results` |
| `--refresh` | `read` | ask GitHub again even when the last answer is under six hours old |  |
| `--cache VALUE` | `read` | the kit's cache folder (default: the setting, then the temporary folder) |  |

Every report also takes `--json` (print JSON instead of Markdown) and `--no-redact` (show the home folder instead of ~).
<!-- end generated -->
