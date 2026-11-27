"""A script and the kit modules it imports, made into one file that runs with Python alone. Game-free.

A tool for other people (phobos-rimworld's vehicle schema checker, for modders) is written against the kit like any script, then
bundled: the kit modules it imports, and the ones those import, are written into the file as text, and a few lines at its top put
them where `import phobos_modkit...` finds them, before the script's own imports run. The script and the modules are unchanged, so
the bundled file behaves as the script does beside the kit.

The same script and kit give the same file, byte for byte (the shared rule rules/builds.md): no date, commit or path goes in,
only the kit's version and the modules' names. A bundled module may import only the standard library and other kit modules, and
nothing from a package's __init__ (only phobos_modkit.__version__ is provided); the bundle refuses anything else, and checks the
syntax of every module against the oldest Python the file promises.
"""
from __future__ import annotations

import ast
import hashlib
from pathlib import Path
import sys

from . import __version__

PACKAGE = 'phobos_modkit'
KIT_ROOT = Path(__file__).resolve().parent
DEFAULT_PYTHON = (3, 10)  # the kit's own oldest Python
STANDARD = set(getattr(sys, 'stdlib_module_names', ())) | {'__future__'}


class BundleError(ValueError):
    """The script cannot be bundled: a module is missing, imports what a bundle cannot carry, or is newer than the Python promised."""


class Bundled:
    def __init__(self, text, modules, python):
        self.text = text            # the whole file
        self.modules = modules      # [(module name, lines)], in the order they are set up
        self.python = python        # the oldest Python checked, as (major, minor)

    @property
    def sha256(self):
        return hashlib.sha256(self.text.encode('utf-8')).hexdigest()


def module_file(name, kit_root=KIT_ROOT):
    """(path, is a package) for a kit module's name, or None when the kit has no such module."""
    parts = name.split('.')
    if parts[0] != PACKAGE:
        return None
    base = Path(kit_root).joinpath(*parts[1:])
    if len(parts) > 1 and base.with_suffix('.py').is_file():
        return base.with_suffix('.py'), False
    if (base / '__init__.py').is_file():
        return base / '__init__.py', True
    return None


def _is_kit(name):
    return name == PACKAGE or name.startswith(PACKAGE + '.')


