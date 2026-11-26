using System.Text.Encodings.Web;
using System.Text.Json;
using System.Text.Json.Nodes;
using Phobos.ModKit.Heap;

// PhobosModKit.Heap serve --pid N --runtime-folder DIR [--limit-seconds S] [--describe PATH]...
//     Takes a snapshot of process N, then answers one JSON request a line on standard input with one JSON answer a line on
//     standard output, until standard input closes, {"op": "release"} arrives, or the time limit passes. The first line out
//     says whether the snapshot was taken ({"ready": true, ...}) or why not ({"ready": false, "error": ...}).
// PhobosModKit.Heap run --pid N --runtime-folder DIR [--describe PATH]... --request JSON [--request JSON]...
//     The same, for the requests given, then lets the snapshot go.
// PhobosModKit.Heap run ... --attach freeze [--limit-seconds S]
//     (1.132.0) Freezes the program and reads it in place, with no snapshot, for when Windows has no room to clone it (error
//     1450). The program stays frozen until the last answer, or the time limit (120 s unless named), and the last line out says
//     how long ({"event": "thawed", "frozenMs": N}). Only run may freeze: serve would hold a game frozen while a page waits.
// PhobosModKit.Heap thaw --pid N
//     (1.132.0) Lets a program run on that a freezing reader left frozen (it stopped before it could): when every thread of it is
//     suspended, resumes each once. Changes nothing when any thread runs. One JSON line out says what it found.
//
// Requests: {"op": "info"}, {"op": "overview"}, {"op": "kind", "type": NAME, "skip", "take", "sort": "size", "match"},
// {"op": "object", "address": "0x...", "skip", "take"}, {"op": "holders", "address", "max"}, {"op": "path", "address"},
// {"op": "why", "type": NAME, "sample"}, {"op": "values", "type": NAME, "paths": [PATH...], "take", "items", "subclasses"},
// {"op": "release"}. Each may carry an "id", which its answer repeats.
//
// Only the memory-reading library beside the program's own coreclr.dll is ever loaded, and only when that folder is the
// RUNTIME-FOLDER named: the caller (a game's adapter) names the install it trusts. Progress goes to standard error as the kit's
// progress lines when PHOBOS_MODKIT_PROGRESS is set.
var options = Arguments.Parse(args);
if (options.Error != null)
{
    Console.Error.WriteLine(options.Error);
    Console.Error.WriteLine("usage: PhobosModKit.Heap serve|run --pid N --runtime-folder DIR [--attach snapshot|freeze] [--limit-seconds S] "
                            + "[--describe PATH]... [--request JSON]...");
    Console.Error.WriteLine("       PhobosModKit.Heap thaw --pid N");
    return 2;
}

var json = new JsonSerializerOptions { Encoder = JavaScriptEncoder.UnsafeRelaxedJsonEscaping };
var output = new Output(json);

if (options.Mode == "thaw")
{
    JsonObject found = Thaw.Run(options.Pid);
    output.Write(found);
    return found["error"] == null ? 0 : 1;
}

HeapSession session;
var frozenClock = System.Diagnostics.Stopwatch.StartNew();
try
{
    session = HeapSession.Open(options.Pid, options.RuntimeFolder!, options.Describe, new Progress(), options.Freeze);
}
catch (Exception error) when (error is SessionError or Microsoft.Diagnostics.Runtime.ClrDiagnosticsException or ArgumentException
                                       or InvalidOperationException or IOException or UnauthorizedAccessException)
{
    output.Write(new JsonObject { ["ready"] = false, ["error"] = error.Message });
    return 1;
}

using (session)
{
    var ready = session.Info();
    ready["ready"] = true;
    ready["limitSeconds"] = options.LimitSeconds;
    output.Write(ready);

    if (options.Mode == "run" && options.Freeze)
    {
        // A frozen game must always be let go: at the time limit (even mid-answer), on Ctrl+C, and when this program ends.
        void LetGo() => session.Dispose();
        AppDomain.CurrentDomain.ProcessExit += (_, _) => LetGo();
        Console.CancelKeyPress += (_, _) => LetGo();
        using var freezeLimit = new Timer(_ =>
        {
            LetGo();
            output.Write(new JsonObject { ["event"] = "thawed", ["frozenMs"] = frozenClock.ElapsedMilliseconds,
                                          ["reason"] = $"frozen for its limit of {options.LimitSeconds} s" });
            Environment.Exit(1);
        }, null, TimeSpan.FromSeconds(options.LimitSeconds), Timeout.InfiniteTimeSpan);
        try
        {
            foreach (string request in options.Requests)
                output.Write(Answer(session, request));
        }
        finally
        {
            LetGo();
        }
        freezeLimit.Change(Timeout.Infinite, Timeout.Infinite);
        output.Write(new JsonObject { ["event"] = "thawed", ["frozenMs"] = frozenClock.ElapsedMilliseconds });
        return 0;
    }

    if (options.Mode == "run")
    {
        foreach (string request in options.Requests)
            output.Write(Answer(session, request));
        return 0;
    }

    // The time limit lets the snapshot go even while a request is being answered: Windows keeps a snapshot by copying each page
    // the program changes afterwards, so one left open grows while the game runs on.
    using var limit = new Timer(_ =>
    {
        output.Write(new JsonObject { ["event"] = "released", ["reason"] = $"held for its limit of {options.LimitSeconds} s" });
        Environment.Exit(0);
    }, null, TimeSpan.FromSeconds(options.LimitSeconds), Timeout.InfiniteTimeSpan);

    string? line;
    while ((line = Console.In.ReadLine()) != null)
    {
        if (line.Trim().Length == 0) continue;
        JsonObject answer = Answer(session, line);
        output.Write(answer);
        if (answer["released"]?.GetValue<bool>() == true) break;
    }
    return 0;
}

