# cleanup: what the tools, builds and tests left behind

Lists what the kit's tools and a repository's builds and tests have left lying about, with the size and the reason
each may go. **It deletes nothing unless you add `--apply`.**

```text
python -m phobos_modkit cleanup --root REPO              list what would go (a preview)
python -m phobos_modkit cleanup --root REPO --apply      delete it, and stop git's file-watcher daemons
python -m phobos_modkit cleanup --root REPO --keep-build leave the kit's development build alone
```

## What it clears

| Source | What goes | Why it is safe |
| --- | --- | --- |
| The kit's cache (`PHOBOS_MODKIT_CACHE`, settings `modkitCachePath`, else `<temp>/phobos-modkit`) | A file a tool says is stale (a save index whose save has been saved again or has gone); anything unchanged for `--older-than` days (default 14); a frozen copy over an hour old | Derived data: each tool rebuilds what it needs on its next run |
| The kit's build folder (`PHOBOS_MODKIT_BUILD`, else `%LOCALAPPDATA%\phobos-modkit\target`) | The `debug` profile only | Only the kit's own tests and development builds use it. **The `release` programs the tools run are never touched** |
| A repository's `config/cleanup.json` | Direct children of each rule's folder that match its patterns | The repository says what its scripts and tests leave, and why |
| Git's file-watcher daemons (Windows) | Stopped on `--apply` | Only a cache: git starts one again when a repository needs it |

**Never touched:** saves, game and mod folders, settings files, the Workshop cache (its pages are fetched slowly, paced
for Steam), and anything no rule matches.

**Under a running build:** when `cargo` or `rustc` is running, the build folder is left alone, and the report says so.

## A tool's cache policy

A command module may declare `CACHE_POLICIES`, a list of dicts for its folders in the cache:

- `folder`: the folder's name in the cache.
- `stale`: a function `(path, environ, settings_file)` returning why one file is no longer any use, or `None`. The
  save index uses this: an index whose save has been saved again would be rebuilt at the next question anyway.
- `keep`: a reason the folder is never cleared.

A folder with no policy follows the age rule alone.

## A repository's rules: config/cleanup.json

```json
{
  "schemaVersion": 1,
  "rules": [
    {"name": "Install backups", "folder": ".local/deploy-backups", "match": ["*-*-*"], "kinds": "folders",
     "group": "^(?P<group>.+)-\\d{8}-\\d{6}$", "order": "name", "keepNewest": 1,
     "liveGroups": "mods/{group}/About/About.xml", "why": "the install each deploy replaced"},
    {"name": "Build logs", "folder": "{temp}", "match": ["Microsoft.NET.Workload_*.log"], "kinds": "files",
     "olderThanDays": 1, "why": "a log the .NET tools write at every build"}
  ]
}
```

| Field | Meaning |
| --- | --- |
| `name`, `why` | Shown in the report. Required |
| `folder` | Relative to the repository, or absolute; `{temp}` is the system's temporary folder and `{env:NAME}` an environment variable. A rule naming an unset variable is skipped. A drive or the home folder itself is refused |
| `match` | Name patterns (`*` and `?`). Only direct children of the folder are matched, never anything deeper. A pattern of only wildcards is refused |
| `kinds` | `files`, `folders` or `any` (the default) |
| `olderThanDays` | Leave anything younger than this |
| `keepNewest` | Keep this many of each group, newest first |
| `order` | `name` to sort by name (names ending in a timestamp), else by time modified |
| `group` | A regular expression with a `(?P<group>...)` part, to keep the newest of each group separately. Names it does not match are left alone |
| `liveGroups` | A path with `{group}` in it: a group whose path no longer exists keeps none |

## Output

The Markdown summary groups what would go, with counts, sizes and reasons, then the largest items. `--json` prints the
report envelope with every item's group, path, bytes and reason under `data.items`. The exit code is 1 when something
could not be deleted (usually a file another program holds open: run it again later).
