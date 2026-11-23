"""A game's side of Workshop publishing, as data (1.97.0; more of it in 1.100.0). Game-free.

The owner, 23 Nov 2026: "The Steam Workshop uploader should be genericized as far as is possible." Each game is a small JSON
file, `games/<game>/workshop.json`, or a `game` block inside a repository's own catalogue for a game nobody has written one
for. It says where a mod keeps what Steam needs:

    {
      "name": "rimworld",
      "appId": "294100",
      "metadata": {"file": "About/About.xml", "format": "xml", "title": "name", "version": "modVersion"},
      "preview": "About/Preview.png",
      "tags": {"fixed": ["Mod"], "fields": ["supportedVersions/li"]},
      "required": {"fields": ["modDependencies/li/steamWorkshopUrl"], "names": "modDependencies/li/displayName"},
      "idFile": {"file": "About/PublishedFileId.txt", "format": "text"},
      "reminders": ["..."],
      "facts": ["format facts, in our own words, with their sources"]
    }

Metadata formats, and what a field names in each:

| Format | A field is | Example |
| --- | --- | --- |
| `xml` | Child elements from the root, joined by `/`, any letter case; the last step may match many | `supportedVersions/li` |
| `json` | Keys and list positions, joined by `.` | `0.strName` |
| `keyvalue` | A key on `key<separator>value` lines (`=` unless `separator` says otherwise, a space splitting at the first space); a repeated key is a list; `quoted` strips one pair of double quotes | `modversion`, `$ITEM_NAME` |
| `catalogue` | The mod's own entry in the catalogue (`title`, `version`, `tags`): for a game whose mods carry no such file; the title defaults to the mod's name | `title` |

In any format, a field written `catalogue:<key>` comes from the catalogue entry instead (a game file with a title but no
version). The metadata `file` may hold `*`: with `"pick": "highest"` the match in the folder whose name is the highest version
number wins (Build 42's `42.15/mod.info`), else the first; `fallback` names a file for when nothing matches. File names are found
in any letter case, as games on Windows do. `{mod}` in a path is the mod's catalogue name.

ID file formats: `text` (the whole file is the number), `keyvalue` (one key's line, written in place, or added before the line
`before` names, such as `$END`) and `xmltag` (one element's text, written only in a file that exists).

Also: `previewRules` (`format` png, `square`, `sizes`, `maxBytes`) and `refuse` (file endings the game's own uploader refuses)
become blockers; `footer` lines (`{itemId}`, `{field:<name>}`) end the description as the game's own uploader ends it; `required`
reads each mod's Required items from its metadata; `layout` gives the game's own defaults for the catalogue's layout keys (a
catalogue's own still win). A game whose format cannot be said as data names a `hook`: a module beside its game file (`.hook`,
relative) whose `read(adapter, folder, item)` returns a ModInfo. Nothing here names a game.
"""
from __future__ import annotations

from importlib import import_module
import json
from pathlib import Path
import re
import struct
import xml.etree.ElementTree as ET

from ...files import atomic_write, inside
from .project import Adapter, ModInfo, PublishError

FORMATS = ("xml", "json", "keyvalue", "catalogue")
ID_FORMATS = ("text", "keyvalue", "xmltag")
BARE_AMPERSAND = re.compile(r"&(?!#?\w+;)")
WORKSHOP_NUMBER = re.compile(r"(?:[?&]id=|CommunityFilePage/|^)(\d{5,})(?:\D|$)")
VERSION_NAME = re.compile(r"\d+(?:\.\d+)*")
SPEC_KEYS = {"name", "appId", "metadata", "preview", "tags", "idFile", "reminders", "facts", "hook", "layout", "title",
             "previewRules", "refuse", "footer", "required"}
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
CATALOGUE_FIELD = "catalogue:"


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


def _version_key(name):
    return tuple(int(p) for p in name.split("."))


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


