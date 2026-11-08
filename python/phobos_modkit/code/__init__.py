"""code: find, outline and show the types and members of C# source trees, and every line that uses a name.

Built for decompiled game and mod assemblies, which a researcher keeps on their own machine (they are never committed),
and for a project's own source. Each tree (a "corpus") is indexed once into SQLite in the kit's cache: every namespace,
type and member with its first and last line. Lookups then cost a query instead of reading hundreds of thousands of
lines; finding uses scans the files directly, which is fast enough (80 MB in about 3 s cold) to need no text index.

    code find "*ApplyDamage*"               declarations whose name matches
    code outline VehicleStatHandler         a type's members, with their lines
    code show VehicleStatHandler.ApplyDamage   one member's source, numbered
    code refs HighlightedComponent          every line using a name, grouped by the member it is in

The scanner reads C# as decompilers and tidy hand-written code lay it out; it is not a compiler. See docs/code.md.
"""
