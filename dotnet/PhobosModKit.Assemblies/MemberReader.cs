using System.Collections.Immutable;
using System.Reflection;
using System.Reflection.Metadata;
using System.Reflection.PortableExecutable;

namespace Phobos.ModKit.Assemblies;

public sealed record MemberField(string Name, string Type, bool IsStatic, string Access);
public sealed record MemberMethod(string Name, string[] Parameters, string Returns, bool IsStatic, string Access);
public sealed record MemberProperty(string Name, string Type, bool HasGetter, bool HasSetter, bool IsStatic);

/// <summary>The members of one type: what a patch or a reflected lookup can name on it.</summary>
public sealed record TypeMembers(string Type, string Assembly, string Path, string Base, string[] Interfaces,
    List<MemberField> Fields, List<MemberMethod> Methods, List<MemberProperty> Properties);

/// <summary>
/// Lists the members of named types across a set of assemblies, through their metadata alone (nothing is loaded or run),
/// and follows each type's base types across the same set, so a lookup that Harmony or reflection would satisfy from a
/// base class can be answered. A name is matched by its full name, or by any dotted suffix of it (a nested type as
/// Outer.Inner, a bare simple name); every match is returned, and the caller decides which it meant.
/// </summary>
public sealed class MemberReader : IDisposable
{
    sealed class Loaded
    {
        public string Path = "";
        public string Assembly = "";
        public FileStream? Stream;
        public PEReader? Pe;
        public MetadataReader? Reader;
        public readonly Dictionary<string, TypeDefinitionHandle> Types = new(StringComparer.Ordinal);
    }

    readonly List<Loaded> loaded = new();
    public readonly List<object> Errors = new();

    public MemberReader(IEnumerable<string> files)
    {
        foreach (string file in files)
        {
            var entry = new Loaded { Path = file };
            try
            {
                entry.Stream = File.OpenRead(file);
                entry.Pe = new PEReader(entry.Stream);
                if (!entry.Pe.HasMetadata)
                {
                    Errors.Add(new { path = file, error = "no .NET metadata (a native DLL)" });
                    entry.Pe.Dispose();
                    entry.Stream.Dispose();
                    continue;
                }
                entry.Reader = entry.Pe.GetMetadataReader();
                entry.Assembly = entry.Reader.IsAssembly ? entry.Reader.GetString(entry.Reader.GetAssemblyDefinition().Name) : "";
                foreach (TypeDefinitionHandle handle in entry.Reader.TypeDefinitions)
                {
                    entry.Types[Names.Full(entry.Reader, entry.Reader.GetTypeDefinition(handle))] = handle;
                }
                loaded.Add(entry);
            }
            catch (Exception error) when (error is IOException or BadImageFormatException or UnauthorizedAccessException or InvalidOperationException)
            {
                Errors.Add(new { path = file, error = error.Message });
                entry.Pe?.Dispose();
                entry.Stream?.Dispose();
            }
        }
    }

    public void Dispose()
    {
        foreach (Loaded entry in loaded)
        {
            entry.Pe?.Dispose();
            entry.Stream?.Dispose();
        }
    }

    /// <summary>The members of every type matching a wanted name, and of their base types, each type once.</summary>
    public List<TypeMembers> Read(IEnumerable<string> wanted)
    {
        var found = new List<TypeMembers>();
        var emitted = new HashSet<string>(StringComparer.Ordinal);
        var queue = new Queue<(Loaded entry, string fullName)>();
        foreach (string name in wanted.Select(n => n.Trim()).Where(n => n.Length > 0).Distinct(StringComparer.Ordinal))
        {
            foreach ((Loaded entry, string fullName) in Matches(name)) queue.Enqueue((entry, fullName));
        }
        while (queue.Count > 0)
        {
            (Loaded entry, string fullName) = queue.Dequeue();
            if (!emitted.Add(entry.Path + "|" + fullName)) continue;
            TypeMembers members = ReadType(entry, entry.Types[fullName]);
            found.Add(members);
            string baseName = StripGenerics(members.Base);
            if (baseName is "" or "System.Object" or "System.ValueType" or "System.Enum") continue;
            foreach (Loaded other in loaded)
            {
                if (other.Types.ContainsKey(baseName)) queue.Enqueue((other, baseName));
            }
        }
        return found;
    }

    IEnumerable<(Loaded entry, string fullName)> Matches(string name)
    {
        string bare = StripGenerics(name);
        foreach (Loaded entry in loaded)
        {
            foreach (string fullName in entry.Types.Keys)
            {
                if (fullName == bare || fullName.EndsWith("." + bare, StringComparison.Ordinal)) yield return (entry, fullName);
            }
        }
    }

    static string StripGenerics(string name)
    {
        int angle = name.IndexOf('<');
        return angle >= 0 ? name[..angle] : name;
    }

