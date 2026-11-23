# Steam Workshop research

**Answer first.** `steam-workshop` and `rimworld-workshop` show what players have reported about Workshop items
lately: the update date, the versions the author declares, how lively the comments are, the uploader's latest
replies and the newest comments that mention problems. Everything is cached, so asking again within a day costs
no requests.

## Read this first (gotchas)

- **Steam limits quick reads.** Comment requests go about 8 s apart; after a "too many requests" answer (HTTP 429)
  the tool waits 150 s once, then stops and reports what it has. Run it again a few minutes later for the rest.
- **Some items' comments are hidden from visitors who are not signed in**, for example when the uploader's profile
  is private. The report says so, with Steam's reason; read those in the Steam client.
- **Only the uploader's own replies are marked.** Replies by other members of a mod team are not recognised.
- **Few problem mentions does not mean few bugs.** Some authors delete bug reports from their comments.
- **Version tags are the author's statement, not a test.** A mod without the game's tag may still work.
- **Read-only.** Public, keyless Steam pages only: nothing logs in, subscribes, uploads or changes anything.
- **Item pages refuse automated fetches** (an error page or HTTP 429, 9 November 2026), so nothing here reads them: the
  details, collections and comment-render APIs answer freely. A collection's members come from the collections API, not
  from its page.
- Checked against Steam on 7 and 9 November 2026.

## Run it

```text
python -m phobos_modkit rimworld-workshop report "Useful Marks" smashphil.vehicleframework 2023507013
python -m phobos_modkit rimworld-workshop versions        every active Workshop mod's declared versions
python -m phobos_modkit rimworld-workshop comments "Field Tents"
python -m phobos_modkit steam-workshop report <Workshop ID or URL> ...
python -m phobos_modkit rimworld-workshop collection 3497770083 --grep "*hover*"   a collection's items
```

| Report | What it shows | Requests |
| --- | --- | --- |
| `report` (the default) | Per item: updated, versions, subscribers, comments read, comments in the last 90 days, the uploader's last reply, how many comments mention problems; then the newest problem comments and the uploader's latest replies | One for every 100 items' details, then one per item's comments, 8 s apart |
| `details` | Updated, versions, whether the game's version is declared, subscribers | One per 100 items |
| `comments` | One item's cached comments in full, newest first | As `report` for one item |
| `versions` (RimWorld) | Every active Workshop mod that does not declare the game's version, in load order | One per 100 mods: about 10 s for 320 mods |
| `collection` | A Steam collection's items in its order: updated, versions, whether the game's version is declared, and the opening of each description with the BBCode stripped; `--grep` keeps the items whose title or description match | One per 100 collections, then one per 100 items; no comments |
| `sql` | Any query over the cache (tables `item`, `comment`, `collection`, `meta`) | None |

`rimworld-workshop` takes a mod's name (with `*` and `?`), its package ID, its Workshop ID or URL, and looks
names up among the installed Workshop mods; it reads the game's version from ModsConfig.xml and flags comments that
mention it. `steam-workshop` takes IDs or URLs for any game.

| Option | What it does |
| --- | --- |
| `--max-age H` | Hours fetched comments and collections stay fresh (default 24) |
| `--details-max-age H` | Hours fetched details (update date, version tags, subscribers) stay fresh (default 1): one request per 100 items, so an update made since shows |
| `--refresh` | Fetch again even when fresh |
| `--offline` | Use the cache only, never contact Steam |
| `--days N` | How far back "recent" comments go (default 90) |
| `--game-version V` | Also flag comments that mention V |
| `--top`, `--json`, `--cache`, `--no-redact` | As for the other tools |

Problem words: crashes, errors, exceptions, bugs, broken, not working, incompatible, conflicts, red text, freezes,
lag, stutter, abandoned, outdated, no longer, null reference, stuck, corrupt, plus the game's version.

## Where it reads from

