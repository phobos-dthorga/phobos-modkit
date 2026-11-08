using System.Collections.Immutable;
using System.Reflection;
using System.Reflection.Emit;
using System.Reflection.Metadata;
using System.Reflection.Metadata.Ecma335;
using System.Reflection.PortableExecutable;

namespace Phobos.ModKit.Assemblies;

/// <summary>One Harmony patch found in an assembly: the method it patches and the method that does the patching.</summary>
public sealed record Patch(
    string Source,          // "attribute" ([HarmonyPatch] on a class or method) or "call" (a harmony.Patch(...) call)
    string Kind,            // prefix, postfix, transpiler, finalizer, reverse, or unknown
    string TargetType,      // the patched method's type, as written ("" when the code works it out at run time)
    string TargetMember,    // its name, ".ctor", or "" (a getter or setter names the property and says so in MethodType)
    string MethodType,      // Normal, Getter, Setter, Constructor, StaticConstructor, Enumerator, Async, or ""
    string[] ArgumentTypes, // the overload's parameter types when the patch names them
    string PatchClass,      // the class holding the patch method
    string PatchMethod,     // the patch method's name
    bool CanSkip,           // a prefix returning bool: it may stop the original (and every later prefix) from running
    int Priority,           // [HarmonyPriority], or -1 when not set
    string Note);           // what could not be read, if anything

/// <summary>
/// Finds Harmony patches through an assembly's metadata alone. Two ways a mod patches: attributes ([HarmonyPatch] on a
/// class gives the target, its Prefix/Postfix/Transpiler/Finalizer methods or [HarmonyPrefix]-marked ones are the
/// patches, method-level [HarmonyPatch] adds to the class's), and calls (harmony.Patch(original, prefix, ...), whose
/// original usually comes from AccessTools.Method(typeof(T), "Name") and whose patches from new HarmonyMethod(typeof(P),
/// "Name"): read from the IL as the type tokens and strings those calls consume). Types are compared by name, so a
/// HarmonyLib in any assembly counts: Harmony's own attribute and method names are the public facts used.
/// </summary>
public sealed class PatchReader
{
    static readonly Dictionary<short, OperandType> operandTypes = BuildOperandTypes();
    static readonly string[] kindNames = { "prefix", "postfix", "transpiler", "finalizer" };
    static readonly HashSet<string> accessToolsTargets = new(StringComparer.Ordinal)
    {
        "Method", "DeclaredMethod", "PropertyGetter", "PropertySetter", "DeclaredPropertyGetter", "DeclaredPropertySetter",
        "Constructor", "DeclaredConstructor", "EnumeratorMoveNext", "AsyncMoveNext", "GetMethod", "GetProperty",
    };

    readonly MetadataReader reader;
    readonly PEReader pe;

    public PatchReader(PEReader pe)
    {
        this.pe = pe;
        reader = pe.GetMetadataReader();
    }

    public string AssemblyName => reader.IsAssembly ? reader.GetString(reader.GetAssemblyDefinition().Name) : "";

    public string AssemblyVersion => reader.IsAssembly ? reader.GetAssemblyDefinition().Version.ToString() : "";

    public List<Patch> Read()
    {
        var found = new List<Patch>();
        foreach (TypeDefinitionHandle handle in reader.TypeDefinitions)
        {
            TypeDefinition type = reader.GetTypeDefinition(handle);
            ReadAttributePatches(type, found);
            foreach (MethodDefinitionHandle methodHandle in type.GetMethods())
            {
                ReadCallPatches(type, reader.GetMethodDefinition(methodHandle), found);
            }
        }
        return found;
    }

    // ---- Attributes ----

    sealed class Target
    {
        public string Type = "";
        public string Member = "";
        public string MethodType = "";
        public string[] Arguments = Array.Empty<string>();
        public bool Any;

        public Target Merge(Target over) => new()
        {
            Type = over.Type != "" ? over.Type : Type,
            Member = over.Member != "" ? over.Member : Member,
            MethodType = over.MethodType != "" ? over.MethodType : MethodType,
            Arguments = over.Arguments.Length > 0 ? over.Arguments : Arguments,
            Any = Any || over.Any,
        };
    }

