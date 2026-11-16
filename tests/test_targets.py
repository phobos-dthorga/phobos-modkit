"""The target check: names read from C# source, compared with a listing of members, and (with the .NET SDK) read from a fixture."""
import os
import shutil
import unittest

from support import FIXTURES
from phobos_modkit import native
from phobos_modkit.targets import Listing, check_targets, collect_constants, normalise, scan_text
from phobos_modkit.games.rimworld.patches import ensure_reader
from phobos_modkit.games.rimworld.targets_cli import read_members
from test_rimworld_patches import fixture_dll

HAVE_DOTNET = shutil.which("dotnet") is not None
REQUIRE = bool(os.environ.get("PHOBOS_REQUIRE_NATIVE"))


def method(name, parameters=(), returns="System.Void", names=None):
    names = list(names) if names is not None else [f"p{i}" for i in range(len(parameters))]
    return {"name": name, "parameters": list(parameters), "parameterNames": names, "returns": returns, "isStatic": False, "access": "public"}


def field(name, kind="System.Int32"):
    return {"name": name, "type": kind, "isStatic": False, "access": "private"}


def prop(name, kind="System.Single", getter=True, setter=False):
    return {"name": name, "type": kind, "hasGetter": getter, "hasSetter": setter, "isStatic": False}


def record(name, base="System.Object", methods=(), fields=(), properties=()):
    return {"type": name, "assembly": "A", "path": "a.dll", "base": base, "interfaces": [],
            "methods": list(methods), "fields": list(fields), "properties": list(properties)}


LISTING = Listing([
    record("Game.Thing", fields=[field("thingID")], methods=[method("Tick")]),
    record("Game.Pawn", base="Game.Thing", fields=[field("health", "System.Single")], properties=[prop("Downed", "System.Boolean")],
           methods=[method(".ctor"), method("Kill", ["System.Object"], names=["cause"]),
                    method("Kill", ["System.Object", "System.Boolean"], names=["cause", "silent"]), method("Age", returns="System.Int32"),
                    method("Heal", ["System.Collections.Generic.List<System.Int32>", "ref System.Single"], names=["parts", "amount"])]),
])


def findings(source, **options):
    scan = scan_text(source, "a.cs", **options)
    return scan, check_targets(scan, LISTING)


def statuses(source):
    return [f.status for f in findings(source)[1]]


