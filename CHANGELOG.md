# Phobos ModKit changelog

Maintained from 7 November 2026. Versions are tags of this repository; consumers pin a commit.

## [Unreleased]

## [1.29.0] - 2026-11-19

The owner asked for it (19 November 2026), after D'thorga Companion read every mod as changed because .NET stamped the git commit into each assembly.

### Added

- A shared rule, in rules/builds.md: the same code builds to the same bytes, whatever the commit, the clock or the folder. Nothing that changes from build to build goes into what is built; the commit belongs in the install record, the changelog or the tag. For .NET, Deterministic and IncludeSourceRevisionInInformationalVersion set to false in Directory.Build.props, and how to check.
- rules/every-session.md says which file to read before which kind of work, starting with builds.md.

### Changed

- The kit's own .NET helpers follow the rule: dotnet/Directory.Build.props no longer lets the SDK stamp the commit.

## [1.28.0] - 2026-11-19

### Fixed

- An entry that many versions repeat word for word, such as "Not yet tested in game.", was given the commit that first ever wrote that line, in every version. Seen on the owner's Changes page the same day: 0.142.0 and 0.141.0 each split off their last entry into a group of its own. Each entry's commit now comes from git blame, by version and first line, with the history pass kept for entries no longer in the changelog.

## [1.27.0] - 2026-11-19

### Added

- installs status names, for a changed assembly that was not only rebuilt, the sources that changed since the installed commit (sources, up to five, and sourcesInAll). Found the same day: turning off .NET's commit stamp in phobos-rimworld's shared build file changed every mod's build inputs, so every assembly read as changed with nothing to say why; now each names Directory.Build.props.

## [1.26.0] - 2026-11-19

From the owner's look at the Companion's Mods page (19 November 2026): "It seems to see changes in DLLs, across the board, where there might not be any", and a tidier page with fewer repeated buttons.

### Added

- changes.entry_commits: every entry a changelog ever held, with the commit that first added its first line, from one pass over its history (about 0.4 s for seven changelogs). changes list and installs status give each entry its commit, so a program can offer one "show the code" for all the entries one commit wrote; changes entry takes its commit from the same pass, so both always agree.
- installs status marks a changed assembly as rebuilt when its project's own sources (its folder, its compiled includes, the shared build files) have not changed since the installed commit, committed or not, with no new source files. Found on the owner's PC: .NET stamps the current git commit into every assembly it builds, so every commit anywhere changed every rebuilt assembly by about 100 bytes. A rebuilt assembly still counts as a change.
- Two states for a mod whose changelogs agree but whose files differ: rebuilt (every changed file only rebuilt) and unlogged (something else changed that no entry describes). A mod in this case read as up to date before.

### Changed

- installs status says what it is doing while it matches entries to their commits.

## [1.25.1] - 2026-11-19

### Changed

- rules/README.md says to name the shared rules' path in backticks, never as a Markdown link: on GitHub a pinned kit's folder is a pointer to this repository, and a link into it leads nowhere. Found when phobos-rimworld's link check refused the first such link. No rule changed.

## [1.25.0] - 2026-11-19

Asked for by the owner (19 November 2026), on choosing how commits are cut for the Companion's code viewer: "a central point from which global rules for all mods can be read and modified", as a folder in this repository to be used as the root for such rules from now on.

### Added

- rules/: the rules every Phobos and D'thorga repository shares. rules/every-session.md is read at the start of every session; rules/README.md says what the folder holds, how a repository takes the rules up, how a rule is changed and where a rule belongs.
- The first shared rules, on commits and changelog entries (the owner's choice): a change and its entry go in one commit; separate changes are committed separately where they are separate anyway, one finished before the next is started; one piece of work stays one commit; nothing is untangled afterwards by staging part of a file; a batch may share a version; an entry keeps its opening words when reworded.
- rules list prints the rule files with when each is read and how many rules it holds. rules check --root REPO says whether a repository reads them (the import in its CLAUDE.md, the pointer in its AGENTS.md, the file its pin holds) and fails when one is missing, for a repository's gate.
- This repository reads its own rules: a CLAUDE.md that imports AGENTS.md and rules/every-session.md.

### Compatibility

- Twelve rules repeated across the repositories are listed in rules/README.md as waiting to move; none was moved. A new or changed rule raises this repository's middle version number from now on, a rewording the last.

## [1.24.1] - 2026-11-19

### Added

- installs status gives each mod's changelog as a path in the repository (changelog), so a program can ask changes for the code behind any entry it lists.

## [1.24.0] - 2026-11-19

Asked for by the owner for D'thorga Companion (19 November 2026): progress bars with status updates wherever they fit, and a code viewer showing the code behind any changelog entry, for every game they mod and not only RimWorld.

### Added

- Progress lines: with PHOBOS_MODKIT_PROGRESS=1 a command writes one JSON line a step to standard error (label, step and of when it can count, detail for a line of the work's own output). Standard output is untouched, and without the variable nothing changes. installs (status, backup, restore, build, install), rimworld-textures (status, encode), rimworld-save and changes speak them.
- progress.run_streaming runs a repository's own command, passes its progress lines on and turns its ordinary output into details, so a build or an install can report each project and mod as it goes. installs build and install use it.
- changes list: every changelog in a repository with its newest versions and their entries. changes entry: the code behind one entry, as the commit that first wrote it into its changelog (found with git log -S) and that commit's diff, file by file with line numbers, code first; an entry in no commit yet shows the uncommitted changes. It names the other entries the same commit wrote. No game in it: checked on RimWorld, Ostranauts, Project Zomboid and Kenshi repositories.
- The manifest's surface gains changes; installs.parse_changelog keeps each version's heading text (headings).

### Compatibility

- Nothing changes for a caller that does not set the variable. A changelog needs no new markup for changes to read it.

## [1.23.0] - 2026-11-18

The third tool the owner wanted that day (18 November 2026): a watch on the mods we tie into, so a change to a method we patch is found on purpose rather than by chance. Vehicle Framework's upgrade research check (VF-412) had been noticed by hand; this finds it, and twelve more like it, in 34 seconds.

### Added

- rimworld-upstream: every member our C# names on another author's type (the scan rimworld-targets checks), against two sources. updates compares the newest two versions rimworld-archive kept of each file updated in the last --days, member by member, through the code tool's compare, and lists those it changed, gave a new signature or removed. pending reads the source clones rimworld-sources made and lists commits since --days ago whose hunks change one of those members, a warning before the Workshop build carries them. Both name the line of ours that depends on the member.

### Changed

- The commit guard's guide says what it cannot pass: a commit that stages only part of a file, since the gate checked the whole file.

## [1.22.0] - 2026-11-18

The owner's go-ahead for two of the tools proposed that day (18 November 2026): readers for a game that hangs, holds too much memory or crashes, and a guard that refuses a commit the gate has not passed. A gate piped through tail had once lost its exit code and let a broken commit in.

### Added

- rimworld-perf stack: a few snapshots of every thread's stack in the running game (Microsoft's dotnet-stack), a moment apart. It finds the thread running the game's loop, says whether it moved between snapshots and which frames never did, names the part of the loop and the innermost mod on its stack, and lists other threads with game or mod code on them. stack-report reads them again.
- rimworld-perf heap: what the game's managed heap holds, by type and by the mod each type belongs to (Microsoft's dotnet-gcdump, which forces a full garbage collection first). A .NET collection whose generic arguments name a mod's type counts for that mod. heap-report reads one again; heap-compare sets two side by side, who grew and which types. The .gcdump file is kept for PerfView or Visual Studio.
- crash-dump names the methods in a dump that holds the full memory of a .NET program: the loop's return addresses, the calls beyond it and those where the stack ran out, through Microsoft's dotnet-dump, with each method's assembly. --no-names skips it. Checked on a stack overflow of a small test program: it named the same method and caller as .NET's own error output.
- windows-dumps: whether Windows keeps full crash dumps of one program, the PowerShell lines that ask it to, and --apply or --off to do it from an administrator window. Only that program's own key is written.
- The gate's commit guard: a full passing run (no --only or --skip) notes, in the repository's .git folder, the content of every changed file it saw unchanged from start to end; gate --verify-staged, run from a pre-commit hook, refuses a commit whose staged files no single passing run saw exactly so. A failing run, a narrowed run or an edit after the pass is refused; another session's failing run leaves an earlier pass standing.
- dotnet_diagnostics installs and runs dotnet-stack, dotnet-gcdump and dotnet-dump beside dotnet-trace and dotnet-counters, each at the pinned version and only when first needed; dotnet_snapshots reads their text.

