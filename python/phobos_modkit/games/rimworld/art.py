"""RimWorld's half of the art audit: the names a texture answers to, and every place a repository's Defs and code use one.

A texture is loaded by its path below a mod's `Textures` folder, without the extension. A `Graphic_Multi` adds a facing
(`_north`, `_south`, `_east`, `_west`), a mask adds `m` (`_northm`, `_m`), and `Graphic_Random` or `Graphic_Appearances`
names the folder. So an image answers to its own path, to that path without facing and mask, and to its folder.

Uses come from the repository's XML and C#:

- **Defs** (`<Defs>` files): every leaf whose text is the name of one of our images, and every texture field (`texPath`,
  `iconPath`, `uiIconPath`, `icon`, and any tag ending in TexPath, IconPath or Texture) whose path is not ours. A list item with
  a `key`, `defName` or `label` names the part of the Def it belongs to, such as an upgrade node. ElementTree drops comments.
- **Inheritance**: a Def takes the texture fields of its parent (`ParentName`, our Defs only) that it does not write itself,
  outside list items. An abstract parent's own fields are reported only when nothing of ours inherits them.
- **Patches** (`<Patch>` files): an operation's value, owned by the first defName its xpath names.
- **C#**: string literals given to `ContentFinder<Texture2D>.Get`, `GraphicDatabase.Get<...>` or `MaterialPool.MatFrom`, and any
  literal that is the name of one of our images, owned by the class it is in. A class is not the thing a picture shows, so code
  is judged only on whether the picture is ours, never borrowed from another of our things.
"""
from __future__ import annotations

from pathlib import Path, PurePosixPath
import re
import xml.etree.ElementTree as ET

from ...artaudit import Use

TEXTURES = "Textures"
DEFAULT_DEFS = ("**/Defs/**/*.xml", "**/Patches/**/*.xml")
TEXTURE_FIELDS = {"texpath", "iconpath", "uiiconpath", "icon", "texture", "expandingicontexture", "graphicpath",
                  "cornertl", "cornertr", "cornerbl", "cornerbr"}
TEXTURE_ENDINGS = ("texpath", "iconpath", "texture")
NOT_TEXTURE_FIELDS = {"clippath", "clipfolderpath", "defname", "xpath"}
PART_KEYS = ("key", "defName", "label")
_FACING = re.compile(r"(?:_(?:north|south|east|west)(?:_?m)?|_m)$", re.IGNORECASE)
_PATHLIKE = re.compile(r"^[\w.\-]+(?:/[\w.\-]+)*$")
_XPATH_DEF = re.compile(r"defName\s*=\s*[\"']([^\"']+)[\"']")
_CS_CALL = re.compile(r"(ContentFinder<Texture2D>\.Get|GraphicDatabase\.Get<[^>]+>|MaterialPool\.MatFrom)\(\s*@?\"([^\"]+)\"")
_CS_LITERAL = re.compile(r"\"([\w.\-]+(?:/[\w.\-]+)+)\"")
_CS_CLASS = re.compile(r"\b(?:class|struct|record)\s+(\w+)")
_CS_BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.DOTALL)
_CS_LINE_COMMENT = re.compile(r"(^|\s)//[^\n]*")
CHAIN_LIMIT = 12

LIMITS = (
    "Defs are read as this repository writes them: other mods' patches are not applied, and a Def that takes its picture "
    "from another mod's parent (the game's, Vanilla Expanded's) is not seen.",
    "Code is read for literal names; a name put together at run time is not seen.",
    "A use is borrowed when other users of the picture share a word with its path and this one shares none; a picture "
    "nobody's name matches counts as shared.",
)


def image_names(path):
    """The names the game loads this image by, lower case: its path below Textures, without facing and mask, its folder."""
    parts = PurePosixPath(path).parts
    if TEXTURES not in parts:
        return []
    at = len(parts) - 1 - parts[::-1].index(TEXTURES)
    inner = parts[at + 1:]
    if not inner:
        return []
    key = "/".join(inner)
    key = key[: -len(PurePosixPath(key).suffix)] if PurePosixPath(key).suffix else key
    names = [key, _FACING.sub("", key)]
    if len(inner) > 1:
        names.append("/".join(inner[:-1]))
    seen, found = set(), []
    for name in names:
        if name and name.lower() not in seen:
            seen.add(name.lower())
            found.append(name)
    return found


def _is_texture_field(tag, extra):
    low = tag.lower()
    if low in NOT_TEXTURE_FIELDS:
        return False
    return low in TEXTURE_FIELDS or low in extra or low.endswith(TEXTURE_ENDINGS)


def _part(element):
    for key in PART_KEYS:
        child = element.find(key)
        if child is not None and (child.text or "").strip():
            return child.text.strip()
    return ""