static JsonObject Answer(HeapSession session, string line)
{
    JsonNode? id = null;
    try
    {
        JsonObject request = JsonNode.Parse(line)?.AsObject() ?? throw new SessionError("A request must be a JSON object.");
        id = request["id"]?.DeepClone();
        JsonObject data = session.Handle(request);
        var answer = new JsonObject { ["ok"] = true };
        if (id != null) answer["id"] = id;
        if (data.Remove("released", out JsonNode? released)) answer["released"] = released;
        answer["data"] = data;
        return answer;
    }
    catch (Exception error) when (error is SessionError or JsonException or FormatException or InvalidOperationException
                                           or Microsoft.Diagnostics.Runtime.ClrDiagnosticsException or OperationCanceledException)
    {
        var answer = new JsonObject { ["ok"] = false, ["error"] = error.Message };
        if (id != null) answer["id"] = id;
        return answer;
    }
}

namespace Phobos.ModKit.Heap
{
    /// <summary>A refusal or a request the session cannot answer, in words for a person.</summary>
    public sealed class SessionError(string message) : Exception(message);

    /// <summary>One JSON line at a time on standard output, never two at once (the time limit writes from a timer).</summary>
    public sealed class Output(JsonSerializerOptions options)
    {
        private readonly object gate = new();
        private readonly Stream stdout = Console.OpenStandardOutput();

        public void Write(JsonNode node)
        {
            byte[] bytes = System.Text.Encoding.UTF8.GetBytes(node.ToJsonString(options) + "\n");
            lock (gate)
            {
                stdout.Write(bytes);
                stdout.Flush();
            }
        }
    }

    /// <summary>The kit's progress lines (python/phobos_modkit/progress.py), only when a program asks for them.</summary>
    public sealed class Progress
    {
        private readonly bool wanted = Environment.GetEnvironmentVariable("PHOBOS_MODKIT_PROGRESS") is { Length: > 0 } v && v != "0";

        public void Say(string label, long? step = null, long? of = null)
        {
            if (!wanted) return;
            var line = new JsonObject { ["progress"] = 1, ["label"] = label };
            if (step != null && of is > 0)
            {
                line["step"] = Math.Min(step.Value, of.Value);
                line["of"] = of.Value;
            }
            Console.Error.WriteLine(line.ToJsonString());
            Console.Error.Flush();
        }
    }

    public sealed class Arguments
    {
        public const int DefaultLimitSeconds = 600;   // ten minutes: the owner's choice of 20 November 2026 (the Companion's decisions)
        // A frozen game's limit (1.132.0, agent default): reading every live check took 12-18 s from a snapshot of the owner's game.
        public const int DefaultFreezeSeconds = 120;

        public string Mode = "";
        public int Pid;
        public string? RuntimeFolder;
        public int LimitSeconds = DefaultLimitSeconds;
        public bool Freeze;
        public List<string> Describe = [];
        public List<string> Requests = [];
        public string? Error;

        public static Arguments Parse(string[] args)
        {
            var result = new Arguments();
            if (args.Length == 0 || (args[0] != "serve" && args[0] != "run" && args[0] != "thaw"))
                return Fail(result, "Name a mode: serve, run or thaw.");
            result.Mode = args[0];
            bool limitNamed = false;
            for (int i = 1; i < args.Length; i++)
            {
                string name = args[i];
                if (i + 1 >= args.Length) return Fail(result, $"{name} needs a value.");
                string value = args[++i];
                switch (name)
                {
                    case "--pid" when int.TryParse(value, out int pid) && pid > 0: result.Pid = pid; break;
                    case "--runtime-folder": result.RuntimeFolder = value; break;
                    case "--limit-seconds" when int.TryParse(value, out int seconds) && seconds > 0:
                        result.LimitSeconds = seconds;
                        limitNamed = true;
                        break;
                    case "--attach" when value is "snapshot" or "freeze": result.Freeze = value == "freeze"; break;
                    case "--describe": result.Describe.Add(value); break;
                    case "--request": result.Requests.Add(value); break;
                    default: return Fail(result, $"Not understood: {name} {value}");
                }
            }
            if (result.Pid == 0) return Fail(result, "--pid is needed.");
            if (result.Mode == "thaw") return result;
            if (string.IsNullOrWhiteSpace(result.RuntimeFolder)) return Fail(result, "--runtime-folder is needed.");
            if (result.Freeze && result.Mode != "run")
                return Fail(result, "Only run may freeze the program: serve would hold it frozen while a page waits.");
            if (result.Freeze && !limitNamed) result.LimitSeconds = DefaultFreezeSeconds;
            if (result.Mode == "run" && result.Requests.Count == 0) return Fail(result, "run needs at least one --request.");
            return result;
        }

        private static Arguments Fail(Arguments result, string error)
        {
            result.Error = error;
            return result;
        }
    }
}
