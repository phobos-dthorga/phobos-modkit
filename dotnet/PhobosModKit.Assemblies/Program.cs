using System.Reflection.PortableExecutable;
using System.Text.Encodings.Web;
using System.Text.Json;
using Phobos.ModKit.Assemblies;

// PhobosModKit.Assemblies patches FILE...             one JSON object per assembly, on its own line, in the order given.
// PhobosModKit.Assemblies members @TYPES FILE...      one JSON object per type named in TYPES (one name per line; a full
//                                                     name or a dotted suffix of one) found in any FILE, and per base type.
// PhobosModKit.Assemblies calls FILE...               one JSON object per assembly: its types (kind, base, interfaces) and
//                                                     each method with what it calls and which fields it uses (CallReader).
// PhobosModKit.Assemblies refs FILE...                one JSON object per assembly: its own name and version, the names of
//                                                     the assemblies it is built on (its AssemblyRef table, 1.84.0), and
//                                                     those its types inherit from.
// PhobosModKit.Assemblies calls-of @METHODS FILE...   as calls, but only the methods METHODS names, one "Type<TAB>Name" a line
//                                                     (1.116.0: a game's own methods a change hands on to, for rings).
// FILE may be @LISTFILE, one path per line. Reads metadata only: an assembly is opened as a file and never loaded or run.
// A file that is not a readable .NET assembly gives an object with an error instead of stopping the run.
string[] commands = ["patches", "members", "calls", "refs", "calls-of"];
if (args.Length < 1 || !commands.Contains(args[0]) || (args[0] == "calls-of" && (args.Length < 3 || !args[1].StartsWith('@'))))
{
    Console.Error.WriteLine("usage: PhobosModKit.Assemblies patches FILE...   (or patches @LISTFILE, one path per line)");
    Console.Error.WriteLine("       PhobosModKit.Assemblies members @TYPESFILE FILE...");
    Console.Error.WriteLine("       PhobosModKit.Assemblies calls FILE...");
    Console.Error.WriteLine("       PhobosModKit.Assemblies refs FILE...");
    Console.Error.WriteLine("       PhobosModKit.Assemblies calls-of @METHODSFILE FILE...");
    return 2;
}
HashSet<(string, string)> wantedMethods = args[0] == "calls-of"
    ? File.ReadAllLines(args[1][1..]).Select(line => line.Split('\t')).Where(p => p.Length == 2).Select(p => (p[0], p[1])).ToHashSet()
    : [];
var options = new JsonSerializerOptions { PropertyNamingPolicy = JsonNamingPolicy.CamelCase, Encoder = JavaScriptEncoder.UnsafeRelaxedJsonEscaping };
using Stream stdout = Console.OpenStandardOutput();
using var writer = new StreamWriter(stdout, new System.Text.UTF8Encoding(false));

if (args[0] == "members")
{
    if (args.Length < 3 || !args[1].StartsWith('@'))
    {
        Console.Error.WriteLine("usage: PhobosModKit.Assemblies members @TYPESFILE FILE...");
        return 2;
    }
    string[] wanted = File.ReadAllLines(args[1][1..]);
    using var members = new MemberReader(Files(args.Skip(2)));
    foreach (TypeMembers type in members.Read(wanted)) writer.WriteLine(JsonSerializer.Serialize(type, options));
    foreach (object error in members.Errors) writer.WriteLine(JsonSerializer.Serialize(error, options));
    return 0;
}

