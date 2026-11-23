# repos: where each repository stands, and whether GitHub's checks passed

Built in 1.89.0 (23 November 2026) for D'thorga Companion's gate lights (phobos-companion `docs/online.md`, O4), at the owner's
go-ahead. Game-free: any git repository, and GitHub's checks for any whose remote is on GitHub.

## Read this first (gotchas)

- **Keyless: 60 calls an hour from this computer, shared by every tool.** The reader keeps the figure GitHub last gave, so every tool
  sees the same one. An automatic look (`--automatic`) stops at 15 left, keeping them for a press; anything stops at none.
- **An "unchanged" answer still costs a call for a keyless client** (measured on the owner's PC, 23 Nov 2026). Calls are saved by
  asking only when something may have changed: with `--automatic`, a repository is asked again only when its pushed commit moved,
  a run was still going five minutes ago, or a day has passed.
- **When GitHub cannot be reached or asked, the last answer is given with its age**, and the report says so ("as of …").
- **"Not pushed" counts commits on the branch that its remote branch lacks, as git last heard**: it reads the remote branch git
  has, and never fetches.
- **"Changed files" counts tracked files only**, staged or not, so a new file not yet added is not counted.
- **A nightly run older than two days is marked late.** GitHub switches a schedule off after 60 days without activity in a public
  repository; a late run is how that, or a run failing to start, shows.

## Use

```text
cd python
python -m phobos_modkit repos status --root ../../phobos-rimworld --root ..                 local only
python -m phobos_modkit repos status --root ../../phobos-rimworld --root .. --online        and GitHub's checks
python -m phobos_modkit repos status --root ... --online --automatic                        as the Companion's own look
```

## What each light says

| State | Meaning |
| --- | --- |
| passed | Every workflow run for the last pushed commit ended well (success, skipped or neutral) |
| failed | One or more ended in failure, a time-out, a failure to start, or waiting for approval; the report names which |
| running | One is still queued or going |
| cancelled | None failed, but one was cancelled |
| waiting | The newest runs for pushes are for an older commit: none yet for the last push |
| no-push-checks | The repository has runs, but none started by a push |
| none | No runs on GitHub at all |
| not-on-github, no-upstream | The remote is elsewhere, or the branch has none |
| unknown | GitHub could not be asked and there was no earlier answer; `why` says what happened |

## The JSON

`data.repositories[]`: `name`, `root`, `branch`, `upstream`, `remoteBranch`, `github` (`owner/repo`), `pushed`, `ahead`, `behind`,
`changed`, `scheduled`, and with `--online` `checks` (`state`, `runs[]` with `workflow`, `event`, `status`, `conclusion`, `commit`,
`when`, `link`; `stale` and `asOf`, the time of the answer given, when it is an earlier one; `why` when unknown) and `nightly[]` (the
same fields, and `late`). Also `data.allowance` (`remaining`, `size`, `reset`, `seen_at`, `turned`), `asked`, `reused`,
`revalidated` and `limited`.

## Reports and options

<!-- generated: options repos -->
Generated from the command's own parser by `python -m phobos_modkit command-docs --write`: change a help text in the parser, not here.

| Report | What it does | Effect |
| --- | --- | --- |
| `status` | Each repository's commits not pushed, files changed, and GitHub's checks for its last push. Each repository's commits not pushed and files changed; with `--online`, GitHub's checks for its last push (keyless). | reads public pages online, with `--online` |

| Option | Reports | What it does | Default |
| --- | --- | --- | --- |
| `--root VALUE` | all | a repository (repeatable; default: the current folder) |  |
| `--online` | all | also ask GitHub for each last push's checks (keyless) |  |
| `--automatic` | all | a look nobody pressed for: ask GitHub only what may have changed, and keep calls for a press |  |
| `--cache VALUE` | all | the kit's cache folder (default: the setting, then the temporary folder) |  |

- Every report also takes `--json` (print JSON instead of Markdown) and `--no-redact` (show the home folder instead of ~).
- [Common options](common-options.md) explains `--root`, `--cache`, `--json` and `--no-redact`, which many commands share.
<!-- end generated -->
