using System.Reflection.PortableExecutable;
using System.Text.Encodings.Web;
using System.Text.Json;
using Phobos.ModKit.Assemblies;

// PhobosModKit.Assemblies patches FILE...   one JSON object per assembly, on its own line, in the order given.
// Reads metadata only: an assembly is opened as a file and never loaded or run. A file that is not a readable .NET
// assembly gives an object with an error instead of stopping the run.
if (args.Length < 1 || args[0] != "patches")
{
    Console.Error.WriteLine("usage: PhobosModKit.Assemblies patches FILE...   (or patches @LISTFILE, one path per line)");
    return 2;
}
var files = new List<string>();
foreach (string arg in args.Skip(1))
{
    if (arg.StartsWith('@')) files.AddRange(File.ReadAllLines(arg[1..]).Where(line => line.Trim().Length > 0));
    else files.Add(arg);
}
var options = new JsonSerializerOptions { PropertyNamingPolicy = JsonNamingPolicy.CamelCase, Encoder = JavaScriptEncoder.UnsafeRelaxedJsonEscaping };
using Stream stdout = Console.OpenStandardOutput();
using var writer = new StreamWriter(stdout, new System.Text.UTF8Encoding(false));
foreach (string file in files)
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
