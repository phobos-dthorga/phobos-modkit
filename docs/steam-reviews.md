# steam-reviews: what players say about a game or its DLC

**Read this first.** It reads Steam's public store and community pages, keyless, and changes nothing. Steam's JSON reviews feed
(`appreviews`) now sends every request to its front page, so this reads what a browser reads: the store's **review histogram** for
how many recommend it, and the game's **community page** for the newest reviews. **A DLC has no review cards on its community
page**, so a DLC gives its own counts alone, and says so. Reviewers' names and profiles are never kept.

    python -m phobos_modkit steam-reviews --app-id 294100                  the game: counts, and the newest reviews
    python -m phobos_modkit steam-reviews --app-id 294100 --match Royalty  the DLC whose name holds the words, else the game

## Why

The owner, 27 Nov 2026, of D'thorga Companion's What players say: "We can still have 'what players say' for the actual vanilla
game itself and the DLCs, it'll just be reviews instead". The Companion shows this for the game's own mods on the Mod list.

## What it reads

| Part | From | Notes |
| --- | --- | --- |
| How many recommend it | `store.steampowered.com/appreviewhistogram/<app>`: monthly since release, and day by day for the last 30 days | All time and the last 30 days, as shares and totals |
| The newest reviews | `steamcommunity.com/app/<app>/homecontent/`, the newest first, ten a page (`--pages`, default 5, at most 10) | Whether each recommends it, hours on record, the day posted, the words (600 characters); the game only |
| Which DLC | `store.steampowered.com/api/appdetails`: the game's own list of DLC, then each one's name | A DLC whose name holds every word of `--match`, the shortest first; names kept in the kit's cache (`steam-reviews/names.json`) for a week |

It waits 0.6 s between requests. A page where data should be ("a page, not data") is a failure, said in words.

## Reports and options

<!-- generated: options steam-reviews -->
Generated from the command's own parser by `python -m phobos_modkit command-docs --write`: change a help text in the parser, not here.

Effect: reads public pages online. Reads Steam's public store and community pages, keyless: review counts and the newest reviews.

| Option | What it does | Default |
| --- | --- | --- |
| `--app-id N` | the game's Steam app ID. Required. |  |
| `--match VALUE` | a DLC of the game whose name holds these words (else the game itself) |  |
| `--pages N` | pages of ten newest reviews to read (default 5, at most 10) | `5` |

- It also takes `--json` (print JSON instead of Markdown) and `--no-redact` (show the home folder instead of ~).
- [Common options](common-options.md) explains `--json` and `--no-redact`, which many commands share.
<!-- end generated -->
