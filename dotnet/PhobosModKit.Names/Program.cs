// connections names: what every name in one C# file is, and where it is declared. Given a request (the projects, their source
// files and the assemblies they refer to, as MSBuild lists them), it builds each project's compilation from source, a project it
// refers to as a compilation too, so a name declared there is placed in its file; then it reads the one file asked for.
//
// Read-only: source is parsed and referenced assemblies' metadata read. No assembly is loaded or run, and no analyser or source
// generator a project names is run. The answer is JSON on standard output; a failure is words on standard error and exit code 1.

using System.Diagnostics;
using System.Text.Json;
using System.Text.Json.Serialization;
using Microsoft.CodeAnalysis;
using Microsoft.CodeAnalysis.CSharp;
using Microsoft.CodeAnalysis.Text;

namespace Phobos.ModKit.Names;

public sealed record ReferenceIn(string Path, string? Project);

public sealed record ProjectIn(
    string Path,
    string Name,
    List<string> Sources,
    List<ReferenceIn> References,
    string? LangVersion,
    string? Nullable,
    string? Defines,
    bool AllowUnsafe);

/// <summary>
/// What to read: one file's names (`Project`, `File`, its `Text` at a commit), or, with `Versions`, the calls of every method in
/// `Files` in each version (1.116.0).
/// </summary>
public sealed record Request(
    List<ProjectIn> Projects,
    string? Project,
    string? File,
    string? Text,
    string Root,
    int Context,
    List<VersionIn>? Versions = null,
    List<string>? Files = null);

public sealed record Declared(string? File, int? Line, int? End, string? Assembly);

public sealed record Name(
    int Line,
    int Column,
    int Length,
    string Text,
    string Kind,
    string Display,
    string? Id,
    bool Here,
    Declared Declared);

public sealed record Snippet(string File, int Start, int End, List<string> Lines, bool Cut);

public sealed record Answer(
    string File,
    string Project,
    List<Name> Names,
    Dictionary<string, Snippet> Snippets,
    int Errors,
    int MissingReferences,
    double Seconds);

public static class Program
{
    static readonly JsonSerializerOptions Json = new()
    {
        PropertyNamingPolicy = JsonNamingPolicy.CamelCase,
        DefaultIgnoreCondition = JsonIgnoreCondition.WhenWritingNull,
    };

    public static int Main(string[] args)
    {
        if (args.Length != 1)
        {
            Console.Error.WriteLine("usage: PhobosModKit.Names REQUEST.json");
            return 2;
        }
        try
        {
            var request = JsonSerializer.Deserialize<Request>(File.ReadAllText(args[0]), Json)
                ?? throw new InvalidDataException("the request is empty");
            Console.Out.Write(request.Versions != null
                ? JsonSerializer.Serialize(Calls.Read(request), Json)
                : JsonSerializer.Serialize(Read(request), Json));
            return 0;
        }
        catch (Exception problem) when (problem is IOException or InvalidDataException or JsonException or ArgumentException)
        {
            Console.Error.WriteLine(problem.Message);
            return 1;
        }
    }

    public static Answer Read(Request request)
    {
        var clock = Stopwatch.StartNew();
        if (request.File == null || request.Project == null) throw new InvalidDataException("names are read from one file of one project");
        var target = Full(request.File);
        var texts = new Dictionary<string, string?>();
        if (request.Text != null) texts[target] = request.Text;
        var builder = new Builder(request.Projects, texts);
        var asked = builder.Project(request.Project)
            ?? throw new InvalidDataException("the project asked for is not among the projects given");
        var compilation = builder.Build(asked);
        var tree = compilation.SyntaxTrees.FirstOrDefault(t => string.Equals(t.FilePath, target, StringComparison.OrdinalIgnoreCase))
            ?? throw new InvalidDataException($"{Relative(request.Root, target)} is not one of {asked.Name}'s source files");
        var model = compilation.GetSemanticModel(tree);
        var ours = new HashSet<SyntaxTree>(builder.Built.SelectMany(c => c.SyntaxTrees));
        var missing = builder.Missing;

        var names = new List<Name>();
        var snippets = new Dictionary<string, Snippet>();
        foreach (var token in tree.GetRoot().DescendantTokens().Where(t => t.IsKind(SyntaxKind.IdentifierToken)))
        {
            var node = token.Parent;
            if (node == null) continue;
            var info = model.GetSymbolInfo(node);
            var symbol = info.Symbol ?? model.GetDeclaredSymbol(node) ?? info.CandidateSymbols.FirstOrDefault();
            if (symbol == null) continue;
            symbol = Original(symbol);
            var position = token.GetLocation().GetLineSpan().StartLinePosition;
            var source = symbol.Locations.FirstOrDefault(l => l.IsInSource && l.SourceTree != null && ours.Contains(l.SourceTree));
            var here = source != null && source.SourceTree == tree && source.SourceSpan == token.Span;
            Declared declared;
            if (source?.SourceTree != null)
            {
                var file = Relative(request.Root, source.SourceTree.FilePath);
                var (start, end) = Lines(symbol, source);
                declared = new Declared(file, start, end, null);
                if (!Inside(symbol) && !snippets.ContainsKey($"{file}:{start}"))
                    snippets[$"{file}:{start}"] = SnippetOf(source.SourceTree, file, start, end, request.Context);
            }
            else
            {
                declared = new Declared(null, null, null, symbol.ContainingAssembly?.Name);
            }
            names.Add(new Name(
                position.Line + 1,
                position.Character,
                token.Span.Length,
                token.Text,
                KindOf(symbol),
                symbol.ToDisplayString(SymbolDisplayFormat.CSharpShortErrorMessageFormat),
                symbol.GetDocumentationCommentId(),
                here,
                declared));
        }
        var errors = model.GetDiagnostics().Count(d => d.Severity == DiagnosticSeverity.Error);
        return new Answer(Relative(request.Root, target), asked.Name, names, snippets, errors, missing, clock.Elapsed.TotalSeconds);
    }

