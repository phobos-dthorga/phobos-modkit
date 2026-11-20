using System.Diagnostics;
using System.Globalization;
using System.Text.Json.Nodes;
using Microsoft.Diagnostics.Runtime;

namespace Phobos.ModKit.Heap;

/// <summary>
/// One snapshot of a running .NET program, held while requests about it are answered. Read-only: every answer comes from the
/// snapshot, never from the program, which runs on. Addresses are only good within the snapshot they came from: the garbage
/// collector moves objects, so a new snapshot gives new ones.
/// </summary>
public sealed class HeapSession : IDisposable
{
    public const int DefaultTake = 50, MaxTake = 500, DefaultHolders = 50, DefaultSample = 3, MaxSample = 20;
    public const int TextLimit = 4000, SummaryLimit = 120, StructDepth = 2, WhyTargets = 2000, ArrayScanLimit = 1_000_000;
    public static readonly TimeSpan PathTime = TimeSpan.FromMinutes(5);
    private const int KindsKept = 4;
    private const long ProgressEvery = 1 << 20;

    private readonly DataTarget target;
    private readonly ClrRuntime runtime;
    private readonly ClrHeap heap;
    private readonly List<string[]> describe;
    private readonly Progress progress;
    private readonly Stopwatch age = Stopwatch.StartNew();
    private readonly LinkedList<(string type, List<(ulong address, ulong size)> objects)> kinds = new();
    private Dictionary<ulong, string>? statics;
    private long? objectCount;

    public int Pid { get; }
    public long SnapshotMilliseconds { get; }
    public string RuntimeFolder { get; }
    public string Dac { get; }

    private HeapSession(int pid, DataTarget target, ClrRuntime runtime, long snapshotMs, string folder, string dac,
                        IEnumerable<string> describe, Progress progress)
    {
        Pid = pid;
        this.target = target;
        this.runtime = runtime;
        heap = runtime.Heap;
        SnapshotMilliseconds = snapshotMs;
        RuntimeFolder = folder;
        Dac = dac;
        this.describe = describe.Where(p => p.Length > 0).Select(p => p.Split('.')).ToList();
        this.progress = progress;
    }

    /// <summary>
    /// Takes the snapshot and opens it with the memory-reading library beside the program's own coreclr.dll, which must be in
    /// <paramref name="runtimeFolder"/>. That library may not be signed by Microsoft (a game that ships its own build of .NET, as
    /// RimWorld 1.7 does), so the signature check is off; the folder check is what makes it the trusted install's own file.
    /// </summary>
    public static HeapSession Open(int pid, string runtimeFolder, IEnumerable<string> describe, Progress progress)
    {
        if (!OperatingSystem.IsWindows())
            throw new SessionError("A snapshot of a running program can be read on Windows only.");
        string folder = Normal(runtimeFolder);
        progress.Say("Taking a snapshot of the game");
        var clock = Stopwatch.StartNew();
        DataTarget target = DataTarget.CreateSnapshotAndAttach(pid, new DataTargetOptions { VerifyDacOnWindows = false });
        long snapshotMs = clock.ElapsedMilliseconds;
        try
        {
            ClrInfo info = target.ClrVersions.FirstOrDefault()
                           ?? throw new SessionError("No .NET runtime was found in that program; nothing was read.");
            string own = Normal(Path.GetDirectoryName(info.ModuleInfo.FileName) ?? "");
            if (!string.Equals(own, folder, StringComparison.OrdinalIgnoreCase))
                throw new SessionError($"That program's .NET runtime is in {own}, not in the install named ({folder}); nothing was read.");
            string dac = Path.Combine(folder, "mscordaccore.dll");
            if (!File.Exists(dac))
                throw new SessionError($"The install has no memory-reading library (mscordaccore.dll in {folder}); nothing was read.");
            progress.Say("Opening the snapshot");
            ClrRuntime runtime = info.CreateRuntime(dac, ignoreMismatch: true);
            if (!runtime.Heap.CanWalkHeap)
            {
                runtime.Dispose();
                throw new SessionError("The game was in the middle of a garbage collection when the snapshot was taken, so its memory "
                                       + "cannot be read; take another.");
            }
            return new HeapSession(pid, target, runtime, snapshotMs, folder, dac, describe, progress);
        }
        catch
        {
            target.Dispose();
            throw;
        }
    }

