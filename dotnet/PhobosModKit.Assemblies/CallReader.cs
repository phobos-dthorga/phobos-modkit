using System.Reflection;
using System.Reflection.Emit;
using System.Reflection.Metadata;
using System.Reflection.Metadata.Ecma335;
using System.Reflection.PortableExecutable;

namespace Phobos.ModKit.Assemblies;

/// <summary>A method or field another method uses: its declaring type, its name, and the assembly it comes from ("" for this one).</summary>
public sealed record CallTarget(string Type, string Name, string Assembly);

/// <summary>A type: what it is, what it derives from and which interfaces it implements.</summary>
public sealed record CallType(string Name, string Kind, string Base, string[] Interfaces);

/// <summary>
/// A method as the source names it, with what it calls and which fields it reads or writes. Overloads share one entry (the
/// source declares them under one name), and the code the compiler made for a method's lambdas, local functions, iterators and
/// async parts counts as the method's own.
/// </summary>
public sealed record CallMethod(string Type, string Name, bool Virtual, List<CallTarget> Calls, List<CallTarget> Fields);

/// <summary>
/// Reads which methods call which, from an assembly's metadata and method bodies (System.Reflection.Metadata): the assembly is
/// opened as a file and never loaded or run. Exact for what the compiled code does, across assemblies: a call into the game or
/// another mod names that type and its assembly. A body with an opcode it does not know is read up to that opcode.
/// </summary>
public sealed class CallReader
{
    static readonly Dictionary<short, OperandType> operandTypes = BuildOperandTypes();

    readonly PEReader pe;
    readonly MetadataReader reader;
    readonly NameProvider provider;

    public CallReader(PEReader pe)
    {
        this.pe = pe;
        reader = pe.GetMetadataReader();
        provider = new NameProvider(reader);
    }

    public string AssemblyName => reader.IsAssembly ? reader.GetString(reader.GetAssemblyDefinition().Name) : "";

    public (List<CallType> Types, List<CallMethod> Methods) Read()
    {
        var types = new List<CallType>();
        var methods = new Dictionary<(string, string), CallMethod>();
        foreach (TypeDefinitionHandle handle in reader.TypeDefinitions)
        {
            TypeDefinition type = reader.GetTypeDefinition(handle);
            string full = Names.Full(reader, type);
            if (full == "<Module>") continue;
            var context = new GenericContext(GenericNames(type.GetGenericParameters()), Array.Empty<string>());
            if (!IsGenerated(full))
            {
                var interfaces = new List<string>();
                foreach (InterfaceImplementationHandle implementation in type.GetInterfaceImplementations())
                {
                    interfaces.Add(Plain(Names.OfHandle(reader, reader.GetInterfaceImplementation(implementation).Interface, provider, context)));
                }
                string baseName = type.BaseType.IsNil ? "" : Plain(Names.OfHandle(reader, type.BaseType, provider, context));
                types.Add(new CallType(full, KindOf(type, baseName), baseName, interfaces.ToArray()));
            }
            foreach (MethodDefinitionHandle methodHandle in type.GetMethods())
            {
                MethodDefinition method = reader.GetMethodDefinition(methodHandle);
                var (ownerType, ownerName) = Owner(full, reader.GetString(method.Name));
                if (!methods.TryGetValue((ownerType, ownerName), out CallMethod? entry))
                {
                    bool isVirtual = (method.Attributes & MethodAttributes.Virtual) != 0 && ownerName == reader.GetString(method.Name);
                    entry = new CallMethod(ownerType, ownerName, isVirtual, new List<CallTarget>(), new List<CallTarget>());
                    methods[(ownerType, ownerName)] = entry;
                }
                if (method.RelativeVirtualAddress != 0) Walk(method, entry);
            }
        }
        foreach (CallMethod method in methods.Values)
        {
            method.Calls.RemoveAll(c => c.Assembly == "" && Owner(c.Type, c.Name) == (method.Type, method.Name));
            Dedupe(method.Calls);
            Dedupe(method.Fields);
        }
        return (types, methods.Values.Where(m => m.Calls.Count > 0 || m.Fields.Count > 0 || !IsGenerated(m.Name)).ToList());
    }

