using System.Diagnostics;
using Microsoft.CodeAnalysis;
using Microsoft.CodeAnalysis.CSharp;
using Microsoft.CodeAnalysis.CSharp.Syntax;

namespace Phobos.ModKit.Names;

/// <summary>A text of some files: their full paths, and the file to read each from, or null where the file did not exist.</summary>
public sealed record VersionIn(string Name, Dictionary<string, string?> Texts);

/// <summary>
/// A method one of ours calls, or one ours overrides: its documentation id and signature, its type and name as compiled
/// (`Verse.RecipeWorker`, `AvailableReport`, `get_Label`, `.ctor`), the assembly it is in, or its place in this repository; and
/// how it is called: through `base`, as a virtual method, on the same object.
/// </summary>
public sealed record CallOut(
    string? Id,
    string Display,
    string Type,
    string Name,
    string? Assembly,
    string? File,
    int? Line,
    bool ViaBase,
    bool Virtual,
    bool OnThis);

/// <summary>
/// A method, constructor or accessor declared in one of the files, with what it overrides and every method it calls. `Base` marks
/// one of ours read only because a method in the files calls it through `base` or overrides it: for its calls, not as a change.
/// </summary>
public sealed record MethodOut(
    string? Id,
    string Display,
    string File,
    int Line,
    int End,
    string Type,
    string Name,
    CallOut? Overrides,
    List<CallOut> Calls,
    bool Base = false);

public sealed record VersionOut(string Name, List<MethodOut> Methods, int Errors);

public sealed record CallsAnswer(List<VersionOut> Versions, int MissingReferences, double Seconds);

/// <summary>
/// The calls of every method in some files, in each of several texts of them (as they stood before a commit and after it):
/// read from source with Roslyn, each version a build of its own with those files swapped in. Calls inside a method's lambdas
/// and local functions count as the method's own, as the kit's assembly reader counts them.
/// </summary>
public static class Calls
{
    public static CallsAnswer Read(Request request)
    {
        var clock = Stopwatch.StartNew();
        var versions = new List<VersionOut>();
        var missing = 0;
        foreach (var version in request.Versions ?? [])
        {
            var builder = new Builder(request.Projects, version.Texts);
            var ours = new HashSet<SyntaxTree>();
            foreach (var project in builder.Projects) ours.UnionWith(builder.Build(project).SyntaxTrees);
            var methods = new List<MethodOut>();
            var errors = 0;
            foreach (var file in request.Files ?? [])
            {
                var found = builder.Find(file);
                if (found == null) continue;
                var (compilation, tree) = found.Value;
                var model = compilation.GetSemanticModel(tree);
                errors += model.GetDiagnostics().Count(d => d.Severity == DiagnosticSeverity.Error);
                foreach (var declaration in tree.GetRoot().DescendantNodes().Where(IsMember))
                {
                    if (model.GetDeclaredSymbol(declaration) is IMethodSymbol method)
                        methods.Add(Method(request.Root, model, declaration, method, ours));
                    else if (declaration is BasePropertyDeclarationSyntax { } property
                        && model.GetDeclaredSymbol(property) is IPropertySymbol { GetMethod: { } getter })
                        methods.Add(Method(request.Root, model, declaration, getter, ours));
                }
            }
            methods.AddRange(BaseMethods(request.Root, builder, methods, ours));
            missing = Math.Max(missing, builder.Missing);
            versions.Add(new VersionOut(version.Name, methods, errors));
        }
        return new CallsAnswer(versions, missing, clock.Elapsed.TotalSeconds);
    }

    /// <summary>
    /// Our methods outside the files that the files' methods reach through `base` or override, read one level deep, so a ring
    /// through one of our own base classes can close: each marked `Base`.
    /// </summary>
    static IEnumerable<MethodOut> BaseMethods(string root, Builder builder, List<MethodOut> methods, HashSet<SyntaxTree> ours)
    {
        var have = new HashSet<string>(methods.Select(m => m.Id ?? $"{m.Type}.{m.Name}"));
        var wanted = methods
            .SelectMany(m => m.Calls.Where(c => c.ViaBase).Append(m.Overrides))
            .Where(c => c?.File != null && c.Id != null && !have.Contains(c.Id))
            .Select(c => (c!.File!, c.Id!))
            .Distinct()
            .ToList();
        foreach (var (file, id) in wanted)
        {
            var found = builder.Find(Path.Combine(root, file));
            if (found == null) continue;
            var model = found.Value.Compilation.GetSemanticModel(found.Value.Tree);
            foreach (var declaration in found.Value.Tree.GetRoot().DescendantNodes().Where(IsMember))
            {
                var symbol = model.GetDeclaredSymbol(declaration) as IMethodSymbol
                    ?? (model.GetDeclaredSymbol(declaration) as IPropertySymbol)?.GetMethod;
                if (symbol?.OriginalDefinition.GetDocumentationCommentId() == id && have.Add(id))
                    yield return Method(root, model, declaration, symbol, ours) with { Base = true };
            }
        }
    }