def _imports(tree, module_name, is_package):
    """[(imported module's full name, names taken from it, line)] for every import in a module, at any depth, relative ones
    resolved against the module's own package."""
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found += [(alias.name, (), node.lineno) for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                package = module_name if is_package else module_name.rpartition('.')[0]
                parts = package.split('.')
                if node.level - 1 >= len(parts):
                    raise BundleError(f'{module_name}, line {node.lineno}: a relative import above the kit')
                base = '.'.join(parts[:len(parts) - (node.level - 1)])
                full = f'{base}.{node.module}' if node.module else base
            else:
                full = node.module or ''
            found.append((full, tuple(alias.name for alias in node.names), node.lineno))
    return found


def _kit_needs(imports, where, kit_root, check_standard):
    """The kit modules these imports need, sorted; a refusal for what a bundle cannot carry."""
    needs = set()
    for full, names, line in imports:
        if not _is_kit(full):
            if check_standard and full.split('.')[0] not in STANDARD:
                raise BundleError(f'{where}, line {line}: imports {full}, which is not in the standard library')
            continue
        found = module_file(full, kit_root)
        if found is None:
            raise BundleError(f'{where}, line {line}: the kit has no module {full}')
        attributes = []
        for name in names:
            sub = module_file(f'{full}.{name}', kit_root)
            if sub is not None and not sub[1]:
                needs.add(f'{full}.{name}')     # from a package import a module
            else:
                attributes.append(name)
        if not found[1]:
            needs.add(full)                     # import a module, or names from it
        elif attributes and not (full == PACKAGE and attributes == ['__version__']):
            raise BundleError(f'{where}, line {line}: takes {", ".join(attributes)} from the package {full}, whose __init__ is not '
                              f'bundled; import it from its own module')
    return sorted(needs)


def _parse(source, where, python):
    try:
        return ast.parse(source, filename=where, feature_version=python)
    except SyntaxError as error:
        raise BundleError(f'{where}, line {error.lineno}: not valid Python {python[0]}.{python[1]} ({error.msg})') from None


def _literal(source):
    """The source as a Python string literal: raw and triple-quoted, so it reads as code, unless that cannot hold it."""
    if "'''" not in source and source.endswith('\n'):
        return "r'''" + source + "'''"
    return repr(source)


LOADER = '''
def _phobos_modkit_bundle(version, modules):
    """Sets up the kit's modules bundled below, so `import phobos_modkit...` finds them with nothing installed."""
    import linecache
    import sys
    import types
    for name, source in modules:
        parts = name.split('.')
        for depth in range(1, len(parts)):
            package = '.'.join(parts[:depth])
            if package not in sys.modules:
                made = types.ModuleType(package)
                made.__path__ = []
                if depth == 1:
                    made.__version__ = version
                else:
                    setattr(sys.modules['.'.join(parts[:depth - 1])], parts[depth - 1], made)
                sys.modules[package] = made
        module = types.ModuleType(name)
        module.__package__ = '.'.join(parts[:-1])
        module.__file__ = '<bundled ' + name + '>'
        sys.modules[name] = module
        setattr(sys.modules[module.__package__], parts[-1], module)
        linecache.cache[module.__file__] = (len(source), None, source.splitlines(True), module.__file__)
        exec(compile(source, module.__file__, 'exec', dont_inherit=True), module.__dict__)
'''


def bundle(script, python=DEFAULT_PYTHON, kit_root=KIT_ROOT, version=__version__):
    """The script with the kit modules it needs set up at its top, as a Bundled. Raises BundleError for what cannot be bundled."""
    script = Path(script)
    source = script.read_text(encoding='utf-8')
    tree = _parse(source, script.name, python)
    roots = _kit_needs(_imports(tree, '__main__', False), script.name, kit_root, check_standard=False)
    if not roots:
        raise BundleError(f'{script.name} imports nothing from {PACKAGE}: there is nothing to bundle')
    order, sources, state = [], {}, {}

    def visit(name, chain):
        if state.get(name) == 'done':
            return
        if state.get(name) == 'open':
            raise BundleError('the kit modules import one another in a loop: ' + ' -> '.join(chain + (name,)))
        state[name] = 'open'
        path, is_package = module_file(name, kit_root)
        text = path.read_text(encoding='utf-8')
        module_tree = _parse(text, name, python)
        for need in _kit_needs(_imports(module_tree, name, is_package), name, kit_root, check_standard=True):
            visit(need, chain + (name,))
        state[name] = 'done'
        order.append(name)
        sources[name] = text if text.endswith('\n') else text + '\n'

    for name in roots:
        visit(name, ())
    lines = source.splitlines(keepends=True)
    body = tree.body
    at = 0
    if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) and isinstance(body[0].value.value, str):
        at = body[0].end_lineno
        body = body[1:]
    for node in body:
        if isinstance(node, ast.ImportFrom) and node.module == '__future__':
            at = node.end_lineno
        else:
            break
    rule = '# ' + '-' * 126
    block = [rule,
             f'# Bundled by phobos-modkit {version} (https://github.com/phobos-dthorga/phobos-modkit, MIT licence): the kit modules this',
             f'# script imports, set up here so it runs with Python {python[0]}.{python[1]} or newer and nothing else. Change the script or the kit',
             '# and bundle again, never this block.',
             rule]
    block += LOADER.strip('\n').split('\n')
    block += ['', '', '_phobos_modkit_bundle(' + repr(version) + ', (']
    for name in order:
        block.append(f'    ({name!r}, {_literal(sources[name])}),')
    block += ['))', 'del _phobos_modkit_bundle', rule]
    head = ''.join(lines[:at])
    if head and not head.endswith('\n'):
        head += '\n'
    text = head + ('\n' if head else '') + '\n'.join(block) + '\n\n' + ''.join(lines[at:]).lstrip('\n')
    _verify(text, order, sources, python)
    return Bundled(text, [(name, sources[name].count('\n')) for name in order], python)


def _verify(text, order, sources, python):
    """The bundled file parses, and every module in it reads back exactly as its source."""
    tree = _parse(text, 'the bundled file', python)
    call = next(node.value for node in tree.body if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call)
                and getattr(node.value.func, 'id', None) == '_phobos_modkit_bundle')
    pairs = ast.literal_eval(call.args[1])
    if [name for name, _ in pairs] != order or any(sources[name] != source for name, source in pairs):
        raise BundleError('a bundled module does not read back as its source')


def parse_python(text):
    """'3.9' as (3, 9)."""
    try:
        major, minor = (int(part) for part in text.split('.'))
    except ValueError:
        raise BundleError(f'--python takes a version such as 3.9, not {text}') from None
    return major, minor
