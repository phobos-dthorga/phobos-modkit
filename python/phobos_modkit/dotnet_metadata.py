"""The types a .NET assembly defines, read from its metadata tables in pure Python: never loaded, never run. Game-free.

The kit's C# reader (`assemblies.py`, dotnet/PhobosModKit.Assemblies) answers far more (members, calls, Harmony patches), but needs
the .NET SDK. This one needs nothing beyond Python, so a single-file tool a modder downloads (`bundle`) can still read the
assemblies a mod ships: each type's full name, base type, instance fields with what they hold, enum members, and whether the type
reads its own XML. Written from the metadata format as ECMA-335 partition II (sections 22 to 24) describes it, in our own words.

Python 3.9 or newer, standard library only: a bundled tool promises 3.9.
"""
from __future__ import annotations

from pathlib import Path

# Element types of a field's signature (ECMA-335 II.23.1.16), as a check of an XML value needs them: what text the field takes.
PRIMITIVES = {0x02: 'bool', 0x03: 'char', 0x04: 'int', 0x05: 'int', 0x06: 'int', 0x07: 'int', 0x08: 'int', 0x09: 'int', 0x0A: 'int',
              0x0B: 'int', 0x0C: 'float', 0x0D: 'float', 0x0E: 'string', 0x18: 'int', 0x19: 'int', 0x1C: 'object'}
LIST_TYPE = 'System.Collections.Generic.List`1'


def _compressed(data, at):
    first = data[at]
    if first & 0x80 == 0:
        return first, at + 1
    if first & 0xC0 == 0x80:
        return ((first & 0x3F) << 8) | data[at + 1], at + 2
    return ((first & 0x1F) << 24) | (data[at + 1] << 16) | (data[at + 2] << 8) | data[at + 3], at + 4


