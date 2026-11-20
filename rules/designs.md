# Rules for designing a new behaviour, in every Phobos and D'thorga repository

Read before designing or building a new behaviour for any game or mod: something a player can newly do, or that newly happens to
them. Two rules: the four questions it answers, and the setting a riskier one has. The rules for every session are in [every-session.md](every-session.md); how this folder works is in [README.md](README.md).

## A new behaviour answers for itself

- **Every new behaviour answers three questions before it is built** (owner, 8 Nov 2026, first for the RimWorld mods; for every
  game on 20 Nov 2026): its design record says **what it lets the player do, what it stops them doing, and how it changes the way
  they do things**. Ask this when a behaviour is introduced, not for every figure or data entry. A behaviour with no answer to any
  of the three is not built.
- **And a fourth: what outside the thing itself notices?** (the owner's yes for every mod, 20 Nov 2026, to an agent's proposal,
  after a review found the RimWorld vehicles "deep inside, thin outside": detailed within each vehicle, with almost nothing
  reaching the rest of the game). The record names who or what else in the game takes notice: a person, another faction, the map
  or the world, the game's own records, a letter or an alert. **"Nothing" is allowed as a choice the record states, never by
  accident**: depth that nothing outside the thing can see makes no story.

## A riskier behaviour has its own setting

- **A behaviour that puts the player's things or people at risk has its own setting to switch it off** (owner, 20 Nov 2026, for
  every mod and game, first said of the RimWorld depots' pressures: "Activities with a higher risk should get a proper setting to
  disable them as such but otherwise, they are enabled by default UNLESS they are a HIGH or HIGHER risk"). **It starts on, unless
  its risk is high or higher: then it starts off**, and the player chooses it.
- **The design record grades the risk and says why**, in plain words: what the player can lose, how much at once, and whether they
  can see it coming. A slow loss the player is warned of is low or moderate; losing a whole thing at once, or a person, is high. The
  grade is the designer's proposal until the owner confirms it, and the setting's default follows the grade.
- **Existing behaviours follow the rule when next touched**, not in a sweep. Telling the owner about a new setting, its default and
  where it is stays each repository's own rule.

## Why

Unplanned stories come from rules meeting each other. A behaviour that reaches nothing beyond itself can be as detailed as it
likes and still give the player nothing to tell. The four questions cost a few lines in a design record and catch that before the
work is done.
