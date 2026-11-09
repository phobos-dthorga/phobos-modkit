// A made-up mod assembly for the assembly reader's tests, written for them. HarmonyLib here is a stand-in with only the
// public names Harmony's documentation gives (the attributes, Harmony.Patch, HarmonyMethod, AccessTools): no code of
// Harmony's is copied. The reader matches those names, so it treats this as it would the real library.
using System;
using System.Collections.Generic;
using System.Reflection;

namespace HarmonyLib
{
    public enum MethodType { Normal, Getter, Setter, Constructor, StaticConstructor, Enumerator, Async }

    [AttributeUsage(AttributeTargets.Class | AttributeTargets.Method, AllowMultiple = true)]
    public class HarmonyPatch : Attribute
    {
        public HarmonyPatch() { }
        public HarmonyPatch(Type declaringType) { }
        public HarmonyPatch(Type declaringType, string methodName, MethodType methodType) { }
        public HarmonyPatch(Type declaringType, string methodName) { }
        public HarmonyPatch(Type declaringType, string methodName, params Type[] argumentTypes) { }
        public HarmonyPatch(Type declaringType, MethodType methodType) { }
        public HarmonyPatch(string methodName) { }
        public HarmonyPatch(MethodType methodType) { }
    }

    public class HarmonyPrefix : Attribute { }
    public class HarmonyPostfix : Attribute { }
    public class HarmonyPriority : Attribute { public HarmonyPriority(int priority) { } }

    public class HarmonyMethod
    {
        public HarmonyMethod(MethodInfo method) { }
        public HarmonyMethod(Type type, string name) { }
    }

    public class Harmony
    {
        public MethodInfo Patch(MethodBase original, HarmonyMethod prefix = null, HarmonyMethod postfix = null) => null;
    }

    public static class AccessTools
    {
        public static MethodInfo Method(Type type, string name, Type[] parameters = null) => null;
        public static MethodInfo PropertyGetter(Type type, string name) => null;
        public static Type TypeByName(string name) => null;
    }
}

namespace Game
{
    // A base class with a private field and a method a derived type inherits, for the member listing's tests.
    public class Thing
    {
        private int thingID;
        public virtual void Tick() { }
        public int ThingID => thingID;
    }

    public class Pawn : Thing
    {
        private float health;
        public static int Count;
        public void Kill(object cause) { }
        public void Kill(object cause, bool silent) { }
        public bool Downed => false;
        public void Heal(List<int> parts, float amount) { }
    }
    public class Map { public void Tick() { } }
}

namespace FixtureMod
{
    using Game;
    using HarmonyLib;

    // A class-level target with a bool prefix (it may skip the original) and a postfix.
    [HarmonyPatch(typeof(Pawn), nameof(Pawn.Kill))]
    [HarmonyPriority(800)]
    public static class KillPatch
    {
        public static bool Prefix(Pawn __instance) => true;
        public static void Postfix() { }
    }

    // A getter, named by MethodType.
    [HarmonyPatch(typeof(Pawn), nameof(Pawn.Downed), MethodType.Getter)]
    public static class DownedPatch
    {
        public static void Postfix(ref bool __result) { }
    }

    // An overload named by its argument types (a generic among them), and marked patch methods with other names.
    [HarmonyPatch(typeof(Pawn), nameof(Pawn.Heal), new[] { typeof(List<int>), typeof(float) })]
    public static class HealPatch
    {
        [HarmonyPrefix] public static void Before() { }
        [HarmonyPostfix] public static void After() { }
    }

    // The target chosen in code.
    [HarmonyPatch]
    public static class TickPatch
    {
        static MethodBase TargetMethod() => AccessTools.Method(typeof(Map), nameof(Map.Tick));
        public static void Postfix() { }
    }

    // Patches made by calls: the original looked up first, the patch method through AccessTools or by name.
    public static class Manual
    {
        public static void Apply(Harmony harmony)
        {
            var bridge = AccessTools.TypeByName("Other.Bridge");
            harmony.Patch(AccessTools.Method(bridge, "Install", new[] { typeof(Harmony) }),
                postfix: new HarmonyMethod(AccessTools.Method(typeof(Manual), nameof(AfterInstall))));
            harmony.Patch(AccessTools.PropertyGetter(typeof(Pawn), nameof(Pawn.Downed)),
                prefix: new HarmonyMethod(typeof(Manual), nameof(DownedPrefix)));
        }

        public static void AfterInstall() { }
        public static bool DownedPrefix() => true;
    }

    // Not a patch: a class with Prefix-like names but no HarmonyPatch anywhere.
    public static class NotAPatch
    {
        public static void Postfix() { }
    }
}