class ReadingSource(unittest.TestCase):
    def test_a_class_attribute_with_a_string_member(self):
        scan, _ = findings('[HarmonyPatch(typeof(Pawn), "Age")] static class P { static void Postfix() { } }')
        self.assertEqual([(t.type_name, t.member, t.member_kind, t.compiler_checked) for t in scan.targets], [("Pawn", "Age", "method", False)])

    def test_nameof_is_marked_as_checked_by_the_compiler(self):
        scan, _ = findings('[HarmonyPatch(typeof(Pawn), nameof(Pawn.Age))] static class P { static void Postfix() { } }')
        self.assertTrue(scan.targets[0].compiler_checked)
        self.assertEqual(scan.targets[0].member, "Age")

    def test_a_getter_and_an_overload(self):
        scan, _ = findings('[HarmonyPatch(typeof(Pawn), "Downed", MethodType.Getter)] static class A { static void Postfix() { } }\n'
                           '[HarmonyPatch(typeof(Pawn), "Kill", new[] { typeof(object) })] static class B { static void Postfix() { } }')
        self.assertEqual(scan.targets[0].member_kind, "getter")
        self.assertEqual(scan.targets[1].arguments, ["object"])

    def test_a_constructor_with_its_argument_types(self):
        scan, _ = findings('[HarmonyPatch(typeof(Pawn), MethodType.Constructor, typeof(int))] static class A { static void Postfix() { } }')
        self.assertEqual((scan.targets[0].member_kind, scan.targets[0].arguments), ("ctor", ["int"]))

    def test_stacked_attributes_merge(self):
        scan, _ = findings('[HarmonyPatch(typeof(Pawn))]\n[HarmonyPatch("Age")]\nstatic class P { static void Postfix() { } }')
        self.assertEqual([(t.type_name, t.member) for t in scan.targets], [("Pawn", "Age")])

    def test_a_method_level_attribute_refines_the_class(self):
        scan, _ = findings('[HarmonyPatch(typeof(Pawn))] static class P { [HarmonyPatch("Age")] [HarmonyPostfix] static void After(ref int __result) { } }')
        self.assertEqual([(t.type_name, t.member) for t in scan.targets], [("Pawn", "Age")])
        self.assertEqual([i.name for i in scan.injections], ["__result"])

    def test_a_target_chosen_at_run_time_is_listed_not_guessed(self):
        scan, _ = findings('[HarmonyPatch] static class P { static MethodBase TargetMethod() => null; static void Postfix() { } }')
        self.assertEqual(scan.targets, [])
        self.assertEqual(len(scan.unresolved), 1)

    def test_comments_are_not_read(self):
        scan, _ = findings('// [HarmonyPatch(typeof(Pawn), "Gone")]\n/* AccessTools.Field(typeof(Pawn), "gone") */\nclass A { }')
        self.assertEqual(scan.targets, [])

    def test_access_tools_and_get_field(self):
        scan, _ = findings('class A { object a = AccessTools.Field(typeof(Pawn), "health"); object b = typeof(Pawn).GetField("health", Flags);'
                           ' object c = AccessTools.FieldRefAccess<Pawn, float>("health"); }')
        self.assertEqual([(t.source, t.type_name, t.member) for t in scan.targets],
                         [("AccessTools.Field", "Pawn", "health"), ("AccessTools.FieldRefAccess", "Pawn", "health"), ("GetField", "Pawn", "health")])

    def test_a_type_in_a_variable_cannot_be_checked(self):
        scan, _ = findings('class A { object a = AccessTools.Method(current, "Thing"); object b = owner.GetField("name"); }')
        self.assertEqual(scan.targets, [])
        self.assertEqual(len(scan.unresolved), 2)

    def test_a_type_colon_member_string(self):
        scan, _ = findings('class A { object a = AccessTools.Method("Game.Pawn:Age"); object b = AccessTools.Field("Game.Outer+Inner:x"); }')
        self.assertEqual([(t.type_name, t.member) for t in scan.targets], [("Game.Pawn", "Age"), ("Game.Outer.Inner", "x")])

    def test_a_constant_names_the_member_and_its_overload_still_counts(self):
        scan, _ = findings('class A { const string Space = "Game"; const string Hook = Space + ".Pawn:" + "Kill";'
                           ' object a = AccessTools.Method(Hook, new[] { typeof(object) }); }')
        self.assertEqual([(t.type_name, t.member, t.arguments) for t in scan.targets], [("Game.Pawn", "Kill", ["object"])])

    def test_another_files_constant_as_class_dot_name(self):
        shared = collect_constants(['static class Names { public const string Pawn = "Game.Pawn"; }'])
        scan, _ = findings('class A { object a = AccessTools.Field(AccessTools.TypeByName(Names.Pawn), "health"); }', constants=shared)
        self.assertEqual([(t.type_name, t.member) for t in scan.targets], [("Game.Pawn", "health")])

    def test_a_type_found_by_name_through_a_variable(self):
        scan, _ = findings('class A { static Type? kind; void Go() { kind = AccessTools.TypeByName("Game.Pawn");'
                           ' Type? t = Type.GetType("Game.Thing, Game"); object a = kind?.GetField("health"); object b = AccessTools.Method(t, "Tick"); } }')
        self.assertEqual([(t.type_name, t.member) for t in scan.targets], [("Game.Thing", "Tick"), ("Game.Pawn", "health")])
        self.assertEqual(scan.unresolved, [])

    def test_a_projects_own_lookup(self):
        source = 'class A { void Go() { Type? t = Mods.TypeNamed("Game.Pawn"); object a = t?.GetField("health"); } }'
        self.assertEqual(len(findings(source)[0].unresolved), 1)
        scan, _ = findings(source, type_lookups=("AccessTools.TypeByName", "Mods.TypeNamed"))
        self.assertEqual([(t.type_name, t.member) for t in scan.targets], [("Game.Pawn", "health")])

    def test_a_variable_given_two_types_or_shadowed_is_not_guessed(self):
        two = ('class A { void One() { Type t = AccessTools.TypeByName("Game.Pawn"); }'
               ' void Two() { Type t = AccessTools.TypeByName("Game.Map"); t.GetField("x"); } }')
        shadowed = 'class A { void One() { Type t = AccessTools.TypeByName("Game.Pawn"); } void Two(Type t) { t.GetField("x"); } }'
        lambda_ = 'class A { void One() { Type t = AccessTools.TypeByName("Game.Pawn"); kinds.Select(t => t.GetField("x")); } }'
        for source in (two, shadowed, lambda_):
            scan, _ = findings(source)
            self.assertEqual(scan.targets, [], source)
            self.assertEqual(len(scan.unresolved), 1, source)

    def test_a_name_put_together_at_run_time_is_listed(self):
        scan, _ = findings('class A { MethodBase Helper(string name) => AccessTools.Method(Space + ":" + name); }')
        self.assertEqual(scan.targets, [])
        self.assertIn("put together", scan.unresolved[0].reason)

    def test_a_generic_type_made_at_run_time_is_not_read_as_typeof(self):
        scan, _ = findings('class A { object a = typeof(List<>).MakeGenericType(kind).GetProperty("Count"); }')
        self.assertEqual(scan.targets, [])
        self.assertEqual(len(scan.unresolved), 1)

    def test_a_target_method_naming_one_member_gives_its_class_that_target(self):
        scan, _ = findings('[HarmonyPatch] static class P { static bool Prepare() => TargetMethod() != null;'
                           ' static MethodBase? TargetMethod() => Active ? AccessTools.Method("Game.Pawn:Age") : null;'
                           ' static void Postfix(ref int __result) { } }')
        self.assertEqual(scan.unresolved, [])
        self.assertEqual([(i.target.member, i.name) for i in scan.injections], [("Age", "__result")])

    def test_a_target_method_naming_two_members_stays_unresolved(self):
        scan, _ = findings('[HarmonyPatch] static class P { static MethodBase TargetMethod() { var a = AccessTools.Method("Game.Pawn:Age");'
                           ' return a ?? AccessTools.Method("Game.Pawn:Tick"); } static void Postfix(ref int __result) { } }')
        self.assertEqual(len(scan.unresolved), 1)
        self.assertEqual(scan.injections, [])

    def test_a_by_ref_overload_is_read(self):
        scan, _ = findings('class A { object a = AccessTools.Method(typeof(Pawn), "Heal", new[] { typeof(List<int>), typeof(float).MakeByRefType() }); }')
        self.assertEqual(scan.targets[0].arguments, ["List<int>", "float"])