    void ReadAttributePatches(TypeDefinition type, List<Patch> found)
    {
        var classTargets = new List<Target>();
        foreach (CustomAttributeHandle handle in type.GetCustomAttributes())
        {
            Target? target = HarmonyPatchTarget(reader.GetCustomAttribute(handle));
            if (target != null) classTargets.Add(target);
        }
        bool hasTargetMethod = false;
        var patchMethods = new List<(MethodDefinition method, string kind, List<Target> targets, int priority)>();
        foreach (MethodDefinitionHandle methodHandle in type.GetMethods())
        {
            MethodDefinition method = reader.GetMethodDefinition(methodHandle);
            string name = reader.GetString(method.Name);
            if (name is "TargetMethod" or "TargetMethods") hasTargetMethod = true;
            string kind = KindByName(name);
            var methodTargets = new List<Target>();
            int priority = -1;
            foreach (CustomAttributeHandle handle in method.GetCustomAttributes())
            {
                CustomAttribute attribute = reader.GetCustomAttribute(handle);
                string attributeName = AttributeTypeName(attribute);
                switch (attributeName)
                {
                    case "HarmonyLib.HarmonyPrefix": kind = "prefix"; break;
                    case "HarmonyLib.HarmonyPostfix": kind = "postfix"; break;
                    case "HarmonyLib.HarmonyTranspiler": kind = "transpiler"; break;
                    case "HarmonyLib.HarmonyFinalizer": kind = "finalizer"; break;
                    case "HarmonyLib.HarmonyReversePatch": kind = "reverse"; break;
                    case "HarmonyLib.HarmonyTargetMethod": case "HarmonyLib.HarmonyTargetMethods": hasTargetMethod = true; break;
                    case "HarmonyLib.HarmonyPriority":
                        priority = FirstInt(attribute) ?? -1;
                        break;
                    default:
                        Target? target = HarmonyPatchTarget(attribute);
                        if (target != null) methodTargets.Add(target);
                        break;
                }
            }
            if (kind != "") patchMethods.Add((method, kind, methodTargets, priority));
        }
        if (patchMethods.Count == 0 || (classTargets.Count == 0 && patchMethods.All(p => p.targets.Count == 0))) return;
        string patchClass = FullName(type);
        int classPriority = -1;
        foreach (CustomAttributeHandle handle in type.GetCustomAttributes())
        {
            CustomAttribute attribute = reader.GetCustomAttribute(handle);
            if (AttributeTypeName(attribute) == "HarmonyLib.HarmonyPriority") classPriority = FirstInt(attribute) ?? -1;
        }
        Target classTarget = classTargets.Aggregate(new Target(), (all, next) => all.Merge(next));
        var computed = hasTargetMethod ? TargetMethodTargets(type) : new();
        foreach (var (method, kind, targets, priority) in patchMethods)
        {
            Target target = targets.Aggregate(classTarget, (all, next) => all.Merge(next));
            bool skip = kind == "prefix" && ReturnsBool(method);
            int order = priority >= 0 ? priority : classPriority;
            string patchName = reader.GetString(method.Name);
            if (target.Type == "" && computed.Count > 0)
            {
                // TargetMethod picks the original at run time; what its code names through AccessTools is the likely answer.
                foreach (var (computedType, member, methodType) in computed)
                {
                    found.Add(new Patch("attribute", kind, computedType, member, methodType, Array.Empty<string>(), patchClass,
                        patchName, skip, order, "target read from TargetMethod's code"));
                }
                continue;
            }
            string note = target.Type == "" && hasTargetMethod ? "target chosen at run time by TargetMethod" :
                          target.Type == "" ? "no target type in the attributes" : "";
            found.Add(new Patch("attribute", kind, target.Type, target.Member, target.MethodType, target.Arguments, patchClass,
                patchName, skip, order, note));
        }
    }

    static string KindByName(string name)
    {
        foreach (string kind in kindNames)
        {
            if (string.Equals(name, kind, StringComparison.OrdinalIgnoreCase)) return kind;
        }
        return "";
    }

