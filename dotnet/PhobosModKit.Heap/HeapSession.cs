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
    // The values request (1.120.0): objects read per kind, and items opened per path on one object, unless the request asks otherwise.
    public const int DefaultValuesTake = 5000, MaxValuesTake = 50_000, DefaultItems = 1000, MaxItems = 100_000;
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
    /// <summary>Read in place with the program frozen (1.132.0), not from a snapshot.</summary>
    public bool Frozen { get; private init; }
    private int disposed;
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
    /// <remarks>
    /// <paramref name="freeze"/> (1.132.0): suspend the program's threads and read it in place instead of taking a snapshot, for
    /// when Windows has no room to clone it (error 1450, a game near the machine's free commit). The program stays frozen until
    /// the session is disposed, so the caller holds it no longer than it must and always disposes it.
    /// </remarks>
    public static HeapSession Open(int pid, string runtimeFolder, IEnumerable<string> describe, Progress progress, bool freeze = false)
    {
        if (!OperatingSystem.IsWindows())
            throw new SessionError("A snapshot of a running program can be read on Windows only.");
        string folder = Normal(runtimeFolder);
        progress.Say(freeze ? "Freezing the game to read it" : "Taking a snapshot of the game");
        var clock = Stopwatch.StartNew();
        var targetOptions = new DataTargetOptions { VerifyDacOnWindows = false };
        DataTarget target = freeze ? DataTarget.AttachToProcess(pid, suspend: true, targetOptions)
                                   : DataTarget.CreateSnapshotAndAttach(pid, targetOptions);
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
            return new HeapSession(pid, target, runtime, snapshotMs, folder, dac, describe, progress) { Frozen = freeze };
        }
        catch
        {
            target.Dispose();
            throw;
        }
    }

    private static string Normal(string path) => Path.GetFullPath(path).TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar);

    /// <summary>Lets the snapshot go, or (frozen) lets the program run on. Safe to call twice, and from the time limit's thread.</summary>
    public void Dispose()
    {
        if (Interlocked.Exchange(ref disposed, 1) == 1) return;
        try
        {
            runtime.Dispose();
        }
        finally
        {
            target.Dispose();
        }
    }

    public JsonObject Info() => new()
    {
        ["pid"] = Pid,
        ["snapshotMs"] = SnapshotMilliseconds,
        ["attach"] = Frozen ? "freeze" : "snapshot",
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
            "values" => Values(Text(request, "type"), ValuePath.All(request), Math.Clamp(Int(request, "take", DefaultValuesTake), 1, MaxValuesTake),
                               Math.Clamp(Int(request, "items", DefaultItems), 1, MaxItems),
                               request["subclasses"] is JsonValue sub && sub.TryGetValue(out bool also) && also),
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

    /// <summary>
    /// Named values read from every object of a kind (1.120.0, for the kit's live checks): each path follows fields by name through links
    /// and structs; "[]" after a name opens a list, array, set or dictionary into its items (a dictionary's values); a final "#" gives a
    /// collection's count without reading its items. A path that opened anything answers with a list; one that did not, with one value
    /// or null. Values come as text, as the object request gives them; a link at the end of a path gives its summary.
    /// </summary>
    private JsonObject Values(string type, List<ValuePath> paths, int take, int itemLimit, bool subclasses)
    {
        List<(ulong address, ulong size)> all = Instances(type, subclasses);
        var items = new JsonArray();
        foreach (var (address, _) in all.Take(take))
        {
            ClrObject o = heap.GetObject(address);
            var values = new JsonObject();
            bool cut = false;
            foreach (ValuePath path in paths)
            {
                try
                {
                    values[path.Text] = ReadPath(new Place(o.Address, o.Type, false), path, itemLimit, ref cut);
                }
                catch (Exception error) when (error is ClrDiagnosticsException or InvalidOperationException or ArgumentException
                                                       or IndexOutOfRangeException or NullReferenceException)
                {
                    values[path.Text] = null;
                }
            }
            var item = new JsonObject { ["address"] = Hex(address), ["type"] = o.Type?.Name, ["summary"] = Summary(o), ["values"] = values };
            if (cut) item["cut"] = true;
            items.Add(item);
        }
        return new JsonObject
        {
            ["type"] = type, ["subclasses"] = subclasses, ["count"] = all.Count, ["take"] = take, ["more"] = all.Count > take,
            ["itemLimit"] = itemLimit, ["items"] = items,
        };
    }

    /// <summary>Where a value is: an object (Interior false) or a struct inside one (Interior true); or, for an item of a list of
    /// numbers or text, the value itself (IsValue).</summary>
    private readonly record struct Place(ulong Address, ClrType? Type, bool Interior, string? Value = null, bool IsValue = false);

    private JsonNode? ReadPath(Place start, ValuePath path, int itemLimit, ref bool cut)
    {
        var current = new List<Place> { start };
        bool listed = false;
        for (int i = 0; i < path.Steps.Count; i++)
        {
            ValueStep step = path.Steps[i];
            bool last = i == path.Steps.Count - 1;
            var next = new List<Place>();
            var answers = new JsonArray();
            foreach (Place place in current)
            {
                if (place.IsValue || place.Type == null) continue;
                ClrInstanceField? field = place.Type.GetFieldByName(step.Name);
                if (field == null) continue;
                if (last && !step.Open && !path.Count)
                {
                    answers.Add(FieldValue(field, place));
                    continue;
                }
                Place? child = Child(field, place);
                if (child == null)
                {
                    if (last && path.Count && listed) answers.Add(null);
                    continue;
                }
                if (last && path.Count)
                {
                    answers.Add(CountOf(child.Value));
                    continue;
                }
                if (step.Open)
                {
                    listed = true;
                    next.AddRange(ItemsOf(child.Value, itemLimit - next.Count, ref cut));
                }
                else next.Add(child.Value);
            }
            if (last && !step.Open)
                return listed ? answers : answers.Count > 0 ? answers[0]?.DeepClone() : null;
            current = next;
        }
        // The path ended by opening a collection: each item as a value (a number, text, or a link's summary).
        return new JsonArray(current.Select(PlaceValue).ToArray());
    }

    private Place? Child(ClrInstanceField field, Place place)
    {
        if (field.ElementType == ClrElementType.String || field.IsObjectReference)
        {
            ClrObject value = field.ReadObject(place.Address, place.Interior);
            if (value.IsNull || !value.IsValid || value.Type == null) return null;
            return new Place(value.Address, value.Type, false);
        }
        if (field.ElementType == ClrElementType.Struct && field.Type is ClrType structType && !structType.IsEnum)
        {
            ClrValueType inner = field.ReadStruct(place.Address, place.Interior);
            return new Place(inner.Address, structType, true);
        }
        return null;
    }

    private JsonNode? FieldValue(ClrInstanceField field, Place place)
    {
        if (field.ElementType == ClrElementType.String || field.IsObjectReference)
        {
            ClrObject value = field.ReadObject(place.Address, place.Interior);
            if (value.IsNull || !value.IsValid || value.Type == null) return null;
            return value.Type.IsString ? value.AsString(TextLimit) : Summary(value) is { Length: > 0 } s ? s : value.Type.Name;
        }
        if (field.ElementType == ClrElementType.Struct && field.Type is ClrType structType && !structType.IsEnum) return null;
        string? text = Primitive(field.Type?.IsEnum == true ? field.Type.AsEnum().ElementType : field.ElementType, field, place.Address,
                                 place.Interior);
        return field.Type?.IsEnum == true && text != null ? EnumName(field.Type, text) : text;
    }

    private JsonNode? PlaceValue(Place place)
    {
        if (place.IsValue) return place.Value;
        if (place.Interior || place.Type == null) return null;
        ClrObject o = heap.GetObject(place.Address);
        if (!o.IsValid || o.Type == null) return null;
        return o.Type.IsString ? o.AsString(TextLimit) : Summary(o) is { Length: > 0 } s ? s : o.Type.Name;
    }

    /// <summary>How many items a list, array, set or dictionary holds; null for anything else.</summary>
    private JsonNode? CountOf(Place place)
    {
        if (place.Interior || place.Type == null) return null;
        ClrObject o = heap.GetObject(place.Address);
        if (o.IsArray) return o.AsArray().Length;
        string bare = (o.Type?.Name ?? "").Split('<')[0];
        if (bare == "System.Collections.Generic.List") return o.ReadField<int>("_size");
        if (bare is "System.Collections.Generic.Dictionary" or "System.Collections.Generic.HashSet")
            return o.ReadField<int>("_count") - o.ReadField<int>("_freeCount");
        return null;
    }

    /// <summary>A collection's items, as places to read on from: objects, structs, or numbers and text as values.</summary>
    private List<Place> ItemsOf(Place place, int limit, ref bool cut)
    {
        var items = new List<Place>();
        if (limit <= 0)
        {
            cut = true;
            return items;
        }
        if (place.Interior || place.Type == null) return items;
        ClrObject o = heap.GetObject(place.Address);
        string bare = (o.Type?.Name ?? "").Split('<')[0];
        if (o.IsArray) cut |= ArrayItems(o.AsArray(), o.AsArray().Length, limit, items);
        else if (bare == "System.Collections.Generic.List" && o.TryReadObjectField("_items", out ClrObject array) && !array.IsNull)
            cut |= ArrayItems(array.AsArray(), o.ReadField<int>("_size"), limit, items);
        else if (bare is "System.Collections.Generic.Dictionary" or "System.Collections.Generic.HashSet"
                 && o.TryReadObjectField("_entries", out ClrObject entries) && !entries.IsNull)
        {
            ClrArray slots = entries.AsArray();
            ClrType? entryType = slots.Type.ComponentType;
            ClrInstanceField? value = EntryField(entryType, "value");
            string next = EntryField(entryType, "next")?.Name ?? "next";
            int count = o.ReadField<int>("_count");
            for (int i = 0; i < Math.Min(count, slots.Length) && value != null; i++)
            {
                ClrValueType entry = slots.GetStructValue(i);
                if (entry.ReadField<int>(next) < -1) continue;   // a free slot: .NET marks them below -1
                if (items.Count >= limit)
                {
                    cut = true;
                    break;
                }
                var at = new Place(entry.Address, entryType, true);
                if (Child(value, at) is Place child) items.Add(child);
                else if (FieldValue(value, at) is JsonNode node) items.Add(new Place(0, null, false, node.GetValue<string>(), true));
            }
        }
        return items;
    }

    /// <summary>Adds up to <paramref name="limit"/> of an array's first <paramref name="length"/> items; whether any were left out.</summary>
    private bool ArrayItems(ClrArray array, int length, int limit, List<Place> items)
    {
        ClrType? component = array.Type.ComponentType;
        int end = Math.Min(length, array.Length);
        for (int i = 0; i < end; i++)
        {
            if (items.Count >= limit) return true;
            if (component == null) continue;
            if (component.IsObjectReference || component.IsString)
            {
                ClrObject item = array.GetObjectValue(i);
                if (!item.IsNull && item.IsValid && item.Type != null) items.Add(new Place(item.Address, item.Type, false));
            }
            else if (component.IsValueType && !component.IsPrimitive && !component.IsEnum)
                items.Add(new Place(array.GetStructValue(i).Address, component, true));
            else
                items.Add(new Place(0, null, false,
                                    ArrayPrimitive(array, component.IsEnum ? component.AsEnum().ElementType : component.ElementType, i), true));
        }
        return false;
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

    private List<(ulong address, ulong size)> Instances(string type, bool subclasses = false)
    {
        string key = subclasses ? type + " and its subclasses" : type;
        for (var node = kinds.First; node != null; node = node.Next)
            if (node.Value.type == key)
            {
                kinds.Remove(node);
                kinds.AddFirst(node);
                return node.Value.objects;
            }
        var found = new List<(ulong, ulong)>();
        var answers = new Dictionary<ClrType, bool>();
        long seen = 0;
        foreach (ClrObject o in heap.EnumerateObjects())
        {
            if (++seen % ProgressEvery == 0) progress.Say($"Finding every {type}", seen, objectCount);
            ClrType? t = o.Type;
            if (t == null) continue;
            if (!answers.TryGetValue(t, out bool wanted))
                answers[t] = wanted = t.Name == type || (subclasses && IsBelow(t, type));
            if (wanted) found.Add((o.Address, o.Size));
        }
        objectCount ??= seen;
        kinds.AddFirst((key, found));
        while (kinds.Count > KindsKept) kinds.RemoveLast();
        return found;
    }

    /// <summary>A dictionary's or set's entry field by name: .NET's Dictionary names them in lower case (next, value), its HashSet
    /// with a capital (Next, Value).</summary>
    private static ClrInstanceField? EntryField(ClrType? entryType, string name) =>
        entryType?.GetFieldByName(name) ?? entryType?.GetFieldByName(char.ToUpperInvariant(name[0]) + name[1..]);

    private static bool IsBelow(ClrType type, string name)
    {
        for (ClrType? t = type.BaseType; t != null; t = t.BaseType)
            if (t.Name == name) return true;
        return false;
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
                string next = EntryField(entryType, "next")?.Name ?? "next";
                for (int i = 0; i < Math.Min(count, array.Length) && list.Count < take; i++)
                {
                    ClrValueType entry = array.GetStructValue(i);
                    if (entry.ReadField<int>(next) < -1) continue;   // a free slot: .NET marks them below -1
                    if (used++ < skip) continue;
                    var node = new JsonObject { ["name"] = $"[{used - 1}]", ["kind"] = "struct", ["type"] = entryType?.Name ?? "?" };
                    var fields = new JsonArray();
                    // A dictionary's entry names them key and value; a set's, Value (1.120.0: sets showed no items before).
                    foreach (ClrInstanceField f in entryType?.Fields ?? [])
                        if (f.Name is "key" or "value" or "Value") fields.Add(Field(f, entry.Address, true, 1));
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

/// <summary>One step of a values path: a field's name, and whether its value is opened into items ("[]").</summary>
public sealed record ValueStep(string Name, bool Open);

/// <summary>A values path as written ("held.innerList[].stackCount", "orders#"), read into steps (1.120.0).</summary>
public sealed class ValuePath
{
    public string Text { get; }
    public List<ValueStep> Steps { get; } = new();
    /// <summary>The path ends in "#": the last value's count, not its items.</summary>
    public bool Count { get; }

    public ValuePath(string text)
    {
        Text = text;
        string body = text.Trim();
        if (body.EndsWith('#'))
        {
            Count = true;
            body = body[..^1];
        }
        foreach (string part in body.Split('.'))
        {
            bool open = part.EndsWith("[]", StringComparison.Ordinal);
            string name = open ? part[..^2] : part;
            if (name.Length == 0 || name.Any(c => !(char.IsLetterOrDigit(c) || c is '_' or '<' or '>')))
                throw new SessionError($"\"{text}\" is not a values path: field names joined by dots, [] to open a list, # at the end to count.");
            Steps.Add(new ValueStep(name, open));
        }
        if (Count && Steps[^1].Open)
            throw new SessionError($"\"{text}\" both opens and counts its last list; write it without [] to count it.");
    }

    public static List<ValuePath> All(JsonObject request)
    {
        if (request["paths"] is not JsonArray list || list.Count == 0)
            throw new SessionError("A values request needs \"paths\", a list of field paths.");
        return list.Select(n => new ValuePath(n?.GetValue<string>() ?? "")).ToList();
    }
}
