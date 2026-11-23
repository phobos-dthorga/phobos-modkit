"""A game's side of Workshop publishing, as data (1.97.0). Game-free.

The owner, 23 Nov 2026: "The Steam Workshop uploader should be genericized as far as is possible." Each game is a small JSON
file, `games/<game>/workshop.json`, or a `game` block inside a repository's own catalogue for a game nobody has written one
for. It says where a mod keeps what Steam needs:

    {
      "name": "rimworld",
      "appId": "294100",
      "metadata": {"file": "About/About.xml", "format": "xml", "title": "name", "version": "modVersion"},
      "preview": "About/Preview.png",
      "tags": {"fixed": ["Mod"], "fields": ["supportedVersions/li"]},
      "idFile": {"file": "About/PublishedFileId.txt", "format": "text"},
      "reminders": ["..."],
      "facts": ["format facts, in our own words, with their sources"]
    }

Metadata formats, and what a field names in each:

| Format | A field is | Example |
| --- | --- | --- |
| `xml` | Child elements from the root, joined by `/`, any letter case; the last step may match many | `supportedVersions/li` |
| `json` | Keys and list positions, joined by `.` | `0.strName` |
| `keyvalue` | A key on `key<separator>value` lines (separator `=` unless the format says otherwise); a repeated key is a list | `modversion` |
| `catalogue` | The mod's own entry in the catalogue (`title`, `version`, `tags`): for a game whose mods carry no such file | `title` |

File names in the game file are found in any letter case, as games on Windows do. `{mod}` in a path is the mod's catalogue name.
ID file formats: `text` (the whole file is the number) and `keyvalue` (one key's line, written in place or added).

`layout` gives the game's own defaults for the catalogue's layout keys (where a Workshop item wraps the mod folder, say);
a catalogue's own layout still wins. A game whose format cannot be said as data names a `hook`: a module beside its game
file (`.hook`, relative) whose `read(adapter, folder, item)` returns a ModInfo. Nothing here names a game.
"""
from __future__ import annotations

from importlib import import_module
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET

from ...files import atomic_write, inside
from .project import Adapter, ModInfo, PublishError

FORMATS = ("xml", "json", "keyvalue", "catalogue")
ID_FORMATS = ("text", "keyvalue")
BARE_AMPERSAND = re.compile(r"&(?!#?\w+;)")
SPEC_KEYS = {"name", "appId", "metadata", "preview", "tags", "idFile", "reminders", "facts", "hook", "layout", "title"}


def find(folder, relative):
    """folder/relative, each part matched in any letter case; the exact path when nothing matches."""
    path = Path(folder)
    for part in Path(relative).parts:
        exact = path / part
        if exact.exists():
            path = exact
            continue
        try:
            match = next((p for p in path.iterdir() if p.name.lower() == part.lower()), None)
        except OSError:
            match = None
        path = match or exact
    return path


def _xml_root(path):
    raw = path.read_text(encoding="utf-8-sig", errors="replace")
    for attempt in (raw, BARE_AMPERSAND.sub("&amp;", raw)):
        try:
            return ET.fromstring(attempt)
        except ET.ParseError:
            continue
    raise PublishError(f"Unreadable XML in {path}")


def _xml_values(root, field):
    nodes = [root]
    for step in field.split("/"):
        nodes = [c for n in nodes for c in n if isinstance(c.tag, str) and c.tag.lower() == step.lower()]
    return [(n.text or "").strip() for n in nodes]


def _json_values(value, field):
    for step in field.split("."):
        if isinstance(value, list) and step.isdigit() and int(step) < len(value):
            value = value[int(step)]
        elif isinstance(value, dict) and step in value:
            value = value[step]
        else:
            return []
    if isinstance(value, list):
        return [str(v) for v in value if isinstance(v, (str, int, float))]
    return [str(value)] if isinstance(value, (str, int, float)) else []


def keyvalue_lines(text, separator="="):
    """[(key, value)] from key<separator>value lines, in order; blank lines and lines without the separator skipped."""
    found = []
    for line in text.splitlines():
        if separator in line:
            key, _, value = line.partition(separator)
            if key.strip():
                found.append((key.strip(), value.strip()))
    return found


