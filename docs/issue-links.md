# issue-links: where a fault in a mod is reported, and the new-issue form filled in

Built in 1.94.0 (23 November 2026) for D'thorga Companion's report links (phobos-companion `docs/online.md`, O4), at the owner's
go-ahead: pre-filled reports to our own repositories; for other authors, their existing issues and their blank new-issue form, on
the Logs page.

## Read this first (gotchas)

- **Nothing here posts anything.** `new` only builds an address; a person opens it in their browser, reads it and presses Submit.
  Drafts to other authors still go through the owner's private tracker (`rules/reports.md`): the Companion offers their blank
  form, not a filled-in one.
- **A text too long for an address goes to the clipboard**: GitHub refuses an address that is too long and names no figure, so
  above 6,000 characters (agent default) the form opens with the title and a line asking to paste.
- **A repository that uses GitHub's issue forms (YAML) may ignore the text**; the title still carries.
- **`issues` costs keyless calls** from the hourly 60 every tool shares: one for each 100 issues, up to three, cached an hour.
  GitHub's own search can miss matches (`rules/reports.md`), so this lists them all and puts those naming every word first.

## Use

```text
cd python
python -m phobos_modkit issue-links where --name RimWorld --root ../../phobos-rimworld --mod "Vehicle Framework"
python -m phobos_modkit issue-links new --repository OWNER/REPO --title "A fault" --body-file report.md --label Bug
python -m phobos_modkit issue-links issues --repository SmashPhil/Vehicle-Framework --words "turret queue"
```

## How `where` decides

| Whose | When |
| --- | --- |
| ours | The mod is installed from a folder named like one of a repository's own mods (`config/installs.json`'s `mods` folder, each with a `CHANGELOG.md`), and that repository's `origin` is on GitHub |
| theirs | A repository's `config/source-repos.json` confirms the mod's public source on GitHub, by its package ID |
| unknown | Neither: no form to open |

**First real run (23 Nov 2026, the owner's PC):** D'thorga Framework ours (phobos-rimworld); Vehicle Framework, Combat Extended
and Adaptive Storage Framework theirs; Dubs Mint Menus unknown.

## The JSON

`where`: `data.mods[]` with `mod`, `id`, `whose`, `repository`. `new`: `data.url` and `data.clipboard` (the text to paste, or
null). `issues`: `data.issues[]` with `number`, `title`, `state`, `updated`, `url`, `matches`, and `limited`, `stale`.
