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
| `report` | The report: `format`, `title`, `lines`, `blocks` and `sections` |
| `data` | Anything else the tool offers; empty when it has nothing. `rimworld-save` and `rimworld-defs` give `index` and `built`, `rimworld-log` gives every signature |

Redaction reaches every string in `report` and `data`.

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

- Table cells in `report` are still text, so "12.5%" sorts as text.
- The commands report nothing while they work.
- The manifest describes the kit. A game repository's own scripts are not in it.