    void Walk(MethodDefinition method, CallMethod entry)
    {
        MethodBodyBlock body;
        try
        {
            body = pe.GetMethodBody(method.RelativeVirtualAddress);
        }
        catch (BadImageFormatException)
        {
            return;
        }
        BlobReader il = body.GetILReader();
        while (il.RemainingBytes > 0)
        {
            short code = il.ReadByte();
            if (code == 0xFE) code = (short)(0xFE00 | il.ReadByte());
            if (!operandTypes.TryGetValue(code, out OperandType operand)) return;
            switch (operand)
            {
                case OperandType.InlineNone: break;
                case OperandType.ShortInlineBrTarget: case OperandType.ShortInlineI: case OperandType.ShortInlineVar: il.ReadByte(); break;
                case OperandType.InlineVar: il.ReadInt16(); break;
                case OperandType.InlineI8: case OperandType.InlineR: il.ReadInt64(); break;
                case OperandType.InlineSwitch:
                    int count = il.ReadInt32();
                    for (int i = 0; i < count; i++) il.ReadInt32();
                    break;
                case OperandType.InlineMethod:
                    CallTarget? callee = MethodTarget(MetadataTokens.EntityHandle(il.ReadInt32()));
                    if (callee is not null)
                    {
                        // A call into the method's own lambdas or iterator parts is the method itself; what they call is read with them.
                        var (calleeType, calleeName) = Owner(callee.Type, callee.Name);
                        if (callee.Assembly != "" || (calleeType, calleeName) != (entry.Type, entry.Name))
                            entry.Calls.Add(callee.Assembly == "" ? callee with { Type = calleeType, Name = calleeName } : callee);
                    }
                    break;
                case OperandType.InlineField:
                    CallTarget? field = FieldTarget(MetadataTokens.EntityHandle(il.ReadInt32()));
                    if (field is not null && !IsGenerated(field.Name) && !IsGenerated(field.Type)) entry.Fields.Add(field);
                    break;
                default: il.ReadInt32(); break;   // a token or 32-bit operand this reader does not follow
            }
        }
    }

    CallTarget? MethodTarget(EntityHandle handle)
    {
        switch (handle.Kind)
        {
            case HandleKind.MethodDefinition:
                MethodDefinition method = reader.GetMethodDefinition((MethodDefinitionHandle)handle);
                return new CallTarget(Names.Full(reader, reader.GetTypeDefinition(method.GetDeclaringType())), reader.GetString(method.Name), "");
            case HandleKind.MemberReference:
                MemberReference member = reader.GetMemberReference((MemberReferenceHandle)handle);
                var (type, assembly) = Parent(member.Parent);
                return type == "" ? null : new CallTarget(type, reader.GetString(member.Name), assembly);
            case HandleKind.MethodSpecification:
                return MethodTarget(reader.GetMethodSpecification((MethodSpecificationHandle)handle).Method);
            default:
                return null;
        }
    }

    CallTarget? FieldTarget(EntityHandle handle)
    {
        switch (handle.Kind)
        {
            case HandleKind.FieldDefinition:
                FieldDefinition field = reader.GetFieldDefinition((FieldDefinitionHandle)handle);
                return new CallTarget(Names.Full(reader, reader.GetTypeDefinition(field.GetDeclaringType())), reader.GetString(field.Name), "");
            case HandleKind.MemberReference:
                MemberReference member = reader.GetMemberReference((MemberReferenceHandle)handle);
                var (type, assembly) = Parent(member.Parent);
                return type == "" ? null : new CallTarget(type, reader.GetString(member.Name), assembly);
            default:
                return null;
        }
    }