class Checking(unittest.TestCase):
    def test_what_exists_passes(self):
        self.assertEqual(statuses('class A { object a = AccessTools.Field(typeof(Pawn), "health"); }'), ["ok"])

    def test_a_private_field_of_a_base_class_counts_as_inherited(self):
        self.assertEqual(statuses('class A { object a = AccessTools.Field(typeof(Pawn), "thingID"); }'), ["inherited"])

    def test_a_field_that_went_away_fails(self):
        self.assertEqual(statuses('class A { object a = AccessTools.Field(typeof(Pawn), "gone"); }'), ["missing"])

    def test_a_method_that_became_a_property_says_so(self):
        found = findings('class A { object a = AccessTools.Method(typeof(Pawn), "Downed"); }')[1][0]
        self.assertEqual(found.status, "missing")
        self.assertIn("property", found.detail)

    def test_an_overload_that_changed_fails_and_names_the_real_ones(self):
        found = findings('class A { object a = AccessTools.Method(typeof(Pawn), "Kill", new[] { typeof(int) }); }')[1][0]
        self.assertEqual(found.status, "overload")
        self.assertIn("System.Object", found.detail)

    def test_overload_types_match_across_aliases_namespaces_and_by_ref(self):
        self.assertEqual(statuses('class A { object a = AccessTools.Method(typeof(Pawn), "Heal", new[] { typeof(List<int>), typeof(float).MakeByRefType() }); }'), ["ok"])

    def test_a_setter_on_a_getter_only_property_fails(self):
        self.assertEqual(statuses('class A { object a = AccessTools.PropertySetter(typeof(Pawn), "Downed"); }'), ["no-setter"])

    def test_a_type_not_read_is_not_a_failure(self):
        found = findings('class A { object a = AccessTools.Field(typeof(OptionalThing), "x"); }')[1][0]
        self.assertEqual(found.status, "type-missing")
        self.assertFalse(found.fails)

    def test_several_overloads_with_none_named_is_a_note(self):
        found = findings('[HarmonyPatch(typeof(Pawn), "Kill")] static class P { static void Postfix() { } }')[1][0]
        self.assertEqual(found.status, "note")
        self.assertFalse(found.fails)

    def test_a_patch_on_an_inherited_method_is_a_note(self):
        found = findings('[HarmonyPatch(typeof(Pawn), "Tick")] static class P { static void Postfix() { } }')[1][0]
        self.assertEqual(found.status, "note")

    def test_reflection_on_an_inherited_method_is_fine(self):
        self.assertEqual(statuses('class A { object a = AccessTools.Method(typeof(Pawn), "Tick"); }'), ["inherited"])