    Target? HarmonyPatchTarget(CustomAttribute attribute)
    {
        if (AttributeTypeName(attribute) != "HarmonyLib.HarmonyPatch") return null;
        var target = new Target { Any = true };
        CustomAttributeValue<string> value;
        try
        {
            value = attribute.DecodeValue(new AttributeTypes());
        }
        catch (Exception error) when (error is BadImageFormatException or InvalidOperationException or ArgumentException)
        {
            return target;
        }
        var strings = new List<string>();
        foreach (CustomAttributeTypedArgument<string> argument in value.FixedArguments)
        {
            switch (argument.Value)
            {
                case string text when argument.Type == "System.Type":
                    if (target.Type == "") target.Type = TypeFromSerialized(text);
                    break;
                case string text:
                    strings.Add(text);
                    break;
                case ImmutableArray<CustomAttributeTypedArgument<string>> items when argument.Type == "System.Type[]":
                    target.Arguments = items.Select(i => TypeFromSerialized(i.Value as string ?? "")).ToArray();
                    break;
                case int number when argument.Type.EndsWith("MethodType", StringComparison.Ordinal):
                    target.MethodType = MethodTypeName(number);
                    break;
            }
        }
        // (string typeName, string methodName) names both; one string is the method.
        if (strings.Count >= 2 && target.Type == "")
        {
            target.Type = strings[0];
            target.Member = strings[1];
        }
        else if (strings.Count >= 1)
        {
            target.Member = strings[0];
        }
        return target;
    }

    static string MethodTypeName(int value) => value switch
    {
        0 => "Normal", 1 => "Getter", 2 => "Setter", 3 => "Constructor", 4 => "StaticConstructor", 5 => "Enumerator",
        6 => "Async", _ => value.ToString(System.Globalization.CultureInfo.InvariantCulture),
    };

    /// <summary>
    /// A serialized type name as it reads in C#: "System.Collections.Generic.List`1[[Verse.Pawn, Assembly-CSharp, ...]], mscorlib"
    /// as System.Collections.Generic.List&lt;Verse.Pawn&gt;; nested types with a dot; arrays and by-ref marks kept.
    /// </summary>
    static string TypeFromSerialized(string serialized)
    {
        int index = 0;
        return ParseType(serialized.Trim(), ref index);
    }

    static string ParseType(string text, ref int index)
    {
        int start = index;
        while (index < text.Length && text[index] is not ('[' or ',' or ']')) index++;
        string name = text[start..index].Replace('+', '.').Trim();
        var arguments = new List<string>();
        if (index + 1 < text.Length && text[index] == '[' && text[index + 1] == '[')
        {
            index++;                                  // past the outer [
            while (index < text.Length && text[index] == '[')
            {
                index++;                              // past this argument's [
                arguments.Add(ParseType(text, ref index));
                int depth = 0;                        // skip the argument's assembly name, up to its closing ]
                while (index < text.Length && !(text[index] == ']' && depth == 0))
                {
                    if (text[index] == '[') depth++;
                    else if (text[index] == ']') depth--;
                    index++;
                }
                index++;                              // past the ]
                if (index < text.Length && text[index] == ',') index++;
            }
            index++;                                  // past the outer ]
        }
        string suffix = "";
        while (index < text.Length && text[index] == '[')
        {
            int close = text.IndexOf(']', index);
            if (close < 0) break;
            suffix += text[index..(close + 1)];
            index = close + 1;
        }
        if (arguments.Count > 0)
        {
            int tick = name.IndexOf('`');
            name = (tick >= 0 ? name[..tick] : name) + "<" + string.Join(", ", arguments) + ">";
        }
        return name + suffix;
    }

    int? FirstInt(CustomAttribute attribute)
    {
        try
        {
            CustomAttributeValue<string> value = attribute.DecodeValue(new AttributeTypes());
            foreach (CustomAttributeTypedArgument<string> argument in value.FixedArguments)
            {
                if (argument.Value is int number) return number;
            }
        }
        catch (Exception error) when (error is BadImageFormatException or InvalidOperationException or ArgumentException)
        {
        }
        return null;
    }

    bool ReturnsBool(MethodDefinition method)
    {
        BlobReader blob = reader.GetBlobReader(method.Signature);
        SignatureHeader header = blob.ReadSignatureHeader();
        if (header.IsGeneric) blob.ReadCompressedInteger();
        blob.ReadCompressedInteger();
        return blob.ReadSignatureTypeCode() == SignatureTypeCode.Boolean;
    }

