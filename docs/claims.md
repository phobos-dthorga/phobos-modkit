# Claims: who is working on what

**Status (19 Nov 2026):** built in 1.44.0, with its rule in `rules/every-session.md`. D'thorga Companion's Home shows the board
from 0.22.0.

## Read this first (gotchas)

- **Take a claim before using a shared version number, test row or file; release it once committed.** Several agent sessions
  share one machine and one set of repositories; the board replaces asking each of them in a message.
- **A thing is its words**, compared ignoring case and spacing: say it the way others will ("phobos-modkit 1.44.0", "phobos-rimworld
  row 237", "D'thorga Framework 0.174.0").
- **A session names itself as other sessions address it** (`phobos-rimworld-11`), so a refused claim tells you whom to ask.
- **Nothing expires by itself.** A claim older than a day is shown as old; `--force` takes it over or lets it go once its session
  has ended or agreed.

## Use

```text
python -m phobos_modkit claims list
python -m phobos_modkit claims take "phobos-modkit 1.44.0" --by phobos-rimworld-11 --note "claims board"
python -m phobos_modkit claims release "phobos-modkit 1.44.0" --by phobos-rimworld-11
python -m phobos_modkit claims release --all --by phobos-rimworld-11
```

`--json` gives the envelope. `list`'s `data.claims` holds each claim's `what`, `by`, `taken` (UTC), `note` when given, `hours` and
`old`; `data.board` is the file. `take` and `release` answer `data.ok`, with `refusal` when refused (exit 3).

## The board

One file, `claims.json` in D'thorga Companion's folder (`claimsPath`, `PHOBOS_CLAIMS`): `{"format": 1, "claims": [...]}`. Every
change holds `claims.json.lock` (made with exclusive create, waited on for up to ten seconds, broken when a crashed run left it more
than a minute old) and writes the board whole through `claims.json.partial`.