| What | Endpoint |
| --- | --- |
| Details | `POST https://api.steampowered.com/ISteamRemoteStorage/GetPublishedFileDetails/v1/` (Valve's public Web API, no key), up to 100 items at once |
| Comments | `POST https://steamcommunity.com/comment/PublishedFile_Public/render/<creator>/<item>/` with `start` and `count`: the markup an item's own comment pages show. The uploader is the commenter whose account number is the creator's SteamID64 less 76561197960265728 |

## Reports and options

### `rimworld-workshop`

<!-- generated: options rimworld-workshop -->
Generated from the command's own parser by `python -m phobos_modkit command-docs --write`: change a help text in the parser, not here.

| Report | What it does | Effect |
| --- | --- | --- |
| `report` | Details and comment research per item. | reads public pages online |
| `details` | Update dates, version tags and subscribers; no comments fetched. | reads public pages online |
| `comments` | One item's comments in full, newest first. | reads public pages online |
| `collection` | A collection's items: versions and the opening of each description; no comments fetched. | reads public pages online |
| `sql` | Any read-only SQL query over the cache. | reads only |
| `versions` | The active Workshop mods' declared versions against the game's (details only, one quick request per 100 mods). | reads public pages online |

| Option | Reports | What it does | Default |
| --- | --- | --- | --- |
| `--max-age N` | all | hours fetched comments and collections stay fresh (default 24) | `24` |
| `--details-max-age N` | all | hours fetched details (update date, versions) stay fresh (default 1) | `1` |
| `--refresh` | all | fetch again even when the cache is fresh |  |
| `--offline` | all | use the cache only; never contact Steam |  |
| `--cache VALUE` | all | where the cache is kept (else PHOBOS_MODKIT_CACHE, settings, the temp folder) |  |
| `--settings VALUE` | all | a JSON settings file with modkitCachePath |  |
| `--days N` | all | how far back 'recent' comments go (default 90) | `90` |
| `--game-version VALUE` | all | also flag comments that mention this version, e.g. 1.7 |  |
| `--top N` | all | rows per table (default 30) | `30` |
| `TARGETS ...` | `report`, `details` | a mod's name, package ID, Workshop ID or URL |  |
| `--game VALUE` | all but `sql`, `versions` | the RimWorld folder (for finding the Workshop folder) |  |
| `--workshop VALUE` | all but `sql`, `versions` | the Workshop content folder, where mods are looked up by name |  |
| `--config VALUE` | all but `sql`, `versions` | the folder holding ModsConfig.xml (for the game's version) |  |
| `TARGETS` | `comments` | a mod's name, package ID, Workshop ID or URL |  |
| `TARGETS ...` | `collection` | a collection's Workshop ID or URL |  |
| `--grep VALUE` | `collection` | keep the items whose title or description matches (\* and ? are wildcards) |  |
| `QUERY` | `sql` | one read-only SQL statement, in quotes |  |
| `--game VALUE` | `versions` | the RimWorld folder |  |
| `--workshop VALUE` | `versions` | the Workshop content folder |  |
| `--config VALUE` | `versions` | the folder holding ModsConfig.xml |  |

- Every report also takes `--json` (print JSON instead of Markdown) and `--no-redact` (show the home folder instead of ~).
- Names in capitals are given bare, without a flag, in the order shown.
- A path left out is looked for in the order [settings](settings.md) explains: an environment variable, the repository's own settings file, the central settings file, then the default.
<!-- end generated -->

### `steam-workshop`

<!-- generated: options steam-workshop -->
Generated from the command's own parser by `python -m phobos_modkit command-docs --write`: change a help text in the parser, not here.

| Report | What it does | Effect |
| --- | --- | --- |
| `report` | Details and comment research per item. | reads public pages online |
| `details` | Update dates, version tags and subscribers; no comments fetched. | reads public pages online |
| `comments` | One item's comments in full, newest first. | reads public pages online |
| `collection` | A collection's items: versions and the opening of each description; no comments fetched. | reads public pages online |
| `sql` | Any read-only SQL query over the cache. | reads only |

| Option | Reports | What it does | Default |
| --- | --- | --- | --- |
| `--max-age N` | all | hours fetched comments and collections stay fresh (default 24) | `24` |
| `--details-max-age N` | all | hours fetched details (update date, versions) stay fresh (default 1) | `1` |
| `--refresh` | all | fetch again even when the cache is fresh |  |
| `--offline` | all | use the cache only; never contact Steam |  |
| `--cache VALUE` | all | where the cache is kept (else PHOBOS_MODKIT_CACHE, settings, the temp folder) |  |
| `--settings VALUE` | all | a JSON settings file with modkitCachePath |  |
| `--days N` | all | how far back 'recent' comments go (default 90) | `90` |
| `--game-version VALUE` | all | also flag comments that mention this version, e.g. 1.7 |  |
| `--top N` | all | rows per table (default 30) | `30` |
| `TARGETS ...` | `report`, `details` | a Workshop item ID or URL |  |
| `TARGETS` | `comments` | a Workshop item ID or URL |  |
| `TARGETS ...` | `collection` | a collection's Workshop ID or URL |  |
| `--grep VALUE` | `collection` | keep the items whose title or description matches (\* and ? are wildcards) |  |
| `QUERY` | `sql` | one read-only SQL statement, in quotes |  |

- Every report also takes `--json` (print JSON instead of Markdown) and `--no-redact` (show the home folder instead of ~).
- Names in capitals are given bare, without a flag, in the order shown.
- A path left out is looked for in the order [settings](settings.md) explains: an environment variable, the repository's own settings file, the central settings file, then the default.
<!-- end generated -->
