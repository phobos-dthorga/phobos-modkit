namespace NamesFixture.Core;

/// <summary>A made-up boat.</summary>
public class Boat
{
    public const int MaxKnots = 30;

    public string Name { get; set; } = "";

    /// <summary>Whether it floats.</summary>
    public bool Float(int load)
    {
        return load < MaxKnots;
    }
}