def read_assembly_types(path):
    """The types an assembly defines, from its metadata tables: {full name: info}. Each info holds 'base' (the base type's full
    name, or None), 'fields' (instance fields: {name: kind}), 'members' (an enum's values), 'custom' (it reads its own XML through
    LoadDataFromXmlCustom), 'enum' and 'abstract' (abstract or an interface). A kind is ('prim', 'int'|'float'|'bool'|'string'|
    'char'|'object'), ('type', full name), ('list', kind) for a List<T> or an array, or ('other', a generic's name or None). A
    nested type has a key of its own after '#', which no XML Class attribute can name. An empty dict for a file that is no .NET
    assembly, or one this reader cannot follow."""
    data = Path(path).read_bytes()

    def u16(at):
        return int.from_bytes(data[at:at + 2], 'little')

    def u32(at):
        return int.from_bytes(data[at:at + 4], 'little')

    try:
        pe = u32(0x3C)
        if data[:2] != b'MZ' or data[pe:pe + 4] != b'PE\0\0':
            return {}
        optional, optional_size = pe + 24, u16(pe + 20)
        directories = optional + (96 if u16(optional) == 0x10B else 112)
        cli = u32(directories + 14 * 8)
        if not cli:
            return {}
        table = optional + optional_size
        sections = [(u32(at + 12), max(u32(at + 8), u32(at + 16)), u32(at + 20)) for at in range(table, table + 40 * u16(pe + 6), 40)]

        def offset(rva):
            return next(rva - start + raw for start, size, raw in sections if start <= rva < start + size)

        meta = offset(u32(offset(cli) + 8))
        if data[meta:meta + 4] != b'BSJB':
            return {}
        length = u32(meta + 12)
        streams, at = {}, meta + 20 + length
        for _ in range(u16(meta + 18 + length)):
            end = data.index(b'\0', at + 8)
            streams[data[at + 8:end].decode('ascii')] = meta + u32(at)
            at += 8 + ((end - at - 8) // 4 + 1) * 4
        tables = streams.get('#~', streams.get('#-'))
        heaps, valid = data[tables + 6], int.from_bytes(data[tables + 8:tables + 16], 'little')
        rows, at = [0] * 64, tables + 24
        for number_ in range(64):
            if valid >> number_ & 1:
                rows[number_], at = u32(at), at + 4
        string_size, guid_size, blob_size = (4 if heaps & bit else 2 for bit in (1, 2, 4))

        def index_size(of):
            return 4 if rows[of] > 0xFFFF else 2

        def coded_size(of, bits):
            return 4 if max(rows[t] for t in of) >= 1 << (16 - bits) else 2

        type_ref = coded_size((2, 1, 0x1B), 2)
        widths = [[2, string_size, guid_size, guid_size, guid_size],                     # Module
                  [coded_size((0, 0x1A, 0x23, 1), 2), string_size, string_size],          # TypeRef
                  [4, string_size, string_size, type_ref, index_size(4), index_size(6)],  # TypeDef
                  [index_size(4)],                                                        # FieldPtr
                  [2, string_size, blob_size],                                            # Field
                  [index_size(6)],                                                        # MethodPtr
                  [4, 2, 2, string_size, blob_size, index_size(8)]]                       # MethodDef
        starts = []
        for number_, width in enumerate(widths):
            starts.append(at)
            at += rows[number_] * sum(width)

        def row(of, index):
            at_ = starts[of] + (index - 1) * sum(widths[of])
            values = []
            for width in widths[of]:
                values.append(u16(at_) if width == 2 else u32(at_))
                at_ += width
            return values

        def string(index):
            start = streams['#Strings'] + index
            return data[start:data.index(b'\0', start)].decode('utf-8', 'replace')

        def blob(index):
            size, start = _compressed(data, streams['#Blob'] + index)
            return data[start:start + size]

        definitions = [row(2, i) for i in range(1, rows[2] + 1)]

        def full_name(name, namespace):
            return f'{string(namespace)}.{string(name)}' if string(namespace) else string(name)

        def definition_name(index):
            # A nested type has no namespace of its own and may share its name with another: it gets a key of its own,
            # after '#', which no Class attribute can name.
            flags, name, namespace = definitions[index - 1][:3]
            return f'{string(name)}#{Path(path).stem}:{index}' if flags & 7 >= 2 else full_name(name, namespace)

        def coded(value):
            tag, index = value & 3, value >> 2
            if index == 0:
                return None
            if tag == 0:
                return definition_name(index)
            if tag == 1:
                return full_name(*row(1, index)[1:3])
            return '<generic>'

        def signature_type(signature, at_):
            kind = signature[at_]
            at_ += 1
            while kind in (0x1F, 0x20):  # custom modifiers
                at_ = _compressed(signature, at_)[1]
                kind, at_ = signature[at_], at_ + 1
            if kind in PRIMITIVES:
                return ('prim', PRIMITIVES[kind]), at_
            if kind in (0x11, 0x12):
                value, at_ = _compressed(signature, at_)
                return ('type', coded(value)), at_
            if kind == 0x15:
                value, at_ = _compressed(signature, at_ + 1)
                generic = coded(value)
                count, at_ = _compressed(signature, at_)
                arguments = []
                for _ in range(count):
                    argument, at_ = signature_type(signature, at_)
                    arguments.append(argument)
                if generic == LIST_TYPE:
                    return ('list', arguments[0]), at_
                return ('other', generic), at_
            if kind == 0x1D:
                inner, at_ = signature_type(signature, at_)
                return ('list', inner), at_
            return ('other', None), len(signature)

        def field_row(index):
            return row(4, row(3, index)[0] if rows[3] else index)

        def method_row(index):
            return row(6, row(5, index)[0] if rows[5] else index)

        types = {}
        field_count, method_count = rows[3] or rows[4], rows[5] or rows[6]
        for number_, (flags, name, namespace, extends, first_field, first_method) in enumerate(definitions):
            following = definitions[number_ + 1] if number_ + 1 < len(definitions) else None
            last_field = following[4] if following else field_count + 1
            last_method = following[5] if following else method_count + 1
            fields, members = {}, []
            for index in range(first_field, last_field):
                field_flags, field_name, field_signature = field_row(index)
                label = string(field_name)
                if field_flags & 0x10:  # static: an enum's members are its static literal fields
                    if field_flags & 0x40:
                        members.append(label)
                    continue
                if '<' not in label:
                    fields[label] = signature_type(blob(field_signature), 1)[0]
            methods = {string(method_row(index)[3]) for index in range(first_method, last_method)}
            base = coded(extends)
            types[definition_name(number_ + 1)] = {
                'base': base, 'fields': fields, 'members': members, 'custom': 'LoadDataFromXmlCustom' in methods,
                'enum': base == 'System.Enum', 'abstract': bool(flags & 0xA0)}  # abstract or an interface
        return types
    except (IndexError, KeyError, StopIteration, TypeError, ValueError):
        return {}


class TypeIndex:
    """Types read from a set of assemblies: which exist, what fields each has (its own and its bases'), and which are "ours".

    A subclass (or a game's adapter) says two things: KNOWN_BASES, the fields of base types that live in assemblies not read
    (a game's own, the runtime's), so a type built on them still has a complete list; and OWN_PREFIXES, the namespace prefixes
    whose classes are the reader's own, so a name in one of those namespaces that no assembly defines is a mistake rather than
    another author's class."""

    KNOWN_BASES = {'System.Object': {}, 'System.ValueType': {}}
    OWN_PREFIXES = ()

    def __init__(self, types, assemblies=()):
        self.types = types
        self.assemblies = list(assemblies)
        self.namespaces = {name.rsplit('.', 1)[0] for name in types
                           if '.' in name and any(name.startswith(prefix) for prefix in self.OWN_PREFIXES)}

    @classmethod
    def from_assemblies(cls, paths):
        """The index of every type in these assemblies (a later file's type replaces an earlier one's of the same name), or None
        when none of them could be read."""
        types, read = {}, []
        for path in paths:
            found = read_assembly_types(path)
            if found:
                read.append(path)
                types.update(found)
        return cls(types, read) if types else None

    def ours(self, class_name):
        """Whether a class name lies in one of our namespaces (a nested '+' name never does)."""
        return '+' not in class_name and class_name.rsplit('.', 1)[0] in self.namespaces

    def fields(self, name):
        """Every field of the type and the types it is built on, and whether that list is known to be complete: not when a type
        on the way is unknown, or reads its own XML."""
        fields, seen = {}, set()
        while name is not None and name not in seen:
            seen.add(name)
            if name in self.KNOWN_BASES:
                for field, kind in self.KNOWN_BASES[name].items():
                    fields.setdefault(field, kind)
                return fields, True
            info = self.types.get(name)
            if info is None or info['custom']:
                return fields, False
            for field, kind in info['fields'].items():
                fields.setdefault(field, kind)
            name = info['base']
        return fields, name is None
