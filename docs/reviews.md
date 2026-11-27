# reviews: what the owner has marked as read

**Read this first.** A check that asks the owner to read something keeps asking until it is told the reading is done. This
command keeps that word: one mark per thing, for one build. **A newer build asks again.** Marks live in D'thorga Companion's own
folder, so nothing in a repository changes; the check reads them beside any note the repository keeps itself.

    python -m phobos_modkit reviews list --root REPO
    python -m phobos_modkit reviews mark --root REPO --kind temporary-patch --id "6 (Harrier)" --build 3d9ff12528d1 --note "..."
    python -m phobos_modkit reviews mark --root REPO --kind temporary-patch --id "6 (Harrier)" --clear

## Why

On 27 Nov 2026 the update check kept calling eight of phobos-rimworld's temporary patches `changed`, though the repository had
been rewritten for those very builds the day before. The owner asked to mark them reviewed, which meant an agent editing a JSON
file. D'thorga Companion's **I've read it** now does it on a press, and this command is what it runs.

## What is kept

One JSON line per mark, appended to `reviews/<repository>.jsonl` in the Companion's folder (`companionReviewsPath`,
`PHOBOS_REVIEWS`), as [picks and decisions](owner-queues.md) keep their answers: `format`, `kind`, `id`, `build` (6 to 64
hexadecimal digits, the start of the build's SHA-256), `note` (one line) and `time`. The last line for a kind and id decides;
`--clear` writes a line that takes the mark back.

## Which checks read it

| Kind | The check | What a mark does |
| --- | --- | --- |
| `temporary-patch` | [rimworld-update-check](rimworld-update-check.md)'s temporary patches | A row whose newest build the mark names reads `reviewed` (`reviewedBy: owner`), unless the repository's own `reviewed` note names it first |

A new kind is a word the check that asks chooses; this command knows no game.

## Reports and options

<!-- generated: options reviews -->
Generated from the command's own parser by `python -m phobos_modkit command-docs --write`: change a help text in the parser, not here.

| Report | What it does | Effect |
| --- | --- | --- |
| `list` | Every mark kept for a repository. | reads only |
| `mark` | Marks one thing as read for one build, or takes a mark back. Appends the owner's mark to the Companion's reviews file; nothing in the repository changes. | writes |

| Option | Reports | What it does | Default |
| --- | --- | --- | --- |
| `--root VALUE` | `list` | the repository. Required. |  |
| `--kind VALUE` | `list` | only this kind of mark |  |
| `--root VALUE` | `mark` | the repository the thing belongs to. Required. |  |
| `--kind VALUE` | `mark` | what kind of thing, as the check names it (today: temporary-patch). Required. |  |
| `--id VALUE` | `mark` | the thing, as the check names it. Required. |  |
| `--build VALUE` | `mark` | the start of the SHA-256 of the build that was read, as the check shows it |  |
| `--note VALUE` | `mark` | what was found, in a line |  |
| `--clear` | `mark` | take the mark back instead |  |

- Every report also takes `--json` (print JSON instead of Markdown) and `--no-redact` (show the home folder instead of ~).
- [Common options](common-options.md) explains `--root`, `--json` and `--no-redact`, which many commands share.
<!-- end generated -->
