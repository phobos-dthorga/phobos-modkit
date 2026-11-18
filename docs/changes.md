# Changes: what the changelogs say changed, and the code behind an entry

**Status (19 Nov 2026):** built in 1.24.0. D'thorga Companion's Changes page and its code viewer are its first consumers.

## Read this first (gotchas)

- **Nothing new is asked of a changelog.** An entry's code is the commit that first wrote the entry into its changelog; git finds
  it. This is right wherever a change and its changelog entry go in one commit, which is the rule in the Phobos repositories.
- **One commit may write several entries.** The answer then holds the whole commit and names the other entries; it cannot say
  which lines belong to which. Smaller commits give sharper answers.
- **An entry in no commit yet** shows the uncommitted changes to files git already tracks. New files git has not been told of
  are not shown.
- **It only reads**, with git's optional locks and file watcher off.
- **Any game.** It reads every `CHANGELOG.md` up to three folders deep, skipping dependency and build folders. A repository
  with no changelog file has nothing to list.

## Run it

```text
python -m phobos_modkit changes list --root REPO
python -m phobos_modkit changes list --root REPO --versions 10
python -m phobos_modkit changes entry --root REPO --changelog mods/Thing/CHANGELOG.md --text "Boats float."
python -m phobos_modkit changes entry --root REPO --changelog mods/Thing/CHANGELOG.md --commit 401c6a93
```

`changes pending --root REPO [--root REPO ...]` (1.32.0) lists what each changelog has not released yet: entries with no version
(`unreleased`), and the newest Draft version (`draftVersion`, `draftDate`) with `earlierDrafts`. It reads the files only, never git.

`--commit` (1.30.0) shows one commit's code with every entry it wrote into the changelog, for a fact on the timeline whose
entries may since have been reworded or removed (docs/history.md); the changelog may be one the repository no longer has.

`--text` takes the entry's whole text or its bold opening. Add `--json` for the envelope; a refusal is still an envelope, with
`data.ok` false and `data.refusal` saying why.

## How an entry's commit is found

1. **An entry's commit is the one that last wrote its first line where it stands now** (`git blame`, about 0.1 s for a changelog
   of 4,000 lines; 1.28.0). A line many versions repeat word for word ("Not yet tested in game.") so gets each version's own
   commit. An entry no longer in the changelog (one an installed copy has and the repository dropped) falls back to the oldest
   commit that ever added a line opening that way, from one pass over the history (`git log -p`). `changes list` gives every entry its commit this way, and so does `installs status`, so a program can show
   one "the code behind these" for all the entries one commit wrote.
2. `changes entry` looks the entry up in the changelog as it stands, by its text or its bold opening, and takes its commit from
   the same pass. Only an entry the pass cannot place is searched for by its opening (`git log -S`, openings of 80, 48 and 28
   characters and the bold opening, longest first).
3. That commit's diff is read (`git show`), or `git diff HEAD` when no commit holds the entry.

## What the answer holds (`data`)

| Field | What it holds |
| --- | --- |
| `commit` | `hash`, `time`, `author`, `subject`; null when the entry is in no commit yet. In `changes list`, each entry's `commit` is its hash's first 12 characters, or null |
| `writtenWith` | The other entries the same commit wrote into this changelog, as written |
| `files` | Each file but the changelog itself: `path`, `oldPath` (a rename), `change` (added, changed, removed, renamed), `kind` (code, data, words, other), `language`, `binary`, `additions`, `deletions`, `hunks`, `truncated` |
| `hunks` | `header` (the function or section git names) and `lines`: `kind` (`+`, `-` or a space), `old` and `new` line numbers, `text` |

Files come code first, then data (XML, JSON), then words (Markdown, text), then the rest, each by path. `language` names what a
file is (csharp, lua, xml, python, rust...) so a program can colour it; it is never a colour. At most 600 diff lines are kept for
a file and 8,000 for an answer; a file cut short says `truncated`, and its `additions` and `deletions` still count every line.

## Limits

- A reworded entry is found by its present opening, so it shows the commit that reworded it if the opening itself changed.
- An entry moved in from another file (a merged mod's old changelog) shows the commit that moved it.
- Two entries with the same first 28 characters cannot be told apart.
