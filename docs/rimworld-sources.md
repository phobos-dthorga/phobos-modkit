# RimWorld sources: where each tied mod's public source lives

Built in 1.16.0 (18 November 2026), at the owner's request in phobos-rimworld, beside its rule to read a mod's public repository
before decompiling it: "the original source will be so much more rich in what it can offer". A mod's About.xml is a poor guide on
its own: most GitHub links in the owner's tied mods were the Harmony mod's, not their own.

## Read this first

- **A repository counts only when it is checked:** an About.xml in it must name the mod's own package ID. A link to another mod is
  ruled out by that check, so there is no hand-kept list of links to ignore.
- **Unconfirmed is not wrong.** A repository may hold only the source, with no About.xml, or a fork or rename under another package
  ID. The report says which ("its About.xml names X", "no About.xml in it"), for a person to judge.
- **A confirmed repository can still be stale.** The report shows its last push and whether it is archived. Read it at the tag or
  commit matching the build in play, and compare with the installed build when in doubt (`rimworld-archive`).
- **Keyless and slow on purpose.** GitHub allows a client that does not log in 60 API calls an hour and 10 searches a minute.
  Calls are paced, every answer is cached for a week in the kit's cache, and a run that meets the limit says when to run again and
  keeps what it found. It never logs in or sends a token.

## Use

```text
cd python
python -m phobos_modkit rimworld-sources --root ..                  every active mod the project's mods tie into
python -m phobos_modkit rimworld-sources --root .. --write          record the answers in config/source-repos.json
python -m phobos_modkit rimworld-sources --root .. --mod some.id --only-named   one installed mod
python -m phobos_modkit rimworld-sources --root .. --recheck        look again at mods the register already confirmed
python -m phobos_modkit rimworld-sources --root .. --no-search      links only, no GitHub search
```

Which mods: the same tie-ins as [rimworld-archive](rimworld-archive.md), every active mod named in the project's About.xml
(`modDependencies`, `loadAfter`, `forceLoadAfter`) or LoadFolders.xml (`IfModActive`, `IfModActiveAll`), plus any named with `--mod`.

## Where it looks, cheapest first

1. **The mod's About.xml**: its `url` and any GitHub address in it.
2. **Its Workshop page's description**, through the Workshop tool's cache (details are refreshed when an hour old).
3. **A GitHub search** by the mod's name without bracketed tags, with "rimworld", only when neither of the above held a confirmed
   repository. The best three results are checked.

Each candidate is checked by fetching its top-level `About/About.xml` (from raw.githubusercontent.com, outside the API's hourly
count). If that names another mod, the repository is that mod's and is passed over. If there is none, the repository's file list is
read and up to six About.xml files in it are checked, for repositories that hold several mods.

## Clones, and a watch on what they cost

With `--clone-into DIR` (under the root; phobos-rimworld uses `.local/decompiled`), each confirmed repository is kept as a lean
clone, `DIR/<Name>-src`, and the report says what each one and all of them cost, and how much the drive has free.

- **Lean:** the whole commit history (git's partial clone, `--filter=blob:none`) but file contents only for what is checked out,
  and only source and project files are checked out (a sparse checkout: `*.cs`, project files, About.xml, README, licence,
  changelog). Never textures, sounds or binaries. Git LFS downloads are skipped and nothing in a clone is ever run.
- **`--update-clones`** fetches new history and moves forward only when that needs no merge; anything else is left as it was.
- **Nothing is ever deleted by the tool.** While the drive has less than `--floor-gb` free (default 10 GB) or under `--floor-percent` (default 3%), no new clone
  is made; when that happens, or when the clones together pass `--budget-gb` (default 3 GB), the report adds **"Storage needs a
  decision: nothing was deleted"**, with the largest clones and the choices: free space elsewhere, remove some clones (they come back
  with `--clone-into`), keep them on another drive, or change the limits (`--budget-gb`, `--floor-gb`, `--floor-percent`).
- A folder of the same name that is not a clone is left alone and reported.

## The register

With `--write`, the answers go to `config/source-repos.json` under the root, by package ID: the repository, where it was found,
which About.xml confirmed it, its last push, licence and whether it is archived, the candidates passed over with why, and the date
checked. Later runs take confirmed mods from the register without asking GitHub again, unless `--recheck`.