def keyvalue_lines(text, separator="=", quoted=False):
    """[(key, value)] from key<separator>value lines, in order; blank lines and lines without the separator skipped.
    A separator of one space splits at the first run of whitespace."""
    found = []
    for line in text.splitlines():
        if separator == " ":
            parts = line.strip().split(None, 1)
            if not parts:
                continue
            key, value = parts[0], parts[1] if len(parts) > 1 else ""
        elif separator in line:
            key, _, value = line.partition(separator)
        else:
            continue
        key, value = key.strip(), value.strip()
        if quoted and len(value) >= 2 and value[0] == value[-1] == '"':
            value = value[1:-1]
        if key:
            found.append((key, value))
    return found


def png_size(data):
    """(width, height) of PNG bytes, or None when they are not a PNG."""
    if not data.startswith(PNG_SIGNATURE) or len(data) < 24:
        return None
    return struct.unpack(">II", data[16:24])


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

    def metadata_path(self, folder, mod=None):
        """The mod's metadata file: a wildcard resolved (the highest version folder with pick), else its fallback."""
        relative = self.metadata.format(mod=mod or Path(folder).name)
        if "*" not in relative:
            return find(folder, relative)
        found = sorted(Path(folder).glob(relative))
        if self.meta.get("pick") == "highest":
            depth = relative.split("/").index(next(p for p in relative.split("/") if "*" in p))
            versioned = [p for p in found if VERSION_NAME.fullmatch(p.relative_to(folder).parts[depth])]
            found = sorted(versioned, key=lambda p: _version_key(p.relative_to(folder).parts[depth]), reverse=True)
        if found:
            return found[0]
        return find(folder, self.meta["fallback"].format(mod=mod or Path(folder).name)) if self.meta.get("fallback") \
            else Path(folder) / relative

    def values(self, folder, field, item=None, mod=None):
        """Every value of field in the mod's metadata (or its catalogue entry, for catalogue:<key>)."""
        kind = self.meta["format"]
        if kind == "catalogue" or field.startswith(CATALOGUE_FIELD):
            key = field[len(CATALOGUE_FIELD):] if field.startswith(CATALOGUE_FIELD) else field
            value = (item or {}).get(key)
            if not value and key == "title" and kind == "catalogue":
                value = mod or Path(folder).name
            return [str(v) for v in value] if isinstance(value, list) else [str(value)] if value else []
        path = self.metadata_path(folder, mod)
        if not path.is_file():
            raise PublishError(f"No {self.metadata} in {folder}")
        try:
            if kind == "xml":
                return _xml_values(_xml_root(path), field)
            text = path.read_text(encoding="utf-8-sig", errors="replace")
            if kind == "json":
                return _json_values(json.loads(text), field)
            lines = keyvalue_lines(text, self.meta.get("separator", "="), self.meta.get("quoted", False))
            return [v for k, v in lines if k.lower() == field.lower()]
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

    def required_items(self, folder, item=None, mod=None):
        """[(Workshop number, name)] the mod's own metadata names as needed (required.fields; names from required.names)."""
        spec = self.spec.get("required") or {}
        if spec.get("each") and self.meta["format"] == "xml":
            # One element per dependency, its number and name read from its own children, so a dependency with no
            # Workshop link (one of the repository's own mods, say) never shifts the names of the others.
            path = self.metadata_path(folder, mod)
            nodes = [_xml_root(path)] if path.is_file() else []
            for step in spec["each"].split("/"):
                nodes = [c for n in nodes for c in n if isinstance(c.tag, str) and c.tag.lower() == step.lower()]
            found = []
            for node in nodes:
                number = next((m[1] for v in _xml_values(node, spec.get("number", "")) for m in [WORKSHOP_NUMBER.search(v)]
                               if m), None)
                if number:
                    name = next(iter(_xml_values(node, spec["name"])), "") if spec.get("name") else ""
                    found.append((number, name or f"Workshop item {number}"))
            return list(dict.fromkeys(found))
        numbers = []
        for field in spec.get("fields", []):
            numbers += [m[1] for v in self.values(folder, field, item, mod) for m in [WORKSHOP_NUMBER.search(v)] if m]
        names = self.values(folder, spec["names"], item, mod) if spec.get("names") else []
        if len(names) != len(numbers):
            names = []
        return list(dict.fromkeys((n, names[i] if names else f"Workshop item {n}") for i, n in enumerate(numbers)))

    def footer(self, folder, item=None, mod=None):
        """The footer lines, {field:<name>} filled in from the metadata; {itemId} is filled in when sending."""
        lines = []
        for line in self.spec.get("footer", []):
            for field in re.findall(r"\{field:([^}]+)\}", line):
                line = line.replace(f"{{field:{field}}}", next(iter(self.values(folder, field, item, mod)), ""))
            lines.append(line)
        return lines

    def blockers(self, payload, preview):
        """What the game's own uploader would refuse, in words: cover rules and refused files."""
        found = []
        rules = self.spec.get("previewRules") or {}
        data = payload.get(preview)
        if rules and data is not None:
            size = png_size(data)
            if rules.get("format") == "png" and size is None:
                found.append(f"{preview} must be a PNG for this game")
            if size and rules.get("square") and size[0] != size[1]:
                found.append(f"{preview} is {size[0]} by {size[1]} pixels; this game wants it square")
            if size and rules.get("sizes") and size[0] not in rules["sizes"]:
                found.append(f"{preview} is {size[0]} pixels wide; this game takes "
                             + " or ".join(str(s) for s in rules["sizes"]))
            if rules.get("maxBytes") and len(data) > rules["maxBytes"]:
                found.append(f"{preview} is {len(data):,} bytes; this game takes at most {rules['maxBytes']:,}")
        endings = tuple(e.lower() for e in self.spec.get("refuse", []))
        refused = sorted(p for p in payload if endings and p.lower().endswith(endings))
        if refused:
            found.append("this game's uploader refuses " + ", ".join(refused[:5]) + (" and more" if len(refused) > 5 else ""))
        return found

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
        kind, key = self.id_spec["format"], self.id_spec.get("key", "id")
        if kind == "text":
            values = [text]
        elif kind == "xmltag":
            values = re.findall(rf"<{re.escape(key)}>\s*(\d*)\s*</{re.escape(key)}>", text, re.IGNORECASE)
        else:
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
        kind, key = self.id_spec["format"], self.id_spec.get("key", "id")
        if kind == "text":
            data = item_id
        elif kind == "xmltag":
            if not path.is_file():
                return []       # the game's own tool writes this file; only a file it made is kept in step
            text = path.read_text(encoding="utf-8-sig")
            tag = re.compile(rf"<{re.escape(key)}>\s*\d*\s*</{re.escape(key)}>", re.IGNORECASE)
            if tag.search(text):
                data = tag.sub(f"<{key}>{item_id}</{key}>", text, count=1)
            else:
                closing = text.rstrip().rfind("</")
                if closing < 0:
                    return []
                data = text[:closing] + f"  <{key}>{item_id}</{key}>\n" + text[closing:]
        else:
            sep = self.id_spec.get("separator", "=")
            lines = path.read_text(encoding="utf-8-sig").splitlines() if path.is_file() else []
            line_key = (lambda line: (line.strip().split(None, 1) or [""])[0]) if sep == " " else \
                (lambda line: line.partition(sep)[0].strip())
            hit = [i for i, line in enumerate(lines) if line_key(line).lower() == key.lower()]
            new = f"{key}{sep}{item_id}"
            before = self.id_spec.get("before")
            if hit:
                lines[hit[0]] = new
            elif before and before in [line.strip() for line in lines]:
                lines.insert([line.strip() for line in lines].index(before), new)
            else:
                lines.append(new)
            data = "\n".join(lines) + "\n"
        atomic_write(path, data.encode("utf-8"))
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