    private static string Normal(string path) => Path.GetFullPath(path).TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar);

    public void Dispose()
    {
        runtime.Dispose();
        target.Dispose();
    }

    public JsonObject Info() => new()
    {
        ["pid"] = Pid,
        ["snapshotMs"] = SnapshotMilliseconds,
        ["ageSeconds"] = Math.Round(age.Elapsed.TotalSeconds, 1),
        ["runtime"] = runtime.ClrInfo.Version.ToString(),
        ["runtimeFolder"] = RuntimeFolder,
        ["dac"] = Dac,
        ["modules"] = runtime.EnumerateModules().Count(),
        ["threads"] = runtime.Threads.Length,
        ["segments"] = heap.Segments.Length,
        ["objects"] = objectCount,
    };

    public JsonObject Handle(JsonObject request)
    {
        string op = request["op"]?.GetValue<string>() ?? throw new SessionError("A request needs an op.");
        return op switch
        {
            "info" => Info(),
            "overview" => Overview(),
            "kind" => Kind(Text(request, "type"), Int(request, "skip", 0), Take(request), Text(request, "sort", ""), Text(request, "match", ""),
                           request["open"] is JsonValue open && open.TryGetValue(out bool yes) && yes),
            "object" => Object(Address(request), Int(request, "skip", 0), Take(request)),
            "holders" => Holders(Address(request), Math.Clamp(Int(request, "max", DefaultHolders), 1, MaxTake)),
            "path" => Path_(Address(request)),
            "why" => Why(Text(request, "type"), Math.Clamp(Int(request, "sample", DefaultSample), 1, MaxSample)),
            "release" => new JsonObject { ["released"] = true },
            _ => throw new SessionError($"Unknown op: {op}"),
        };
    }

    // ---- Requests ----

    /// <summary>Every type on the heap with its count and bytes, and the free space between objects, which is not counted.</summary>
    private JsonObject Overview()
    {
        var clock = Stopwatch.StartNew();
        var byType = new Dictionary<ClrType, (long count, long bytes)>();
        long objects = 0, bytes = 0, freeBytes = 0, untyped = 0, seen = 0;
        foreach (ClrObject o in heap.EnumerateObjects())
        {
            if (++seen % ProgressEvery == 0) progress.Say("Reading every object", seen, objectCount);
            if (o.Type == null) { untyped++; continue; }
            if (o.IsFree) { freeBytes += (long)o.Size; continue; }
            objects++;
            bytes += (long)o.Size;
            byType.TryGetValue(o.Type, out var c);
            byType[o.Type] = (c.count + 1, c.bytes + (long)o.Size);
        }
        objectCount = seen;
        var types = new JsonArray();
        foreach (var (type, c) in byType.OrderByDescending(kv => kv.Value.bytes).ThenBy(kv => kv.Key.Name, StringComparer.Ordinal))
            types.Add(new JsonObject { ["type"] = type.Name ?? "?", ["module"] = ModuleName(type), ["count"] = c.count, ["bytes"] = c.bytes });
        return new JsonObject
        {
            ["totalObjects"] = objects, ["totalBytes"] = bytes, ["freeBytes"] = freeBytes, ["untyped"] = untyped,
            ["seconds"] = Math.Round(clock.Elapsed.TotalSeconds, 1), ["types"] = types,
        };
    }

    private JsonObject Kind(string type, int skip, int take, string sort, string match, bool open)
    {
        List<(ulong address, ulong size)> all = Instances(type);
        IEnumerable<(ulong address, ulong size)> list = sort == "size" ? all.OrderByDescending(o => o.size).ThenBy(o => o.address) : all;
        long total = all.Sum(o => (long)o.size);
        var items = new JsonArray();
        int matched = 0;
        foreach (var (address, size) in list)
        {
            ClrObject o = heap.GetObject(address);
            string summary = Summary(o);
            if (match.Length > 0 && !summary.Contains(match, StringComparison.OrdinalIgnoreCase)) continue;
            if (matched++ < skip) continue;
            if (items.Count >= take) { matched = -1; break; }
            items.Add(new JsonObject { ["address"] = Hex(address), ["size"] = (long)size, ["summary"] = summary });
        }
        var data = new JsonObject
        {
            ["type"] = type, ["count"] = all.Count, ["totalBytes"] = total, ["skip"] = skip, ["take"] = take,
            ["more"] = matched == -1, ["match"] = match, ["items"] = items,
        };
        // Opened in the same snapshot: an address from one snapshot means nothing in the next.
        if (open && items.Count > 0) data["opened"] = Object(Address(items[0]!.AsObject()), 0, DefaultTake);
        return data;
    }

    private JsonObject Object(ulong address, int skip, int take)
    {
        ClrObject o = Valid(address);
        var data = new JsonObject
        {
            ["address"] = Hex(address), ["type"] = o.Type!.Name, ["module"] = ModuleName(o.Type), ["size"] = (long)o.Size,
            ["summary"] = Summary(o), ["static"] = Statics().GetValueOrDefault(address),
        };
        if (o.Type.IsString)
        {
            data["kind"] = "text";
            data["text"] = o.AsString(TextLimit);
            return data;
        }
        if (o.IsArray)
        {
            ClrArray array = o.AsArray();
            data["kind"] = "array";
            data["length"] = array.Length;
            data["elements"] = Elements(array, 0, array.Length, skip, take);
            data["skip"] = skip;
            return data;
        }
        data["kind"] = "object";
        var fields = new JsonArray();
        foreach (ClrInstanceField field in o.Type.Fields) fields.Add(Field(field, address, false, 0));
        data["fields"] = fields;
        JsonObject? items = Collection(o, skip, take);
        if (items != null) data["items"] = items;
        return data;
    }

    private JsonObject Holders(ulong address, int max)
    {
        Valid(address);
        var holders = new JsonArray();
        bool cut = false;
        long seen = 0;
        foreach (ClrObject o in heap.EnumerateObjects())
        {
            if (++seen % ProgressEvery == 0) progress.Say("Looking for what holds it", seen, objectCount);
            if (o.Type == null || !o.ContainsPointers) continue;
            foreach (ulong reference in o.EnumerateReferenceAddresses(false, false))
            {
                if (reference != address) continue;
                if (holders.Count >= max) { cut = true; break; }
                holders.Add(Node(o, FieldTo(o, address)));
                break;
            }
            if (cut) break;
        }
        var roots = new JsonArray();
        foreach (ClrRoot root in heap.EnumerateRoots())
            if (root.Object.Address == address) roots.Add(root.RootKind.ToString());
        return new JsonObject
        {
            ["address"] = Hex(address), ["holders"] = holders, ["more"] = cut, ["roots"] = roots,
            ["static"] = Statics().GetValueOrDefault(address),
        };
    }

    private JsonObject Path_(ulong address)
    {
        ClrObject o = Valid(address);
        var paths = RootPaths([address], 1, out bool finished);
        return new JsonObject
        {
            ["address"] = Hex(address), ["type"] = o.Type!.Name, ["path"] = paths.Count > 0 ? paths[0] : null,
            ["unreachable"] = paths.Count == 0 && finished, ["timedOut"] = paths.Count == 0 && !finished,
        };
    }

    /// <summary>Why a kind's objects are still in memory: paths from a root to a few of them, its largest first.</summary>
    private JsonObject Why(string type, int sample)
    {
        List<(ulong address, ulong size)> all = Instances(type);
        var targets = all.OrderByDescending(o => o.size).Take(WhyTargets).Select(o => o.address).ToList();
        var paths = targets.Count == 0 ? [] : RootPaths(targets, sample, out bool finished);
        bool done = targets.Count == 0 || paths.Count >= sample || LastFinished;
        return new JsonObject
        {
            ["type"] = type, ["count"] = all.Count, ["totalBytes"] = all.Sum(o => (long)o.size), ["checked"] = targets.Count,
            ["paths"] = new JsonArray(paths.Select(p => (JsonNode)p).ToArray()),
            ["noneReachable"] = targets.Count > 0 && paths.Count == 0 && LastFinished,
            ["timedOut"] = !done,
        };
    }

    // ---- Walking ----

    private bool LastFinished;

    /// <summary>Paths from roots to up to <paramref name="wanted"/> of the targets, each to a different one.</summary>
    private List<JsonObject> RootPaths(IReadOnlyCollection<ulong> targets, int wanted, out bool finished)
    {
        progress.Say("Following the links from the roots");
        var found = new List<JsonObject>();
        var reached = new HashSet<ulong>();
        using var cancel = new CancellationTokenSource(PathTime);
        finished = false;
        try
        {
            var gcroot = new GCRoot(heap, targets);
            foreach (var (root, chain) in gcroot.EnumerateRootPaths(cancel.Token))
            {
                var addresses = new List<ulong>();
                for (GCRoot.ChainLink? link = chain; link != null; link = link.Next) addresses.Add(link.Object);
                if (addresses.Count == 0 || !reached.Add(addresses[^1])) continue;
                found.Add(Chain(root, addresses));
                if (found.Count >= wanted) break;
            }
            finished = !cancel.IsCancellationRequested;
        }
        catch (OperationCanceledException)
        {
            finished = false;
        }
        LastFinished = finished;
        return found;
    }

    /// <summary>A path as links from the root to the target; a static field on the way starts it, as the most telling name.</summary>
    private JsonObject Chain(ClrRoot root, List<ulong> addresses)
    {
        Dictionary<ulong, string> named = Statics();
        int start = 0;
        string? staticName = null;
        for (int i = addresses.Count - 1; i >= 0; i--)
            if (named.TryGetValue(addresses[i], out string? name)) { start = i; staticName = name; break; }
        var links = new JsonArray();
        for (int i = start; i < addresses.Count; i++)
        {
            ClrObject o = heap.GetObject(addresses[i]);
            string? field = i > start ? FieldTo(heap.GetObject(addresses[i - 1]), addresses[i]) : null;
            links.Add(Node(o, field));
        }
        return new JsonObject
        {
            ["root"] = staticName != null ? "StaticVar" : root.RootKind.ToString(), ["static"] = staticName,
            ["pinned"] = root.IsPinned, ["links"] = links, ["skipped"] = start,
        };
    }

    private List<(ulong address, ulong size)> Instances(string type)
    {
        for (var node = kinds.First; node != null; node = node.Next)
            if (node.Value.type == type)
            {
                kinds.Remove(node);
                kinds.AddFirst(node);
                return node.Value.objects;
            }
        var found = new List<(ulong, ulong)>();
        ClrType? matched = null;
        long seen = 0;
        foreach (ClrObject o in heap.EnumerateObjects())
        {
            if (++seen % ProgressEvery == 0) progress.Say($"Finding every {type}", seen, objectCount);
            ClrType? t = o.Type;
            if (t == null) continue;
            if (!ReferenceEquals(t, matched))
            {
                if (t.Name != type) continue;
                matched = t;
            }
            found.Add((o.Address, o.Size));
        }
        objectCount ??= seen;
        kinds.AddFirst((type, found));
        while (kinds.Count > KindsKept) kinds.RemoveLast();
        return found;
    }

    /// <summary>Every object a static field holds, named Type.field: the names a path from a root is easiest to read by.</summary>
    private Dictionary<ulong, string> Statics()
    {
        if (statics != null) return statics;
        progress.Say("Reading every static field");
        statics = [];
        ClrAppDomain? domain = runtime.AppDomains.FirstOrDefault() ?? runtime.SystemDomain;
        if (domain == null) return statics;
        foreach (ClrModule module in runtime.EnumerateModules())
        {
            IEnumerable<ClrType> types;
            try { types = module.EnumerateTypesWithStaticFields().ToList(); }
            catch (ClrDiagnosticsException) { continue; }
            foreach (ClrType type in types)
                foreach (ClrStaticField field in type.StaticFields)
                {
                    if (!field.IsObjectReference) continue;
                    try
                    {
                        if (!field.IsInitialized(domain)) continue;
                        ClrObject value = field.ReadObject(domain);
                        if (value.IsValid && !value.IsNull) statics.TryAdd(value.Address, $"{type.Name}.{field.Name}");
                    }
                    catch (ClrDiagnosticsException) { }
                }
        }
        return statics;
    }

    // ---- Values ----

    private ClrObject Valid(ulong address)
    {
        ClrObject o = heap.GetObject(address);
        if (!o.IsValid || o.Type == null || o.IsFree)
            throw new SessionError($"There is no object at {Hex(address)} in this snapshot (addresses change with every snapshot).");
        return o;
    }

    private JsonObject Node(ClrObject o, string? field)
    {
        var node = new JsonObject
        {
            ["address"] = Hex(o.Address), ["type"] = o.Type?.Name ?? "?", ["module"] = ModuleName(o.Type), ["size"] = (long)o.Size,
            ["summary"] = Summary(o),
        };
        if (field != null) node["field"] = field;
        return node;
    }

    /// <summary>The name of the field in <paramref name="holder"/> that points to <paramref name="target"/>; "[i]" for an array.</summary>
    private string? FieldTo(ClrObject holder, ulong target)
    {
        if (holder.Type == null) return null;
        if (holder.IsArray)
        {
            ClrArray array = holder.AsArray();
            ClrType? component = array.Type.ComponentType;
            if (component != null && component.IsObjectReference)
                for (int i = 0; i < Math.Min(array.Length, ArrayScanLimit); i++)
                    if (array.GetObjectValue(i).Address == target) return $"[{i}]";
            return "an item";
        }
        foreach (ClrReference reference in holder.EnumerateReferencesWithFields(false, false))
        {
            if (reference.Object.Address != target) continue;
            if (reference.IsDependentHandle) return "(a dependent handle)";
            string? name = reference.Field?.Name;
            if (reference.InnerField is ClrReference inner && inner.Field?.Name is string innerName)
                name = name == null ? innerName : $"{name}.{innerName}";
            return name;
        }
        return null;
    }

    /// <summary>A short line saying which one this is: a string's text, else the first values the describe paths find.</summary>
    private string Summary(ClrObject o)
    {
        if (!o.IsValid || o.Type == null) return "";
        if (o.Type.IsString) return Cut(o.AsString(SummaryLimit + 1) ?? "");
        if (o.IsArray) return $"{o.AsArray().Length:N0} items";
        var parts = new List<string>();
        foreach (string[] path in describe)
        {
            string? value = Follow(o, path);
            if (!string.IsNullOrEmpty(value) && !parts.Contains(value)) parts.Add(value);
            if (parts.Count == 2) break;
        }
        return Cut(string.Join(" · ", parts));
    }

    private static string Cut(string text) => text.Length > SummaryLimit ? text[..SummaryLimit] + "…" : text;

    private static string? Follow(ClrObject o, string[] path)
    {
        ClrObject current = o;
        for (int i = 0; i < path.Length; i++)
        {
            ClrInstanceField? field = current.Type?.GetFieldByName(path[i]);
            if (field == null) return null;
            if (i < path.Length - 1)
            {
                if (!field.IsObjectReference) return null;
                current = field.ReadObject(current.Address, false);
                if (current.IsNull || !current.IsValid) return null;
                continue;
            }
            if (field.ElementType == ClrElementType.String) return field.ReadString(current.Address, false);
            if (field.IsObjectReference)
            {
                ClrObject value = field.ReadObject(current.Address, false);
                return value.IsValid && value.Type?.IsString == true ? value.AsString(SummaryLimit + 1) : null;
            }
            return field.IsPrimitive ? Primitive(field.ElementType, field, current.Address, false) : null;
        }
        return null;
    }

    private JsonObject Field(ClrInstanceField field, ulong address, bool interior, int depth)
    {
        var node = new JsonObject { ["name"] = field.Name ?? "?", ["type"] = field.Type?.Name ?? field.ElementType.ToString() };
        try
        {
            if (field.ElementType == ClrElementType.String || field.IsObjectReference)
                return Link(node, field.ReadObject(address, interior));
            if (field.ElementType == ClrElementType.Struct && field.Type is ClrType structType && !structType.IsEnum)
            {
                ClrValueType value = field.ReadStruct(address, interior);
                return Struct(node, structType, value.Address, depth);
            }
            string? text = Primitive(field.Type?.IsEnum == true ? field.Type.AsEnum().ElementType : field.ElementType, field, address, interior);
            node["kind"] = "value";
            node["value"] = field.Type?.IsEnum == true && text != null ? EnumName(field.Type, text) : text ?? $"({field.ElementType})";
        }
        catch (Exception error) when (error is ClrDiagnosticsException or InvalidOperationException or ArgumentException
                                               or IndexOutOfRangeException or NullReferenceException)
        {
            node["kind"] = "unreadable";
            node["value"] = error.GetType().Name;
        }
        return node;
    }

    private JsonObject Struct(JsonObject node, ClrType type, ulong address, int depth)
    {
        node["kind"] = "struct";
        if (depth >= StructDepth)
        {
            node["value"] = "(deeper than shown)";
            return node;
        }
        var fields = new JsonArray();
        foreach (ClrInstanceField inner in type.Fields) fields.Add(Field(inner, address, true, depth + 1));
        node["fields"] = fields;
        return node;
    }

    private JsonObject Link(JsonObject node, ClrObject value)
    {
        if (value.IsNull || value.Address == 0)
        {
            node["kind"] = "null";
            return node;
        }
        if (!value.IsValid || value.Type == null)
        {
            node["kind"] = "unreadable";
            node["value"] = Hex(value.Address);
            return node;
        }
        if (value.Type.IsString)
        {
            node["kind"] = "text";
            node["value"] = value.AsString(TextLimit);
            node["address"] = Hex(value.Address);
            return node;
        }
        node["kind"] = "link";
        node["address"] = Hex(value.Address);
        node["valueType"] = value.Type.Name;
        node["summary"] = Summary(value);
        return node;
    }

    private JsonArray Elements(ClrArray array, int from, int count, int skip, int take)
    {
        var items = new JsonArray();
        ClrType? component = array.Type.ComponentType;
        int end = Math.Min(from + count, array.Length);
        for (int i = from + skip; i < end && items.Count < take; i++)
        {
            var node = new JsonObject { ["name"] = $"[{i - from}]", ["type"] = component?.Name ?? "?" };
            try
            {
                if (component == null) node["kind"] = "unreadable";
                else if (component.IsObjectReference || component.IsString) Link(node, array.GetObjectValue(i));
                else if (component.IsValueType && !component.IsPrimitive && !component.IsEnum)
                    Struct(node, component, array.GetStructValue(i).Address, 0);
                else
                {
                    node["kind"] = "value";
                    node["value"] = ArrayPrimitive(array, component.IsEnum ? component.AsEnum().ElementType : component.ElementType, i);
                }
            }
            catch (Exception error) when (error is ClrDiagnosticsException or InvalidOperationException or ArgumentException)
            {
                node["kind"] = "unreadable";
                node["value"] = error.GetType().Name;
            }
            items.Add(node);
        }
        return items;
    }

    /// <summary>.NET's own list, dictionary and set opened for a person: their live items, not their inner arrays.</summary>
    private JsonObject? Collection(ClrObject o, int skip, int take)
    {
        string name = o.Type?.Name ?? "";
        string bare = name.Split('<')[0];
        try
        {
            if (bare is "System.Collections.Generic.List" && o.TryReadObjectField("_items", out ClrObject items) && !items.IsNull)
            {
                int size = o.ReadField<int>("_size");
                return new JsonObject { ["kind"] = "list", ["count"] = size, ["skip"] = skip, ["items"] = Elements(items.AsArray(), 0, size, skip, take) };
            }
            if (bare is "System.Collections.Generic.Dictionary" or "System.Collections.Generic.HashSet"
                && o.TryReadObjectField("_entries", out ClrObject entries) && !entries.IsNull)
            {
                int count = o.ReadField<int>("_count");
                ClrArray array = entries.AsArray();
                ClrType? entryType = array.Type.ComponentType;
                var list = new JsonArray();
                int used = 0;
                for (int i = 0; i < Math.Min(count, array.Length) && list.Count < take; i++)
                {
                    ClrValueType entry = array.GetStructValue(i);
                    if (entry.ReadField<int>("next") < -1) continue;   // a free slot: .NET marks them below -1
                    if (used++ < skip) continue;
                    var node = new JsonObject { ["name"] = $"[{used - 1}]", ["kind"] = "struct", ["type"] = entryType?.Name ?? "?" };
                    var fields = new JsonArray();
                    foreach (ClrInstanceField f in entryType?.Fields ?? [])
                        if (f.Name is "key" or "value") fields.Add(Field(f, entry.Address, true, 1));
                    node["fields"] = fields;
                    list.Add(node);
                }
                return new JsonObject
                {
                    ["kind"] = bare.EndsWith("HashSet", StringComparison.Ordinal) ? "set" : "dictionary",
                    ["count"] = count - o.ReadField<int>("_freeCount"), ["skip"] = skip, ["items"] = list,
                };
            }
        }
        catch (Exception error) when (error is ClrDiagnosticsException or InvalidOperationException or ArgumentException)
        {
            return null;
        }
        return null;
    }

    private static string? Primitive(ClrElementType type, ClrInstanceField f, ulong a, bool i) => type switch
    {
        ClrElementType.Boolean => f.Read<bool>(a, i) ? "true" : "false",
        ClrElementType.Char => f.Read<char>(a, i).ToString(),
        ClrElementType.Int8 => f.Read<sbyte>(a, i).ToString(CultureInfo.InvariantCulture),
        ClrElementType.UInt8 => f.Read<byte>(a, i).ToString(CultureInfo.InvariantCulture),
        ClrElementType.Int16 => f.Read<short>(a, i).ToString(CultureInfo.InvariantCulture),
        ClrElementType.UInt16 => f.Read<ushort>(a, i).ToString(CultureInfo.InvariantCulture),
        ClrElementType.Int32 => f.Read<int>(a, i).ToString(CultureInfo.InvariantCulture),
        ClrElementType.UInt32 => f.Read<uint>(a, i).ToString(CultureInfo.InvariantCulture),
        ClrElementType.Int64 => f.Read<long>(a, i).ToString(CultureInfo.InvariantCulture),
        ClrElementType.UInt64 => f.Read<ulong>(a, i).ToString(CultureInfo.InvariantCulture),
        ClrElementType.Float => f.Read<float>(a, i).ToString("R", CultureInfo.InvariantCulture),
        ClrElementType.Double => f.Read<double>(a, i).ToString("R", CultureInfo.InvariantCulture),
        ClrElementType.NativeInt or ClrElementType.Pointer or ClrElementType.FunctionPointer => Hex((ulong)f.Read<long>(a, i)),
        ClrElementType.NativeUInt => Hex(f.Read<ulong>(a, i)),
        _ => null,
    };

    private static string ArrayPrimitive(ClrArray array, ClrElementType type, int i) => type switch
    {
        ClrElementType.Boolean => array.GetValue<bool>(i) ? "true" : "false",
        ClrElementType.Char => array.GetValue<char>(i).ToString(),
        ClrElementType.Int8 => array.GetValue<sbyte>(i).ToString(CultureInfo.InvariantCulture),
        ClrElementType.UInt8 => array.GetValue<byte>(i).ToString(CultureInfo.InvariantCulture),
        ClrElementType.Int16 => array.GetValue<short>(i).ToString(CultureInfo.InvariantCulture),
        ClrElementType.UInt16 => array.GetValue<ushort>(i).ToString(CultureInfo.InvariantCulture),
        ClrElementType.Int32 => array.GetValue<int>(i).ToString(CultureInfo.InvariantCulture),
        ClrElementType.UInt32 => array.GetValue<uint>(i).ToString(CultureInfo.InvariantCulture),
        ClrElementType.Int64 => array.GetValue<long>(i).ToString(CultureInfo.InvariantCulture),
        ClrElementType.UInt64 => array.GetValue<ulong>(i).ToString(CultureInfo.InvariantCulture),
        ClrElementType.Float => array.GetValue<float>(i).ToString("R", CultureInfo.InvariantCulture),
        ClrElementType.Double => array.GetValue<double>(i).ToString("R", CultureInfo.InvariantCulture),
        _ => $"({type})",
    };

    private static string EnumName(ClrType type, string number)
    {
        if (!long.TryParse(number, NumberStyles.Integer, CultureInfo.InvariantCulture, out long value)) return number;
        foreach (var (name, raw) in type.AsEnum().EnumerateValues())
            if (raw != null && Convert.ToInt64(raw, CultureInfo.InvariantCulture) == value) return $"{name} ({number})";
        return number;
    }

    // ---- Small helpers ----

    private static string ModuleName(ClrType? type)
    {
        ClrModule? module = type?.Module;
        if (module == null) return "";
        if (!string.IsNullOrEmpty(module.Name))
        {
            string file = Path.GetFileName(module.Name);
            if (file.EndsWith(".dll", StringComparison.OrdinalIgnoreCase) || file.EndsWith(".exe", StringComparison.OrdinalIgnoreCase))
                return file[..^4];
            return file;
        }
        return module.AssemblyName?.Split(',')[0] ?? "";
    }

    private static string Hex(ulong address) => "0x" + address.ToString("X", CultureInfo.InvariantCulture);

    private static ulong Address(JsonObject request)
    {
        string text = Text(request, "address").Trim();
        if (text.StartsWith("0x", StringComparison.OrdinalIgnoreCase)) text = text[2..];
        if (!ulong.TryParse(text, NumberStyles.HexNumber, CultureInfo.InvariantCulture, out ulong address) || address == 0)
            throw new SessionError("An address is written in hexadecimal, as 0x1629EFD6E98.");
        return address;
    }

    private static string Text(JsonObject request, string name, string? fallback = null)
    {
        string? value = request[name]?.GetValue<string>();
        if (string.IsNullOrEmpty(value))
            return fallback ?? throw new SessionError($"The request needs {name}.");
        return value;
    }

    private static int Int(JsonObject request, string name, int fallback) =>
        request[name] is JsonValue v && v.TryGetValue(out int n) ? Math.Max(0, n) : fallback;

    private static int Take(JsonObject request) => Math.Clamp(Int(request, "take", DefaultTake), 1, MaxTake);
}