foreach (string file in Files(args.Skip(args[0] == "calls-of" ? 2 : 1)))
{
    object result;
    try
    {
        using FileStream stream = File.OpenRead(file);
        using var pe = new PEReader(stream);
        if (!pe.HasMetadata)
        {
            result = new { path = file, error = "no .NET metadata (a native DLL)" };
        }
        else if (args[0] == "refs")
        {
            var metadata = System.Reflection.Metadata.PEReaderExtensions.GetMetadataReader(pe);
            string name = metadata.IsAssembly ? metadata.GetString(metadata.GetAssemblyDefinition().Name) : "";
            var references = metadata.AssemblyReferences
                .Select(handle => metadata.GetString(metadata.GetAssemblyReference(handle).Name))
                .Distinct()
                .ToList();
            string version = metadata.IsAssembly ? metadata.GetAssemblyDefinition().Version.ToString() : "";
            result = new { path = file, assembly = name, version, references, inherits = Inherited(metadata) };
        }
        else if (args[0] == "calls")
        {
            var callReader = new CallReader(pe);
            var (types, methods) = callReader.Read();
            result = new { path = file, assembly = callReader.AssemblyName, types, methods };
        }
        else if (args[0] == "calls-of")
        {
            var callReader = new CallReader(pe);
            var (_, methods) = callReader.Read();
            result = new
            {
                path = file,
                assembly = callReader.AssemblyName,
                methods = methods.Where(m => wantedMethods.Contains((m.Type, m.Name))).ToList(),
            };
        }
        else
        {
            var patchReader = new PatchReader(pe);
            result = new { path = file, assembly = patchReader.AssemblyName, version = patchReader.AssemblyVersion, patches = patchReader.Read() };
        }
    }
    catch (Exception error) when (error is IOException or BadImageFormatException or UnauthorizedAccessException or InvalidOperationException)
    {
        result = new { path = file, error = error.Message };
    }
    writer.WriteLine(JsonSerializer.Serialize(result, options));
}
return 0;

// The assemblies this one's types are built on top of: where each type's parent class and interfaces come from. These must be
// loaded first, since the runtime needs a type's parents the moment it reads the type; a reference used only inside a method
// body is looked up when the method first runs, so it does not tie the load order (1.84.0).
static List<string> Inherited(System.Reflection.Metadata.MetadataReader metadata)
{
    var found = new HashSet<string>();
    void Add(System.Reflection.Metadata.EntityHandle handle, int depth)
    {
        if (handle.IsNil || depth > 8) return;
        if (handle.Kind == System.Reflection.Metadata.HandleKind.TypeReference)
        {
            var scope = metadata.GetTypeReference((System.Reflection.Metadata.TypeReferenceHandle)handle).ResolutionScope;
            while (scope.Kind == System.Reflection.Metadata.HandleKind.TypeReference)
            {
                scope = metadata.GetTypeReference((System.Reflection.Metadata.TypeReferenceHandle)scope).ResolutionScope;
            }
            if (scope.Kind == System.Reflection.Metadata.HandleKind.AssemblyReference)
            {
                found.Add(metadata.GetString(metadata.GetAssemblyReference((System.Reflection.Metadata.AssemblyReferenceHandle)scope).Name));
            }
        }
        else if (handle.Kind == System.Reflection.Metadata.HandleKind.TypeSpecification)
        {
            // A generic parent, Parent<Argument>: the generic type itself, and each argument that is a class or a struct.
            var spec = metadata.GetTypeSpecification((System.Reflection.Metadata.TypeSpecificationHandle)handle);
            var blob = metadata.GetBlobReader(spec.Signature);
            if (blob.ReadSignatureTypeCode() != System.Reflection.Metadata.SignatureTypeCode.GenericTypeInstance) return;
            blob.ReadSignatureTypeCode();
            Add(blob.ReadTypeHandle(), depth + 1);
            int count = blob.ReadCompressedInteger();
            for (int n = 0; n < count && blob.RemainingBytes > 0; n++)
            {
                var code = blob.ReadSignatureTypeCode();
                if (code == System.Reflection.Metadata.SignatureTypeCode.TypeHandle) Add(blob.ReadTypeHandle(), depth + 1);
                else break;   // a nested generic or an array argument: its own parents load with it, and reading on would need a full decoder
            }
        }
    }
    foreach (var typeHandle in metadata.TypeDefinitions)
    {
        var type = metadata.GetTypeDefinition(typeHandle);
        Add(type.BaseType, 0);
        foreach (var implementation in type.GetInterfaceImplementations())
        {
            Add(metadata.GetInterfaceImplementation(implementation).Interface, 0);
        }
    }
    return found.OrderBy(name => name, StringComparer.Ordinal).ToList();
}

static List<string> Files(IEnumerable<string> arguments)
{
    var files = new List<string>();
    foreach (string arg in arguments)
    {
        if (arg.StartsWith('@')) files.AddRange(File.ReadAllLines(arg[1..]).Where(line => line.Trim().Length > 0));
        else files.Add(arg);
    }
    return files;
}
