"""dotnet_metadata: types read from an assembly's metadata in pure Python, and the type index built on them.

The reading tests use the made-up mod assembly the C# reader's tests build (fixtures/dotnet/PatchFixture); without the .NET SDK
they are skipped, unless PHOBOS_REQUIRE_NATIVE is set. The index tests use types written by hand.
"""
import os
from pathlib import Path
import shutil
import tempfile
import unittest

import support  # noqa: F401  (puts the package on the import path)
from phobos_modkit.dotnet_metadata import TypeIndex, read_assembly_types
from phobos_modkit.games.rimworld.mod_xml import DefTypeIndex

HAVE_DOTNET = shutil.which("dotnet") is not None
REQUIRE = bool(os.environ.get("PHOBOS_REQUIRE_NATIVE"))


def kind(**info):
    return {"base": "System.Object", "fields": {}, "members": [], "custom": False, "enum": False, "abstract": False, **info}


class Ours(TypeIndex):
    OWN_PREFIXES = ("My",)


class Reading(unittest.TestCase):
    def test_a_file_that_is_no_assembly_gives_nothing(self):
        folder = Path(tempfile.mkdtemp())
        try:
            for name, content in (("empty.dll", b""), ("text.dll", b"not a real assembly"), ("mz.dll", b"MZ" + b"\0" * 200)):
                (folder / name).write_bytes(content)
                self.assertEqual(read_assembly_types(folder / name), {}, name)
        finally:
            shutil.rmtree(folder, ignore_errors=True)

    @unittest.skipUnless(HAVE_DOTNET or REQUIRE, "the .NET SDK builds the fixture assembly")
    def test_types_bases_fields_enums_and_abstract_classes(self):
        from test_rimworld_patches import fixture_dll
        types = read_assembly_types(fixture_dll())
        pawn, thing = types["Game.Pawn"], types["Game.Thing"]
        self.assertEqual(pawn["base"], "Game.Thing")
        self.assertEqual(pawn["fields"], {"health": ("prim", "float")}, "static fields are left out")
        self.assertEqual(thing["fields"], {"thingID": ("prim", "int")})
        self.assertEqual(thing["base"], "System.Object")
        method_type = types["HarmonyLib.MethodType"]
        self.assertTrue(method_type["enum"])
        self.assertEqual(method_type["members"][:3], ["Normal", "Getter", "Setter"])
        self.assertTrue(types["HarmonyLib.AccessTools"]["abstract"], "a static class is abstract in metadata")
        self.assertFalse(pawn["abstract"] or pawn["custom"] or pawn["enum"])
        index = TypeIndex.from_assemblies([fixture_dll()])
        self.assertEqual(index.fields("Game.Pawn"), ({"health": ("prim", "float"), "thingID": ("prim", "int")}, True))


class Index(unittest.TestCase):
    def index(self, cls=Ours):
        return cls({
            "My.Things.Base": kind(fields={"a": ("prim", "int")}),
            "My.Things.Child": kind(base="My.Things.Base", fields={"b": ("prim", "bool"), "a": ("prim", "float")}),
            "My.Things.Custom": kind(base="My.Things.Base", custom=True),
            "My.Things.OnTheirs": kind(base="Their.Unknown", fields={"c": ("prim", "string")}),
            "My.Things.ADef": kind(base="Verse.Def", fields={"d": ("prim", "int")}),
            "Their.Thing": kind(),
        })

    def test_fields_follow_the_bases_and_say_whether_they_are_complete(self):
        index = self.index()
        self.assertEqual(index.fields("My.Things.Child"), ({"b": ("prim", "bool"), "a": ("prim", "float")}, True),
                         "the child's own field wins")
        self.assertEqual(index.fields("My.Things.Custom"), ({}, False), "a type reading its own XML")
        self.assertEqual(index.fields("My.Things.OnTheirs"), ({"c": ("prim", "string")}, False), "built on a type not read")
        self.assertEqual(index.fields("Nowhere"), ({}, False))

    def test_a_game_adapter_knows_its_base_types(self):
        self.assertFalse(self.index().fields("My.Things.ADef")[1])
        fields, complete = self.index(type("RimWorldOurs", (DefTypeIndex,), {"OWN_PREFIXES": ("My",)})).fields("My.Things.ADef")
        self.assertTrue(complete)
        self.assertIn("defName", fields)
        self.assertEqual(fields["d"], ("prim", "int"))

    def test_ours_is_by_namespace(self):
        index = self.index()
        self.assertTrue(index.ours("My.Things.Missing"))
        self.assertFalse(index.ours("Their.Missing"))
        self.assertFalse(index.ours("My.Things.Base+Nested"))
        self.assertFalse(TypeIndex(index.types).ours("My.Things.Missing"), "no namespace is ours unless a subclass says so")

    def test_no_readable_assembly_gives_no_index(self):
        folder = Path(tempfile.mkdtemp())
        try:
            (folder / "a.dll").write_bytes(b"nothing")
            self.assertIsNone(Ours.from_assemblies([folder / "a.dll"]))
        finally:
            shutil.rmtree(folder, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
