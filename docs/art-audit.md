# Art audit

Every shipped image paired with the record that says how it was made, and every picture a Def or class borrows, so a
stand-in audit is one command.

## Read this first (gotchas)

- **A kind is decided by the record's first statement.** The kind whose pattern matches earliest in the record wins, so a
  generated picture whose record later mentions the stand-in drawing it was made from stays generated. Write a record's
  opening line about how the picture was made.
- **"Borrowed" is judged by names.** A use is borrowed when the picture is not one of ours, or when other users of it share a
  word with its path and this one shares none (a shower trailer drawing the fuel bowser's body). A picture nobody's name
  matches is shared, not borrowed. Code is judged only on whether the picture is ours.
- **The repository says where its images are**, in `config/art-audit.json`. Without that file the tool stops and says so.
- It reads only, caches nothing, and never opens an image: it reads file names and records.

## Run it

```text
python -m phobos_modkit art-audit report --root REPO                    open stand-ins, images without a record, borrowed pictures
python -m phobos_modkit art-audit report --root REPO --all              accepted images and borrowings too, with their reasons
python -m phobos_modkit art-audit report --root REPO --kind code-drawn  every image of one kind (or no-record, unclassified)
python -m phobos_modkit art-audit check --root REPO                     exit 1 when an image has no record
```

`--mod PATTERN` narrows to one mod or folder (wildcards), `--json` gives every image with its records, kind and evidence, and
every use with its status, for a program.

## How an image finds its record

A record is a file beside the image whose name is a name below plus a record suffix (`.record.md`, `.export.json`). The tool
tries, in order, and reads every record it finds, nearest first and Markdown before JSON:

1. the image's own stem (`Tank_Damage_east.png` -> `Tank_Damage_east.record.md`);
2. the name before each underscore, shortest last (`Tank_Damage`, then `Tank`), so a body's facings and masks share one record;
3. the image's folder's name (`Atlas/Atlas.record.md`).

The report says how many images were paired each way.

**Records may be kept out of the shipped folders** (1.104.0, for phobos-rimworld, whose deploy copied every record beside its
image into the game's Mods folder): `records.mirrors` maps a leading folder to the folder its records live in, and the tool
looks in the same place under it as well as beside the image. With `{"mods": "assets/records"}`, `mods/A/Textures/X.png` finds
`assets/records/A/Textures/X.record.md`. Beside the image is looked in first, so a record not yet moved still pairs.
**A tool that writes records asks the kit where**: `artaudit.record_home(path, artaudit.mirrors_of(root))` gives the place for
a file's record (the same place under the first matching mirror, else beside it), and the writer adds its suffix.

## The repository's config: `config/art-audit.json`

| Field | What it holds |
| --- | --- |
| `images` | Globs, from the repository root, for the images to audit |
| `groupBy` | Globs whose last part names an image's or file's group, the mod (`mods/*`); `--mod` matches it |
| `records` | `suffixes` that make a record, and whether records are shared by a name before an underscore (`sharedByPrefix`) or named after the folder (`folderRecord`); both default on. `mirrors` (default none) maps a leading folder to where its records are kept |
| `kinds` | Each kind's `kind`, `label` and regular-expression `patterns`; `listed: true` gives the kind a section of its own (drawn in code) |
| `standIn` | Patterns by which a record calls its own image a stand-in; a generated image so called gets its own section |
| `game` | The game adapter that reads Defs and code (`rimworld`); without it no uses are read |
| `defs`, `code`, `textureFields` | For the adapter: globs for Def XML and source files, and extra field names that hold texture paths |
| `commonWords` | Words too common to show what a picture is of (`phobos`, `vehicles`, `icon`) |
| `accepted` | Images (`image` glob) and borrowings (`texture` glob, optional `owner` glob) accepted as they are, each with its `reason` |

## RimWorld: where uses come from

- **The names a texture answers to**: its path below `Textures` without the extension; that path without a facing (`_north`)
  or mask (`_m`, `_northm`); its folder (for `Graphic_Random`).
- **Defs**: every leaf whose text is one of our images' names, and every texture field (`texPath`, `iconPath`, `uiIconPath`,
  `icon`, any tag ending in TexPath, IconPath or Texture) with a path not ours. A list item with a `key`, `defName` or `label`
  names the part of the Def it belongs to, such as an upgrade node. A sound's `clipPath` is never a picture.
- **Inheritance**: a Def takes the texture fields of its parent (`ParentName`, the repository's Defs only) that it does not
  write itself, outside list items; an abstract parent is reported through its children.
- **Patches**: an operation's value, owned by the first `defName` its xpath names.
- **C#**: literals given to `ContentFinder<Texture2D>.Get`, `GraphicDatabase.Get<...>` or `MaterialPool.MatFrom`, and any
  literal that is one of our images' names, owned by the class.

## Limits

- Defs are read as the repository writes them: other mods' patches are not applied, and a Def that takes its picture from
  another mod's parent is not seen.
- Code is read for literal names; a name put together at run time is not seen.
- Word matching is a heuristic: a word of four letters or more inside another counts as the same word (light, headlights).
  Accept a borrowing the owner keeps, with a reason, rather than renaming things to suit the tool.