class Injections(unittest.TestCase):
    def patch(self, parameters, target='"Age"'):
        return statuses(f'[HarmonyPatch(typeof(Pawn), {target})] static class P {{ static void Postfix({parameters}) {{ }} }}')[1:]

    def test_the_right_instance_type(self):
        self.assertEqual(self.patch("Pawn __instance"), ["ok"])

    def test_a_base_class_instance_is_fine(self):
        self.assertEqual(self.patch("Thing __instance"), ["ok"])

    def test_the_wrong_instance_type_fails(self):
        self.assertEqual(self.patch("Map __instance"), ["injection"])

    def test_a_field_that_went_away_fails(self):
        self.assertEqual(self.patch("float ___gone"), ["injection"])

    def test_a_field_of_the_wrong_type_fails(self):
        self.assertEqual(self.patch("int ___health"), ["injection"])

    def test_a_base_class_field(self):
        self.assertEqual(self.patch("ref int ___thingID"), ["ok"])

    def test_the_result_type_is_compared(self):
        self.assertEqual(self.patch("ref int __result"), ["ok"])
        self.assertEqual(self.patch("ref bool __result"), ["injection"])

    def test_a_result_on_a_void_method_fails(self):
        self.assertEqual(self.patch("ref int __result", '"Tick"')[-1:], ["injection"])

    def test_a_getter_result_comes_from_the_property(self):
        source = '[HarmonyPatch(typeof(Pawn), "Downed", MethodType.Getter)] static class P { static void Postfix(ref bool __result) { } }'
        self.assertEqual(statuses(source), ["ok", "ok"])