    TypeMembers ReadType(Loaded entry, TypeDefinitionHandle handle)
    {
        MetadataReader reader = entry.Reader!;
        TypeDefinition type = reader.GetTypeDefinition(handle);
        var provider = new NameProvider(reader);
        var context = new GenericContext(GenericNames(reader, type.GetGenericParameters()), Array.Empty<string>());
        string baseName = type.BaseType.IsNil ? "" : Names.OfHandle(reader, type.BaseType, provider, context);
        var interfaces = new List<string>();
        foreach (InterfaceImplementationHandle implementation in type.GetInterfaceImplementations())
        {
            interfaces.Add(Names.OfHandle(reader, reader.GetInterfaceImplementation(implementation).Interface, provider, context));
        }
        var fields = new List<MemberField>();
        foreach (FieldDefinitionHandle fieldHandle in type.GetFields())
        {
            FieldDefinition field = reader.GetFieldDefinition(fieldHandle);
            fields.Add(new MemberField(reader.GetString(field.Name), Safe(() => field.DecodeSignature(provider, context)),
                (field.Attributes & FieldAttributes.Static) != 0, FieldAccess(field.Attributes)));
        }
        var methods = new List<MemberMethod>();
        var accessors = new HashSet<MethodDefinitionHandle>();
        var properties = new List<MemberProperty>();
        foreach (PropertyDefinitionHandle propertyHandle in type.GetProperties())
        {
            PropertyDefinition property = reader.GetPropertyDefinition(propertyHandle);
            PropertyAccessors pair = property.GetAccessors();
            if (!pair.Getter.IsNil) accessors.Add(pair.Getter);
            if (!pair.Setter.IsNil) accessors.Add(pair.Setter);
            MethodDefinitionHandle any = pair.Getter.IsNil ? pair.Setter : pair.Getter;
            bool isStatic = !any.IsNil && (reader.GetMethodDefinition(any).Attributes & MethodAttributes.Static) != 0;
            string propertyType = Safe(() => property.DecodeSignature(provider, context).ReturnType);
            properties.Add(new MemberProperty(reader.GetString(property.Name), propertyType, !pair.Getter.IsNil, !pair.Setter.IsNil, isStatic));
        }
        foreach (MethodDefinitionHandle methodHandle in type.GetMethods())
        {
            MethodDefinition method = reader.GetMethodDefinition(methodHandle);
            string name = reader.GetString(method.Name);
            var methodContext = new GenericContext(context.TypeParameters, GenericNames(reader, method.GetGenericParameters()));
            string[] parameters;
            string returns;
            try
            {
                MethodSignature<string> signature = method.DecodeSignature(provider, methodContext);
                parameters = signature.ParameterTypes.ToArray();
                returns = signature.ReturnType;
            }
            catch (Exception error) when (error is BadImageFormatException or InvalidOperationException or ArgumentException)
            {
                parameters = Array.Empty<string>();
                returns = "?";
            }
            methods.Add(new MemberMethod(name, parameters, returns, (method.Attributes & MethodAttributes.Static) != 0, MethodAccess(method.Attributes)));
        }
        return new TypeMembers(Names.Full(reader, type), entry.Assembly, entry.Path, baseName, interfaces.ToArray(), fields, methods, properties);
    }

    static string Safe(Func<string> read)
    {
        try
        {
            return read();
        }
        catch (Exception error) when (error is BadImageFormatException or InvalidOperationException or ArgumentException)
        {
            return "?";
        }
    }

    static string[] GenericNames(MetadataReader reader, GenericParameterHandleCollection parameters) =>
        parameters.Select(p => reader.GetString(reader.GetGenericParameter(p).Name)).ToArray();

    static string FieldAccess(FieldAttributes attributes) => (attributes & FieldAttributes.FieldAccessMask) switch
    {
        FieldAttributes.Public => "public",
        FieldAttributes.Private => "private",
        FieldAttributes.Family => "protected",
        FieldAttributes.Assembly => "internal",
        FieldAttributes.FamORAssem => "protected internal",
        FieldAttributes.FamANDAssem => "private protected",
        _ => "",
    };

    static string MethodAccess(MethodAttributes attributes) => (attributes & MethodAttributes.MemberAccessMask) switch
    {
        MethodAttributes.Public => "public",
        MethodAttributes.Private => "private",
        MethodAttributes.Family => "protected",
        MethodAttributes.Assembly => "internal",
        MethodAttributes.FamORAssem => "protected internal",
        MethodAttributes.FamANDAssem => "private protected",
        _ => "",
    };
}

/// <summary>The names of the generic parameters in scope while a signature is decoded.</summary>
public sealed record GenericContext(string[] TypeParameters, string[] MethodParameters);

