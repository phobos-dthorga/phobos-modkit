"""data_names: the names that cross between a game's data files and its code (1.117.0), on made-up repositories laid out as each
game's mods are. Every file is written by hand in temporary folders; the cache points there too. Nothing here needs the .NET SDK:
with no project to read, a C# file's names are the rules' alone, which is the path a computer without the SDK takes."""
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

import support  # noqa: F401  (puts the package on the path)
import test_connections as sample
from phobos_modkit import connections, connections_cli, data_names

KEYED = """<?xml version="1.0" encoding="utf-8"?>
<LanguageData>
  <Lamps_Lit>The lamp is lit.</Lamps_Lit>
  <Lamps_Dark>The lamp is dark, says LampThing.</Lamps_Dark>
  <Lamps_Saved>Saved</Lamps_Saved>
  <Lamps_Long>A lamp
    over two lines.</Lamps_Long>
</LanguageData>
"""
DEFS = """<?xml version="1.0" encoding="utf-8"?>
<Defs>
  <ThingDef Name="LampParent" ParentName="BuildingBase">
    <defName>Lamps_BaseLamp</defName>
    <thingClass>Sample.Lamps.LampThing</thingClass>
    <graphicClass>Graphic_Single</graphicClass>
  </ThingDef>
  <ThingDef ParentName="LampParent">
    <defName>Lamps_Lamp</defName>
    <message>Lamps_Lit</message>
    <fuelClass>Lamps_BaseLamp</fuelClass>
    <comps>
      <li Class="Sample.Lamps.CompGlow" />
    </comps>
  </ThingDef>
  <RecipeDef>
    <defName>Lamps_MakeLamp</defName>
    <products><li>Lamps_Lamp</li></products>
  </RecipeDef>
  <SoundDef>
    <defName>Lamps_Lamp</defName>
  </SoundDef>
</Defs>
"""
PATCH = """<?xml version="1.0" encoding="utf-8"?>
<Patch>
  <Operation Class="PatchOperationAdd">
    <xpath>Defs/ThingDef[defName="Lamps_Lamp" or defName="OtherMod_Lamp"]/comps</xpath>
  </Operation>
</Patch>
"""
CSHARP = """using Verse;

namespace Sample.Lamps
{
    public class LampThing { }

    public class CompGlow
    {
        // "Lamps_Dark".Translate() in a comment is not read
        public string Words(bool lit, string verb)
        {
            string a = "Lamps_Lit".Translate();
            string b = (lit ? "Lamps_Lit" : "Lamps_Dark").Translate();
            string c = ("Lamps_" + verb).Translate();
            string d = (verb == "Lamps_Dark" ? "Lamps_Lit" : "Game_Key").Translate();
            Scribe_Values.Look(ref lit, "Lamps_Saved", false);
            string e = Pick("Lamps_Dark");
            ThingDef f = DefDatabase<ThingDef>.GetNamedSilentFail("Lamps_Lamp");
            ThingDef g = DefDatabase<ThingDef>.GetNamed("Steel");
            const string LampName = "Lamps_MakeLamp";
            return a + b + c + d + e + lit.Named("LIT");
        }
    }

    [DefOf]
    public static class LampDefOf
    {
        public static SoundDef Lamps_Lamp = null!;
        public static ThingDef Steel;

        static LampDefOf() { }
    }
}
"""

ALPHA_WORDS = """{
  "Panel.on": "On",
  "Panel.off": "Off",
  "Shared.title": "Alpha's title"
}
"""
BETA_WORDS = """{
  "Shared.title": "Beta's title"
}
"""
SERVICE = """class Service
{
    string Words(bool on, string verb)
    {
        var a = Text.Get("Shared.title");
        var b = Text.Get(on ? "Panel.on" : "Panel.off", 3);
        var c = Text.Get("Panel." + verb);
        var d = Text.Get(verb == "export" ? "Panel.on" : "Panel.missing");
        var e = Text.Get("Panel." + (on ? "on" : "off"));
        const string Marker = "AlphaContentMarker";
        return a + b + c + d + e;
    }
}
"""
CONDITIONS = """[
  {
    "strName": "AlphaContentMarker",
    "strNameFriendly": "Alpha content",
    "aReqs": ["AlphaOtherThing"]
  },
  {
    "strName": "AlphaOtherThing"
  }
]
"""
RECIPES = """{
  "recipes": [
    {
      "nameKey": "Shared.title",
      "item": "AlphaContentMarker",
      "art": "Panel.on"
    }
  ]
}
"""


