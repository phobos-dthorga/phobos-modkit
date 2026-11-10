# The tool manifest and the JSON envelope

## Read this first (gotchas)

- **Every command's `--json` prints the same shape** since 1.0.0. Read `report` for what the tool found and `data` for
  anything extra it has.
- **`effect` is declared by hand** beside each command's parser, and a test checks it names real reports. It says what a
  report is for, not what the code proves. A program should still refuse anything marked `owner-only`.
- **`rimworld-log` takes a file name for `--json`**, with `-` for standard output. Every other command takes the flag alone.

## Run it

```text
python -m phobos_modkit manifest           a table of the commands
python -m phobos_modkit manifest --json    the whole description, in the envelope's data
```

## The envelope

```json
{"envelope": 1, "tool": "rimworld-save", "kit_version": "1.0.0", "report": {}, "data": {}}
```

| Field | What it holds |
| --- | --- |
| `envelope` | The shape's version |
| `tool` | The command that made it |
| `kit_version` | The kit that made it |
| `report` | The report: `format`, `title`, `lines`, `blocks` and `sections`. A block's `type` is `text`, `bullets`, `table` (with `values`, the number each cell sorts by), `code`, `chart` or `globe` |
| `data` | Anything else the tool offers; empty when it has nothing. `rimworld-save` and `rimworld-defs` give `index` and `built`, `rimworld-log` gives every signature |

Redaction reaches every string in `report` and `data`.

**A chart block** (1.5.0) pictures numbers the report also states in a table or a line, so a program may draw it and a
reader without it loses nothing. Markdown shows it as text bars, or as a table when a category has several values.

| Field | What it holds |
| --- | --- |
| `kind` | `bar` (one bar per category, running sideways) or `line` (along the categories in order) |
| `title`, `description` | A name, and one sentence saying what it shows, for reading in place of the picture |
| `categories` | The labels along the category axis |
| `series` | Each has `label`, `role` and `values`: one number or null per category |
| `lines` | Reference lines across the value axis, such as thresholds: `label`, `value`, `role` |
| `unit`, `value_label`, `stacked` | The unit after each value (`%`, `ms`), what the value axis measures, and whether series stack |

A `role` says what a series means, never its colour: `accent`, `observed`, `comparison`, `risk`, `success` or `neutral`.
A program colours each role from its own theme.

**A globe block** (1.7.0) is a planet of tiles a program can draw and explore; Markdown says what it holds in one line, and
the report's tables list what it shows. Arrays are objects of `dtype` (`u8`, `u16`, `i32`, `f32`), `count` and `data`
(little-endian bytes in base64).

| Field | What it holds |
| --- | --- |
| `title`, `description`, `tiles` | A name, one sentence, and the number of tiles |
| `positions` | `f32`: x, y, z of each tile's point on the unit sphere. y is up; longitude is atan2(x, -z) and latitude asin(y) of the mean of the tile's corners, as RimWorld reckons them |
| `ring_start`, `ring` | `i32`: each tile's neighbours, `ring[ring_start[t]:ring_start[t + 1]]`, in order round it, anticlockwise seen from outside. A tile's corners are the normalised sums of the tile and each pair of neighbours next to each other in its ring |
| `layers` | One value per tile each: `key`, `label`, `description`, `kind`, `values`, `categories` (`label`, `colour`, `description`), `unit`, `scale`, `offset`, `precision`, `ramp`, `missing`, `missing_label`, `overlay`, `bands` (`label`, `low`, `high`) |
| `places` | `tile`, `label`, `kind`, `group` (which list it belongs in), `role` (as for charts), `detail`, `priority` (higher is labelled first) |
| `lines` | Tile centre to tile centre: `key`, `label`, `description`, `style` (`river` or `road`), `pairs` (`i32`, two tiles a piece), `widths` (`u8`, 1 to 4), `names` and `kinds` (`u16`, an index into names) |
| `tags` | Short notes, several per tile allowed: `key`, `label`, `names`, `tiles` (`i32`) and `tags` (`u16`, an index into names) |
| `labels` | Named regions where the game draws their names: `label`, `kind`, `position` (on the unit sphere) and `size` in tiles |

A layer's `kind` is `categories` (each value indexes `categories`, whose `colour` is the map's own, such as a biome's look),
`measure` (shown value = raw x `scale` + `offset`, in `unit`, coloured by `ramp`: `temperature`, `rainfall`, `elevation`,
`sequential` or `pollution`) or `names` (each value indexes `categories`, shown as text and never as a colour). A raw value
equal to `missing` means nothing is there, and `missing_label` says why (`water`). An `overlay` layer is drawn over the
chosen view, clear where its raw value is 0 or missing. The first `categories` layer is the view to open with.

## The manifest

`data` holds `manifest` (the format's version) and `commands`. Each command has `name`, `summary`, `game` (null for core)
and `reports`. Each report has:

| Field | What it holds |
| --- | --- |
| `name` | The word after the command, or null when the command has no reports of its own |
| `help` | One line on what it does |
| `effect` | One of the effects below |
| `when` | The flag that brings the effect on; null when it always applies |
| `note` | Anything else a caller should know, or null |
| `question` | The report as a person would ask for it, or null |
| `surface` | What the report mostly is, when a program should give it a page of its own: `globe` (1.7.0), or null |
| `options` | `name`, `positional`, `kind` (`flag`, `integer`, `number` or `text`), `required`, `repeatable`, `choices`, `default` and `help`, read from the command's own parser |
| `exclusive` | Groups of options that cannot be used together |

| Effect | Meaning |
| --- | --- |
| `reads` | Reads only. It may keep derived data in the kit's cache |
| `reads-online` | Also reads public pages, slowly and with a cache |
| `writes` | Changes files outside the kit's cache |
| `runs` | Builds and runs a repository's own code |
| `owner-only` | Only the owner runs it, in their own console. Never a program or an agent |

## Adding a command

Add it to `python/phobos_modkit/commands.py`, and give its module a `MANIFEST` beside its parser:

```python
MANIFEST = {"game": "rimworld", "parser": _parser, "effect": READS,
            "reports": {"snapshot": {"effect": WRITES, "note": "writes the snapshot file you name"}}}
```

`tests/test_manifest.py` fails if a command has no manifest, an effect is unknown, or a report named there does not exist.

## Limits

- A table's `values` give the number each cell sorts by, read from its text: `null` for every cell in a column that isn't all numbers
  in one unit. A table's cells themselves stay as written.
- The commands report nothing while they work.
- The manifest describes the kit. A game repository's own scripts are not in it.
