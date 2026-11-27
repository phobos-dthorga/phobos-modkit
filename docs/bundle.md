# Bundle: a script and its kit modules as one file

`bundle` writes a script that imports from `phobos_modkit` as one file that runs with Python alone, for people who do not have the
kit: a modder downloading a checker, for example. It is read by the person who makes the file and by a repository's gate or test
(`--check`).

## Read this first

- **The script and the kit modules are copied in unchanged**, as text at the top of the file, and set up before the script's own
  imports run. A bug in the bundled file is a bug in the script or the kit: fix it there and bundle again, never in the file.
- **The same script and kit give the same bytes**, whatever the folder, the clock, the commit or the line endings of the checkout
  (the shared rule `rules/builds.md`). Only the kit's version and the modules' names go in, so a new kit version changes the
  header line even when no bundled module changed.
- **A bundled module may import only the standard library and other kit modules**, at any depth (imports inside functions are
  followed too), and may take nothing from a package's `__init__` except `phobos_modkit.__version__`. Anything else is refused,
  with the module and line.
- **`--python` is the oldest Python the file promises**, and every module's syntax is checked against it. A library call that is
  newer than that (a keyword argument added later, say) is not caught: run the bundled file once on that Python.
- **Run the bundled file as a program.** It puts its modules in `sys.modules` under their real names, replacing a kit already
  imported in the same process.
- **The script decides how it finds the kit when it is not bundled.** phobos-rimworld's checker asks its shim only when
  `phobos_modkit` is not imported yet, which a bundled copy has done: `if 'phobos_modkit' not in sys.modules: ...`.

## Examples

```text
python -m phobos_modkit bundle ../../../scripts/check-vehicle-schemas.py --python 3.9 --out K:/dist/check-vehicle-schemas.py
python -m phobos_modkit bundle SCRIPT --check FILE --python 3.9    is FILE what bundling gives now? exit 1 when not
python -m phobos_modkit bundle SCRIPT --out FILE --json            the modules, lines and sha256 for a program
```

## Reports and options

<!-- generated: options bundle -->
Generated from the command's own parser by `python -m phobos_modkit command-docs --write`: change a help text in the parser, not here.

Effect: writes, with `--out`. Fails when the script cannot be bundled, or with `--check` when the file differs; with `--out`, writes only that file.

| Option | What it does | Default |
| --- | --- | --- |
| `SCRIPT` | the script to bundle: it imports what it needs from phobos_modkit |  |
| `--out FILE` | write the bundled file here |  |
| `--check FILE` | only compare FILE with what bundling gives now; exit 1 when it differs |  |
| `--python VALUE` | the oldest Python the file promises, such as 3.9 (default 3.10) | `3.10` |

- It also takes `--json` (print JSON instead of Markdown) and `--no-redact` (show the home folder instead of ~).
- Names in capitals are given bare, without a flag, in the order shown.
- [Common options](common-options.md) explains `--json` and `--no-redact`, which many commands share.
- Only one of `--out`, `--check` at a time.
<!-- end generated -->

## Inputs

- **The script**, read as UTF-8. Every `import phobos_modkit...` and `from phobos_modkit... import ...` in it is followed, at any
  depth; its other imports are its own business (phobos-rimworld's checker imports its shim only when not bundled).
- **The kit modules those name, and the ones they import in turn**, from this kit's `python/phobos_modkit/` folder: relative imports
  are resolved against each module's package. A name taken from a package is a module when the package has a file of that name,
  and otherwise must come from the package's `__init__`, which is refused.

## Outputs

The file: the script's docstring and `from __future__` imports, then a marked block (a header naming the kit's version, its
repository and licence, the loader, and each module's source as a raw string, or an escaped one where a raw string cannot hold it),
then the rest of the script. Line endings are `\n`. Before writing, the bundle checks the file parses for `--python` and that
every module reads back exactly as its source.

The summary says whether the file was written, was already up to date, or (with `--check`) is up to date, missing or out of date,
with its lines, the Python it promises, its sha256, and a table of the modules in the order they are set up (each after the ones
it imports). The envelope's `data` has `script`, `file`, `state`, `sha256`, `python` and `modules` (each `module` and `lines`); a
refusal gives `script` and `error`.

## Effects

Reads the script and the kit's modules. `--out` writes that one file (and its folder), and only when its bytes would change;
`--check` writes nothing. Nothing is run: the modules are parsed, not imported.

## Failures and exit codes

| Exit | When |
| --- | --- |
| 0 | Written, already up to date, or `--check` found it up to date |
| 1 | The script cannot be bundled (the message names the module, the line and why), or `--check` found the file missing or out of date |
| 2 | Usage: no script, or neither `--out` nor `--check` |

## Limits

- Only syntax is checked against `--python`; the standard library's own changes between versions are not.
- A module that reads a data file beside itself (`Path(__file__).parent / ...`) cannot work bundled: its `__file__` names the
  bundled module, not a folder. None of the modules bundled today does; the bundle does not check for it.
- Game-free: any game's tool can be bundled. phobos-rimworld's vehicle schema checker is the first, with
  `dotnet_metadata`, `games/rimworld/loading`, `games/rimworld/mod_xml` and `games/rimworld/xml_patches` inside.