    string AttributeTypeName(CustomAttribute attribute)
    {
        switch (attribute.Constructor.Kind)
        {
            case HandleKind.MemberReference:
                MemberReference member = reader.GetMemberReference((MemberReferenceHandle)attribute.Constructor);
                return TypeHandleName(member.Parent);
            case HandleKind.MethodDefinition:
                MethodDefinition method = reader.GetMethodDefinition((MethodDefinitionHandle)attribute.Constructor);
                return FullName(reader.GetTypeDefinition(method.GetDeclaringType()));
            default:
                return "";
        }
    }

    string TypeHandleName(EntityHandle handle) => handle.Kind switch
    {
        HandleKind.TypeReference => FullName(reader.GetTypeReference((TypeReferenceHandle)handle)),
        HandleKind.TypeDefinition => FullName(reader.GetTypeDefinition((TypeDefinitionHandle)handle)),
        HandleKind.TypeSpecification => "(generic)",
        _ => "",
    };

    string FullName(TypeReference type)
    {
        string name = reader.GetString(type.Name);
        if (type.ResolutionScope.Kind == HandleKind.TypeReference)
            return FullName(reader.GetTypeReference((TypeReferenceHandle)type.ResolutionScope)) + "." + name;
        string space = reader.GetString(type.Namespace);
        return space.Length > 0 ? space + "." + name : name;
    }

    string FullName(TypeDefinition type)
    {
        string name = reader.GetString(type.Name);
        TypeDefinitionHandle outer = type.GetDeclaringType();
        if (!outer.IsNil) return FullName(reader.GetTypeDefinition(outer)) + "." + name;
        string space = reader.GetString(type.Namespace);
        return space.Length > 0 ? space + "." + name : name;
    }

    // ---- Calls: harmony.Patch(original, prefix, postfix, transpiler, finalizer) ----

    void ReadCallPatches(TypeDefinition type, MethodDefinition method, List<Patch> found)
    {
        if (method.RelativeVirtualAddress == 0) return;
        MethodBodyBlock body;
        try
        {
            body = pe.GetMethodBody(method.RelativeVirtualAddress);
        }
        catch (BadImageFormatException)
        {
            return;
        }
        WalkIl(body, (targets, patchMethods) => Emit(type, method, targets, patchMethods, found));
    }

