"""One RimWorld mod's XML read straight from its folder, without the game: Defs, patches and translation keys with the line each
element starts on, XML inheritance across mods, and the base types every Def is built on.

For checks of a mod's own files (phobos-rimworld's vehicle schema checker is the first), where defs.py's index answers questions
about every active mod. Summarised in our own words from the 1.7 game code (Verse.XmlInheritance, Verse.Def) and from checks run
against real mods:

- Inheritance: a child's elements override its parent's; a list's items (<li>) are added after the parent's, unless the list says
  Inherit="False", which replaces the parent's element whole; a Def is Abstract only when it says so itself.
- A parent is looked for among Defs of the same type, in the child's own mod first, then in any other mod read with it.
- Every Def is built on Verse.Def, whose fields are known here (KNOWN_BASES), as the game's own assembly is never read.

Lines come from expat as each file is read, kept on an attribute in a namespace of the kit's own (LINE), which survives
inheritance and patches; FROM marks what a patch put in (xml_patches.py). Python 3.9 or newer, standard library only: a bundled
tool promises 3.9.
"""
from __future__ import annotations

import copy
from pathlib import Path
import xml.etree.ElementTree as ET
import xml.parsers.expat as expat

from ...dotnet_metadata import TypeIndex

LINE = '{urn:phobos-modkit}line'  # the line an element starts on, kept through inheritance and patches
FROM = '{urn:phobos-modkit}from'  # the patch file an element was copied in from

# Verse.Def's fields (RimWorld 1.7), the base of every Def; its own assembly is the game's, which these checks never read.
STRING, BOOL = ('prim', 'string'), ('prim', 'bool')
DEF_FIELDS = {'defName': STRING, 'label': STRING, 'description': STRING, 'descriptionHyperlinks': ('other', None),
              'ignoreConfigErrors': BOOL, 'ignoreIllegalLabelCharacterConfigError': BOOL,
              'modExtensions': ('list', ('type', 'Verse.DefModExtension')), 'shortHash': ('prim', 'int'), 'index': ('prim', 'int'),
              'modContentPack': ('other', None), 'fileName': STRING, 'defNameHash': ('prim', 'int'),
              'cachedLabelCap': ('other', None), 'generated': BOOL, 'debugRandomId': ('prim', 'int')}
KNOWN_BASES = {'System.Object': {}, 'System.ValueType': {}, 'Verse.Def': DEF_FIELDS, 'Verse.Editable': {}}


class DefTypeIndex(TypeIndex):
    """A type index (dotnet_metadata.TypeIndex) that knows the base types every RimWorld Def is built on."""

    KNOWN_BASES = KNOWN_BASES


def text(element, tag, default=None):
    """The stripped text of an element's first child with this tag, or default when there is none or it is empty."""
    found = element.find(tag)
    return default if found is None or found.text is None else found.text.strip()


def items(element, tag):
    """The <li> items of an element's child list with this tag; none when there is no such child."""
    found = element.find(tag)
    return [] if found is None else [li for li in found.findall('li')]


def parse_lines(path):
    """An XML file as ElementTree reads it, each element also holding the line it starts on (under LINE). Raises
    expat.ExpatError for a file that is not well-formed."""
    builder = ET.TreeBuilder()
    parser = expat.ParserCreate()

    def start(tag, attributes):
        attributes = dict(attributes)
        attributes[LINE] = str(parser.CurrentLineNumber)
        builder.start(tag, attributes)

    parser.StartElementHandler = start
    parser.EndElementHandler = builder.end
    parser.CharacterDataHandler = builder.data
    with open(path, 'rb') as stream:
        parser.ParseFile(stream)
    return builder.close()


def line_of(element):
    """The line an element read by parse_lines starts on, or None for one made otherwise."""
    value = element.attrib.get(LINE)
    return int(value) if value else None


def package_id(folder):
    """A mod's packageId as its About/About.xml writes it (case kept), or '' when it has none or the file cannot be read.
    mods.py's reader is more forgiving of a broken About.xml, and lowers the case, for the installed-mods index."""
    try:
        return (ET.parse(Path(folder, 'About', 'About.xml')).getroot().findtext('packageId') or '').strip()
    except (OSError, ET.ParseError):
        return ''


