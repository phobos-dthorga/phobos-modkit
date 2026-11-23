using NamesFixture.Core;

namespace NamesFixture.Mod;

public static class Sail
{
    public static bool Ready(Boat boat, int crew)
    {
        int load = crew * 2;
        return boat.Float(load) && boat.Name.Length > 0;
    }
}