class ArgumentsByName(unittest.TestCase):
    def patch(self, parameters, target='"Kill", new[] { typeof(object), typeof(bool) }', method="Postfix"):
        return findings(f'[HarmonyPatch(typeof(Pawn), {target})] static class P {{ static void {method}({parameters}) {{ }} }}')[1][1:]

    def test_the_originals_names_pass(self):
        self.assertEqual([f.status for f in self.patch("object cause, bool silent")], ["ok", "ok"])

    def test_a_name_the_original_lacks_fails_and_lists_its_names(self):
        found = self.patch("object reason")
        self.assertEqual([f.status for f in found], ["injection"])
        self.assertIn("(cause, silent)", found[0].detail)

    def test_with_no_overload_named_any_overloads_names_will_do(self):
        self.assertEqual([f.status for f in self.patch("bool silent", target='"Kill"')], ["ok"])

    def test_harmonys_own_names_and_a_transpiler_are_not_matched(self):
        self.assertEqual(self.patch("object __state, object[] __args, MethodBase __originalMethod, bool __runOriginal"), [])
        self.assertEqual(self.patch("IEnumerable<CodeInstruction> instructions, ILGenerator generator", method="Transpiler"), [])

    def test_a_harmony_argument_mark_renames_or_skips(self):
        self.assertEqual([f.status for f in self.patch('[HarmonyArgument("cause")] object why')], ["ok"])
        self.assertEqual(self.patch("[HarmonyArgument(0)] object why"), [])

    def test_a_call_to_a_prefix_is_not_its_declaration(self):
        source = '[HarmonyPatch(typeof(Pawn), "Age")] static class P { static void Prefix() { } static void Other() { Prefix(ref x, y); } }'
        self.assertEqual(statuses(source), ["ok"])

    def test_an_older_reader_without_names_is_not_judged(self):
        old = Listing([record("Game.Pawn", methods=[{"name": "Kill", "parameters": ["System.Object"], "returns": "System.Void",
                                                     "isStatic": False, "access": "public"}])])
        scan = scan_text('[HarmonyPatch(typeof(Pawn), "Kill")] static class P { static void Postfix(object anything) { } }', "a.cs")
        self.assertEqual([f.status for f in check_targets(scan, old)], ["ok"])


class Normalising(unittest.TestCase):
    def test_aliases_namespaces_and_modifiers(self):
        for written, read in [("float", "System.Single"), ("ref int", "ref System.Int32"), ("Thing?", "Verse.Thing"),
                              ("List<Pawn>", "System.Collections.Generic.List<Verse.Pawn>"), ("Outer.Inner", "Space.Outer.Inner"[6:])]:
            self.assertEqual(normalise(written), normalise(read), written)


@unittest.skipUnless(HAVE_DOTNET or REQUIRE, "needs the .NET SDK")
class ReadingAssemblies(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tool = ensure_reader()
        cls.listing = Listing(read_members(cls.tool, ["Pawn"], [fixture_dll()]))

    def test_members_private_and_public(self):
        pawn = self.listing.types["Game.Pawn"]
        self.assertIn("health", [f["name"] for f in pawn["fields"]])
        self.assertIn("Downed", [p["name"] for p in pawn["properties"]])

    def test_a_base_class_is_followed(self):
        self.assertEqual(self.listing.chain("Game.Pawn"), ["Game.Pawn", "Game.Thing"])
        self.assertEqual(self.listing.fields("Game.Pawn", "thingID")[0], "Game.Thing")

    def test_overloads_and_generic_parameters_read_in_full(self):
        heal = next(m for _, m in self.listing.methods("Game.Pawn", "Heal"))
        self.assertEqual(heal["parameters"], ["System.Collections.Generic.List<System.Int32>", "System.Single"])
        self.assertEqual(len(self.listing.methods("Game.Pawn", "Kill")), 2)

    def test_parameter_names_are_read(self):
        heal = next(m for _, m in self.listing.methods("Game.Pawn", "Heal"))
        self.assertEqual(heal["parameterNames"], ["parts", "amount"])

    def test_a_scan_passes_against_the_real_listing(self):
        source = '[HarmonyPatch(typeof(Pawn), "Heal", new[] { typeof(List<int>), typeof(float) })] static class P { static void Postfix(Pawn __instance, float ___health, float amount) { } }'
        scan = scan_text(source, "a.cs")
        self.assertEqual([f.status for f in check_targets(scan, self.listing)], ["ok", "ok", "ok", "ok"])


if __name__ == "__main__":
    unittest.main()
