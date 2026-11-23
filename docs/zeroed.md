# Zeroed: files a crash left filled with zeros

Finds files a crash or power cut left at their full size with every byte zero, and puts back the ones git tracks. The owner's
choice: a check to run after a crash, by hand or from D'thorga Companion.

## Read this first

- **Nothing says a file was zeroed until a program trips over it.** A file being written when a PC crashes or loses power can be
  left at its full size with every byte zero: on 23 Nov 2026 two of the kit's version files and a test assembly the kit builds
  were found that way, all written seconds before a crash, and only because the kit's gate failed on them.
- **`check` only reads.** `restore` writes only with `--apply`, and only files git tracks whose last commit holds a real copy.
- **Only files written in the last three days are opened** (`--days N` for more, `--all` for every file, which is slow): a crash
  damages only what it interrupts. Their dates come with the folder listing, so the rest cost almost nothing.
- **Right after a restart it takes about two minutes**, while Windows lists folders it has not cached; a few seconds after that.
- **Some files are all zeros by design** (a placeholder, an empty image). Each found file says where it is, so one can be told
  apart; nothing is changed unless `restore --apply` is asked for, and then only tracked files.
- **Nothing is deleted.** A damaged build is remade by a full rebuild; damage in git's own store is `git fsck`'s to describe.

## Examples

```text
python -m phobos_modkit zeroed check                       every zero-filled file, newest first, what kind it is and what puts it right
python -m phobos_modkit zeroed check --days 14             the same, for files written in the last 14 days
python -m phobos_modkit zeroed check --root PATH           look only in one folder
python -m phobos_modkit zeroed check --games FILE          the repositories another games list names
python -m phobos_modkit zeroed restore                     which zero-filled files git tracks it would write back
python -m phobos_modkit zeroed restore --apply             write the last commit's copy over each of them
```

## Reports and options

<!-- generated: options zeroed -->
Generated from the command's own parser by `python -m phobos_modkit command-docs --write`: change a help text in the parser, not here.

| Report | What it does | Effect |
| --- | --- | --- |
| `check` | Every zero-filled file, what it is and what puts it right. | reads only |
| `restore` | Put zero-filled files git tracks back as the last commit has them; only with `--apply`. | writes, with `--apply` |

| Option | Reports | What it does | Default |
| --- | --- | --- | --- |
| `--root PATH` | all | look only here (again for several). Repeatable. |  |
| `--days N` | all | open files written in the last N days (default 3) | `3` |
| `--all` | all | open every file, however old (slow on large folders) |  |
| `--games FILE` | all | the games list naming the repositories (else the Companion's) |  |
| `--apply` | `restore` | write them back; without it, only say which |  |

- Every report also takes `--json` (print JSON instead of Markdown) and `--no-redact` (show the home folder instead of ~).
- [Common options](common-options.md) explains `--root`, `--json` and `--no-redact`, which many commands share.
- Only one of `--days`, `--all` at a time.
<!-- end generated -->

## Inputs

Without `--root` it looks through every repository on D'thorga Companion's games list (`.git` folders included), the kit's build
folder and the Companion's own data folder.

## Outputs

### What each kind means

| Kind | Where | What puts it right |
| --- | --- | --- |
| tracked | A file git tracks, with a real copy in the last commit | `zeroed restore --apply` (any change since that commit was already lost) |
| committed | A file whose last commit holds the zeros too | An older commit, or a safe copy |
| untracked | In a repository, not in git | A safe copy, or making it again |
| git's own store | Inside `.git` | `git fsck` in that repository |
| built | The kit's build folder | A full rebuild (`--no-incremental` for .NET; a .NET build that thinks it is up to date keeps a damaged file) |
| Companion data | D'thorga Companion's own folder | The Companion's backups, or the safe copies |
