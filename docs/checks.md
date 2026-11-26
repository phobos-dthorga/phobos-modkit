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
- **A figure is evidence, never a verdict** (1.129.0). A rule's `note` turns the figures it reads into seen-in-play notes, which a
  test list's evidence map judges against what each row expects. A figure that meets the expectation says the state was right at
  that moment; whether it *looked* right, and whether the row passes, is still the owner's word.

## Examples

```text
python -m phobos_modkit rimworld-save checks --checks config/checks.json        every save check, on the newest save
python -m phobos_modkit rimworld-save checks --save PG20 --check "work-store*"  some checks, on one save
python -m phobos_modkit rimworld-perf look-check --checks config/checks.json    every live check, from one snapshot (ask first)
```

## Inputs

### The check file

JSON, with a list under `checks`. phobos-rimworld keeps its own in `config/checks.json`.

**Which file runs** (1.122.0): the one named with `--checks`; else `config/checks.json` in the current folder; else that file in
every repository the owner's games list gives the game (`games.json`, as D'thorga Companion keeps it), all of them run together.
That last is how a program that runs the kit from the kit's own folder, D'thorga Companion's Reports page among them, finds a
game's checks with nothing typed. The report's facts name the files it ran.

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
| `select` | Which things to read. Save checks (RimWorld): `def`, `class` (both take `*` and `?`), `place`, `map`; required, as reading every thing would take minutes. Live checks: `type` (a kind's full name, as `look` lists it; required), `subclasses` (kinds below it too), `take` (objects, default 5,000) and `items` (items opened per path on one object, default 1,000) |
| `read` | Each value's name and its path. A name is letters, digits and `_`, and not a function's name |
| `when` | Optional: a condition saying which things the rule applies to |
| `fault` | The condition that makes it a fault. A rule needs it, or a `note`, or both |
| `says` | The sentence for each finding: each `{expression}` is replaced by its value. Without it, the title is used |
| `row` | Optional: the test row the rule belongs to, shown beside its findings |
| `why` | Optional: a sentence on why the rule holds, shown beside its findings |
| `note` | Optional (1.129.0), save checks only: the figures to note for a test list, from each thing the rule applies to. See [Figures for a test list](#figures-for-a-test-list) |

### Paths

**In a save** (RimWorld): a path is a value's place in the thing's own saved data, as `rimworld-save thing` shows it: tags joined by
`/`, a list's items as `li[0]`, `li[1]`, a dictionary's values as `name[key]`. `*` stands for any run of characters within one
step, `**` for any run across steps, `?` for one character. **A path with a wildcard reads a list** of every match, in save order;
one without reads one value, or None when it is not saved. A thing another thing holds (a vehicle's cargo, a pawn's inventory) is
cut out of its holder's data, as `thing` does, but keeps its `def`, `id` and `stackCount` from the index at the paths its own XML
would give, so a check can count a store's stacks.

**In a running game** (live checks, any .NET game): a path follows fields by name, joined by dots, through links and structs
(`parent.def.defName`). `[]` after a name opens a list, array, set or dictionary into its items, and the rest of the path is read
from each (`held.innerList[].stackCount`); a final `#` gives a collection's count without reading its items (`orders#`). A path
that opened anything reads a list; one that did not, one value or None. Names are the code's own fields, private ones included, as
`look-kind --open` shows them; a property is not a field. The heap reader's [values request](heap-reader.md) does the reading. A
finding names the object by its summary (RimWorld's: a pawn's name, a Def's defName, a thing's ID number), else its kind and address.

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
| `samples(text, low, high)` | A series saved as base64 text, each value a little-endian 16-bit number scaled over low..high, oldest first (1.130.0; D'thorga Framework's graph histories). None when the text is not one |
| `first(x)`, `last(x)`, `at(x, i)` | A list's first or last item, or the one at place i (from 0; a negative place counts from the end); None when there is none |
| `tail(x, n)` | The last n items: a series' last hours (the Framework's histories keep ten samples an hour) |
| `diffs(x)` | Each number's change from the one before: `min(diffs(x))` is the largest single drop, `max(diffs(x))` the largest rise |
| `mean(x)` | The numbers' average, or None |

**How values are read:** text that reads as a number is a number (whole numbers stay whole); `True` and `False` are flags; `NaN`
and the infinities are numbers, for `isnan`; anything else is text. Arithmetic on anything but numbers, or dividing by nothing,
gives None. A comparison between text and a number is false.

### Figures for a test list

A rule with a `note` (1.129.0) gives, for each thing it applies to (after `when`), a note in the
[seen-in-play format](test-pass.md#the-seen-in-play-notes): its key, the mod it stands for, the thing as `on` and its def as `kind`,
and the figures as `values`. **test-pass reads them from the same newest saves as the saved histories**, when the repository's
evidence map has a `saved` section, and judges them like any note: a row's `expect` says what each figure should be, and a figure
that misses lands in "Seen, but not with the figures the row expects". A rule may have a `fault` too: its findings still show here.

```json
{"id": "shooting", "title": "A colonist's shooting skill", "source": "save", "select": {"class": "Pawn", "def": "Human"},
 "read": {"skills": "skills/skills/li[*]/def", "levels": "skills/skills/li[*]/level"},
 "when": "contains(skills, 'Shooting')",
 "note": {"key": "check.example.shooting", "mod": "Example Widgets", "figures": {"level": "max(levels)"}},
 "row": "12"}
```

| A note's field | What it holds |
| --- | --- |
| `key` | The note's key; `{expression}` is filled from the values read, as in `says` |
| `mod` | The mod the figures stand for, as the version ledger names it: the note's version is the one running when the save was written |
| `figures` | Each figure's name and its expression. Only numbers are kept (a flag as 1 or 0); a figure that is text or None is left out |
| `variant` | Optional: the note's case, as a template, for an evidence map's `variant` |
| `detail` | Optional: the note's sentence, as a template; else the figures, named |

**Each save gives its own notes**: a figure is a state at a moment, so the same thing in four saves is four readings, each with its
save's time. Live checks cannot take a `note` yet: a snapshot is not kept, and its version would need the running game's own ledger.
`rimworld-save checks` lists what each figure check noted, under "Figures noted for the test list".

### A saved series (1.130.0)

D'thorga Framework saves a vehicle's last day of each quantity it shows as one string,
`PhobosVehicleSystems_History_<system>_<quantity>`: 240 samples, one each tenth of an hour, oldest first, each scaled over the
quantity's `min` and `max` from its system Def. **The range is written in the rule**, from the Def: the wrong range gives wrong
figures without any error. Derived quantities are in it too, so a figure the saved values leave out (flight control, crew oxygen)
is readable. A vehicle new to the world may hold only a sample or two: narrow a rule with `count(samples(...)) >= N`.

```json
{"id": "camp-night-heater", "title": "A camped truck's night heater holds its coolant warm", "source": "save",
 "select": {"class": "*VehiclePawn", "place": "world object"},
 "read": {"heater": "PhobosVehicleSystems_Loads[nightHeater]",
          "coolant": "PhobosVehicleSystems_History_PhobosVehicleSystem_Cooling_coolantTemperature"},
 "when": "heater == True and count(samples(coolant, -60, 200)) >= 100",
 "note": {"key": "check.vehicle.camp-coolant", "mod": "D'thorga Framework",
          "figures": {"low": "min(tail(samples(coolant, -60, 200), 100))", "high": "max(tail(samples(coolant, -60, 200), 100))"}}}
```

### RimWorld's own kinds (save checks)

| Kind | Finds | Option |
| --- | --- | --- |
| `numbers` | Any value saved as NaN or infinity: the mark of a division by nothing | `paths`: which values, default `**Phobos**` |
| `references` | Any reference to a thing (`Thing_` and its ID) that the save does not hold: the game drops it on load, with an error | `paths`, as above |

## Outputs

**The report** lists faults first, then what is worth a look, each check as a section with up to 20 findings (the JSON has every
one), then the checks that found nothing with how many things each read, then any that could not run and why.

**`--json`** carries the report and, under `data`, `checks` (each with `id`, `title`, `source`, `level`, `row`, `read`,
`problem`, `limits`, `findings`, each finding an `id`, `label` and `text`, and `noted`, each thing's `id`, `label`, `key`,
`variant` and `figures`), `faults` and `looks` (counts), and `waiting` (1.129.0: the two together, what waits on the person;
the manifest's `waits` names it, so a program such as D'thorga Companion can show the count without reading the words).

## Limits

- A live check reads one instant: a value mid-change (a list being rebuilt, a cache cleared for its next look) can break a rule for
  that moment only. Run it again before believing a finding, or make the rule allow for it.
- RimWorld's save checks read each chosen thing's part of the save: about 50 vehicles take a second or two on a 450 MB save
  (25 November 2026, the owner's colony). Every pawn in a large colony would take far longer.
- Values another thing holds are only those the index keeps (`def`, `id`, `stackCount`); read the held thing itself with its own
  `select` for anything more.