### Fixed

- crash-dump read the wrong bytes as the stack in a dump .NET writes itself (createdump): its thread record points to no stack, which is kept in the full memory list instead. It now looks there, and a stack overflow's loop is found.
- A test of installs status could fail by timing: two files of the same size written in the same clock tick were taken for the same file. The test now gives them different times.

### Changed

- The kit's rules allow one more writer, for Windows' crash dump setting only: windows-dumps --apply and --off write the one LocalDumps key of the program named, on request, from an administrator window.

## [1.21.0] - 2026-11-18

The owner's four asks for D'thorga Companion's Mods page (18 November 2026): compile as needed, refresh after, see before and after ahead of a compile, and know whether textures need encoding before the next launch, Workshop mods included. Their picks: check and fix textures, a build button plus installing everything that changed, all four before-and-after extras, and a "before you play" strip.

### Added

- rimworld-textures status: every active mod's encoded textures against its pictures. Stale (the game would show the old picture, since it loads a .dds instead of the .png beside it without comparing dates), never encoded, and left over. About 3 seconds for 342 mods.
- rimworld-textures encode: RimSort's own todds preset on the named mods, Workshop ones included (owner's choice), refused while the game runs; each mod is checked again afterwards. The preset moved here from phobos-rimworld's deploy.py, so both use one copy.
- installs status, for each mod: the files installing would add, change or remove, by kind; whether its C# projects need a build; the installed commit (the record's, or the one that first set its version); its settings changes since then, from the repository's own command; and the test rows the install would bring.
- installs build runs the repository's build command, which writes only inside the repository, so it does not wait for the game to close. installs install takes --mod more than once, for one run and one restart.
- installs.json keys: installOnly, build (projects, modProperty, shared, command) and settingsChanges.

### Changed

- The kit's rules allow one more writer, for textures only: encode writes .dds files into the mod folders it is named, never deletes, and never runs while the game does.
- The status summary says "1 mod", not "1 mods".

### Compatibility

- installs install's JSON names its mods under mods (a list) instead of mod.

## [1.20.0] - 2026-11-18

Asked for by the owner for D'thorga Companion (18 November 2026): a part of it for updating, going back and backups, starting with a live view of what each change to the changelogs would give them or take away. This is the install helper the kit's rules have named since 1.0.0, and the first step of moving deploy.py's install pattern here (docs/migration.md).

### Added

- installs status: each of a repository's mods, its installed copy, the repository's copy and every backup, with what moving to the repository or to each backup gains, loses or rewords, read from the changelog each copy carries. An entry is matched by its text wherever it sits, so one that moved from Unreleased into a version is neither gained nor lost. Entries under Save compatibility are listed apart. Backups' sizes, free space on both drives and whether the game is running come with it.
- installs backup copies an installed mod into the backups folder. installs restore puts a backup back: the replaced install becomes a backup first and the backup is kept, the swap is two renames on the game's drive, and it refuses while the game runs or while something holds the folder open. installs install runs the repository's own install command. Each refuses rather than leave a drive with less than 1 GB free.
- The install record (InstallRecord.json): the commit, the time and any uncommitted files a copy was installed from, written by the repository's install and read by status. installs.record_for and write_record make it.
- A repository opts in with config/installs.json (docs/installs.md). RimWorld's adapter: games/rimworld/installs.py.

### Compatibility

- Read-only unless backup, restore or install is asked for; manifest effects say which (writes, runs). Backups use deploy.py's names, so cleanup's install-backup rule still covers them.

## [1.19.1] - 2026-11-18

Found on the first run against phobos-rimworld's test list: four rows still said "seen working" from notes that, judged by the new evidence, no longer stand for them (an engine stop on a thrown-track row, a 0 W grid draw, a warning from before its row changed).

### Fixed

- apply takes back its own "seen working, awaiting the owner's word" sentence when no note read stands for the row any more. Never when the row has a verdict, and never when no notes were read at all, so a missing or moved notes file takes nothing back.
- The report says "1 kind", not "1 kinds".

## [1.19.0] - 2026-11-18

Asked for by the owner in phobos-rimworld (18 November 2026, its design record "Seen-in-play checks"): two faults sat in the seen-in-play notes and only a reading by eye found them, a grid hook-up noted at 0 W on a row expecting about a kilowatt, and a refusal with no warning before it.

### Added

- test-pass reads optional note fields: what a note was seen on (on), its kind, its case (variant) and its figures (values). Every note is kept, not only the last of each key.
- Evidence that judges: a row in named parts; a piece of evidence narrowed by a case or a wildcard on the detail; expected figures (>= N, > N, <= N, < N, = N, A..B). A part whose notes never show the figures is listed as seen but off, and does not mark its row seen.
- Order rules: a note that must come before another on the same thing, such as a warning before a refusal. Each break is listed with the thing and the time.
- Sightings older than the row: versionNames says how each mod is written in the rows, and a note from an older version than the newest the row names is listed apart.
- How widely a row was seen: the kinds of thing its notes came from.
- The owner's decisions on notes no row names, read from D'thorga Companion's folder (test-key-decisions, or --decisions): no row needed leaves a key out, make a row lists it as a request.
- testpass.map_problems: a key with nothing narrowing it that stands for several rows without a shared entry. testpass.mapped_keys: every key the map names, in any form.
- --json: each row's parts with their state, figures and staleness, its kinds, the versions it names and its order problems; and the whole map's order problems, notes no row names and map problems.