    /// <summary>A member with a body of its own: a method, constructor, operator or accessor, or a property written as an expression.</summary>
    static bool IsMember(SyntaxNode node) => node switch
    {
        BaseMethodDeclarationSyntax => true,
        AccessorDeclarationSyntax accessor => accessor.Body != null || accessor.ExpressionBody != null,
        PropertyDeclarationSyntax property => property.ExpressionBody != null,
        IndexerDeclarationSyntax indexer => indexer.ExpressionBody != null,
        _ => false,
    };

    static MethodOut Method(string root, SemanticModel model, SyntaxNode declaration, IMethodSymbol method, HashSet<SyntaxTree> ours)
    {
        var span = declaration.GetLocation().GetLineSpan();
        var calls = new List<CallOut>();
        foreach (var node in declaration.DescendantNodes())
        {
            if (node is not (InvocationExpressionSyntax or BaseObjectCreationExpressionSyntax)) continue;
            if (model.GetSymbolInfo(node).Symbol is not IMethodSymbol called) continue;
            var (viaBase, onThis) = Receiver(node, called);
            var call = Out(root, called, ours, viaBase, onThis);
            if (!calls.Contains(call)) calls.Add(call);
        }
        var overridden = method.OverriddenMethod ?? (method.AssociatedSymbol as IPropertySymbol)?.OverriddenProperty?.GetMethod;
        return new MethodOut(
            method.OriginalDefinition.GetDocumentationCommentId(),
            method.ToDisplayString(SymbolDisplayFormat.CSharpShortErrorMessageFormat),
            Path.GetRelativePath(root, declaration.SyntaxTree.FilePath).Replace('\\', '/'),
            span.StartLinePosition.Line + 1,
            span.EndLinePosition.Line + 1,
            TypeName(method.ContainingType),
            method.MetadataName,
            overridden == null ? null : Out(root, overridden, ours, false, false),
            calls);
    }

    /// <summary>Whether a call goes through `base`, and whether it is made on the same object (no receiver, `this` or `base`).</summary>
    static (bool ViaBase, bool OnThis) Receiver(SyntaxNode node, IMethodSymbol called)
    {
        if (node is not InvocationExpressionSyntax invocation || called.IsStatic) return (false, false);
        return invocation.Expression switch
        {
            MemberAccessExpressionSyntax { Expression: BaseExpressionSyntax } => (true, true),
            MemberAccessExpressionSyntax { Expression: ThisExpressionSyntax } => (false, true),
            IdentifierNameSyntax or GenericNameSyntax => (false, true),
            _ => (false, false),
        };
    }

    static CallOut Out(string root, IMethodSymbol called, HashSet<SyntaxTree> ours, bool viaBase, bool onThis)
    {
        var original = (called.ReducedFrom ?? called).OriginalDefinition;
        var source = original.Locations.FirstOrDefault(l => l.IsInSource && l.SourceTree != null && ours.Contains(l.SourceTree));
        return new CallOut(
            original.GetDocumentationCommentId(),
            original.ToDisplayString(SymbolDisplayFormat.CSharpShortErrorMessageFormat),
            TypeName(original.ContainingType),
            original.MetadataName,
            source == null ? original.ContainingAssembly?.Name : null,
            source == null ? null : Path.GetRelativePath(root, source.SourceTree!.FilePath).Replace('\\', '/'),
            source?.GetLineSpan().StartLinePosition.Line + 1,
            viaBase,
            (original.IsVirtual || original.IsAbstract || original.IsOverride) && !original.IsSealed,
            onThis);
    }

    /// <summary>A type's name as the kit's assembly reader writes it: its namespace, its outer types and its own name, dotted.</summary>
    public static string TypeName(INamedTypeSymbol? type)
    {
        if (type == null) return "";
        if (type.ContainingType != null) return TypeName(type.ContainingType) + "." + type.MetadataName;
        var space = type.ContainingNamespace;
        return space == null || space.IsGlobalNamespace ? type.MetadataName : space.ToDisplayString() + "." + type.MetadataName;
    }
}
