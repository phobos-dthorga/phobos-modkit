using System.Diagnostics;
using System.Runtime.InteropServices;
using System.Text.Json.Nodes;

namespace Phobos.ModKit.Heap;

/// <summary>
/// Lets a program run on that a freezing reader left frozen (1.132.0). The reader freezes a program by suspending each of its
/// threads once; if the reader stops before it lets go (killed, or the machine's own trouble), every thread stays suspended and the
/// game hangs. Thaw resumes each thread once, and only when every thread it can open is suspended: a program with any thread
/// running was not left frozen by the reader, and is left alone.
/// </summary>
public static class Thaw
{
    private const uint ThreadSuspendResume = 0x0002;
    private const uint Failed = 0xFFFFFFFF;

    public static JsonObject Run(int pid)
    {
        if (!OperatingSystem.IsWindows())
            return new JsonObject { ["error"] = "Thawing a program works on Windows only." };
        Process process;
        try
        {
            process = Process.GetProcessById(pid);
        }
        catch (ArgumentException)
        {
            return new JsonObject { ["error"] = $"No program runs with ID {pid}." };
        }
        var handles = new List<IntPtr>();
        try
        {
            foreach (ProcessThread thread in process.Threads)
            {
                IntPtr handle = OpenThread(ThreadSuspendResume, false, (uint)thread.Id);
                if (handle != IntPtr.Zero) handles.Add(handle);
            }
            if (handles.Count == 0)
                return new JsonObject { ["error"] = $"None of program {pid}'s threads could be opened; nothing was changed." };
            // A thread's suspend count, read without changing it: suspend once (which gives the count before), then resume once.
            int suspended = 0;
            foreach (IntPtr handle in handles)
            {
                uint before = SuspendThread(handle);
                if (before == Failed) continue;
                ResumeThread(handle);
                if (before >= 1) suspended++;
            }
            var found = new JsonObject { ["pid"] = pid, ["threads"] = handles.Count, ["suspended"] = suspended };
            if (suspended < handles.Count)
            {
                found["thawed"] = false;
                found["says"] = $"{handles.Count - suspended} of {handles.Count} threads are running, so it was not left frozen; nothing was changed.";
                return found;
            }
            foreach (IntPtr handle in handles)
                ResumeThread(handle);
            found["thawed"] = true;
            found["says"] = $"Every one of its {handles.Count} threads was suspended; each was resumed once.";
            return found;
        }
        finally
        {
            foreach (IntPtr handle in handles)
                CloseHandle(handle);
            process.Dispose();
        }
    }

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern IntPtr OpenThread(uint access, bool inherit, uint threadId);

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern uint SuspendThread(IntPtr thread);

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern uint ResumeThread(IntPtr thread);

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern bool CloseHandle(IntPtr handle);
}
