using Microsoft.CodeAnalysis;
using Microsoft.CodeAnalysis.CSharp;
using Microsoft.CodeAnalysis.Text;

namespace Phobos.ModKit.Names;

/// <summary>
/// Builds the request's projects from source, each the first time it is asked for, a project another refers to as a compilation
/// too, so a name declared there is placed in its file. Any source file may be read from another text (a file as it stood at a
/// commit) or left out (one that did not exist then); every other file is read as it stands. Nothing is loaded or run.
/// </summary>
public sealed class Builder
{
    readonly Dictionary<string, ProjectIn> projects;
    readonly Dictionary<string, string?> texts;
    readonly Dictionary<string, CSharpCompilation> built = new(StringComparer.OrdinalIgnoreCase);
    readonly HashSet<string> building = new(StringComparer.OrdinalIgnoreCase);

    /// <param name="texts">A source file's full path, and the file to read its text from instead, or null to leave it out.</param>
    public Builder(IEnumerable<ProjectIn> projects, Dictionary<string, string?> texts)
    {
        this.projects = projects.ToDictionary(p => Full(p.Path), StringComparer.OrdinalIgnoreCase);
        this.texts = new Dictionary<string, string?>(texts.Select(kv => KeyValuePair.Create(Full(kv.Key), kv.Value)),
            StringComparer.OrdinalIgnoreCase);
    }

    /// <summary>How many of the assemblies the projects refer to were not found.</summary>
    public int Missing { get; private set; }

    public IEnumerable<CSharpCompilation> Built => built.Values;

    public ProjectIn? Project(string path) => projects.TryGetValue(Full(path), out var found) ? found : null;

    public IEnumerable<ProjectIn> Projects => projects.Values;

    public CSharpCompilation Build(ProjectIn project)
    {
        var key = Full(project.Path);
        if (built.TryGetValue(key, out var done)) return done;
        if (!building.Add(key)) throw new InvalidDataException($"{project.Name} refers to itself through another project");
        var parse = new CSharpParseOptions(
            LanguageVersionFacts.TryParse(project.LangVersion ?? "latest", out var version) ? version : LanguageVersion.Latest,
            preprocessorSymbols: (project.Defines ?? "").Split(';', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries));
        var trees = new List<SyntaxTree>();
        var sources = project.Sources.Select(Full).ToList();
        // A file asked for in another text that the project does not list now (one since removed) is read too, when it belongs here.
        sources.AddRange(texts.Where(kv => kv.Value != null && Belongs(project, kv.Key)).Select(kv => kv.Key));
        foreach (var source in sources.Distinct(StringComparer.OrdinalIgnoreCase))
        {
            string? text;
            if (texts.TryGetValue(source, out var other)) text = other == null ? null : File.ReadAllText(other);
            else text = File.Exists(source) ? File.ReadAllText(source) : null;
            if (text != null) trees.Add(CSharpSyntaxTree.ParseText(SourceText.From(text), parse, source));
        }
        var references = new List<MetadataReference>();
        foreach (var reference in project.References)
        {
            if (reference.Project != null && projects.TryGetValue(Full(reference.Project), out var referred))
                references.Add(Build(referred).ToMetadataReference());
            else if (File.Exists(reference.Path))
                references.Add(MetadataReference.CreateFromFile(reference.Path));
            else
                Missing++;
        }
        var options = new CSharpCompilationOptions(
            OutputKind.DynamicallyLinkedLibrary,
            nullableContextOptions: project.Nullable?.Equals("enable", StringComparison.OrdinalIgnoreCase) == true
                ? NullableContextOptions.Enable
                : NullableContextOptions.Disable,
            allowUnsafe: project.AllowUnsafe);
        var compilation = CSharpCompilation.Create(project.Name, trees, references, options);
        built[key] = compilation;
        return compilation;
    }

    /// <summary>Every project built, and the tree of one file in whichever holds it.</summary>
    public (CSharpCompilation Compilation, SyntaxTree Tree)? Find(string file)
    {
        var target = Full(file);
        foreach (var project in projects.Values)
        {
            var compilation = Build(project);
            var tree = compilation.SyntaxTrees.FirstOrDefault(t => string.Equals(t.FilePath, target, StringComparison.OrdinalIgnoreCase));
            if (tree != null) return (compilation, tree);
        }
        return null;
    }

    /// <summary>Whether a file sits under a project's folder, and no deeper project's: the project that would list it.</summary>
    bool Belongs(ProjectIn project, string file)
    {
        var folder = Path.GetDirectoryName(Full(project.Path))! + Path.DirectorySeparatorChar;
        if (!file.StartsWith(folder, StringComparison.OrdinalIgnoreCase)) return false;
        return !projects.Values.Any(other =>
        {
            var deeper = Path.GetDirectoryName(Full(other.Path))! + Path.DirectorySeparatorChar;
            return deeper.Length > folder.Length && file.StartsWith(deeper, StringComparison.OrdinalIgnoreCase);
        });
    }

    public static string Full(string path) => Path.GetFullPath(path);
}
