# Claims: who is working on what

The claims board, with its rule in `rules/every-session.md`. D'thorga Companion's Home shows the board.

## Read this first

- **Take a claim before using a shared version number, test row or file; release it once committed.** Several agent sessions
  share one machine and one set of repositories; the board replaces asking each of them in a message.
- **A thing is its words**, compared ignoring case and spacing: say it the way others will ("phobos-modkit 1.44.0", "phobos-rimworld
  row 237", "D'thorga Framework 0.174.0").
- **A session names itself as other sessions address it** (`phobos-rimworld-11`), so a refused claim tells you whom to ask.
- **Nothing expires by itself.** A claim older than a day is shown as old; `--force` takes it over or lets it go once its session
  has ended or agreed.

## Examples

```text
python -m phobos_modkit claims list
python -m phobos_modkit claims take "phobos-modkit 1.44.0" --by phobos-rimworld-11 --note "claims board"
python -m phobos_modkit claims release "phobos-modkit 1.44.0" --by phobos-rimworld-11
python -m phobos_modkit claims release --all --by phobos-rimworld-11
```

## Reports and options

<!-- generated: options claims -->
Generated from the command's own parser by `python -m phobos_modkit command-docs --write`: change a help text in the parser, not here.

| Report | What it does | Effect |
| --- | --- | --- |
| `list` | Every claim, oldest first, with its age. | reads only |
| `take` | Holds a thing for a session. Adds or refreshes one claim on the board. | writes |
| `release` | Lets a thing go. Removes a session's claims from the board. | writes |

| Option | Reports | What it does | Default |
| --- | --- | --- | --- |
| `WHAT` | `take` | the thing, in a few words ("phobos-modkit 1.44.0") |  |
| `--by VALUE` | `take` | the session, as other sessions address it. Required. |  |
| `--note VALUE` | `take` | what it is for, in a few words |  |
| `--force` | `take` | take over a claim a session left behind |  |
| `WHAT` | `release` | (optional) the thing, as it was taken |  |
| `--by VALUE` | `release` | the session letting go. Required. |  |
| `--all` | `release` | everything the session holds |  |
| `--force` | `release` | let go of a claim another session left behind |  |

- Every report also takes `--json` (print JSON instead of Markdown) and `--no-redact` (show the home folder instead of ~).
- Names in capitals are given bare, without a flag, in the order shown.
- [Common options](common-options.md) explains `--json` and `--no-redact`, which many commands share.
<!-- end generated -->

## Outputs

With `--json` ([common options](common-options.md)), `list`'s `data.claims` holds each claim's `what`, `by`, `taken` (UTC), `note`
when given, `hours` and `old`; `data.board` is the file. `take` and `release` answer `data.ok`, with `refusal` when refused.

## Effects

### The board

One file, `claims.json` in D'thorga Companion's folder (`claimsPath`, `PHOBOS_CLAIMS`): `{"format": 1, "claims": [...]}`. Every
change holds `claims.json.lock` (made with exclusive create, waited on for up to ten seconds, broken when a crashed run left it more
than a minute old) and writes the board whole through `claims.json.partial`.

## Failures and exit codes

- A refused `take` or `release` exits 3.
