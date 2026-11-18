// A made-up mod assembly for the connections tool's tests, written for them: one of each shape the call reader follows.
using System;
using System.Collections.Generic;

namespace Sample.Boats
{
    public class Vessel
    {
        public virtual void Tick() { }
    }

    public class Boat : Vessel
    {
        int oars;
        readonly List<int> crew = new List<int>();

        public string Label => "Boat " + oars;

        public override void Tick()
        {
            Harbour.Count();
            crew.Add(oars);
            Action later = () => Harbour.Moor(this);
            later();
        }

        public IEnumerable<int> Gather()
        {
            yield return Harbour.Count();
        }
    }

    public static class Harbour
    {
        public static int Count() => 1;

        public static void Moor(Boat boat) => Console.WriteLine(boat.Label);
    }
}
