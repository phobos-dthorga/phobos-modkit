using System.Reflection.PortableExecutable;
using System.Text.Encodings.Web;
using System.Text.Json;
using Phobos.ModKit.Assemblies;

// PhobosModKit.Assemblies patches FILE...             one JSON object per assembly, on its own line, in the order given.
// PhobosModKit.Assemblies members @TYPES FILE...      one JSON object per type named in TYPES (one name per line; a full
//                                                     name or a dotted suffix of one) found in any FILE, and per base type.
// FILE may be @LISTFILE, one path per line. Reads metadata only: an assembly is opened as a file and never loaded or run.
// A file that is not a readable .NET assembly gives an object with an error instead of stopping the run.
if (args.Length < 1 || (args[0] != "patches" && args[0] != "members"))
{
    Console.Error.WriteLine("usage: PhobosModKit.Assemblies patches FILE...   (or patches @LISTFILE, one path per line)");
    Console.Error.WriteLine("       PhobosModKit.Assemblies members @TYPESFILE FILE...");
    return 2;
}
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

foreach (string file in Files(args.Skip(1)))
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