    /// <summary>A member reference's declaring type, with generic arguments left off, and the assembly it comes from.</summary>
    (string Type, string Assembly) Parent(EntityHandle parent)
    {
        switch (parent.Kind)
        {
            case HandleKind.TypeDefinition:
                return (Names.Full(reader, reader.GetTypeDefinition((TypeDefinitionHandle)parent)), "");
            case HandleKind.TypeReference:
                TypeReference reference = reader.GetTypeReference((TypeReferenceHandle)parent);
                return (Names.Full(reader, reference), ScopeAssembly(reference));
            case HandleKind.TypeSpecification:
                var context = new GenericContext(Array.Empty<string>(), Array.Empty<string>());
                string name = Plain(reader.GetTypeSpecification((TypeSpecificationHandle)parent).DecodeSignature(provider, context));
                return (name, "?");
            case HandleKind.MethodDefinition:
                MethodDefinition method = reader.GetMethodDefinition((MethodDefinitionHandle)parent);
                return (Names.Full(reader, reader.GetTypeDefinition(method.GetDeclaringType())), "");
            default:
                return ("", "");
        }
    }

    string ScopeAssembly(TypeReference reference)
    {
        EntityHandle scope = reference.ResolutionScope;
        while (scope.Kind == HandleKind.TypeReference) scope = reader.GetTypeReference((TypeReferenceHandle)scope).ResolutionScope;
        return scope.Kind == HandleKind.AssemblyReference
            ? reader.GetString(reader.GetAssemblyReference((AssemblyReferenceHandle)scope).Name)
            : "";
    }

    /// <summary>
    /// The method a piece of compiled code belongs to in the source: a lambda or local function ("&lt;Tick&gt;b__3_0" in the closure
    /// class "&lt;&gt;c") and an iterator or async state machine ("&lt;Gather&gt;d__5.MoveNext") count as the method that wrote them.
    /// </summary>
    public static (string Type, string Name) Owner(string type, string name)
    {
        string last = type[(type.LastIndexOf('.') + 1)..];
        string outer = type.Contains('.') ? type[..type.LastIndexOf('.')] : type;
        string? written = Written(name);
        if (last.StartsWith("<>c")) return (outer, written ?? name);
        string? machine = Written(last);
        if (machine is not null && last.Contains(">d__")) return (outer, machine);
        return (type, written ?? name);
    }

    /// <summary>The source method's name inside a compiler-made name ("Tick" in "&lt;Tick&gt;b__3_0"); null when the name is the source's own.</summary>
    static string? Written(string name)
    {
        if (!name.StartsWith('<')) return null;
        int end = name.IndexOf('>');
        return end > 1 ? name[1..end] : null;
    }

    static bool IsGenerated(string name) => name.Contains('<');

    static string Plain(string name)
    {
        int generic = name.IndexOf('<');
        return generic > 0 ? name[..generic] : name;
    }

    static void Dedupe(List<CallTarget> targets)
    {
        var seen = new HashSet<CallTarget>();
        targets.RemoveAll(t => !seen.Add(t));
    }

    string KindOf(TypeDefinition type, string baseName)
    {
        if ((type.Attributes & TypeAttributes.Interface) != 0) return "interface";
        if (baseName == "System.Enum") return "enum";
        if (baseName == "System.ValueType") return "struct";
        if (baseName == "System.MulticastDelegate") return "delegate";
        return "class";
    }

    string[] GenericNames(GenericParameterHandleCollection parameters) =>
        parameters.Select(p => reader.GetString(reader.GetGenericParameter(p).Name)).ToArray();

    static Dictionary<short, OperandType> BuildOperandTypes()
    {
        var table = new Dictionary<short, OperandType>();
        foreach (FieldInfo field in typeof(OpCodes).GetFields(BindingFlags.Public | BindingFlags.Static))
        {
            if (field.GetValue(null) is OpCode opcode) table[opcode.Value] = opcode.OperandType;
        }
        return table;
    }
}