### Changed

- apply's seen sentence names the parts seen ("2 of 3 parts (wet brakes, air filter)"), and is written again when more parts are seen.

### Compatibility

- Every existing evidence map, note and verdict reads as before: a list of keys is one part, and a note without the new fields is a sighting with no figures, which cannot meet an expectation or be checked for order.

## [1.18.0] - 2026-11-18

The owner's first clones (19 repositories, 59 MB on K:) showed five that hold built files only: Dubs Bad Hygiene, Rimatomics, Rimefeller, Medical System Expansion 2 and Frontline Workshop.

### Added

- rimworld-sources --clone-into: each clone's C# file count, read from the repository's file list, and a note when there is none: decompile for code, and read its history for what changed and when.

## [1.17.0] - 2026-11-18

Asked for by the owner in phobos-rimworld (18 November 2026): clone the confirmed repositories, watch what they cost as they grow, and ask before anything is deleted.

### Added

- rimworld-sources --clone-into DIR: a lean clone of each confirmed repository (whole history, but only source and project files checked out and fetched), --update-clones to move them forward without ever discarding work, and a report of each clone's size, their total against a budget and the drive's free space. When the drive is short (under 10 GB or 3% free, both adjustable) no new clone is made; when it is short or the budget is passed, the report asks for a decision and lists the choices. The tool never deletes.
- source_clones: the game-free clones and the storage watch behind it.

### Fixed

- rimworld-sources: a register entry missing a field no longer stops the report.

## [1.16.0] - 2026-11-18

Asked for by the owner in phobos-rimworld (18 November 2026), beside its new rule to read a mod's public repository before decompiling it.

### Added

