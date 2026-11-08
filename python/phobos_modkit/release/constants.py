"""Keep every copy of a value in step: a mod's version in its metadata, project file, README and store page, or a
tuning figure quoted in several documents.

A catalogue (config/maintained-constants.json by default) registers each constant with its type, current value and
every place it appears:

    {
      "schemaVersion": 1,
      "targetsUnder": ["mods/", "src/", "README.md"],      optional: where targets may live
      "constants": {
        "Framework.version": {
          "type": "version", "parts": 3, "value": "0.12.0", "description": "...",
          "targets": [
            {"path": "mods/Framework/About/About.xml", "pattern": "<modVersion>(?P<value>[0-9.]+)</modVersion>"},
            {"path": "mods/Framework/data.json", "pointer": "/version"}
          ],
          "review": ["Write the new changelog entry."]
        }
      }
    }

Types are version (3 or 4 parts), number and integer (with min and max) and boolean. A pattern target captures the
value in a group named value and must match count times (default 1); a pointer target names one value in a JSON
file and keeps the file's formatting. "literal": "csharp-float" adds the f suffix a C# float needs.

Every registered copy is checked before anything is written, even for a one-key change, so drift anywhere stops the
whole update. Writes go through temporary files, are read back, and are undone if anything fails.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET

from ..files import UnsafePath, atomic_write, inside, sha256

CATALOGUE = "config/maintained-constants.json"
REFUSED = (".git/", ".local/")
XML_SUFFIXES = (".xml", ".csproj", ".props", ".targets")


class UpdateError(ValueError):
    pass


def validate(entry, value):
    if not isinstance(value, str):
        raise UpdateError("Catalogue values must be strings")
    kind = entry["type"]
    if kind == "version":
        parts = entry.get("parts", 3)
        if parts not in (3, 4):
            raise UpdateError("Version types need 3 or 4 parts")
        if not re.fullmatch(r"(?:0|[1-9][0-9]*)" + r"\.(?:0|[1-9][0-9]*)" * (parts - 1), value):
            raise UpdateError(f"Expected a {parts}-part numeric version: {value!r}")
        if any(int(part) > 65534 for part in value.split(".")):
            raise UpdateError("Version parts must be at most 65534")
        return value
    if kind in ("number", "integer"):
        if not re.fullmatch(r"-?(?:[0-9]+(?:\.[0-9]+)?|\.[0-9]+)", value):
            raise UpdateError(f"Expected a finite decimal: {value!r}")
        number = Decimal(value)
        if kind == "integer" and number != number.to_integral_value():
            raise UpdateError("Expected an integer")
        if not Decimal(str(entry["min"])) <= number <= Decimal(str(entry["max"])):
            raise UpdateError(f"Value outside [{entry['min']}, {entry['max']}]")
        return str(int(number)) if kind == "integer" else format(number, "f")
    if kind == "boolean" and value in ("true", "false"):
        return value
    raise UpdateError(f"Unsupported type or value: {kind}, {value!r}")


def equal(entry, left, right):
    left, right = validate(entry, left), validate(entry, right)
    return Decimal(left) == Decimal(right) if entry["type"] in ("number", "integer") else left == right


def target_path(root, name, allowed):
    relative = Path(name)
    if relative.is_absolute() or ".." in relative.parts or not relative.parts:
        raise UpdateError(f"Unsafe target path: {name}")
    posix = relative.as_posix()
    if posix.startswith(REFUSED) or (allowed and not any(posix == a or posix.startswith(a.rstrip("/") + "/")
                                                         for a in allowed)):
        raise UpdateError(f"Target outside the catalogue's targetsUnder: {name}")
    try:
        path = inside(root, relative)
    except UnsafePath as error:
        raise UpdateError(f"{error}: {name}") from None
    if not path.is_file():
        raise UpdateError(f"Missing target: {name}")
    return path


def json_value_span(text, pointer):
    """(start, end) of the scalar value a JSON pointer (RFC 6901) names, in the file's own text."""
    segments = [s.replace("~1", "/").replace("~0", "~") for s in pointer.split("/")[1:]] if pointer.startswith("/") else None
    if not segments:
        raise UpdateError(f"Invalid JSON pointer: {pointer}")
    n = len(text)

    def skip(i):
        while i < n and text[i] in " \t\r\n":
            i += 1
        return i

    def string_end(i):
        i += 1
        while i < n:
            if text[i] == "\\":
                i += 2
            elif text[i] == '"':
                return i + 1
            else:
                i += 1
        raise UpdateError("Unterminated string in a JSON target")

    def value_end(i):
        i = skip(i)
        c = text[i]
        if c == '"':
            return string_end(i)
        if c in "{[":
            close = "}" if c == "{" else "]"
            i = skip(i + 1)
            while text[i] != close:
                if c == "{":
                    i = skip(string_end(i))
                    if text[i] != ":":
                        raise UpdateError("Malformed JSON target")
                    i += 1
                i = skip(value_end(i))
                if text[i] == ",":
                    i = skip(i + 1)
            return i + 1
        j = i
        while j < n and text[j] not in ",}] \t\r\n":
            j += 1
        return j

    def find(i, remaining):
        i = skip(i)
        if not remaining:
            if text[i] in "{[":
                raise UpdateError(f"JSON pointer names an object or array, not a value: {pointer}")
            if text[i] == '"':
                # A string's value is what lies between its quotes; a value needing escapes is not a constant.
                end = string_end(i)
                if "\\" in text[i:end]:
                    raise UpdateError(f"JSON pointer names a string with escapes: {pointer}")
                return i + 1, end - 1
            return i, value_end(i)
        head, rest = remaining[0], remaining[1:]
        if text[i] == "{":
            i = skip(i + 1)
            while text[i] != "}":
                key_start = i
                i = string_end(i)
                key = json.loads(text[key_start:i])
                i = skip(i)
                if text[i] != ":":
                    raise UpdateError("Malformed JSON target")
                i = skip(i + 1)
                if key == head:
                    return find(i, rest)
                i = skip(value_end(i))
                if text[i] == ",":
                    i = skip(i + 1)
            raise UpdateError(f"JSON pointer segment not found: {head!r} in {pointer}")
        if text[i] == "[":
            index = int(head) if head.isdigit() else -1
            i, position = skip(i + 1), 0
            while text[i] != "]":
                if position == index:
                    return find(i, rest)
                i = skip(value_end(i))
                if text[i] == ",":
                    i = skip(i + 1)
                position += 1
            raise UpdateError(f"JSON pointer index not found: {head!r} in {pointer}")
        raise UpdateError(f"JSON pointer walks into a scalar: {pointer}")

    return find(0, segments)