/// <summary>Type names as full names: System.Single, Verse.Pawn, System.Collections.Generic.List&lt;Verse.Pawn&gt;, Verse.Thing[], ref System.Int32.</summary>
public sealed class NameProvider : ISignatureTypeProvider<string, GenericContext>
{
    readonly MetadataReader reader;

    public NameProvider(MetadataReader reader)
    {
        this.reader = reader;
    }

    public string GetPrimitiveType(PrimitiveTypeCode typeCode) => typeCode switch
    {
        PrimitiveTypeCode.Boolean => "System.Boolean",
        PrimitiveTypeCode.Byte => "System.Byte",
        PrimitiveTypeCode.SByte => "System.SByte",
        PrimitiveTypeCode.Char => "System.Char",
        PrimitiveTypeCode.Int16 => "System.Int16",
        PrimitiveTypeCode.UInt16 => "System.UInt16",
        PrimitiveTypeCode.Int32 => "System.Int32",
        PrimitiveTypeCode.UInt32 => "System.UInt32",
        PrimitiveTypeCode.Int64 => "System.Int64",
        PrimitiveTypeCode.UInt64 => "System.UInt64",
        PrimitiveTypeCode.Single => "System.Single",
        PrimitiveTypeCode.Double => "System.Double",
        PrimitiveTypeCode.IntPtr => "System.IntPtr",
        PrimitiveTypeCode.UIntPtr => "System.UIntPtr",
        PrimitiveTypeCode.String => "System.String",
        PrimitiveTypeCode.Object => "System.Object",
        PrimitiveTypeCode.Void => "System.Void",
        PrimitiveTypeCode.TypedReference => "System.TypedReference",
        _ => typeCode.ToString(),
    };

    public string GetTypeFromDefinition(MetadataReader r, TypeDefinitionHandle handle, byte rawTypeKind) => Names.Full(r, r.GetTypeDefinition(handle));

    public string GetTypeFromReference(MetadataReader r, TypeReferenceHandle handle, byte rawTypeKind) => Names.Full(r, r.GetTypeReference(handle));

    public string GetTypeFromSpecification(MetadataReader r, GenericContext context, TypeSpecificationHandle handle, byte rawTypeKind) =>
        r.GetTypeSpecification(handle).DecodeSignature(this, context);

    public string GetSZArrayType(string elementType) => elementType + "[]";

    public string GetArrayType(string elementType, ArrayShape shape) => elementType + "[" + new string(',', Math.Max(0, shape.Rank - 1)) + "]";

    public string GetByReferenceType(string elementType) => "ref " + elementType;

    public string GetPointerType(string elementType) => elementType + "*";

    public string GetGenericInstantiation(string genericType, ImmutableArray<string> typeArguments)
    {
        int tick = genericType.IndexOf('`');
        return (tick >= 0 ? genericType[..tick] : genericType) + "<" + string.Join(", ", typeArguments) + ">";
    }

    public string GetGenericMethodParameter(GenericContext context, int index) =>
        index < context.MethodParameters.Length ? context.MethodParameters[index] : "!!" + index;

    public string GetGenericTypeParameter(GenericContext context, int index) =>
        index < context.TypeParameters.Length ? context.TypeParameters[index] : "!" + index;

    public string GetModifiedType(string modifier, string unmodifiedType, bool isRequired) => unmodifiedType;

    public string GetPinnedType(string elementType) => elementType;

    public string GetFunctionPointerType(MethodSignature<string> signature) => "fnptr";
}

/// <summary>Full type names as the patch reader writes them: namespace, then nested types joined with dots.</summary>
public static class Names
{
    public static string Full(MetadataReader reader, TypeDefinition type)
    {
        string name = reader.GetString(type.Name);
        TypeDefinitionHandle outer = type.GetDeclaringType();
        if (!outer.IsNil) return Full(reader, reader.GetTypeDefinition(outer)) + "." + name;
        string space = reader.GetString(type.Namespace);
        return space.Length > 0 ? space + "." + name : name;
    }

    public static string Full(MetadataReader reader, TypeReference type)
    {
        string name = reader.GetString(type.Name);
        if (type.ResolutionScope.Kind == HandleKind.TypeReference)
            return Full(reader, reader.GetTypeReference((TypeReferenceHandle)type.ResolutionScope)) + "." + name;
        string space = reader.GetString(type.Namespace);
        return space.Length > 0 ? space + "." + name : name;
    }

    public static string OfHandle(MetadataReader reader, EntityHandle handle, NameProvider provider, GenericContext context) => handle.Kind switch
    {
        HandleKind.TypeDefinition => Full(reader, reader.GetTypeDefinition((TypeDefinitionHandle)handle)),
        HandleKind.TypeReference => Full(reader, reader.GetTypeReference((TypeReferenceHandle)handle)),
        HandleKind.TypeSpecification => reader.GetTypeSpecification((TypeSpecificationHandle)handle).DecodeSignature(provider, context),
        _ => "",
    };
}