    /// <summary>
    /// Reads a method body's IL and follows what Harmony's helpers consume: AccessTools.Method(typeof(T), "Name") and its
    /// kin give a method (a target, or a patch method when new HarmonyMethod(...) takes it next), new HarmonyMethod(typeof(P),
    /// "Name") a patch method, and harmony.Patch(...) ends one patch (onPatch). Returns every method AccessTools found, for a
    /// TargetMethod body. An opcode it does not know stops the walk of that body.
    /// </summary>
    List<(string type, string member, string methodType)> WalkIl(MethodBodyBlock body,
        Action<List<(string type, string member, string methodType)>, List<(string type, string name)>>? onPatch)
    {
        BlobReader il = body.GetILReader();
        // Type tokens and strings in the order they are loaded: a call takes its member as the last string, its type as the
        // last type loaded before that string (types loaded after it are the overload's argument types).
        var loaded = new List<(bool isType, string value)>();
        var targets = new List<(string type, string member, string methodType)>();
        var everyTarget = new List<(string type, string member, string methodType)>();
        var patchMethods = new List<(string type, string name)>();
        while (il.RemainingBytes > 0)
        {
            short code = il.ReadByte();
            if (code == 0xFE) code = (short)(0xFE00 | il.ReadByte());
            if (!operandTypes.TryGetValue(code, out OperandType operand)) return everyTarget;   // unknown opcode: stop here
            switch (operand)
            {
                case OperandType.InlineNone: break;
                case OperandType.ShortInlineBrTarget: case OperandType.ShortInlineI: case OperandType.ShortInlineVar:
                    il.ReadByte(); break;
                case OperandType.InlineVar: il.ReadInt16(); break;
                case OperandType.InlineI8: case OperandType.InlineR: il.ReadInt64(); break;
                case OperandType.InlineSwitch:
                    int count = il.ReadInt32();
                    for (int i = 0; i < count; i++) il.ReadInt32();
                    break;
                case OperandType.InlineString:
                    loaded.Add((false, reader.GetUserString(MetadataTokens.UserStringHandle(il.ReadInt32()))));
                    break;
                case OperandType.InlineTok: case OperandType.InlineType:
                    int typeToken = il.ReadInt32();
                    if (code == 0xD0)   // ldtoken
                    {
                        EntityHandle handle = MetadataTokens.EntityHandle(typeToken);
                        if (handle.Kind is HandleKind.TypeReference or HandleKind.TypeDefinition) loaded.Add((true, TypeHandleName(handle)));
                    }
                    break;
                case OperandType.InlineMethod:
                    var (owner, name) = MethodName(MetadataTokens.EntityHandle(il.ReadInt32()));
                    if ((owner == "HarmonyLib.AccessTools" && name == "TypeByName" || owner == "System.Type" && name == "GetType")
                        && loaded.Count > 0 && !loaded[^1].isType)
                    {
                        loaded[^1] = (true, loaded[^1].value);   // AccessTools.TypeByName("Mod.Type") names a type
                    }
                    else if (owner == "HarmonyLib.AccessTools" && accessToolsTargets.Contains(name) || owner == "System.Type" && name is "GetMethod" or "GetProperty")
                    {
                        var (targetType, member) = TypeAndMember(loaded);
                        string methodType = name.Contains("Getter") ? "Getter" : name.Contains("Setter") ? "Setter" :
                                            name.Contains("Constructor") ? "Constructor" : name.StartsWith("Enumerator") ? "Enumerator" :
                                            name.StartsWith("Async") ? "Async" : "Normal";
                        if (name.Contains("Constructor")) member = ".ctor";
                        targets.Add((targetType, member, methodType));
                        everyTarget.Add((targetType, member, methodType));
                        loaded.Clear();
                    }
                    else if (owner == "HarmonyLib.HarmonyMethod" && name == ".ctor")
                    {
                        if (loaded.Count > 0)
                        {
                            patchMethods.Add(TypeAndMember(loaded));
                        }
                        else if (targets.Count > 0)
                        {
                            // new HarmonyMethod(AccessTools.Method(typeof(P), "Postfix")): that method is the patch, not a target.
                            var taken = targets[^1];
                            targets.RemoveAt(targets.Count - 1);
                            patchMethods.Add((taken.type, taken.member));
                        }
                        else
                        {
                            patchMethods.Add(("", ""));
                        }
                        loaded.Clear();
                    }
                    else if (owner == "HarmonyLib.Harmony" && name == "Patch")
                    {
                        onPatch?.Invoke(targets, patchMethods);
                        targets.Clear();
                        patchMethods.Clear();
                    }
                    break;
                default:
                    il.ReadInt32(); break;
            }
        }
        return everyTarget;
    }

    /// <summary>The member a lookup names (the last string loaded) and its type (the last type loaded before that string);
    /// "Type:Method" in one string names both, as AccessTools.Method("Type:Method") does.</summary>
    static (string type, string member) TypeAndMember(List<(bool isType, string value)> loaded)
    {
        int at = loaded.FindLastIndex(item => !item.isType);
        string member = at >= 0 ? loaded[at].value : "";
        int before = at >= 0 ? loaded.FindLastIndex(at, item => item.isType) : loaded.FindLastIndex(item => item.isType);
        string type = before >= 0 ? loaded[before].value : "";
        if (type == "" && member.Contains(':'))
        {
            type = member[..member.IndexOf(':')];
            member = member[(member.IndexOf(':') + 1)..];
        }
        return (type, member);
    }