- rimworld-sources: where the public source of each mod a project ties into lives. Candidates come from the mod's About.xml, then its Workshop page, then a GitHub search by name, cheapest first; one counts only when an About.xml in the repository names the mod's package ID, so links to another mod (the Harmony mod's, most often) are ruled out by the check. With --write it keeps a register in the project (config/source-repos.json) that later runs reuse. On the owner's 54 tied mods: 19 confirmed, 22 with only unconfirmed candidates, 13 with none.
- github: a keyless, paced client with a week's cache in the kit's cache folder, for repository facts, file lists, raw files and searches. It stops at GitHub's limit for clients that do not log in and says when to run again.

### Changed

- rimworld-archive: the tie-ins it watches come from one function the source finder shares.

## [1.15.0] - 2026-11-18

Asked for by the owner in phobos-rimworld (18 November 2026): that day's game update could not be compared with the build before it, because Steam had replaced the file and nothing had kept it.

### Added

- rimworld-archive: keeps every version of the game's Assembly-CSharp.dll and of each active mod a project's own mods name (About.xml dependencies and load order, LoadFolders.xml IfModActive), each distinct file once and compressed, with an SQLite index of owner, file, version text and first-seen time. Reports snapshot, list, get and compare; compare hands two kept versions to code compare. Its folder is its own (PHOBOS_ASSEMBLY_ARCHIVE, assemblyArchivePath, else the user's local application data), never the cache, which defaults to a temp folder.
- The guide (docs/rimworld-archive.md) says how the owner can fetch a game build the archive never saw with SteamRE's DepotDownloader, which logs in with the owner's account and is never run by the kit.

## [1.14.0] - 2026-11-18

A tooling round asked for by the owner in phobos-rimworld (18 November 2026), for three gaps met that day: a part-pass written into the test list by hand, a profile that could not find the game loop, and a scratch script for heights.

### Added

- test-pass: a `partial` verdict, written "Passed in part", for a row of which only some has been seen; and `--verdict ROW:WORD[:NOTE]` on report and apply, for a verdict the owner gives an agent in conversation, written "in conversation" and replacing the file's for its row. Verdict lines may say `via`.
- rimworld-save terrain: how high the land stands and how rough it is; land heights and hilliness across the world, the player's places with their height, the steps between neighbouring land tiles, and with --near the heights in rings round a place.
- rimworld-perf: the alerts column, sound and music, and the engine's own frame drawing are named parts of the loop.

### Fixed

- rimworld-perf: Harmony 3's names for rewritten methods (`Type.Method_PatchN` and its `Glue:AbiFixup` glue) read as the original method, so a patched game loop is found. The owner's recording of 18 November 2026 had put two thirds of the main thread outside every named part; it now names all but 2%. Recordings already indexed are read the new way.

## [1.13.1] - 2026-11-17

The first recording of the owner's game (3 minutes, many wounded) put 95.6% of ticking down to Smart Medicine, when Search and Rescue was calling it in a scoring loop; the headline named the mod doing the work, not the one deciding how often.

### Fixed

- rimworld-perf report: a new table, one mod's code running another's, pairs the outermost mod on each stack with the innermost, so a mod that calls another in a loop is named beside it.
- The phase list and the guide say what the first recording of the game confirmed: the named parts matched 99.2% of the main thread, and every mod assembly with time was matched to its mod.

## [1.13.0] - 2026-11-17

In phobos-rimworld (17 November 2026) a slow game with many wounded pawns could only be answered by reading code, because nothing measured the running game. RimWorld 1.7 turned out to run on Microsoft's CoreCLR with its diagnostics pipe open, so Microsoft's own tools can record it from outside; the owner asked for a tool built on that.

### Added

- rimworld-perf record: attaches dotnet-trace and dotnet-counters (10.0.750501, installed into the kit's build folder on first use) to the running game for --seconds, indexes the trace with the owners of every module against the mod list of the day, and reports it. --label, --pid, --keep-speedscope.
- rimworld-perf report: the main thread by part of the game loop (ticking, drawing, interface, loading), who caused the time (the innermost mod on the stack), mods' busiest methods, where the thread was when sampled, game methods other mods patched, garbage collection and runtime counters, other busy threads, and time outside the named parts.
- rimworld-perf mod, compare (as shares of the main thread and of ticking), list, and index for a trace recorded by hand.
- The core reader of sampled stacks (sampling.py) and the diagnostics tools' runner (dotnet_diagnostics.py), with no game in them.
- A cache policy may give its own reason for the age rule (aged); rimworld-perf's says a recording cannot be made again.

### Changed

- AGENTS.md: in-game instrumentation stays Phobos Scope's; sampling a game from outside belongs here.

## [1.12.0] - 2026-11-17

In phobos-rimworld (17 November 2026) a one-off audit of stand-in art took two throwaway scripts and a hand check of every "mixed" result; the owner asked for it as a reusable tool.

### Added

- art-audit report: every shipped image paired with its records (its own name, the name before each underscore, or its folder's name) and classed by the record's first statement of how it was made, using the repository's patterns; images drawn in code, without a record, or with a record no rule recognises; generated images whose record calls them a stand-in; and pictures used by a Def that belong to another thing or are not ours, open or accepted with a reason. --mod, --kind, --all, --json.
- art-audit check: exits 1 when an image has no record, for a repository's gate.
- The RimWorld adapter's art part: the names a texture answers to (facings, masks, folders), and every use in Defs (with list-item parts and ParentName inheritance), patch operations and C# literals.
- A repository's config/art-audit.json describes its images, records, kinds and accepted borrowings; docs/art-audit.md describes it.

## [1.11.0] - 2026-11-17

In phobos-rimworld (17 November 2026), a Workshop report gave an update date some hours old for a mod updated minutes before, while its first line said nothing was reused from the cache. Details, reused for a day, were never counted. The owner asked for it fixed. This entry followed the tagged commit, which went up without it.

### Added

- --details-max-age H for steam-workshop and rimworld-workshop: how long fetched details (update date, version tags, subscribers) stay fresh. Default 1 hour, since details cost one request per 100 items; --max-age (default 24) now covers comments and collections only.

### Fixed

- The first line of a report names what came from the cache: items' details with the age of the oldest, and comment pages or collections, and says --refresh gives the newest. It used to count reused comments only, so a report built on old details looked freshly fetched.

## [1.10.0] - 2026-11-17

A crash in phobos-rimworld (17 November 2026) was fixed with a patch whose target is named as a "Type:Member" string, and its parameters had to be checked against Combat Extended by hand: the target check read neither. The owner asked for the gap closed.

### Added

- rimworld-targets reads Harmony's "Namespace.Type:Member" names in AccessTools lookups, and types found by name with a fixed name (AccessTools.TypeByName, Type.GetType, the game's GenTypes.GetTypeInAnyAssembly, and a project's own lookups given with --type-lookup), directly or through a variable every assignment in its file sets to the same type. String constants count, joined with +, from the file itself or as Class.Name from any file scanned.
- A patch class's TargetMethod whose body names one member gives the class that target, so its parameters are checked too.
- Patch parameters Harmony matches by name with the original's (every name in a prefix, postfix or finalizer but Harmony's own) are checked against the original's parameter names; a name the original lacks fails, with the names it has. The assembly reader's member listing now gives each method's parameterNames.

### Fixed

- A typeof that a call follows, as in typeof(X<>).MakeGenericType(...), is no longer read as the type X.

## [1.9.0] - 2026-11-17

The owner sees in-game tests pass but the news rarely reaches the test list, and asked for the checklist to live in D'thorga Companion (phobos-rimworld, 17 November 2026).

### Added

- test-pass report: a repository's in-game test list (named by its config/test-evidence.json), the rows waiting for the owner, the rows the game has seen working, and verdicts not yet written; --json gives every row's cells, sightings and verdict for a program to show. test-pass apply writes each verdict into its row, and "seen working, awaiting the owner's word" for a row the notes flag that has no verdict; a preview without --apply, and it writes only inside the test list.
- The seen-in-play notes file and the owner's verdicts file, both JSON lines, described in docs/test-pass.md. A note never passes a row; only a verdict does. Verdicts default to D'thorga Companion's own folder, one file per repository.
- rimworld paths: seen_in_play_path, where D'thorga Framework 0.118.0 writes its notes (PhobosSnapshots/SeenInPlay.jsonl beside the Config folder).

## [1.8.0] - 2026-11-11

The owner asked for a cleanup of every temporary file the RimWorld work had left, and for the tool to live here (phobos-rimworld, 11 November 2026).

### Added

- cleanup: lists what the kit's tools and a repository's builds and tests left behind, with sizes and the reason each may go, and deletes it only with --apply. It covers the kit's cache (a file a tool says is stale, anything unchanged for 14 days, frozen copies a stopped run left), the kit's development build (never the release programs the tools run, and never while cargo or rustc runs), the folders and patterns a repository names in config/cleanup.json, and git's file-watcher daemons. docs/cleanup.md describes the rules file.
- A command may declare CACHE_POLICIES for its cache folders: a stale test, or a reason to keep the folder. rimworld-save's index is stale once its save has been saved again or has gone; the Workshop cache is always kept, its pages being slow to fetch.

## [1.7.0] - 2026-11-10

The owner asked for the atlas in D'thorga Companion: the whole world map, with biomes, settlements, pollution, climate and terrain views, roads and rivers (phobos-rimworld, 10 November 2026).

### Added

- rimworld-save atlas: every surface tile of a save's world as a globe a program can draw, with its biome, elevation, temperature, rainfall, hills, swampiness, pollution, named region and landscape features; settlements and other world objects grouped by how their faction stands with the player; roads, rivers and the game's region labels. Tables list biomes, places with latitude and longitude, named regions, and roads and rivers.
- A globe block in the report model: tile positions, each tile's neighbours in order round it, layers of one value per tile, places, lines, tags and labels, with arrays as base64 in JSON. docs/manifest.md describes it.
- The save index holds the surface layer's per-tile arrays, the world's named regions, and how each faction stands with the others.
- The manifest's surface field names a report that is mostly a picture (globe for the atlas), so a program can give it a page of its own.
- Biome colours and road and river widths in a data file (atlas-palette.json), agent-authored for the owner to revise.

### Changed

- The planet model keeps each tile's neighbours in order round it as well, and gives a tile's outline, longitude and latitude as the game reckons them. Its cache rebuilds once.

### Fixed

- The planet model kept each tile's neighbours in an order of its own, not the game's. Saves name a road's or river's other end by its place in that list, so the model would have put every road and river piece on the wrong neighbour; no report read them before the atlas. Now in the game's order: on the owner's save, river pieces join into 233 river systems and road pieces into 33 networks, where the wrong order scattered them into thousands of scraps. The planet's cache rebuilds once.

### Notes

- The planet's orientation is settled from the game's code: it builds the world from the same icosahedron and never rotates it, so no in-game reading is needed.

## [1.6.0] - 2026-11-10

The owner said yes to naming the half of mood a save leaves out, to suggested fixes labelled as advice, and to colonists, slaves and prisoners together (10 November 2026).

### Added

- rimworld-save mood reads the colony mood file D'thorga Framework writes at each save, when its tick count and world seed match the save: every thought as the game counted it, bedrooms, pain, cold and beliefs included, with each pawn's own break thresholds. A file from another save, or of another shape, is said and set aside. --mood-file names one; --no-mood-file ignores it.
- Where to start: the costliest causes a player can do something about, each with a suggestion. Needs running low and one pawn's thoughts carry advice too. The suggestions are ours, kept in a data file anyone can add to, and always labelled as advice.
- The save index records the world's seed.

## [1.5.1] - 2026-11-10

### Fixed

- rimworld-save mood: the charts of what hurts and helps most have titles of their own, instead of repeating their section's heading (seen in D'thorga Companion).

## [1.5.0] - 2026-11-10

The owner's colony showed "Extreme break risk x29" and they asked to see where it was lacking mood-wise, in D'thorga Companion (phobos-rimworld, 10 November 2026). They also asked for graphs.

### Added

- rimworld-save mood: each pawn's mood against its own break thresholds, the remembered events that cost the colony most and help it most, needs running low, and addictions and drug needs. --pawn gives one pawn in full; --who narrows it to colonists, slaves or prisoners.
- It counts remembered events by the game's own rules (stage, strength, fading, stacking, trait cancelling) from the Defs as patched where a patched-Defs file exists, else as written, and says plainly that situational thoughts are not in a save. What they cost comes as one figure, mood minus the remembered events.
- The save index gains need and memory tables, and each pawn's prisoner or slave status.
- A chart block in the report model: bars or lines, with series and reference lines that carry a meaning (risk, success and so on), never a colour. Markdown shows text bars; JSON carries the chart for a program to draw.
- The patched-Defs file is found by default where D'thorga Framework writes it, beside the Config folder.

### Fixed

- A need whose level is 0 is left out of the save by the game; the mood report reads that as 0, not as unknown.

## [1.4.0] - 2026-11-09

A game died with a stack overflow and nothing in its log, and reading its crash dump took a debugger, a downloaded tool and a hand-written script (phobos-rimworld, 9 November 2026).

### Added

- crash-dump: reads a Windows minidump with no debugger or symbols. It names the exception and the thread, finds a call loop that ran away (how big one level is, how often it repeats, and whether every level held the same objects), and says which modules the stack points at.
- It says what a small dump cannot tell, and for a .NET stack overflow how to get the method names next time.

## [1.3.0] - 2026-11-09

What changed between two builds of an assembly could not be answered well by the metadata tools tried: one read nearly every method of a small rebuild as changed, and could not read a game's main assembly at all (phobos-rimworld, 9 November 2026).

### Added

- code compare OLD NEW: what changed between two builds, declaration by declaration. Each side is a .dll, an indexed corpus, or a folder of C#. It lists what was added and removed, new signatures, and new bodies with lines changed, marking a change that touches only strings or numbers as values only; a new type is one row. --only narrows it by name and --show prints one declaration's changes as a diff.
- A .dll is decompiled once with ilspycmd, named by --decompiler, PHOBOS_MODKIT_ILSPYCMD, ilspycmdPath or the PATH, and kept in the kit's cache by its bytes and --reference folders; the 12 most recently used are kept. ilspycmd reads the file without loading or running it.
- A side with no declarations is an error, never a list of removals, and two sides with nothing in common are called out.

## [1.2.0] - 2026-11-09

Which vehicle types other mods already provide could not be answered without reading a Steam collection, and Steam's item pages refuse automated fetches while its keyless APIs do not (phobos-rimworld, 9 November 2026).

### Added

- steam-workshop and rimworld-workshop collection: a Steam collection's items by ID or URL, in the collection's order, with each item's update date, declared versions, whether it declares the game's version, and the opening of its description with the BBCode stripped; --grep keeps the items whose title or description match (* and ? wildcards). One request per 100 collections and one per 100 items; no comments are fetched. A collection Steam does not return is named as such.
- The cache keeps each item's description (column description) and each collection's members (table collection), so sql can ask across them. Caches made before this version gain the column on first use.


A program showing the kit's reports needs to sort numbers as numbers, and to name a report as a person would ask for it (owner, 9 November 2026).

### Added

- Every table in a report's JSON now has values: the number each cell sorts by, so 12.5% sorts as a number. A column that isn't all numbers in one unit has none.
- A report in the manifest can carry a question: the report as a person would ask for it. The RimWorld reports that need nothing typed have theirs.

## [1.0.0] - 2026-11-09

A desktop program over the tools needs to read every command the same way, and to know what each one does before it runs it (owner, 9 November 2026).

### Changed

- **Incompatible: every command's --json now prints one envelope**: envelope, tool, kit_version, report and data. What consumers must change: the report that was at the top level (release, gate, code, steam-publish, rimworld-patches, rimworld-readiness, rimworld-settings, rimworld-startup, rimworld-targets) is now under report; the save, index and built fields of rimworld-save and rimworld-defs are now under data; rimworld-log's JSON is now under data, beside its summary report. Nothing in phobos-rimworld reads this output.
- The command table moved to commands.py, and the dispatcher imports each command's module by name.

### Added

- manifest: every command, its reports and options read from its own parser, and what each report reads or changes (reads, reads-online, writes, runs, owner-only). See docs/manifest.md.

## [0.19.0] - 2026-11-09

Why a world tile is polluted could not be answered from a save without reading the file by hand (owner, 9 November 2026).

### Added

- rimworld-save planet: pollution on the world map from the save's planet layer, by band and as patches of touching tiles with what stands on or nearest each, rings of tiles around a named place or tile (--near, --hops), what changed against another save (--compare), and every save of the same world by in-game day (--history, read straight from the saves without indexing them).
- The save index holds the planet's pollution layer (table planet_grid).
- A planet's tile centres and neighbours are rebuilt from a model of its shape and cached by subdivision count; a world generated with less than full coverage is reported as such and its tiles are not placed.

## [0.18.0] - 2026-11-09

The compiler checks typeof and nameof; nothing checked the names C# holds in strings (owner, 9 November 2026).

### Added

- rimworld-targets: every Harmony patch and reflected lookup in a source tree, and the parameters Harmony fills at run time, checked against the game's and active mods' assemblies as metadata. Exit 1 when a name no longer matches.
- The assembly reader's members command: the fields, methods and properties of named types and their base types.

## [0.17.0] - 2026-11-08

Two tools from the planned list (owner, 8 November 2026).

### Added

- rimworld-startup: every recorded launch from Loading Progress's StartupImpact sessions, the costliest mods and slowest stages over the launches with the newest mod list, a comparison of any two launches, and one mod across them.
- rimworld-readiness: per active mod, the versions its About.xml and Steam tags declare, its Harmony transpilers, and byte scans for Prepatcher and asset bundles, riskiest first, with what changed since the last run. It says what a mod declares and how closely it depends on the game, not whether it works.

## [0.16.0] - 2026-11-08

The patched view becomes the first place to look (owner, 8 November 2026), so it has to say when it cannot be trusted.

### Added

- rimworld-defs patched says when the file may be out of date: a different count of active mods or game version, a mod list or Workshop manifest saved after it, or XML changed after it in the game's Mods folder, naming those folders.
- rimworld-defs who and show take --dump and add one line pointing at the patched report when the file exists.

### Fixed

- The Workshop publishing and release history tests set core.fsmonitor false in their test repositories. They had passed it only on their own git calls, so the plain git status in the code under test started a watcher for each test repository that never exited, and one could hang the test run.

### Changed

- README: the opening list names all ten built tools and says the Harmony patch reader needs the .NET SDK.

## [0.15.0] - 2026-11-09

The resolved-Defs half of the plan's shared frameworks, at the owner's go-ahead (9 November 2026): a Def with every
patch applied, which no file on disk holds.

### Added

- rimworld-defs patched NAME: the Def with every mod's XML patches applied (before inheritance), from a patched-Defs file a running game wrote, and a diff against the kept definition as written. A Def only a patch adds, and one the patches leave alone, each say so. The file is indexed in the cache by streaming, again whenever it changes, and is named by --dump, RIMWORLD_PATCHED_DEFS or the rimworldPatchedDefsPath setting.
- docs/rimworld-defs.md: what such a file holds and how phobos-rimworld's D'thorga Framework writes one; 2 tests on a hand-written file.

## [0.14.0] - 2026-11-09

The plan's tool 4, the assembly metadata reader, at the owner's request (9 November 2026). On the owner's 254 active mods:
5,356 Harmony patches in 333 assemblies, read in 6 seconds.

### Added

- rimworld-patches: which active mods patch a method (who, with wildcards on the member and type), what one mod patches (mod), and methods several mods patch (hotspots), each patch with its kind, its patch method, its priority, and whether a prefix returning bool may stop the original. Only the assemblies the game loads are read (each active mod's load folders for the game's version), and only ones that changed since last time.
- PhobosModKit.Assemblies (C#, dotnet/): reads assemblies through System.Reflection.Metadata, never loading them. Finds [HarmonyPatch] classes (merged as Harmony merges class and method attributes, with MethodType, argument types and HarmonyPriority), the targets a TargetMethod's code names through AccessTools, and harmony.Patch calls read from the IL. Its build goes to the kit's build folder, outside the repository.
- docs/rimworld-patches.md; a made-up mod assembly in C# source (fixtures/dotnet/PatchFixture) and 4 tests that build and read it.

### Changed

- CI installs .NET 10 so the reader's tests run, as the Rust tools' do.

## [0.13.1] - 2026-11-09

### Fixed

- code outline: line numbers print plainly (8765, not 8,765), as a file:line reads them.

## [0.13.0] - 2026-11-09

At the owner's request (9 November 2026) for tools that keep agent sessions lean: research into a mod's code used to
mean agents searching hundreds of thousands of decompiled lines. On the owner's 54 trees (about 330,000 declarations)
the first index took 34 seconds; a query then takes under a second.

### Added

- code: indexes C# source trees (decompiled assemblies kept on the researcher's machine, a project's own source) into the cache, and answers find (declarations by name, with wildcards and kinds), outline (a type's members with their lines), show (a member's source by bare, dotted or full name, numbered, every overload, decompiler notes hidden) and refs (every line using a name, grouped by the member holding it). Indexes rebuild when a tree's files change.
- The scanner blanks comments and every kind of string first (verbatim, interpolated with quotes nested in their holes, raw) and reads attributes with braces, default parameters with casts, tuple types, expression bodies and file-scoped namespaces; on the owner's trees it misses about two declarations in 100,000.
- docs/code.md; 6 tests on made-up C#.

## [0.12.0] - 2026-11-09

At the owner's request (9 November 2026) for a tool that captures the settings they play with, to help work out what
causes an error. Run on the owner's Config folder: 154 settings files, 118 of them for active mods, 36 left by mods no
longer active (among them five of phobos-rimworld's, merged on 7 November).

### Added

- rimworld-settings: which mod each settings file belongs to and whether it is active; the values of chosen mods (name, package ID or folder, with wildcards); files left by removed, merged or renamed mods; snapshot and compare. A defaults file from the mod's own source shows each value beside its default, the keys left at default, keys no longer read, and defaults that disagree between a field's starting value and the one a missing key loads as.
- docs/rimworld-settings.md: why a file lists only what the player changed (RimWorld writes nothing for a value at its default), and how files are matched to mods (class names may hold underscores, as Vanilla Expanded Framework's do).
- 7 tests on a made-up install.

## [0.11.0] - 2026-11-09

At the owner's request (9 November 2026) for tools that keep agent sessions lean: one command for every check before a
commit, printing only what failed.

### Added

- gate: runs a repository's checks from its config/gate.json in stages and lanes (steps sharing a lane in order, lanes side by side), repeats a step for every file a glob finds, skips a step whose program is missing and says so, stops later stages when one fails, and keeps a failed step's full output in the cache. Parsers for MSBuild, dotnet test, unittest and cargo keep the errors, failed tests and counts and drop the rest; a passing run prints three lines.
- This repository's own config/gate.json, the list of checks in AGENTS.md.
- docs/gate.md; 11 tests on hand-written tool output and a made-up repository.

## [0.10.1] - 2026-11-09

### Fixed

- release changelog and steam-publish notes: a # inside a line is text again (C#, issue #12); only a line that starts with # is refused, as a stray Markdown heading. phobos-rimworld's changelogs failed on "C# assembly".
- A formatting refusal now names what it found (a backtick, a pipe, # at the start, a numbered list), instead of only quoting the line.

## [0.10.0] - 2026-11-08

At the owner's request (8 November 2026): phobos-ostranauts' Steam Workshop and release tools, made generic and
moved here. Read-only checks against phobos-ostranauts gave the same results as its own scripts: release notes for
444 changelog entries byte for byte, due updates, combined change notes, change-note worksheets, pull findings and
149 constants. Not yet used for a real upload from the kit.

### Added

- steam-publish notes: each changelog entry as a Steam change note in BBCode, written beside the Workshop page; checks the page's title, version and publication status lines, its size and its text; --base refuses content changed without changelog and page edits.
- steam-publish status, pending, prepare and verify: publication order, blockers and sizes; which items have a newer version than the one uploaded; a hashed candidate staged offline in the kit's cache, with a change note covering every version since the last upload, cut to Steam's limit.
- steam-publish upload and update, run by the owner only: SteamCMD takes the login in its own prompt, so the tool never sees a password. New items are created Private; going public needs committed work and --confirm-public; a receipt is written before SteamCMD starts; an update with nothing new does nothing; a create with no returned ID must be reconciled before another. update builds, prepares and updates every due item, dependencies first.
- steam-publish reconcile, pull and change-notes: settle an uncertain upload; bring an item's live visibility, page and release date back from Steam's public API; worksheets for tidying an item's Change Notes tab by hand.
- Game adapters for publishing: RimWorld reads About.xml and keeps About/PublishedFileId.txt in step with the catalogue, and reminds the owner that SteamCMD sets no tags (a Ludeon forum report, not checked against Valve's documentation); Ostranauts reads mod_info.json. A repository may pass its own package checks as a payload hook.
- release changelog: checks changelogs in the Phobos form, including whether every entry fits the store-page text.
- release constants: keeps every registered copy of a version or figure in step, checking all of them before writing any, with read-back and rollback.
- release history: screens every file in a repository's history for credentials, personal paths and refused file types before it goes public.
- Shared modules: phobos_modkit.files (link refusal, tree reads, atomic writes), phobos_modkit.steam.bbcode and phobos_modkit.steam.vdf. The Workshop item model keeps an item's description in memory (not cached).
- 33 tests on made-up repositories, with stand-ins for SteamCMD and Steam's API.

### Changed

- AGENTS.md, README and project direction: the owner-run uploader is the one exception to the read-only Steam rule. Agents, tests and CI never run a real upload.
- Hard-wrapped bullets and paragraphs in a changelog now join, as Markdown reads them, and a heading ending in history after the releases closes the log (mods merged into another keep their old logs there). The Ostranauts scripts refused indented lines.

### Fixed

- Constants: a JSON pointer to a string value now edits inside its quotes; the Ostranauts copy captured the quotes and could not match a string.

### Compatibility and limits

- Moving phobos-ostranauts onto the kit needs layout entries in its catalogue and its package checks as a payload hook; docs/migration.md lists every difference. phobos-rimworld adopts publishing when its first mod reaches its public beta gate.
- Not moved: the Workshop cover composer (Ostranauts' art, and it needs Pillow) and Ostranauts' documentation packager.

## [0.9.0] - 2026-11-09

### Added

- rimworld-defs show --lines N: how many XML lines each Def and parent shows before it is cut (default 80, as before; 0 shows every line). A long VehicleDef's parts list was cut off at 80 lines with no way to see the rest (phobos-rimworld, 9 November 2026). The cut line now names the option.

## [0.8.0] - 2026-11-08

### Added

- rimworld-save world --id: one world object's values in full, such as an aircraft's flight path and destination or a site's parts. The save schema gains the world_object_value table and world_object_value_view.

### Changed

- The save schema changed, so indexes rebuild on their next use (about 70,000 more rows on the owner's save).

## [0.7.0] - 2026-11-08

### Added

- rimworld-save world: world objects (settlements, sites, caravans) counted by def and faction, or listed with ID, name, faction and tile.
- rimworld-save components: the game's, the world's and each map's components with their value counts, or every value with text inside them with its path in the component, so a mod's saved state (a diplomacy mod's wars and battles, for example) can be read without opening the save.
- rimworld-save diff now lists world objects that changed faction, appeared or went (by ID), component values that changed and component lists that grew or shrank; --component narrows those sections to matching component classes.
- The RimWorld save schema gains the world_object, component and component_value tables and the world_object_view and component_view views. 3 new tests and a larger fixture save.

### Changed

- The save schema changed, so indexes rebuild on their next use. An index is larger and slower to build: about 1.1 million more rows and 3.5 s instead of about 2 s on the owner's 11-million-element save.

### Compatibility and limits

- Component values are matched between saves by class, map position and path, so items of a list are compared only by count. State a mod keeps outside components is not covered.

### Changed

- AGENTS.md now holds the rules learned while building the first tools: run every check before a commit and gate the commit on their exit codes; a version bump changes the package, Cargo.toml and Cargo.lock together, and pushed tags are never moved; set CARGO_TARGET_DIR outside the repository when developing; a tool's first change in a consumer adds that consumer's AGENTS.md rule; report filters go through phobos_modkit.query. CONTRIBUTING.md says how to run the checks. Documents only; no tool changed.

## [0.6.0] - 2026-11-07

### Added

- rimworld-save grid: a map's layers counted (terrain, foundations, roofs, each gas, fog, snow, pollution, deep resources), one layer in full with a text picture, or every layer at one cell with the things standing there; --area limits the counts to a rectangle. Grids are decoded as the 1.7 game code writes them, and Defs are named through the Def index; a 325 by 325 map's ten grids decode in 0.02 s.
- rimworld-save diff: what changed since another save, matched by thing ID and hediff load ID: counts, things that appeared and went by def, stacks that grew or shrank, pawns that moved, arrived or left, and pawns' hediffs gained, lost, worse or better (the player's by default).
- The Def index now adds the Defs the game makes in code for stone floors and carpets, with their source (333 on the owner's install), so terrain on the owner's maps is named for 98 to 99 percent of cells instead of 70. show says such a Def has no XML of its own.
- xml-index: a column can hold an element's own tag or its parent's (tag = "self" or "parent"). The RimWorld schema gains a map_grid table.
- 19 Python tests for grids, hashing, comparison and game-made Defs, and 3 Rust tests.

### Changed

- The save index's schema and the Def index's format changed, so both rebuild on their next use.

### Compatibility and limits

- A Def's number follows the game's short-hash rule; when names tie, the game's string order is approximated and such names are marked (?). Defs from other generators (blueprints, frames, meat, corpses, techprints, mods' own) are not named.
- Sand depth, temperatures and terrain colours are not decoded yet.

## [0.5.0] - 2026-11-07

### Added

- Workshop research (python -m phobos_modkit steam-workshop and rimworld-workshop): report, details, comments and sql over a SQLite cache of Steam's public item details (batched 100 at a time) and each item's newest comments. Per item it gives the update date, declared versions, subscribers, comments in the last 90 days, the uploader's last reply and the newest comments that mention problems. Comment requests go 8 s apart and back off 150 s once after HTTP 429, then stop and say so; anything fetched in the last 24 hours is reused; --offline never contacts Steam.
- rimworld-workshop takes mods by name (with wildcards), package ID, Workshop ID or URL, flags comments that mention the game's version from ModsConfig.xml, and adds a versions report: every active Workshop mod that does not declare the game's version (about 10 s for 320 mods).
- 20 tests with a fake Steam and hand-written fixtures in Steam's markup.

### Compatibility and limits

- Items whose uploader's profile is private show no comments to visitors who are not signed in; the report names them with Steam's reason. Only the uploader's own replies are recognised, not other team members'.
- Checked against Steam on 7 November 2026.

## [0.4.0] - 2026-11-07

### Added

- RimWorld Def index (python -m phobos_modkit rimworld-defs): summary, mods, who, show, list, patches and sql reports over a SQLite index of every active mod's Defs and patch operations. It follows the game's load rules (ModsConfig order and the _steam suffix, LoadFolders.xml with IfModActive, IfModActiveAll and IfModNotActive, version-folder fallback, shadowed files, MayRequire and MayRequireAnyOf, abstract Defs) and marks which definition the game keeps when mods share a name: the later mod's, and the first inside one mod, as the 1.7 game code does. show prints a Def's XML with each parent up the chain, choosing parents as the game's XmlInheritance does: the same Name from the latest mod at or before the child's, with its MayRequire met.
- The index rebuilds itself when ModsConfig.xml, the Workshop manifest, the game's version file or any XML file in the game's Mods folder changes. 336 active mods (42,418 Defs, 15,208 patch operations) index in about 8 s; reports take about 0.3 s.
- phobos_modkit.query: the report filters (LIKE patterns with literal underscores, the WHERE builder, counts and capped rows), moved out of the save index so both tools share them. Config-folder setting rimworldConfigPath (RIMWORLD_CONFIG_PATH).
- 23 tests on a synthetic install covering every load rule and the parent rule.

### Compatibility and limits

- Defs are shown as written: other mods' patches are not applied. Patches are found under a Def's name only when their xpath names its defName. Subclass Def tags are kept apart from their base type.
- A Workshop file edited by hand, without Steam, is not noticed until --rebuild.

## [0.3.0] - 2026-11-07

### Added

- A shared report model (phobos_modkit.report): every tool builds a Report of paragraphs, bullets, tables and code blocks, rendered as Markdown or JSON, with redaction applied to every piece of text and table cut-offs stated. Log triage and the save index now use it; their Markdown is unchanged byte for byte (checked on the fixtures, the owner's live log with all 1,560 signature details, and 12 save reports on a real index).
- A shared derived-data cache (phobos_modkit.cache): the cache folder, provenance stamps and hashes, a staleness check over a SQLite meta table, frozen copies of files another program may be writing, and removal of read-only files. The save index now uses it.
- The convention that all derived data is SQLite with a meta table of provenance, written into AGENTS.md and the project direction, so later tools can be joined in one query.
- 23 tests for the report model and the cache.

### Changed

- rimworld-save --json now prints the shared report shape: each section holds typed blocks (text, bullets, table, code), so a table's headers are at sections[n].blocks[m].headers. Log triage's --json data export is unchanged.

### Fixed

- The version test added in 0.2.2 could not be loaded, so the v0.2.2 tag's test run fails. Tests only: the tools in v0.2.2 are unchanged and build and run correctly.
- The save index's command tests now find the indexer in its build folder outside the repository.

## [0.2.2] - 2026-11-07

### Fixed

- Cargo.lock now matches the crate's version. In 0.2.1 it still named 0.2.0, so every build with --locked (CI and --build-indexer) refused to start; **do not build v0.2.1**. A test now checks that the Python package, Cargo.toml and Cargo.lock name one version.

## [0.2.1] - 2026-11-07

### Fixed

- The Rust tools now build outside the repository by default (%LOCALAPPDATA%\phobos-modkit\target on Windows, ~/.cache/phobos-modkit/target elsewhere; PHOBOS_MODKIT_BUILD overrides it). A Rust build folder runs to hundreds of megabytes, and a repository or submodule in a cloud-synced folder would upload it. A build in the repository's own target folder is still found.

## [0.2.0] - 2026-11-07

### Added

- xml-index, a Rust program that reads a large XML file once and writes a SQLite index, driven by a schema file: tables from element-path patterns, columns from child text, attributes, sibling positions and enclosing rows, typed values, indexes and views, plus a census of every element path. A 308 MB RimWorld save (8.2 million elements) indexes in 1.4 s.
- RimWorld save index (python -m phobos_modkit rimworld-save): summary, schema, things, pawns, hediffs, find and sql reports over an index of a save, in Markdown or JSON. The RimWorld schema covers the game header, mods, factions, maps, things (with what holds each), pawns, hediffs, traits and skills, with views for where each thing is and for pawns' names and factions.
- Each index is built from a frozen copy of the save, deleted afterwards, and rebuilt when the save or the schema changes. Indexes live under the system's temp folder by default, away from cloud-synced folders.
- A shared Markdown table helper, the kit's cache-folder setting (modkitCachePath, PHOBOS_MODKIT_CACHE) and RimWorld's Saves-folder setting (rimworldSavesPath, RIMWORLD_SAVES_PATH).
- A hand-written fixture save, 6 Rust integration tests of the RimWorld schema, 19 Rust unit tests and 26 more Python tests; CI now checks Rust formatting and lints, runs the Rust tests and runs the Python tests with the program built.

### Dependencies

- The Rust build downloads quick-xml, rusqlite with SQLite bundled, serde and toml from crates.io; licences are in THIRD_PARTY_NOTICES.md.

### Compatibility and limits

- Checked against RimWorld 1.7.5000 saves. Mods' patches are not applied; the index holds def names, not labels, and body-part indexes, not part names.
- Comparing two saves and reading map grids (terrain, roofs, gas) are not built yet.

## [0.1.1] - 2026-11-07

### Fixed

- RimWorld log triage: when a save is loaded again with the same mods, its notice says so in one sentence instead of listing the same marked mods again (seen with three loads of one save in one session).

## [0.1.0] - 2026-11-07

### Added

- RimWorld log triage (python -m phobos_modkit rimworld-log). It groups a Player.log's messages into signatures, compares them with the previous run, groups signatures that share one exception, and names the mods each points at from clues in the log (source lines, file paths, assemblies and namespaces in traces, the calling code, Harmony patches). It also reports the save loaded and the mods the game marked, where the game stopped logging, engine memory warnings and Harmony finalizers. Output is a short Markdown summary or full JSON; one signature can be shown in full. The home folder is redacted by default.
- A game-free log core (signatures, grouping, comparison, clusters, rendering), a path resolver shared by every tool, and an installed-mod index for RimWorld that reads only About.xml and assembly file names.
- Hand-written fixtures, 71 tests run on Python 3.10, 3.12 and 3.14, and continuous integration on Windows and Linux.

### Compatibility and limits

- Checked against RimWorld 1.7.5000 logs (November 2026). The 1.6 layout is read in a basic way and has not been checked against a real 1.6 log.
- The Linux and macOS default folders are the usual Unity and Steam places and have not been checked.

## [0.0.0] - 2026-11-07

### Added

- The repository's design documents: the README, contributor rules, the project direction (three layers,
  languages, how consumers use it) and the migration list of scripts copied across the Phobos repositories.
  No tools yet.
