# code: C# declarations and their uses, without reading whole files

At the owner's request for tools that keep agent sessions lean: instead of searching hundreds of thousands of decompiled lines by
hand, it indexes each source tree once and answers the usual questions (where is it, what is in it, show me it, who uses it) in a
few hundred tokens.

## Read this first

- **Decompiled code stays on the researcher's machine.** The tool reads trees you name and keeps its indexes in the
  kit's cache, outside any repository. It never copies source anywhere; `show` prints lines to the terminal only.
- **Indexes build themselves**: on first use, and again when a tree's files change (size or time). 54 trees and about
  330,000 declarations took 34 seconds on the owner's PC; a query then takes under a second.
- **`refs` reads the files, not the index**, with a whole-word match, so it finds every use the text holds: calls,
  overrides, reflection by name in a string. It leaves out comment lines and `using` lines, and groups each line under
  the innermost declaration holding it.
- **It reads C# as decompilers and tidy code lay it out; it is not a compiler.** Comments, strings (verbatim,
  interpolated with nested quotes, raw) and character literals are blanked first, so their braces do not count. On the
  owner's trees it misses about two declarations in 100,000; see Limits.
- `show` hides decompiler notes (`//IL_0047: ...`) and says how many; `--raw` keeps them.
- **A query builds only the indexes it reads** (1.141.1). `--in` narrows to matching corpora before any is built. A calling
  script passes its own trees as `--default-corpus` and `--default-each-in`, which are read only when the command line names no
  `--corpus` or `--each-in` of its own, so `--corpus NAME=PATH` alone reads that one tree.
- **Two runs may want one index at once** (1.141.1): the second waits for the first's build and uses it, saying so on stderr.
  Each run writes its own half-built file, so neither can delete the other's; one a stopped run left is cleared after five
  minutes and never blocks a later run.

## Examples

```text
cd python
python -m phobos_modkit code --each-in DIR summary                 every folder and .cs file in DIR is a corpus
python -m phobos_modkit code --corpus ours=../src find "*Damage*"  declarations by name (* and ?), --kind method
python -m phobos_modkit code ... outline VehicleStatHandler        a type's members with their lines
python -m phobos_modkit code ... show VehicleStatHandler.ApplyDamage   the source, numbered; every overload
python -m phobos_modkit code ... refs HighlightedComponent         every line using a name, by member
python -m phobos_modkit code ... --in "VehicleFramework*" show X   only corpora whose name matches
python -m phobos_modkit code compare OLD.dll NEW.dll --decompiler ILSPYCMD --reference DIR   what changed between two builds
```

A name can be bare (`ApplyDamage`), dotted (`VehicleStatHandler.ApplyDamage`) or full
(`Vehicles.VehicleStatHandler.ApplyDamage`); a dotted name matches any full name ending with it. A consumer passes its
trees through a thin script (phobos-rimworld: `python scripts/query-code.py`).

## Reports and options

<!-- generated: options code -->
Generated from the command's own parser by `python -m phobos_modkit command-docs --write`: change a help text in the parser, not here.

| Report | What it does | Effect |
| --- | --- | --- |
| `summary` | The corpora, their files and declarations. | reads only |
| `find` | Declarations whose name or full name matches. | reads only |
| `outline` | A type's members, in source order. | reads only |
| `show` | A declaration's source, numbered. | reads only |
| `refs` | Every line using a name, grouped by the member it is in. | reads only |
| `compare` | What changed between two builds, member by member. Runs ilspycmd on the file, which reads it without loading or running it. | runs other programs, when a side is a .dll |

