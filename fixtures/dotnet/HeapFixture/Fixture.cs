// A small running program whose memory the heap reader's tests read: colonists kept in a static list, each with a name, a
// struct, an enum and a link to another; a dictionary; and orphans nothing holds, garbage the collector has not swept yet.
// It prints "ready <pid>" once everything is in place, then waits until its standard input closes.
using System;
using System.Collections.Generic;
using System.Threading;

namespace HeapFixture
{
    public enum Mood { Content, Stressed, Broken }

    public struct Spot
    {
        public int X;
        public int Z;
    }

    public class Kind
    {
        public string defName;
    }

    public class Colonist
    {
        public string Name;
        public int Age;
        public float Comfort;
        public bool Drafted;
        public Mood Mood;
        public Spot Position;
        public Kind def;
        public Colonist Bonded;
    }

    public class Orphan
    {
        public long[] Payload = new long[64];
    }

    public static class Colony
    {
        public static List<Colonist> Colonists = new List<Colonist>();
        public static Dictionary<string, int> Stock = new Dictionary<string, int>();
    }

    public static class Program
    {
        public static int Main()
        {
            var human = new Kind { defName = "Human" };
            for (int i = 0; i < 12; i++)
            {
                Colony.Colonists.Add(new Colonist
                {
                    Name = "Colonist " + i, Age = 20 + i, Comfort = 0.5f, Drafted = i % 2 == 0, Mood = (Mood)(i % 3),
                    Position = new Spot { X = i, Z = 100 + i }, def = human,
                });
            }
            Colony.Colonists[0].Bonded = Colony.Colonists[1];
            Colony.Stock["Steel"] = 75;
            Colony.Stock["Silver"] = 1200;
            GC.Collect();
            GC.WaitForPendingFinalizers();
            GC.Collect();
            MakeOrphans();
            Console.WriteLine("ready " + Environment.ProcessId);
            Console.Out.Flush();
            Console.In.ReadToEnd();
            GC.KeepAlive(human);
            return 0;
        }

        // Made in their own method, after the last collection, so nothing on the stack keeps them and no collection has run since.
        private static void MakeOrphans()
        {
            for (int i = 0; i < 20; i++) Keep(new Orphan());
            Thread.Sleep(0);
        }

        private static void Keep(Orphan orphan) => orphan.Payload[0] = orphan.Payload.Length;
    }
}