def folder_files(folders):
    """Every Defs and Patches XML file in these load folders, and every Languages/<language>/Keyed one, each once, folder by
    folder. Unlike the game, a file at the same path in two load folders is read from both (loading.xml_files picks one)."""
    found = []
    for folder in folders:
        for sub in ('Defs', 'Patches'):
            found += sorted(Path(folder, sub).rglob('*.xml'))
        found += sorted(Path(folder, 'Languages').glob('*/Keyed/**/*.xml'))
    return list(dict.fromkeys(found))


class ModXml:
    """One mod's Def nodes, patch documents and translation keys from a set of load folders, each Def and patch with its source:
    label/path inside the mod folder. A file that is not well-formed is left out and listed in broken as (source, line, what)."""

    def __init__(self, folder, label, folders):
        self.folder, self.label = Path(folder), label
        self.defs, self.patches, self.keys, self.broken = [], [], set(), []
        for path in folder_files(folders):
            source = f'{label}/{path.relative_to(self.folder).as_posix()}'
            try:
                tree = parse_lines(path)
            except expat.ExpatError as error:
                self.broken.append((source, error.lineno, f'the file is not well-formed XML ({expat.ErrorString(error.code)})'))
                continue
            if 'Keyed' in path.relative_to(self.folder).parts:
                self.keys.update(child.tag for child in tree)
            elif tree.tag == 'Defs':
                self.defs += [(node, source) for node in tree if isinstance(node.tag, str)]
            elif tree.tag == 'Patch':
                self.patches.append((tree, source))


def merge(parent, child):
    """A child Def merged onto a copy of its parent, as XML inheritance does: the child's attributes but the parent's Name, the
    child's Abstract only; a child element with Inherit="False", or one the parent lacks, or an <li>, is added (replacing the
    parent's element of that name); a list of <li> is appended to the parent's; an element with children is merged in turn; a
    leaf takes the child's text and attributes."""
    result = copy.deepcopy(parent)
    result.attrib.update({k: v for k, v in child.attrib.items() if k not in ('Name', 'Abstract')})
    result.attrib.pop('Abstract', None)
    if child.attrib.get('Abstract') == 'True':
        result.attrib['Abstract'] = 'True'
    result.text = child.text
    for node in child:
        existing = result.find(node.tag)
        if node.attrib.get('Inherit') == 'False' or existing is None or node.tag == 'li':
            if existing is not None and node.tag != 'li':
                result.remove(existing)
            result.append(copy.deepcopy(node))
        elif len(node) and all(grand.tag == 'li' for grand in node):
            for grand in node:
                existing.append(copy.deepcopy(grand))
        elif len(node):
            replaced = merge(existing, node)
            index = list(result).index(existing)
            result.remove(existing)
            result.insert(index, replaced)
        else:
            existing.text = node.text
            existing.attrib.update(node.attrib)
    return result


def resolve_defs(nodes, owner_of, tags=()):
    """XML inheritance over Defs from several mods together. nodes is [(node, source)]; owner_of maps id(node) to the mod (any
    label) each came from, and a parent is looked for in the child's own mod first, then in any other, among Defs of its own type.

    Returns ({tag: [(resolved node, source)]} for every Def that is not Abstract, with a key for each of tags first, in that
    order; the nodes whose ParentName was found nowhere; {id(resolved): the node as written}). owner_of gains each resolved
    node's owner. A loop of parents stops where it would repeat."""
    by_owner = {}
    for node, source in nodes:
        if 'Name' in node.attrib:
            by_owner.setdefault((node.tag, owner_of[id(node)]), {})[node.attrib['Name']] = node
    missing = []

    def parent_of(node):
        name, owner = node.attrib.get('ParentName'), owner_of[id(node)]
        own = by_owner.get((node.tag, owner), {})
        if name in own:
            return own[name]
        for (tag, other), named in by_owner.items():
            if tag == node.tag and name in named:
                return named[name]
        return None

    def resolve(node, seen=()):
        name = node.attrib.get('ParentName')
        if not name or name in seen:
            return node
        parent = parent_of(node)
        if parent is None:
            missing.append(node)
            return node
        return merge(resolve(parent, seen + (name,)), node)

    resolved, original_of = {tag: [] for tag in tags}, {}
    for node, source in nodes:
        if node.attrib.get('Abstract') != 'True':
            result = resolve(node)
            owner_of[id(result)], original_of[id(result)] = owner_of[id(node)], node
            resolved.setdefault(node.tag, []).append((result, source))
        elif node.attrib.get('ParentName'):
            resolve(node)  # an abstract Def's parent is looked for too
    return resolved, missing, original_of