    /// <summary>The methods a TargetMethod or TargetMethods body names through AccessTools, read from its IL.</summary>
    List<(string type, string member, string methodType)> TargetMethodTargets(TypeDefinition type)
    {
        foreach (MethodDefinitionHandle handle in type.GetMethods())
        {
            MethodDefinition method = reader.GetMethodDefinition(handle);
            string name = reader.GetString(method.Name);
            bool marked = method.GetCustomAttributes().Any(a => AttributeTypeName(reader.GetCustomAttribute(a))
                is "HarmonyLib.HarmonyTargetMethod" or "HarmonyLib.HarmonyTargetMethods");
            if ((name is "TargetMethod" or "TargetMethods" || marked) && method.RelativeVirtualAddress != 0)
            {
                try
                {
                    return WalkIl(pe.GetMethodBody(method.RelativeVirtualAddress), null);
                }
                catch (BadImageFormatException)
                {
                    return new();
                }
            }
        }
        return new();
    }

    void Emit(TypeDefinition type, MethodDefinition method, List<(string type, string member, string methodType)> targets,
              List<(string type, string name)> patchMethods, List<Patch> found)
    {
        // The original is usually looked up first; later lookups in the same stretch are reflection for other ends.
        (string type, string member, string methodType) target = targets.Count > 0 ? targets[0] : ("", "", "");
        string note = targets.Count == 0 ? "original worked out at run time" :
                      target.type == "" ? "the original's type worked out at run time" : "";
        string where = FullName(type) + "." + reader.GetString(method.Name);
        if (patchMethods.Count == 0)
        {
            found.Add(new Patch("call", "unknown", target.type, target.member, target.methodType, Array.Empty<string>(), where, "",
                false, -1, (note + " patch methods passed in variables").Trim()));
            return;
        }
        foreach (var (patchType, patchName) in patchMethods)
        {
            string kind = kindNames.FirstOrDefault(k => patchName.Contains(k, StringComparison.OrdinalIgnoreCase)) ?? "unknown";
            found.Add(new Patch("call", kind, target.type, target.member, target.methodType, Array.Empty<string>(),
                patchType != "" ? patchType : where, patchName, false, -1, note));
        }
    }

    (string owner, string name) MethodName(EntityHandle handle)
    {
        switch (handle.Kind)
        {
            case HandleKind.MemberReference:
                MemberReference member = reader.GetMemberReference((MemberReferenceHandle)handle);
                return (TypeHandleName(member.Parent), reader.GetString(member.Name));
            case HandleKind.MethodDefinition:
                MethodDefinition method = reader.GetMethodDefinition((MethodDefinitionHandle)handle);
                return (FullName(reader.GetTypeDefinition(method.GetDeclaringType())), reader.GetString(method.Name));
            case HandleKind.MethodSpecification:
                MethodSpecification spec = reader.GetMethodSpecification((MethodSpecificationHandle)handle);
                return MethodName(spec.Method);
            default:
                return ("", "");
        }
    }

    static Dictionary<short, OperandType> BuildOperandTypes()
    {
        var table = new Dictionary<short, OperandType>();
        foreach (FieldInfo field in typeof(OpCodes).GetFields(BindingFlags.Public | BindingFlags.Static))
        {
            if (field.GetValue(null) is OpCode opcode) table[opcode.Value] = opcode.OperandType;
        }
        return table;
    }

    /// <summary>Attribute argument types as names; enums are read as Int32 (Harmony's MethodType and ArgumentType are).</summary>
    sealed class AttributeTypes : ICustomAttributeTypeProvider<string>
    {
        public string GetPrimitiveType(PrimitiveTypeCode typeCode) => typeCode.ToString();
        public string GetSystemType() => "System.Type";
        public string GetSZArrayType(string elementType) => elementType + "[]";
        public string GetTypeFromDefinition(MetadataReader reader, TypeDefinitionHandle handle, byte rawTypeKind) =>
            reader.GetString(reader.GetTypeDefinition(handle).Namespace) + "." + reader.GetString(reader.GetTypeDefinition(handle).Name);
        public string GetTypeFromReference(MetadataReader reader, TypeReferenceHandle handle, byte rawTypeKind) =>
            reader.GetString(reader.GetTypeReference(handle).Namespace) + "." + reader.GetString(reader.GetTypeReference(handle).Name);
        public string GetTypeFromSerializedName(string name) => name;
        public PrimitiveTypeCode GetUnderlyingEnumType(string type) => PrimitiveTypeCode.Int32;
        public bool IsSystemType(string type) => type == "System.Type";
    }
}