def line_of(text, needle, nth=1):
    """The line (from 1) of the nth line holding some words."""
    found = [number for number, line in enumerate(text.splitlines(), 1) if needle in line]
    return found[nth - 1]


def rimworld(tmp):
    root = Path(tmp) / "repo"
    sample.write(root / "Languages" / "English" / "Keyed" / "Lamps.xml", KEYED)
    sample.write(root / "Defs" / "Lamps.xml", DEFS)
    sample.write(root / "Patches" / "Lamps.xml", PATCH)
    sample.write(root / "Source" / "Lamps.cs", CSHARP)
    return root


def ostranauts(tmp):
    root = Path(tmp) / "repo"
    sample.write(root / "translations" / "Alpha" / "en.json", ALPHA_WORDS)
    sample.write(root / "translations" / "Beta" / "en.json", BETA_WORDS)
    sample.write(root / "src" / "Alpha" / "Service.cs", SERVICE)
    sample.write(root / "mods" / "Alpha" / "data" / "conditions" / "alpha.json", CONDITIONS)
    sample.write(root / "mods" / "Alpha" / "framework" / "recipes.json", RECIPES)
    return root


def names(tmp, root, file, game, commit=None):
    argv = ["names", "--root", str(root), "--file", file] + (["--game", game] if game else [])
    code, found = sample.run(argv + (["--commit", commit] if commit else []), tmp)
    return code, found


def by_place(found):
    """{(text, line): name}; a text read twice on one line keeps both, the second as (text, line, 2)."""
    held = {}
    for name in found["names"]:
        key = (name["text"], name["line"])
        held[key if key not in held else (*key, 2)] = name
    return held


class TableTests(unittest.TestCase):
    def test_every_table_the_kit_ships_can_be_used(self):
        shipped = data_names.tables()
        self.assertIn("rimworld", shipped)
        self.assertIn("ostranauts", shipped)
        for game in shipped:
            table = data_names.table_for(game)
            self.assertTrue(table.rules and table.things, game)
            for rule in table.rules:
                self.assertTrue(rule.words and rule.suffixes, f"{game} {rule.id}")

    def test_a_game_with_no_table_has_none_and_no_game_is_no_table(self):
        self.assertIsNone(data_names.table_for(None))
        self.assertIsNone(data_names.table_for("a game nobody made"))
        self.assertEqual(data_names.table_for("RimWorld").source, "rimworld", "a game is found however it is written")

    def test_a_table_that_cannot_be_used_is_refused_in_words(self):
        thing = {"id": "key", "files": ["**/words.json"], "declared": "\"(?P<name>\\w+)\"\\s*:"}
        rule = {"id": "ask", "in": [".cs"], "argumentOf": "\\bAsk\\(", "names": ["key"]}
        data_names.Table({"things": [thing], "rules": [rule]})
        for broken, words in (
            ({"things": [thing], "rules": [{**rule, "names": ["nothing"]}]}, "do not hold"),
            ({"things": [thing], "rules": [{**rule, "match": "(?P<name>x)"}]}, "one of"),
            ({"things": [thing], "rules": [{**rule, "argumentOf": "("}]}, "not a pattern"),
            ({"things": [{**thing, "declared": "\\w+"}], "rules": [rule]}, "`name` group"),
            ({"things": [{**thing, "graph": {"language": "xml"}}], "rules": [rule]}, "one of the two"),
            ({"things": [thing], "rules": [rule, rule]}, "share an id"),
        ):
            with self.assertRaises(data_names.DataNamesError) as raised:
                data_names.Table(broken)
            self.assertIn(words, str(raised.exception))