| Option | Reports | What it does | Default |
| --- | --- | --- | --- |
| `--corpus NAME=PATH` | all | a source tree (a folder or one .cs file) under a name; repeatable |  |
| `--each-in DIR` | all | every folder and .cs file directly inside DIR is a corpus, named after it; repeatable |  |
| `--default-corpus NAME=PATH` | all | like `--corpus`, but read only when no `--corpus` or `--each-in` is given (a calling script's own trees). Repeatable. |  |
| `--default-each-in DIR` | all | like `--each-in`, but read only when no `--corpus` or `--each-in` is given. Repeatable. |  |
| `--in PATTERN` | all | query only corpora whose name matches (\* and ?), and build only their indexes; repeatable |  |
| `--cache VALUE` | all | where indexes are kept (else PHOBOS_MODKIT_CACHE, settings, the temp folder) |  |
| `--settings VALUE` | all | a JSON settings file with modkitCachePath |  |
| `--rebuild` | all | index the chosen corpora again |  |
| `--top N` | all | rows per table (default 40) | `40` |
| `PATTERN` | `find` | a name or full name; \* and ? are wildcards |  |
| `--kind VALUE` | `find` | only these kinds (class, method, property, field, ...). Repeatable. |  |
| `NAME` | `outline` | a type's name or dotted full name |  |
| `NAME` | `show` | Type, Type.Member or Namespace.Type.Member |  |
| `--lines N` | `show` | lines shown per declaration (default 150; 0 for all) | `150` |
| `--raw` | `show` | keep the decompiler's //IL_ notes |  |
| `NAME` | `refs` | an identifier; a dotted name searches for its last part |  |
| `LEFT` | `compare` | the older side: a .dll, a corpus name, or a folder or .cs file |  |
| `RIGHT` | `compare` | the newer side, in any of the same forms |  |
| `--only PATTERN` | `compare` | only declarations whose full name matches (\* and ?); repeatable |  |
| `--show NAME` | `compare` | the changes in one declaration, as a diff: Type.Member or a full name |  |
| `--lines N` | `compare` | lines shown per diff (default 150; 0 for all) | `150` |
| `--decompiler VALUE` | `compare` | ilspycmd, for a .dll (else PHOBOS_MODKIT_ILSPYCMD, settings, the PATH) |  |
| `--reference DIR` | `compare` | a folder of assemblies the .dll refers to, for a truer decompile; repeatable |  |

- Every report also takes `--json` (print JSON instead of Markdown) and `--no-redact` (show the home folder instead of ~).
- Names in capitals are given bare, without a flag, in the order shown.
- A path left out is looked for in the order [settings](settings.md) explains: an environment variable, the repository's own settings file, the central settings file, then the default.
- [Common options](common-options.md) explains `--settings`, `--cache`, `--top`, `--json` and `--no-redact`, which many commands share.
<!-- end generated -->

## Inputs

### compare: what changed between two builds

It reads source, not metadata, so what a rebuild alone disturbs in the compiled file (metadata tokens, retargeted references, the
numbers in compiler-generated names) does not read as a change.

- **Each side** is a `.dll`, a corpus by name, or a folder or `.cs` file. **Compare two `.dll`s, or two trees decompiled
  the same way.** A tree decompiled to one file and another to one file per type qualify names differently, and those
  differences show as changes. Give both sides the same `--reference` folders.
- **A `.dll` needs ilspycmd**: `--decompiler`, `PHOBOS_MODKIT_ILSPYCMD`, `ilspycmdPath` in the settings file, or the
  PATH. It reads the file without loading or running it. The source is kept in the cache folder `decompiled`, outside any
  repository, by the file's bytes and the reference folders; the 12 most recently used are kept, and a cached one needs no
  ilspycmd.
- **Declarations pair by full name and parameters**, so moving a member or reordering overloads changes nothing. If one
  is left over on each side of a name, they are one declaration with a new signature.
- **Comments, decompiler notes and layout are ignored; strings and numbers count.** A body differing only in those is
  "values only", which is how a balance change usually looks.
- **A new type is one row**, not one per member. `--only "*Pattern*"` narrows every count; `--show Type.Member` prints
  one declaration's changes as a diff.
- **An empty side is an error**, never a list of removals, and two sides sharing no declaration are called out. A
  decompile that exits cleanly with no source is a failure.

On real assemblies, 9 November 2026: two builds of a 680-method assembly gave 9 added and 2 changed, every one confirmed by
reading the source; a 1.6 MB assembly with 9,000 declarations took 6 seconds with both decompiles; a 15.6 MB game assembly
with 97,000 declarations took about 5 minutes on first use, decompile included, on a PC also running the game.

## Outputs

### What a declaration is

Namespaces, types (class, struct, interface, enum, record, delegate) and members (method, constructor, property, field,
event, indexer, operator), each with its owner's full name, its first line (attributes included) and its last, and a
one-line signature. Enum members, local functions and lambdas are not declarations here. Nested types are named
`Outer.Inner`.

## Limits

- `compare` calls a renamed declaration one removed and one added, and does not compare attributes on a type.
- Names the compiler generates (`<>z__ReadOnlyArray`) are not identifiers and are skipped.
- A declaration after an attribute block on the same line as another declaration's end, or after a preprocessor
  branch that duplicates a header (`#if A` one signature `#else` another), may be missed or read once.
- `refs` is text: a name that is also a common word in strings (`Label`) finds those strings too, and a different
  member with the same name in another type is found as well. The "In" column tells them apart.
- Partial types are listed once per file that declares a part.
