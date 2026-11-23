# Writing a tool page: one template for every command's doc

Every command's page (`docs/<name>.md`, named in `config/command-docs.json`) follows one order, so a reader finds the same thing
in the same place on every page. New tools follow it; [command-docs](command-docs.md) writes the one part that is generated.

## Read this first

- **Leave out a heading that would be empty**; never add one to say "none". The order of the rest stays as below.
- **No version numbers or dates in headings** ("Sorting", never "Sorting (1.74.0)"), **and no "Status (date): built in X"
  lines**: what each version delivered is in `CHANGELOG.md`, and `changes` finds an entry's code. A version stays in the text
  only where it is a fact a reader needs ("parameter names come from the reader from 1.10.0 on").
- **The Reports and options block is generated**: change a help text in the command's parser, never the block.
- **Deeper detail goes in `###` subsections** under the heading it belongs to: a config file's fields under Inputs, what each
  status means under Outputs.

## The headings, in order

| Heading | What goes there |
| --- | --- |
| `# <Command>: <what it answers>`, then two lines | What the tool is for, and who reads its answers (a person, an agent, D'thorga Companion's page) |
| `## Read this first` | The gotchas: what a reader gets wrong without being told. One bullet each, opening in bold |
| `## Examples` | A `text` block of command lines, each with a few words on what it answers |
| `## Reports and options` | The generated block, between its marks: every report with its effect, every option, and the shared options' line |
| `## Inputs` | What it reads: the files and folders, a repository's config file and its fields, how things are found and matched |
| `## Outputs` | What the Markdown summary shows, and the JSON envelope's `data` fields |
| `## Effects` | What it reads, writes (and only when), runs, or fetches online; what it never touches |
| `## Failures and exit codes` | The exit codes, and the failures a reader will meet with what to do about each |
| `## Limits` | What it cannot know or do, and what a next game would need |

## A page with several commands

`crash-dump.md` (with `windows-dumps`) and `workshop.md` (`rimworld-workshop`, `steam-workshop`) hold two commands each. The
order is followed once; under Reports and options each command has its own `###` heading and block, and a section that differs
between them has a `###` for each.

## The options every command shares

`--root`, `--game`, `--top`, `--json`, `--no-redact` and the other shared options are explained once, in
[common options](common-options.md), which each generated block links to. A page says only what is particular to its command.