class TextTests(unittest.TestCase):
    """A file's text as the rules read it."""

    def strings(self, code, start=0, end=None):
        ready = data_names.Prepared(code, ".cs")
        return [ready.code[s[2]:s[3]] for s in ready.whole_strings(start, len(code) if end is None else end)]

    def test_comments_are_blanked_and_places_hold(self):
        text = 'a = "x"; // "y"\n/* "z" */ b = "w";'
        ready = data_names.Prepared(text, ".cs")
        self.assertEqual(len(ready.code), len(text))
        self.assertNotIn("y", ready.code)
        self.assertNotIn("z", ready.code)
        self.assertEqual([ready.code[s[2]:s[3]] for s in ready.strings], ["x", "w"])
        self.assertEqual(ready.place(text.index("w")), (2, 15))

    def test_a_string_is_a_name_only_by_itself(self):
        self.assertEqual(self.strings('on ? "A" : "B"'), ["A", "B"])
        self.assertEqual(self.strings('"A." + what'), [], "a piece of a name")
        self.assertEqual(self.strings('verb == "export" ? "A" : "B"'), ["A", "B"], "a string tested is not a name")
        self.assertEqual(self.strings('"A." + (on ? "on" : "off")'), [], "a group joined to more text")
        self.assertEqual(self.strings('on ? "A" : (other ? "B" : "C")'), ["A", "B", "C"], "a bracket that only groups")
        self.assertEqual(self.strings('Pick("inner") ?? "A"'), ["A"], "a call's own strings are not this one's")
        self.assertEqual(self.strings('$"A {x}"'), [], "a string with holes in it")

    def test_other_languages_have_their_own_comments_and_joins(self):
        lua = data_names.Prepared('-- "a"\nx = "b" .. y\nz = \'c\'', ".lua")
        self.assertEqual([lua.code[s[2]:s[3]] for s in lua.whole_strings(0, len(lua.code))], ["c"])
        xml = data_names.Prepared("<a><!-- <b>X</b> --><c>Y</c></a>", ".xml")
        self.assertNotIn("X", xml.code)
        self.assertIn("Y", xml.code)


