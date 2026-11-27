"""A mod's XML patches applied to a combined <Defs> document without the game, so far as ElementTree's XPath can follow them.

For checks of a mod's own files (phobos-rimworld's vehicle schema checker is the first). patched_defs.py reads the result the game
itself wrote; this applies the operations here, so a check sees what a patch would make of the Defs it targets, and which patch
to blame. Summarised in our own words from the 1.7 game code (Verse.PatchOperation and its subclasses):

- Followed: PatchOperationAdd (order Prepend or Append), Insert, Remove, Replace, AttributeSet, AttributeAdd, AttributeRemove,
  Sequence, Conditional (match or nomatch), and FindMod, which is taken as if the mods it looks for are active. A Sequence
  applies every operation in it, where the game stops at the first that fails, so each one is checked.
- An xpath is followed when it starts at Defs (or with //) and ElementTree's XPath can read it: no '|' and no functions. Anything
  else, and any other operation class, is noted, never guessed at.
- A patch that matches nothing fails at load unless its <success> is Always or Invert.

Which patches count is the caller's: `mentions(xpath)` says whether an xpath concerns the Defs being checked, and only those
are reported. Python 3.9 or newer, standard library only: a bundled tool promises 3.9.
"""
from __future__ import annotations

import copy
import re

from .mod_xml import FROM, items, line_of, text


def xpath_targets(document, xpath):
    """What an xpath selects in the combined Defs, or None when it uses XPath this module cannot follow."""
    path = (xpath or '').strip()
    if not path or '|' in path or re.search(r'\w\(', path):
        return None
    if path.startswith('//'):
        path = './/' + path[2:]
    else:
        path = path.lstrip('/')
        if path == 'Defs':
            return [document]
        if not path.startswith('Defs/'):
            return None
        path = './' + path[5:]
    try:
        return document.findall(path)
    except (SyntaxError, KeyError, TypeError):
        return None


class Patcher:
    """Patch operations applied to a combined <Defs> document as the game applies them, in the order given.

    findings lists (severity, source, line, problem): 'error' for a patch that changes nothing, 'note' for one not followed,
    only for xpaths `mentions` accepts. touched maps id(top-level Def) to (source, line) of the first patch that changed it, and
    each element a patch put in carries FROM, its patch file."""

    SIMPLE = {'PatchOperationAdd', 'PatchOperationInsert', 'PatchOperationRemove', 'PatchOperationReplace',
              'PatchOperationAttributeSet', 'PatchOperationAttributeAdd', 'PatchOperationAttributeRemove'}

    def __init__(self, document, mentions=None):
        self.document = document
        self.mentions = mentions if mentions is not None else (lambda xpath: True)
        self.touched, self.findings = {}, []

    def concerns(self, xpath):
        return bool(xpath) and self.mentions(xpath)

    def apply(self, patch, source):
        """Every <Operation> of a <Patch> document, from the file named source."""
        for operation in patch:
            if isinstance(operation.tag, str) and operation.tag == 'Operation':
                self.run(operation, source)

    def run(self, operation, source):
        """One operation; whether it succeeded, as a Sequence or Conditional needs it."""
        kind = operation.attrib.get('Class', '').rsplit('.', 1)[-1]
        xpath = text(operation, 'xpath')
        if kind == 'PatchOperationSequence':
            results = [self.run(li, source) for li in items(operation, 'operations')]
            return all(results)
        if kind == 'PatchOperationFindMod':  # taken as if the mods it looks for are active
            match = operation.find('match')
            return True if match is None else self.run(match, source)
        if kind == 'PatchOperationConditional':
            targets = xpath_targets(self.document, xpath)
            branch = operation.find('match' if targets or targets is None else 'nomatch')
            return True if branch is None else self.run(branch, source)
        if kind not in self.SIMPLE:
            if self.concerns(xpath):
                self.note(operation, source, f'a {kind or "patch"} on {xpath} was not followed')
            return True
        targets = xpath_targets(self.document, xpath)
        if targets is None:
            if self.concerns(xpath):
                self.note(operation, source, f'the patch on {xpath} was not followed: its XPath is beyond this check')
            return True
        if not targets:
            if self.concerns(xpath) and text(operation, 'success', 'Normal') not in ('Always', 'Invert'):
                self.findings.append(('error', source, line_of(operation), f'the patch on {xpath} changes nothing: no Def matches it'))
            return False
        parents = {child: parent for parent in self.document.iter() for child in parent}
        for target in targets:
            self.change(kind, operation, target, parents.get(target), source)
            top = target
            while parents.get(top) is not None and parents[top] is not self.document:
                top = parents[top]
            if top is not self.document:
                self.touched.setdefault(id(top), (source, line_of(operation)))
        return True

    def values(self, operation, source):
        copies = [copy.deepcopy(node) for node in (operation.find('value') if operation.find('value') is not None else [])]
        for node in copies:
            for element in node.iter():
                element.attrib[FROM] = source
        return copies

    def change(self, kind, operation, target, parent, source):
        order = text(operation, 'order')
        if kind == 'PatchOperationAdd':
            values = self.values(operation, source)
            for value in (reversed(values) if order == 'Prepend' else values):
                target.insert(0, value) if order == 'Prepend' else target.append(value)
        elif kind in ('PatchOperationInsert', 'PatchOperationReplace') and parent is not None:
            at = list(parent).index(target) + (1 if kind == 'PatchOperationInsert' and order == 'Append' else 0)
            for offset_, value in enumerate(self.values(operation, source)):
                parent.insert(at + offset_, value)
            if kind == 'PatchOperationReplace':
                parent.remove(target)
        elif kind == 'PatchOperationRemove' and parent is not None:
            parent.remove(target)
        elif kind in ('PatchOperationAttributeSet', 'PatchOperationAttributeAdd'):
            if kind == 'PatchOperationAttributeSet' or text(operation, 'attribute') not in target.attrib:
                target.attrib[text(operation, 'attribute')] = text(operation, 'value', '')
        elif kind == 'PatchOperationAttributeRemove':
            target.attrib.pop(text(operation, 'attribute'), None)

    def note(self, operation, source, problem):
        self.findings.append(('note', source, line_of(operation), problem))