def _leaf_uses(element, owner_type, owner, file, names, extra, field_path=(), part=""):
    """Every texture use below element, as Use objects with their field paths."""
    found = []
    for child in element:
        if not isinstance(child.tag, str):
            continue
        path = field_path + (child.tag,)
        child_part = (_part(child) or part) if child.tag == "li" else part
        if len(child):
            found += _leaf_uses(child, owner_type, owner, file, names, extra, path, child_part)
            continue
        value = (child.text or "").strip().replace("\\", "/")
        if not value or not _PATHLIKE.match(value) or child.tag.lower() in NOT_TEXTURE_FIELDS:
            continue
        images = names.get(value.lower(), [])
        if images or (_is_texture_field(child.tag, extra) and "/" in value):
            found.append(Use(owner_type, owner, "/".join(path), value, file, part=child_part, images=list(images)))
    return found


def _parse(path):
    try:
        return ET.parse(path).getroot(), None
    except (ET.ParseError, OSError) as error:
        return None, str(error)


def _def_uses(root, rel, names, extra):
    """[(def record, own uses)] for a <Defs> file."""
    found = []
    for element in root:
        if not isinstance(element.tag, str):
            continue
        name_attr = element.get("Name", "")
        def_name = (element.findtext("defName") or "").strip()
        owner = def_name or name_attr or f"(unnamed {element.tag})"
        record = {"type": element.tag, "owner": owner, "name": name_attr, "parent": element.get("ParentName", ""),
                  "abstract": element.get("Abstract", "").lower() == "true", "file": rel}
        found.append((record, _leaf_uses(element, element.tag, owner, rel, names, extra)))
    return found


def _patch_uses(root, rel, names, extra):
    found = []
    for operation in root.iter():
        xpath, value = operation.find("xpath"), operation.find("value")
        if xpath is None or value is None:
            continue
        target = _XPATH_DEF.search(xpath.text or "")
        owner = target.group(1) if target else "(patch)"
        found += _leaf_uses(value, "Patch", owner, rel, names, extra)
    return found


def _inherit(defs):
    """Each Def's uses with its parents' texture fields it does not write itself (not list items), our Defs only."""
    by_name = {}
    for record, _ in defs:
        if record["name"]:
            by_name[record["name"]] = (record, _)
    children = {}
    for record, _ in defs:
        if record["parent"] in by_name:
            children.setdefault(record["parent"], []).append(record)
    result = []
    for record, own in defs:
        if record["abstract"] and children.get(record["name"]):
            continue
        uses = list(own)
        written = {u.field for u in own}
        parent, depth = record["parent"], 0
        while parent in by_name and depth < CHAIN_LIMIT:
            parent_record, parent_uses = by_name[parent]
            for use in parent_uses:
                if "/li" in f"/{use.field}" or use.field in written:
                    continue
                written.add(use.field)
                uses.append(Use(record["type"], record["owner"], use.field, use.texture, use.file, part=use.part,
                                inherited_from=parent_record["owner"], images=list(use.images)))
            parent, depth = parent_record["parent"], depth + 1
        result += uses
    return result


def _strip_comments(text):
    return _CS_LINE_COMMENT.sub(r"\1", _CS_BLOCK_COMMENT.sub("", text))


def _code_uses(text, rel, names):
    text = _strip_comments(text)
    classes = [(m.start(), m.group(1)) for m in _CS_CLASS.finditer(text)]

    def owner_at(position):
        name = Path(rel).stem
        for start, found in classes:
            if start > position:
                break
            name = found
        return name

    found, taken = [], set()
    for match in _CS_CALL.finditer(text):
        value = match.group(2).replace("\\", "/")
        taken.add(match.start(2))
        found.append(Use("C#", owner_at(match.start()), match.group(1).split("(")[0].split("<")[0], value, rel,
                         images=list(names.get(value.lower(), [])), loose=True))
    for match in _CS_LITERAL.finditer(text):
        if match.start(1) in taken:
            continue
        images = names.get(match.group(1).lower())
        if images:
            found.append(Use("C#", owner_at(match.start()), "literal", match.group(1), rel, images=list(images), loose=True))
    return found


def _glob(root, patterns):
    files = set()
    for pattern in patterns:
        files.update(p for p in root.glob(pattern) if p.is_file())
    return sorted(files)


def find_uses(root, config, names):
    """(uses, unreadable files) across the repository's Defs and code. names maps a lower-case name to our images."""
    root = Path(root)
    extra = {f.lower() for f in config.get("textureFields", [])}
    defs, uses, unreadable = [], [], []
    for path in _glob(root, config.get("defs", DEFAULT_DEFS)):
        rel = path.relative_to(root).as_posix()
        element, error = _parse(path)
        if element is None:
            unreadable.append(f"{rel}: {error}")
            continue
        if element.tag == "Defs":
            defs += _def_uses(element, rel, names, extra)
        elif element.tag == "Patch":
            uses += _patch_uses(element, rel, names, extra)
    uses = _inherit(defs) + uses
    for path in _glob(root, config.get("code", ())):
        rel = path.relative_to(root).as_posix()
        try:
            uses += _code_uses(path.read_text(encoding="utf-8", errors="replace"), rel, names)
        except OSError as error:
            unreadable.append(f"{rel}: {error}")
    return uses, unreadable