class DataAdapter(Adapter):
    """An Adapter made from a game file: no game named in code."""

    def __init__(self, spec, source="(inline)", package=None):
        unknown = set(spec) - SPEC_KEYS
        if unknown:
            raise PublishError(f"{source}: unknown keys {', '.join(sorted(unknown))}")
        self.spec, self.source = spec, source
        self.name = spec.get("name") or "game"
        self.title = spec.get("title") or self.name
        self.app_id = str(spec.get("appId") or "")
        if not re.fullmatch(r"[1-9][0-9]*", self.app_id):
            raise PublishError(f"{source}: appId must be a Steam app number")
        meta = spec.get("metadata") or {"format": "catalogue"}
        if meta.get("format") not in FORMATS:
            raise PublishError(f"{source}: metadata format must be one of {', '.join(FORMATS)}")
        if meta["format"] != "catalogue" and not meta.get("file"):
            raise PublishError(f"{source}: metadata needs a file")
        self.meta = meta
        self.metadata = meta.get("file")
        self.preview = spec.get("preview") or "preview.png"
        self.tag_spec = spec.get("tags") or {}
        self.id_spec = spec.get("idFile")
        if self.id_spec and self.id_spec.get("format") not in ID_FORMATS:
            raise PublishError(f"{source}: idFile format must be one of {', '.join(ID_FORMATS)}")
        self.reminders = list(spec.get("reminders") or [])
        self.hook = import_module(spec["hook"], package) if spec.get("hook") and package else None

    # ---- reading a mod ----

    def values(self, folder, field, item=None, mod=None):
        """Every value of field in the mod's metadata."""
        kind = self.meta["format"]
        if kind == "catalogue":
            value = (item or {}).get(field)
            return [str(v) for v in value] if isinstance(value, list) else [str(value)] if value else []
        path = find(folder, self.metadata.format(mod=mod or Path(folder).name))
        if not path.is_file():
            raise PublishError(f"No {self.metadata} in {folder}")
        try:
            if kind == "xml":
                return _xml_values(_xml_root(path), field)
            text = path.read_text(encoding="utf-8-sig", errors="replace")
            if kind == "json":
                return _json_values(json.loads(text), field)
            return [v for k, v in keyvalue_lines(text, self.meta.get("separator", "=")) if k.lower() == field.lower()]
        except (OSError, ValueError) as error:
            raise PublishError(f"Unreadable {path}: {error}") from None

    def read(self, folder, item=None, mod=None):
        if self.hook and hasattr(self.hook, "read"):
            return self.hook.read(self, Path(folder), item)
        title = next(iter(self.values(folder, self.meta.get("title", "title"), item, mod)), "")
        version = next(iter(self.values(folder, self.meta.get("version", "version"), item, mod)), "")
        return ModInfo(title, version, tuple(self.tags(folder, item, mod)))

    def tags(self, folder, item=None, mod=None):
        """The fixed tags, then each tag field's values, then the catalogue entry's own; each once, in order."""
        found = list(self.tag_spec.get("fixed", []))
        for field in self.tag_spec.get("fields", []):
            found += [v for v in self.values(folder, field, item, mod) if v]
        found += [str(t) for t in (item or {}).get("tags", [])]
        return list(dict.fromkeys(t.strip() for t in found if t.strip()))

    # ---- the game's own record of the item ----

    def _id_path(self, project, mod):
        return inside(project.root, find(project.path("mod", mod), self.id_spec["file"].format(mod=mod)))

    def recorded_id(self, project, mod):
        """The item number the game's own file holds, or None when there is no such file or line."""
        if not self.id_spec:
            return None
        path = self._id_path(project, mod)
        if not path.is_file():
            return None
        text = path.read_text(encoding="utf-8-sig").strip()
        if self.id_spec["format"] == "text":
            return text or None
        key = self.id_spec.get("key", "id")
        values = [v for k, v in keyvalue_lines(text, self.id_spec.get("separator", "=")) if k.lower() == key.lower()]
        return values[0] if values and values[0] not in ("", "0") else None

    def check(self, project, mod, item):
        found = self.recorded_id(project, mod)
        if found is None or found == (item.get("itemId") or ""):
            return []
        path = project.rel(self._id_path(project, mod))
        return [f"{mod}: {path} says {found} but the catalogue says {item.get('itemId')}; the game's own uploader may have "
                "made this item. Make them agree before preparing an upload."]

    def item_recorded(self, project, mod, item_id):
        if not self.id_spec or self.recorded_id(project, mod) == item_id:
            return []
        path = self._id_path(project, mod)
        if self.id_spec["format"] == "text":
            data = item_id
        else:
            key, sep = self.id_spec.get("key", "id"), self.id_spec.get("separator", "=")
            lines = path.read_text(encoding="utf-8-sig").splitlines() if path.is_file() else []
            hit = [i for i, line in enumerate(lines) if line.partition(sep)[0].strip().lower() == key.lower()]
            if hit:
                lines[hit[0]] = f"{key}{sep}{item_id}"
            else:
                lines.append(f"{key}{sep}{item_id}")
            data = "\n".join(lines) + "\n"
        atomic_write(path, data.encode("ascii"))
        return [project.rel(path)]

    def after_upload(self, project, mod):
        return list(self.reminders)


def load_file(path, package=None):
    path = Path(path)
    try:
        spec = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as error:
        raise PublishError(f"Unreadable game file {path}: {error}") from None
    return DataAdapter(spec, str(path.name), package)


def load_folder(folder, package_root):
    """{app ID: DataAdapter} for every <folder>/<game>/workshop.json; package_root names the modules' package."""
    adapters = {}
    for path in sorted(Path(folder).glob("*/workshop.json")):
        adapter = load_file(path, f"{package_root}.{path.parent.name}")
        if adapter.app_id in adapters:
            raise PublishError(f"Two game files for Steam app {adapter.app_id}")
        adapters[adapter.app_id] = adapter
    return adapters
