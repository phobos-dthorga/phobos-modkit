# command-docs: every command's reports and options, generated into its doc

Each command's doc carries a table of its reports and every option it takes, and the README lists every command, both generated
from the [manifest](manifest.md), so they cannot drift from what the commands accept (an audit had found 33 of 48 commands with
options their doc never mentioned). Every page follows [one template](writing-a-tool-page.md).

## Read this first

- **Change a help text in the command's parser, never in a generated block.** The next `--write` puts the block back as the
  parser says. Everything outside the marks is the doc's own, and is never touched.
- **The gate fails when a block is out of date** (its "command docs" step). After changing a parser, run
  `python -m phobos_modkit command-docs --write` and commit the docs with the code.
- **A new command needs a page written to [the template](writing-a-tool-page.md) and a row in `config/command-docs.json`** naming its doc; the check fails until it has one and the doc
  exists.
- **The kit's own commands only.** A game repository's scripts are not in the manifest. What another repository would need is
  in [Limits](#limits).

## Examples

```text
python -m phobos_modkit command-docs            check: which docs are missing a block or out of date (fails when any is)
python -m phobos_modkit command-docs --write    write them
```

## Reports and options

<!-- generated: options command-docs -->
Generated from the command's own parser by `python -m phobos_modkit command-docs --write`: change a help text in the parser, not here.

Effect: writes, with `--write`. Fails when a block is missing or out of date; with `--write`, writes only the generated blocks in the kit's docs.

| Option | What it does | Default |
| --- | --- | --- |
| `--root VALUE` | the kit's repository (default: the one this copy of the kit is in) |  |
| `--write` | write the blocks that are missing or out of date; without it, only check |  |

- It also takes `--json` (print JSON instead of Markdown) and `--no-redact` (show the home folder instead of ~).
- [Common options](common-options.md) explains `--root`, `--json` and `--no-redact`, which many commands share.
<!-- end generated -->

## Inputs

### The config: `config/command-docs.json`

| Field | What it holds |
| --- | --- |
| `docs` | Each command and the doc that holds its block, relative to the repository |
| `readme` | The file that holds the command index |
| `settingsDoc` | The doc the path line points to |
| `brief` | Options said in one line when every report takes them with the same help |
| `paths` | Options that are paths, read in the settings order |
| `commonDoc` | The page that explains the options many commands share |
| `common` | Those options, in the order the line names them |

## Outputs

### The marks

```markdown
<!-- generated: options rimworld-startup -->
...the reports table, the options table, and a few lines on what they share...
<!-- end generated -->
```

The README's index sits between `<!-- generated: command index -->` and the same end mark. A doc with no block yet gains a
"Reports and options" section at its end (with a heading for each command when one doc holds several, as `crash-dump.md`,
`workshop.md` do); move the block anywhere in the doc afterwards and `--write` keeps it there; the [template](writing-a-tool-page.md) puts it
right after Examples.

### What a block holds

- **Reports**: each report's name, what it does (its parser help, with the manifest's note) and its effect in words (reads only,
  writes, writes with a flag, runs other programs, reads public pages online, only on the owner's own press). A note that most
  reports share is said once under the table.
- **Options**: every option once, with the reports that take it (`all`, `all but ...`, or a list), its help text, and its
  default. A flag that takes a value shows `VALUE` or `N`; names in capitals are given bare, without a flag. `Required`,
  `Repeatable` and the choices are added when the help does not already say so.
- **Shared options**: `--json` and `--no-redact`, which every report takes with the same help, are named in one line instead
  of a row each (`brief` in the config). Where a path option appears (`paths` in the config), a line points to
  [settings](settings.md) for the order a path left out is looked for in.
- **Common options**: a line names the options the block's command shares with many others (`common` in the config) and links to
  [common options](common-options.md) (`commonDoc`), which explains them once.
- **Options that cannot be used together** are named in a line.

The report also lists any option whose help states a default other than its parser's (`(default 25)` beside a default of 40),
and the JSON gives the same under `data.mismatchedDefaults`.

## Limits

- **The block says what the parser says.** A help text that is wrong in the parser is wrong here; one left empty shows an empty
  cell.
- **Which report runs when none is named** is not in the manifest, so the block does not say it; the doc's own text does.
- **What another repository would need** to use it for its own scripts: a manifest of its scripts (each script's argparse parser,
  as the kit's commands declare one), and its own `config/command-docs.json`. The writer and the marks are game-free already.
- **The marks are shared with [doc-tables](doc-tables.md)** (1.107.0, `generated_blocks.py`), which fills a repository's own
  docs with tables of its projects, Harmony patches and mods from its files.
