# Fixtures

Every file here is written by hand. None is cut from a real save, log or mod, and every mod, path and name in
them is made up.

## RimWorld logs

| File | Layout | How faithful |
| --- | --- | --- |
| `rimworld/player-1.7.log` | 1.7 | Line shapes follow logs written by RimWorld 1.7.5000 (November 2026): the header, timestamps and padded levels, the two kinds of stack line, Harmony patch lines, XML Extensions' bracketed header and the save-loaded mod list. The "TempJob allocation" wording is taken from a note made in October 2026, not from a log at hand. |
| `rimworld/player-prev-1.7.log` | 1.7 | A shorter previous run, for comparisons. |
| `rimworld/player-1.6.log` | 1.6 | Unity's usual player-log layout as we understand it. **Not checked against a real 1.6 log.** |

## A made-up mod assembly

`dotnet/PatchFixture/` is C# source the assembly reader's tests build (into the kit's build folder) and then read. Its
`HarmonyLib` is a stand-in with only the names Harmony's documentation publishes (the patch attributes, `Harmony.Patch`,
`HarmonyMethod`, `AccessTools`), no code of Harmony's. It holds one of each patch form the reader handles: a class target
with a bool prefix and a priority, a getter, an overload with a generic argument type, marked patch methods, a
TargetMethod, two `harmony.Patch` calls (one through `AccessTools.TypeByName`), and a look-alike that is not a patch.

## RimWorld save

`rimworld/Example.rws` follows the element paths of RimWorld 1.7.5000 saves: a colony map with things, a pawn with
hediffs, traits, skills, inventory and apparel, needs and remembered thoughts (its Food need has no level, as the game
leaves out a level of 0), a corpse holding a pawn, world pawns alive and dead, factions and
mods. Its 8 by 8 map has grids encoded the game's way (base64 of raw deflate, or plain for pollution's `arr`) from
these values, cells numbered z * 8 + x:

| Grid | Values |
| --- | --- |
| terrain | Soil in cells 0 to 31, Sand in 32 to 63 (as their short hashes, 34465 and 21158) |
| roofs | RoofConstructed (5133) where x is 0 or 1, else none |
| gas | toxic gas 128 at (3, 3); blind smoke 255 at (4, 4) |
| fog | every cell with z of 6 or 7 |
| snow | half depth (32768) at (0, 0) |
| pollution | cell 5, that is (5, 0) |
| deep resources | Steel (33787), count 300, at cell 10, that is (2, 1) |

Its world has a surface pollution layer for a planet of three subdivisions (272 tiles, 16-bit values, base64 of raw
deflate): tile 120 at 10% (6554, under Example Home), tile 130 at 100% (65535, under Raider Camp) and tile 7,
a neighbour of tile 130, at 50% (32768).

## Steam

`steam/details.json` and `steam/comments-render.json` follow the shapes of Steam's GetPublishedFileDetails response
and comment-render endpoint (7 November 2026), with made-up items, people and comments. In the comments, the first
is by the item's uploader (account 101, the creator's SteamID64 less 76561197960265728). The first two items carry
made-up BBCode descriptions. `steam/collection.json` follows GetCollectionDetails (9 November 2026): one collection
of the three items, listed out of order with sortorder values, and one collection Steam does not return (result 9).