class RimWorldTests(unittest.TestCase):
    """The table for RimWorld, on a mod laid out as one: Defs, a patch, English Keyed words, and C#."""

    def test_code_names_translation_keys_and_defs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = rimworld(tmp)
            code, found = names(tmp, root, "Source/Lamps.cs", "rimworld")
            self.assertEqual(code, 0, found)
            self.assertEqual(found["game"], "rimworld")
            self.assertTrue(any("C# names were not read" in limit for limit in found["limits"]), "no project: the rules alone")
            held = by_place(found)
            at = lambda needle: line_of(CSHARP, needle)   # noqa: E731

            lit = held[("Lamps_Lit", at('string a ='))]
            self.assertEqual((lit["rule"], lit["kind"], lit["node"]), ("translate-call", "translation key", "data:key/Lamps_Lit"))
            self.assertEqual(lit["declared"], {"file": "Languages/English/Keyed/Lamps.xml", "line": 3, "end": 3})
            self.assertEqual(found["snippets"]["Languages/English/Keyed/Lamps.xml:3"]["lines"],
                             ["  <Lamps_Lit>The lamp is lit.</Lamps_Lit>"], "the English words come with the name")
            self.assertFalse(lit["exact"])
            self.assertEqual(lit["column"], CSHARP.splitlines()[lit["line"] - 1].index("Lamps_Lit"))

            both = at("string b =")
            self.assertEqual({held[("Lamps_Lit", both)]["rule"], held[("Lamps_Dark", both)]["rule"]}, {"translate-call"})
            self.assertFalse(any(line == at("string c =") for _, line, *_ in held), "a piece of a key is not a key")
            tested = at("string d =")
            self.assertEqual(held[("Lamps_Dark", tested)]["rule"], "name-in-code", "tested, not asked for; still a key's name")
            game_key = held[("Game_Key", tested)]
            self.assertTrue(game_key["outside"])
            self.assertEqual((game_key["declared"], game_key["candidates"], game_key["kind"]), ({}, [], "translation key"))
            self.assertFalse(any(line == at("Scribe_Values") for _, line, *_ in held), "a save label is not a key")
            self.assertEqual(held[("Lamps_Dark", at("Pick("))]["rule"], "name-in-code")
            self.assertFalse(any(line == at("// ") for _, line, *_ in held), "a comment is not read")
            self.assertNotIn(("LIT", at("return a")), held, "an argument's name is not a Def")

            asked = held[("Lamps_Lamp", at("GetNamedSilentFail"))]
            self.assertEqual((asked["rule"], asked["node"], len(asked["candidates"])),
                             ("def-database", "def:ThingDef/Lamps_Lamp", 1), "the kind asked for picks between two of a name")
            self.assertTrue(held[("Steel", at('GetNamed("Steel")'))]["outside"])
            self.assertEqual(held[("Lamps_MakeLamp", at("const string"))]["node"], "def:RecipeDef/Lamps_MakeLamp")

            field = held[("Lamps_Lamp", at("public static SoundDef"))]
            self.assertEqual((field["rule"], field["node"]), ("defof-field", "def:SoundDef/Lamps_Lamp"))
            self.assertTrue(held[("Steel", at("public static ThingDef"))]["outside"])

    def test_defs_name_classes_parents_defs_and_keys(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = rimworld(tmp)
            code, found = names(tmp, root, "Defs/Lamps.xml", "rimworld")
            self.assertEqual(code, 0, found)
            held = by_place(found)
            self.assertTrue(held[("BuildingBase", 3)]["outside"], "the game's parent")
            ours = held[("Sample.Lamps.LampThing", 5)]
            self.assertEqual((ours["rule"], ours["node"], ours["declared"]["file"]),
                             ("class-element", "cs:Sample.Lamps.LampThing", "Source/Lamps.cs"))
            theirs = held[("Graphic_Single", 6)]
            self.assertEqual((theirs["outside"], theirs["their"], theirs["kind"]), (True, "Graphic_Single", "class"))
            parent = held[("LampParent", 8)]
            self.assertEqual((parent["rule"], parent["node"]), ("def-parent", "def:ThingDef/Lamps_BaseLamp"),
                             "a parent is named by its Name, and stands for the Def that has it")
            self.assertEqual((held[("Lamps_Lit", 10)]["rule"], held[("Lamps_Lit", 10)]["node"]), ("key-value", "data:key/Lamps_Lit"))
            self.assertEqual((held[("Lamps_BaseLamp", 11)]["rule"], held[("Lamps_BaseLamp", 11)]["node"]),
                             ("def-value", "def:ThingDef/Lamps_BaseLamp"), "an element called ...Class may hold a Def's name")
            self.assertEqual(held[("Sample.Lamps.CompGlow", 13)]["rule"], "class-attribute")
            shared = held[("Lamps_Lamp", 18)]
            self.assertEqual(sorted(c["id"] for c in shared["candidates"]), ["def:SoundDef/Lamps_Lamp", "def:ThingDef/Lamps_Lamp"])
            self.assertTrue(held[("Lamps_Lamp", 9)]["here"], "a Def's own name is still its declaration")

            code, found = names(tmp, root, "Patches/Lamps.xml", "rimworld")
            held = by_place(found)
            self.assertEqual(held[("Lamps_Lamp", 4)]["node"], "def:ThingDef/Lamps_Lamp", "the path's kind picks the Def")
            self.assertEqual(len(held[("Lamps_Lamp", 4)]["candidates"]), 1)
            self.assertTrue(held[("OtherMod_Lamp", 4)]["outside"])
            self.assertEqual(held[("PatchOperationAdd", 3)]["their"], "PatchOperationAdd")

    def test_a_translation_file_gives_its_keys_and_none_of_its_prose(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = rimworld(tmp)
            code, found = names(tmp, root, "Languages/English/Keyed/Lamps.xml", "rimworld")
            self.assertEqual(code, 0, found)
            held = by_place(found)
            self.assertEqual(sorted(text for text, *_ in held), ["Lamps_Dark", "Lamps_Lit", "Lamps_Long", "Lamps_Saved"])
            self.assertTrue(all(name["here"] and name["node"].startswith("data:key/") for name in held.values()))
            self.assertEqual(held[("Lamps_Long", 6)]["declared"]["end"], 7, "a key's words may run over lines")

    def test_without_the_game_nothing_is_read_by_rule(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = rimworld(tmp)
            code, found = names(tmp, root, "Defs/Lamps.xml", None)
            self.assertEqual(code, 0, found)
            self.assertFalse(any(name.get("rule") for name in found["names"]))
            self.assertNotIn("game", found)

    def test_the_things_and_their_uses_join_the_connections(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = rimworld(tmp)
            code, found = sample.run(["around", "--root", str(root), "--game", "rimworld", "--node", "data:key/Lamps_Lit"], tmp)
            self.assertEqual(code, 0, found)
            self.assertEqual((found["centre"]["kind"], found["centre"]["file"]),
                             ("translation key", "Languages/English/Keyed/Lamps.xml"))
            used_by = sample.relations(found)["used-by"]
            self.assertIn("def:ThingDef/Lamps_Lamp", used_by, "the Def whose message it is")
            self.assertTrue(any(node.startswith("cs:Sample.Lamps.CompGlow") for node in used_by), used_by)

            code, found = sample.run(["around", "--root", str(root), "--game", "rimworld", "--node", "def:SoundDef/Lamps_Lamp"], tmp)
            self.assertTrue(any(node.startswith("cs:Sample.Lamps.LampDefOf") for node in sample.relations(found)["used-by"]))

            code, found = sample.run(["summary", "--root", str(root), "--game", "rimworld"], tmp)
            self.assertIn("data names", [reader["language"] for reader in found["readers"]])
            code, found = sample.run(["summary", "--root", str(root)], tmp)
            self.assertNotIn("data names", [reader["language"] for reader in found["readers"]], "a store of its own, by game")
            code, found = sample.run(["around", "--root", str(root), "--node", "data:key/Lamps_Lit"], tmp)
            self.assertEqual(code, 1, "without the game there is no such thing")

    def test_the_count_says_what_each_rule_read(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = rimworld(tmp)
            code, found = sample.run(["jumps", "--root", str(root), "--game", "rimworld"], tmp)
            self.assertEqual(code, 0, found)
            rules = {rule["id"]: rule for rule in found["rules"]}
            asked = rules["translate-call"]
            self.assertEqual((asked["matches"], asked["one"], asked["none"]), (5, 4, 1))
            self.assertEqual(asked["noneTop"], [{"name": "Game_Key", "count": 1}])
            self.assertEqual((rules["def-database"]["matches"], rules["def-database"]["one"], rules["def-database"]["none"]), (2, 1, 1))
            self.assertEqual((rules["name-in-code"]["matches"], rules["name-in-code"]["none"]), (3, 0),
                             "a rule for names that are things never names nothing")
            self.assertEqual(rules["def-value"]["several"], 1)
            things = {thing["id"]: thing for thing in found["things"]}
            self.assertEqual((things["key"]["count"], things["def"]["shared"], things["parent"]["count"]), (4, 1, 1))

            code, found = sample.run(["jumps", "--root", str(root), "--game", "kenshi"], tmp)
            self.assertEqual(code, 1)
            self.assertIn("rimworld", found["refusal"])

    def test_a_commit_that_changes_a_keys_words_changed_that_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = rimworld(tmp)
            for arguments in (("init", "-q"), ("config", "core.fsmonitor", "false"), ("config", "user.email", "test@example.com"),
                              ("config", "user.name", "Test"), ("add", "-A"), ("commit", "-q", "-m", "first")):
                sample.git(root, *arguments)
            sample.write(root / "Languages" / "English" / "Keyed" / "Lamps.xml", KEYED.replace("is lit.", "burns."))
            sample.git(root, "commit", "-q", "-am", "burns")
            commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True).stdout.strip()
            code, found = sample.run(["changed", "--root", str(root), "--commit", commit[:10], "--game", "rimworld"], tmp)
            self.assertEqual(code, 0, found)
            self.assertEqual([(t["id"], t["inGraph"], t["at"]["line"]) for t in found["things"]], [("data:key/Lamps_Lit", True, 3)])
            code, found = sample.run(["changed", "--root", str(root), "--commit", commit[:10]], tmp)
            self.assertEqual(found["things"], [], "without the game a translation file declares nothing")

    def test_a_c_sharp_name_gains_the_def_its_declaration_stands_for(self):
        """With the names reader's reading of a file (made up here), a DefOf field keeps its exact reading and gains its Def: at
        its own place, and wherever it is used."""
        with tempfile.TemporaryDirectory() as tmp:
            root = rimworld(tmp)
            declared = line_of(CSHARP, "public static SoundDef")
            column = CSHARP.splitlines()[declared - 1].index("Lamps_Lamp")
            place = {"file": "Source/Lamps.cs", "line": declared, "end": declared}

            def field(line, at, here):
                return {"line": line, "column": at, "length": 10, "text": "Lamps_Lamp", "kind": "field",
                        "display": "LampDefOf.Lamps_Lamp", "id": "F:Sample.Lamps.LampDefOf.Lamps_Lamp", "here": here,
                        "declared": dict(place)}

            found = {"names": [field(declared, column, True), field(12, 60, False)], "snippets": {}, "limits": []}
            table = data_names.table_for("rimworld")
            conn = connections.open_graph(root, sample.environ(tmp), game="rimworld")
            try:
                connections_cli._add_rule_names(found, table, conn, root, "Source/Lamps.cs", CSHARP, exact_base=True)
            finally:
                conn.close()
            fields = [name for name in found["names"] if name["kind"] == "field"]
            self.assertEqual(len(fields), 2, "the rule's own reading of the declaration is not a second name there")
            for name in fields:
                self.assertEqual(name["id"], "F:Sample.Lamps.LampDefOf.Lamps_Lamp", "its exact reading is kept")
                self.assertEqual((name["also"]["rule"], [c["id"] for c in name["also"]["candidates"]]),
                                 ("defof-field", ["def:SoundDef/Lamps_Lamp"]))
            self.assertIn("Defs/Lamps.xml:21", found["snippets"], "the Def's lines come with it")
            self.assertTrue(any(name.get("rule") == "translate-call" for name in found["names"]), "and the strings are added")


class OstranautsTests(unittest.TestCase):
    """The table for Ostranauts, on mods laid out as phobos-ostranauts lays them out."""

    def test_code_names_its_own_mods_words_and_data_objects(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = ostranauts(tmp)
            code, found = names(tmp, root, "src/Alpha/Service.cs", "ostranauts")
            self.assertEqual(code, 0, found)
            held = by_place(found)
            at = lambda needle: line_of(SERVICE, needle)   # noqa: E731
            title = held[("Shared.title", at("var a ="))]
            self.assertEqual((title["rule"], title["node"], len(title["candidates"])),
                             ("text-call", "data:key/Alpha/Shared.title", 1), "two mods have the key; the file's own is meant")
            self.assertEqual({text for text, line, *_ in held if line == at("var b =")}, {"Panel.on", "Panel.off"})
            self.assertFalse(any(line == at("var c =") for _, line, *_ in held), "a key built from pieces is not read")
            self.assertEqual({(text, held[(text, line)]["outside"]) for text, line, *_ in held if line == at("var d =")},
                             {("Panel.on", False), ("Panel.missing", True)}, "the word tested is not a key; the missing key is said")
            self.assertFalse(any(line == at("var e =") for _, line, *_ in held))
            marker = held[("AlphaContentMarker", at("const string"))]
            self.assertEqual((marker["rule"], marker["kind"], marker["declared"]),
                             ("object-in-code", "data object", {"file": "mods/Alpha/data/conditions/alpha.json", "line": 3, "end": 6}))

    def test_data_files_name_keys_and_objects(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = ostranauts(tmp)
            code, found = names(tmp, root, "mods/Alpha/framework/recipes.json", "ostranauts")
            self.assertEqual(code, 0, found)
            held = by_place(found)
            self.assertEqual(held[("Shared.title", 4)]["node"], "data:key/Alpha/Shared.title")
            self.assertEqual(held[("AlphaContentMarker", 5)]["rule"], "object-in-data")
            self.assertNotIn(("Panel.on", 6), held, "only a property that says it holds a key is read as one")

            code, found = names(tmp, root, "mods/Alpha/data/conditions/alpha.json", "ostranauts")
            held = by_place(found)
            self.assertTrue(held[("AlphaContentMarker", 3)]["here"])
            self.assertEqual((held[("AlphaOtherThing", 5)]["rule"], held[("AlphaOtherThing", 5)]["declared"]["line"]),
                             ("object-in-data", 8))

            code, found = names(tmp, root, "mods/Alpha/framework/recipes.json", None)
            self.assertEqual((code, found["names"]), (0, []), "with no game named, a data file has no names: not a refusal")
            self.assertIn("name the game", found["limits"][0])
            code, found = names(tmp, root, "mods/Alpha/mod_info.json", "rimworld")
            self.assertEqual((code, found["names"]), (0, []), "nor has one no rule of the game reads")
            self.assertIn("for rimworld", found["limits"][0])
            sample.write(root / "notes.md", "words")
            code, found = names(tmp, root, "notes.md", "ostranauts")
            self.assertEqual(code, 1, "a kind of file no game's rules read is refused")

    def test_an_object_is_used_by_the_object_that_names_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = ostranauts(tmp)
            code, found = sample.run(["around", "--root", str(root), "--game", "ostranauts", "--node", "data:object/AlphaOtherThing"],
                                     tmp)
            self.assertEqual(code, 0, found)
            self.assertEqual(sample.relations(found)["used-by"], ["data:object/AlphaContentMarker"])
            self.assertEqual(found["centre"]["language"], "json")
            code, found = sample.run(["jumps", "--root", str(root), "--game", "ostranauts"], tmp)
            rules = {rule["id"]: rule for rule in found["rules"]}
            self.assertEqual((rules["text-call"]["matches"], rules["text-call"]["none"]), (5, 1))
            self.assertEqual(rules["text-call"]["noneTop"][0]["name"], "Panel.missing")


if __name__ == "__main__":
    unittest.main()
