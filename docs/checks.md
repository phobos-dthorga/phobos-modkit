# Checks: rules that say when a game's state is wrong

A repository writes rules as data, saying what to read and what counts as wrong; the kit reads a save (or a snapshot of the running
game) and says which things break them. The engine is game-free (`python/phobos_modkit/checks.py`); a game's adapter reads the
values. The design and its reasons: phobos-rimworld's
[test automation record](https://github.com/phobos-dthorga/phobos-rimworld/blob/main/docs/development/test-automation.md).

## Read this first

- **A finding is not a test.** It says a saved or running state breaks a rule the repository wrote. A rule can be wrong too; a
  finding is something to look at, never proof that a mod works or fails in play.
- **A check file can never run code.** Its conditions are a small language (below); anything else is refused when the file is
  read, with where and why.
- **Save checks only read**, from a frozen copy of the save, as every save tool does. **Live checks take a snapshot of the running
  game**, which pauses it for about half a second: ask before every one ([the heap reader](heap-reader.md)).
- **A missing value never makes a fault by comparison**: `x > 1` is false when `x` was not saved. Test for it with `x == None`.

## Examples

```text
python -m phobos_modkit rimworld-save checks --checks config/checks.json        every save check, on the newest save
python -m phobos_modkit rimworld-save checks --save PG20 --check "work-store*"  some checks, on one save
```

## Inputs

### The check file

JSON, with a list under `checks`. phobos-rimworld keeps its own in `config/checks.json`.

```json
{"checks": [
  {"id": "work-store-heavy", "title": "A work store holds far more than any fitting takes", "source": "save", "level": "look",
   "select": {"class": "Vehicles.VehiclePawn"},
   "read": {"stacks": "PhobosWorkStore_Held/innerList/li[*]/stackCount",
            "kinds": "PhobosWorkStore_Held/innerList/li[*]/def",
            "orders": "PhobosVehicleSystems_FitOrders/li[*]/fitting"},
   "fault": "sum(stacks) > 300",
   "says": "{sum(stacks)} things laid out ({unique(kinds)}) for {count(orders)} fit orders",
   "row": "513", "why": "Framework 0.286.2 keeps only what the waiting work needs."}
]}
```

| Field | What it holds |
| --- | --- |
| `id` | A short name, unique in the file; `--check` chooses by it |
| `title` | What the rule says should hold, in a sentence a person reads |
| `source` | `save` (read from a save) or `live` (read from a snapshot of the running game) |
| `level` | `fault` (the design says it cannot happen; the default) or `look` (worth a look; may be fine) |
| `kind` | `rule` (the default), or a kind the game's adapter builds itself (RimWorld's save checks: `numbers`, `references`) |
| `select` | Which things to read. RimWorld's save checks: `def`, `class` (both take `*` and `?`), `place`, `map`. Required: reading every thing would take minutes |
| `read` | Each value's name and its path. A name is letters, digits and `_`, and not a function's name |
| `when` | Optional: a condition saying which things the rule applies to |
| `fault` | The condition that makes it a fault. Required for a rule |
| `says` | The sentence for each finding: each `{expression}` is replaced by its value. Without it, the title is used |
| `row` | Optional: the test row the rule belongs to, shown beside its findings |
| `why` | Optional: a sentence on why the rule holds, shown beside its findings |

### Paths

**In a save** (RimWorld): a path is a value's place in the thing's own saved data, as `rimworld-save thing` shows it: tags joined by
`/`, a list's items as `li[0]`, `li[1]`, a dictionary's values as `name[key]`. `*` stands for any run of characters within one
step, `**` for any run across steps, `?` for one character. **A path with a wildcard reads a list** of every match, in save order;
one without reads one value, or None when it is not saved. A thing another thing holds (a vehicle's cargo, a pawn's inventory) is
cut out of its holder's data, as `thing` does, but keeps its `def`, `id` and `stackCount` from the index at the paths its own XML
would give, so a check can count a store's stacks.

### The language

| Part | What it is |
| --- | --- |
| Names | The values `read` names, plus `id` and `label` (the thing's) |
| Constants | Numbers, text in quotes, `True`, `False`, `None`, lists in `[ ]` |
| Operators | `==`, `!=`, `<`, `<=`, `>`, `>=`, `and`, `or`, `not`, `+`, `-`, `*`, `/`, `%`, `A if test else B` |
| `sum(x)` | The numbers in a list, added up; text and None are left out |
| `count(x)` | How many values there are, None left out |
| `max(x)`, `min(x)` | The largest or smallest number, or None |
| `any(x)`, `all(x)` | Whether any, or all, are true |
| `abs(x)`, `round(x, places)` | As in arithmetic |
| `isnan(x)` | Whether a value, or any in a list, is NaN or infinite |
| `contains(x, value)` | Whether a list holds a value |
| `unique(x)` | A list's values, each once, in their first order |

**How values are read:** text that reads as a number is a number (whole numbers stay whole); `True` and `False` are flags; `NaN`
and the infinities are numbers, for `isnan`; anything else is text. Arithmetic on anything but numbers, or dividing by nothing,
gives None. A comparison between text and a number is false.

### RimWorld's own kinds (save checks)

| Kind | Finds | Option |
| --- | --- | --- |
| `numbers` | Any value saved as NaN or infinity: the mark of a division by nothing | `paths`: which values, default `**Phobos**` |
| `references` | Any reference to a thing (`Thing_` and its ID) that the save does not hold: the game drops it on load, with an error | `paths`, as above |

## Outputs

**The report** lists faults first, then what is worth a look, each check as a section with up to 20 findings (the JSON has every
one), then the checks that found nothing with how many things each read, then any that could not run and why.

**`--json`** carries the report and, under `data`, `checks` (each with `id`, `title`, `source`, `level`, `row`, `read`,
`problem`, `limits` and `findings`, each finding an `id`, `label` and `text`), `faults` and `looks` (counts).

## Limits

- RimWorld's save checks read each chosen thing's part of the save: about 50 vehicles take a second or two on a 450 MB save
  (25 November 2026, the owner's colony). Every pawn in a large colony would take far longer.
- Values another thing holds are only those the index keeps (`def`, `id`, `stackCount`); read the held thing itself with its own
  `select` for anything more.
