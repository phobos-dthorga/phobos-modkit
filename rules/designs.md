# Rules for designing a new behaviour, in every Phobos and D'thorga repository

Read before designing or building a new behaviour for any game or mod: something a player can newly do, or that newly happens to
them. The rules for every session are in [every-session.md](every-session.md); how this folder works is in [README.md](README.md).

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

## Why

Unplanned stories come from rules meeting each other. A behaviour that reaches nothing beyond itself can be as detailed as it
likes and still give the player nothing to tell. The four questions cost a few lines in a design record and catch that before the
work is done.
