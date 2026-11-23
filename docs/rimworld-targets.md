# RimWorld targets: do the members our C# names by string still exist?

Built in 0.18.0 (9 November 2026), at the owner's request after a review of phobos-rimworld. The compiler checks `typeof` and
`nameof`. It cannot check a Harmony patch on a private method, a reflected private field, an overload chosen by a list of types, or
the parameters Harmony fills at run time. Those break silently or at start-up when the other assembly changes.

## Read this first

- **Assemblies are read, never run**, through the same metadata reader as the Harmony patches tool.
- **A pass says the names and signatures still exist, not that the code still behaves.** It is not a test in game.
- **It needs the game on the machine.** With `--if-installed` it says so and passes where there is none, as on CI: other mods' assemblies
  may not be copied there.
- **A type it did not read is not a failure** (an optional mod that is not active, or the .NET library), and is listed. The compiler has
  already checked that a `typeof` names a real type.

## Use

```text
cd python
python -m phobos_modkit rimworld-targets --root ..                 check src/**/*.cs
python -m phobos_modkit rimworld-targets --root .. --assemblies "mods/*/1.7/Assemblies/*.dll"   our fresh build first
python -m phobos_modkit rimworld-targets --root .. --all           list what passed too
python -m phobos_modkit rimworld-targets --root .. --type-lookup OptionalMods.TypeNamed   a project's own by-name type lookup
```

Exit 0 when everything named was found, 1 when something no longer matches, 2 for a bad command line.

## What it reads from the source

| Form | Read |
| --- | --- |
| `[HarmonyPatch(...)]` on classes and methods | The type, the member by string or `nameof`, `MethodType`, overload types; stacked attributes merged as Harmony merges them |
| Patch method parameters | `__instance`, `__result` and `___field`, compared with the patched type, its return type and its fields; every other name in a prefix, postfix or finalizer (not `__state` and Harmony's other `__` names, not a transpiler's), matched by name with the original's parameters, as Harmony matches it, or the name a `[HarmonyArgument("...")]` gives |
| `AccessTools.Field`, `Method`, `Property`, `PropertyGetter`, `PropertySetter`, `Constructor`, their `Declared` forms, `FieldRefAccess` | The type from `typeof`, the generic argument or a by-name lookup (below), and the member; or both from one `"Namespace.Type:Member"` string |
| `typeof(T).GetField`, `GetMethod`, `GetProperty` | The same, on any receiver whose type is known |
| By-name type lookups with a fixed name | `AccessTools.TypeByName`, `Type.GetType` and the game's `GenTypes.GetTypeInAnyAssembly`, plus each `--type-lookup`; directly, or through a variable that every assignment in its file sets to the same type and that nothing in the file shadows (a `Type` parameter, a `foreach`, `out` or lambda variable) |
| String constants | `const` and `static readonly` strings, joined with `+`: the file's own by name, any scanned file's as `Class.Name` |
| A `TargetMethod` naming one member | Its body's one lookup becomes the patch class's target, so the class's parameters are checked against it |

## What it reports

| Status | Meaning | Fails |
| --- | --- | --- |
| `missing` | No member of that name on the type or its bases | Yes |
| `overload` | The name exists, not with those parameter types; the real ones are listed | Yes |
| `no-getter`, `no-setter`, `not-a-property` | The property is not what the lookup asks for | Yes |
| `injection` | A parameter Harmony fills names a field that is gone, or has the wrong type; or a parameter it matches by name is not a parameter of the original (the original's names are listed) | Yes |
| `note` | Worth a look: a patch on an inherited method, several overloads with none named, a type that could not be compared | No |
| `type-missing` | The type was not among the assemblies read, so nothing was checked | No |

## Limits

- It reads C# as tidy code lays it out; it is not a compiler.
- A lookup whose type or name is worked out at run time cannot be checked, and is listed: a type read from a property or `GetType()`, a
  name put together from a parameter, a variable given two types, a `TargetMethod` whose body names more than one member or none.
- A by-name parameter is matched by its name alone; its type is not compared. Parameter names come from the reader from 1.10.0 on.
- Types are matched by name and by the `using` lines in scope, so two mods' classes of one name can be confused; a target that matches
  several says so.

## Reports and options

<!-- generated: options rimworld-targets -->
Generated from the command's own parser by `python -m phobos_modkit command-docs --write`: change a help text in the parser, not here.

Effect: reads only.

| Option | What it does | Default |
| --- | --- | --- |
| `--root VALUE` | the repository holding the C# source (default: here) | `.` |
| `--source VALUE` | a glob under the root (default src/\*\*/\*.cs); may repeat |  |
| `--assemblies VALUE` | a glob under the root to read before the game's; may repeat |  |
| `--type-lookup NAME` | a method that finds a type by its full name, such as a project's helper (Class.Method); may repeat |  |
| `--game VALUE` | the RimWorld folder (else RIMWORLD_PATH, the settings file, Steam's default) |  |
| `--workshop VALUE` | the Workshop content folder (else RIMWORLD_WORKSHOP_PATH, settings, beside the game) |  |
| `--config VALUE` | the folder holding ModsConfig.xml (else RIMWORLD_CONFIG_PATH, settings, default) |  |
| `--settings VALUE` | a JSON settings file with rimworldPath, workshopPath, rimworldConfigPath |  |
| `--if-installed` | with no game on this machine, say so and pass (for CI) |  |
| `--all` | list what passed too |  |
| `--top N` | rows per table (default 40) | `40` |

- It also takes `--json` (print JSON instead of Markdown) and `--no-redact` (show the home folder instead of ~).
- A path left out is looked for in the order [settings](settings.md) explains: an environment variable, the repository's own settings file, the central settings file, then the default.
<!-- end generated -->