    /// <summary>The symbol a name stands for, as declared: an extension method called as one, a generic's own declaration.</summary>
    static ISymbol Original(ISymbol symbol) => symbol switch
    {
        IMethodSymbol { ReducedFrom: { } reduced } => reduced.OriginalDefinition,
        _ => symbol.OriginalDefinition,
    };

    /// <summary>Whether a symbol lives only inside a member (a parameter, a local, a type parameter): it needs no snippet.</summary>
    static bool Inside(ISymbol symbol) =>
        symbol.Kind is SymbolKind.Parameter or SymbolKind.Local or SymbolKind.TypeParameter or SymbolKind.RangeVariable or SymbolKind.Label;

    /// <summary>The lines a declaration covers, its comments above it included.</summary>
    static (int Start, int End) Lines(ISymbol symbol, Location source)
    {
        var syntax = symbol.DeclaringSyntaxReferences.FirstOrDefault(r => r.SyntaxTree == source.SourceTree)?.GetSyntax();
        if (syntax == null)
        {
            var line = source.GetLineSpan().StartLinePosition.Line + 1;
            return (line, line);
        }
        var leading = syntax.GetLeadingTrivia().FirstOrDefault(t => !t.IsKind(SyntaxKind.WhitespaceTrivia) && !t.IsKind(SyntaxKind.EndOfLineTrivia));
        var from = leading.RawKind != 0 ? leading.SpanStart : syntax.SpanStart;
        var lines = source.SourceTree!.GetText().Lines;
        return (lines.GetLineFromPosition(from).LineNumber + 1, lines.GetLineFromPosition(syntax.Span.End).LineNumber + 1);
    }

    static Snippet SnippetOf(SyntaxTree tree, string file, int start, int end, int context)
    {
        var lines = tree.GetText().Lines;
        var last = Math.Min(end, start + Math.Max(1, context) - 1);
        var text = Enumerable.Range(start - 1, last - start + 1).Select(i => lines[i].ToString()).ToList();
        return new Snippet(file, start, end, text, last < end);
    }

    static string KindOf(ISymbol symbol) => symbol switch
    {
        INamedTypeSymbol type => type.TypeKind switch
        {
            TypeKind.Interface => "interface",
            TypeKind.Struct => type.IsRecord ? "record struct" : "struct",
            TypeKind.Enum => "enum",
            TypeKind.Delegate => "delegate",
            _ => type.IsRecord ? "record" : "class",
        },
        IMethodSymbol method => method.MethodKind is MethodKind.Constructor or MethodKind.StaticConstructor ? "constructor" : "method",
        IPropertySymbol => "property",
        IFieldSymbol field => field.ContainingType?.TypeKind == TypeKind.Enum ? "enum member" : field.IsConst ? "constant" : "field",
        IEventSymbol => "event",
        IParameterSymbol => "parameter",
        ILocalSymbol local => local.IsConst ? "constant" : "local",
        ITypeParameterSymbol => "type parameter",
        INamespaceSymbol => "namespace",
        _ => symbol.Kind.ToString().ToLowerInvariant(),
    };

    static string Full(string path) => System.IO.Path.GetFullPath(path);

    static string Relative(string root, string path) => System.IO.Path.GetRelativePath(root, path).Replace('\\', '/');
}