def assignments(items):
    result = {}
    for item in items:
        key, separator, value = item.partition("=")
        if not separator or not key or key in result:
            raise UpdateError(f"Expected a unique key=value: {item!r}")
        result[key] = value
    return result


def load_catalogue(root, catalogue=CATALOGUE):
    path = inside(root, catalogue)
    original = path.read_bytes()
    data = json.loads(original.decode("utf-8-sig"))
    if data.get("schemaVersion") != 1 or not isinstance(data.get("constants"), dict):
        raise UpdateError("Unsupported constants catalogue")
    for key, entry in data["constants"].items():
        validate(entry, entry["value"])
        if not entry.get("targets"):
            raise UpdateError(f"No targets for {key}")
    return data, original


def plan(root, updates, expected, catalogue=CATALOGUE):
    """(original, proposed, summary): {path: bytes} now and after, and what would change. Writes nothing."""
    root = Path(root).resolve()
    data, catalogue_bytes = load_catalogue(root, catalogue)
    entries, allowed = data["constants"], data.get("targetsUnder", [])
    catalogue_name = Path(catalogue).as_posix()
    unknown = (updates.keys() | expected.keys()) - entries.keys()
    if unknown:
        raise UpdateError("Unknown keys: " + ", ".join(sorted(unknown)))
    if expected.keys() - updates.keys():
        raise UpdateError("--expect keys must also be given with --set")
    for key, value in expected.items():
        if not equal(entries[key], value, entries[key]["value"]):
            raise UpdateError(f"{key} is {entries[key]['value']}, not the expected {value}")
    replacements = {key: validate(entries[key], value) for key, value in updates.items()}
    original, edits, changes = {}, {}, []
    for key, entry in entries.items():
        for target in entry["targets"]:
            count = target.get("count", 1)
            if type(count) is not int or count < 1:
                raise UpdateError(f"Expected a positive match count for {key}")
            name = target["path"]
            if Path(name).as_posix() == catalogue_name:
                raise UpdateError("The catalogue cannot target itself")
            path = target_path(root, name, allowed)
            if name not in original:
                original[name] = path.read_bytes()
            text = original[name].decode("utf-8-sig")
            if "pointer" in target:
                if not name.endswith(".json") or "pattern" in target:
                    raise UpdateError(f"Pointer targets name a .json file and carry no pattern: {key} in {name}")
                spans = [json_value_span(text, target["pointer"])]
            else:
                pattern = re.compile(target["pattern"], re.MULTILINE)
                matches = list(pattern.finditer(text))
                if len(matches) != count or "value" not in pattern.groupindex:
                    raise UpdateError(f"Target shape changed: {key} in {name}; found {len(matches)} matches")
                spans = [m.span("value") for m in matches]
            for start, end in spans:
                current = text[start:end]
                if start == end:
                    raise UpdateError(f"Empty value capture: {key} in {name}")
                if not equal(entry, current, entry["value"]):
                    raise UpdateError(f"Drift: {key} in {name}; catalogue {entry['value']}, file {current}")
                intervals = edits.setdefault(name, [])
                if any(start < other[1] and end > other[0] for other in intervals):
                    raise UpdateError(f"Overlapping targets in {name}")
                new = replacements.get(key, entry["value"])
                changing = key in replacements and not equal(entry, current, new)
                rendered = new
                # A C# float that was a whole number still needs its f once a fractional value arrives.
                if target.get("literal") == "csharp-float" and text[end:end + 1] not in ("f", "F"):
                    rendered += "f"
                intervals.append((start, end, rendered if changing else current))
                if changing:
                    changes.append({"key": key, "path": name, "line": text.count("\n", 0, start) + 1,
                                    "before": current, "after": new})
    proposed = {}
    for name, intervals in edits.items():
        text = original[name].decode("utf-8-sig")
        for start, end, value in sorted(intervals, reverse=True):
            text = text[:start] + value + text[end:]
        data_out = (b"\xef\xbb\xbf" if original[name].startswith(b"\xef\xbb\xbf") else b"") + text.encode("utf-8")
        if data_out != original[name]:
            if name.endswith(".json"):
                json.loads(text)
            if name.endswith(XML_SUFFIXES):
                ET.fromstring(text.encode("utf-8"))
            proposed[name] = data_out
    changed_keys = [k for k, v in replacements.items() if not equal(entries[k], v, entries[k]["value"])]
    if changed_keys:
        for key in changed_keys:
            entries[key]["value"] = replacements[key]
        original[catalogue_name] = catalogue_bytes
        proposed[catalogue_name] = (json.dumps(data, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    summary = {"checked": len(entries), "changes": changes,
               "files": [(n, sha256(original[n])[:12], sha256(d)[:12]) for n, d in sorted(proposed.items())],
               "review": {k: entries[k].get("review", []) for k in changed_keys}, "constants": entries}
    return original, proposed, summary


def apply(root, original, proposed, catalogue=CATALOGUE):
    """Write the proposed files after checking nothing changed since planning; undo them if anything fails."""
    root = Path(root).resolve()
    written = []
    try:
        for name, before in original.items():
            if inside(root, name).read_bytes() != before:
                raise UpdateError(f"Edited while planning: {name}")
        for name, after in proposed.items():
            atomic_write(inside(root, name), after)
            written.append(name)
        plan(root, {}, {}, catalogue)
        for name, after in proposed.items():
            if inside(root, name).read_bytes() != after:
                raise UpdateError(f"Read-back failed: {name}")
    except Exception as error:
        failures = []
        for name in reversed(written):
            try:
                path = inside(root, name)
                if path.read_bytes() != proposed[name]:
                    raise UpdateError("changed again; kept the other edit")
                atomic_write(path, original[name])
            except Exception:
                failures.append(name)
        if failures:
            raise UpdateError(f"Update failed ({error}); recover by hand: {', '.join(failures)}") from error
        raise UpdateError(f"Update failed; written files restored: {error}") from error
