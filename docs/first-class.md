# First-class citizens: the things every tool and page treats as real

**Status (19 Nov 2026):** a design for the owner to edit, **not yet rules**. Written at the owner's request ("because we are
implementing such a large, shared, framework that spans multiple games and paradigms, we need to start thinking about ideologies
like first-class citizens"). Nothing here binds a session until the owner moves a principle into `rules/every-session.md` or
another rules file. It lived in `rules/` until 24 Nov 2026, when it moved here as the design it is (docs rewrite, step 7). The
history tool (kit 1.30.0) and D'thorga Companion's Timeline page are built on the first five citizens below; Setting is the
eleventh, added the same day with the central settings file. Agent-drafted throughout; every choice is the owner's to change.

## Read this first (gotchas)

- **A first-class citizen is a thing the tools and pages treat as real in its own right**, not as a string inside something else:
  it has an identity, can be pointed at, has a history, and looks the same in every game and every tool.
- **Identity is origin and continuity, never the label.** A mod renamed from Phobos to D'thorga is the same mod; an entry reworded
  is the same entry; a mod merged into another has ended, and its history lives on in the one that took it in. Labels are for
  people; identities are for tools and saves.
- **Name a citizen now; give it full support only when a page needs it.** The table below says how far each one is today. Building
  every citizen out at once would be a framework for its own sake, which the project's rules warn against.
- **Promote a principle here into a rule only on the owner's word.**

## What makes a thing first-class

A thing is first-class when it has all six:

| # | Property | What it means | Why it matters |
| --- | --- | --- | --- |
| 1 | **An identity, not a label** | Something that stays the same while its name, words or place change | Renames, rewordings and merges never break a link, a record or a save |
| 2 | **An address** | One way to point at it, the same in every tool: a path, a key, a hash, a pair | A page, a command, a log line and a rule can all name it, and mean the same thing |
| 3 | **A history of facts** | What happened to it, when, and from which source, kept or recoverable | "As it stood" questions can be answered at any moment, never lost to time |
| 4 | **The same shape in every game** | The same fields in RimWorld, Project Zomboid, Ostranauts, Kenshi; or words saying why not | The Companion and the tools work across games without a special case for each |
| 5 | **One shape in the tools and the window** | The kit's JSON and the Companion's page carry the same fields under the same names | Nothing is translated twice; a page never knows more than the tool says |
| 6 | **Rules can be about it** | A rule can name it ("every Change goes in the commit that made it") and a check can test that | The owner's rules can be enforced by tools, not only remembered |

## The citizens

| Citizen | Identity | Address | History from | Today |
| --- | --- | --- | --- | --- |
| **Change** (a changelog entry) | Its product, its version and its first words | changelog path + version + opening | git: added, reworded, removed; its commit | Full: `changes`, `history`, the Changes and Timeline pages |
| **Version** | Its product and its version number | product + version | git: written, released, removed | Full: `history`, `installs` |
| **Product** (a mod, a tool, the Companion) | Where it started: its first changelog, and the package ID it keeps | changelog path (+ package ID for a mod) | git: started, renamed, ended (merged into) | Partial: named by title today; a stable ID beside the label is still to come |
| **Install** (a copy of a product in a game) | The game, the product and when it was put there | game + mod folder + install record's time | The history log: installed, went back, backed up | Partial: from 19 Nov 2026 on; the record in each copy names its commit |
| **Event** (a fact) | Its kind, its time and its source; never changed once written | kind + time + source (+ commit) | It is history | Full: the history log and the facts from git |
| **Game** | A short ID (`rimworld`, `zomboid`, `ostranauts`, `kenshi`) | the ID | Its history log | Partial: named in each repository's installs config; a list of games is still to come |
| **Repository** | Its remote, then its folder name | the folder name | git | Partial: named in every fact; no list of them yet |
| **Commit** | Its hash | the hash | git | Full: git gives everything |
| **Rule** | Its file and heading; who decided it and when | `rules/<file>.md` + heading | git, and the "(owner, date)" beside it | Partial: `rules list` counts them; no rule has an ID of its own yet |
| **Test row** | Its row key in the repository's test list | repository + row key | The owner's verdicts and the notes seen in play | Partial: in phobos-rimworld only |
| **Setting** | Its key | the key | Not yet: where a value comes from is shown, but not when it changed | Partial: `settings`, the Settings page |

## Principles to edit

1. **Identity is origin and continuity, never the label** (agent-drafted, after the owner's view of identity as narrative: past
   selves stay valuable while new experiences reshape their meaning). A thing's identity is where it began and the unbroken line
   from there; its name is how people find it today. The repositories already follow this for saves (package IDs, defNames and
   saved keys never change; display names may). The principle carries it to everything the tools see.
2. **An ending is a fact, not a deletion.** A product merged into another, a version taken back, an entry removed: each is
   recorded as something that happened, with where it went where it went somewhere. Nothing a page once showed vanishes without a
   fact saying so.
3. **Facts are written once and never changed.** A correction is a new fact. A history that rewrites itself cannot be trusted to
   show what the owner saw at the time.
4. **One shape everywhere, or words why not.** Where a game cannot give a field (Ostranauts has no install record yet), the field
   is empty and the reason is written down, never filled with a guess.
5. **The window shows what the tools say.** A page never works out a citizen's identity or history for itself.

## What the timeline uses

The history tool and the Timeline page are built on **Change, Version, Product, Install and Event**: each fact is an Event, about a
Product (and usually a Version and its Changes), from git or from an Install on this PC. Adding a game means adding its history
log and its repositories, not a new kind of page.

## The central settings page

The owner asked for "a central settings page where everything or at least, most, of these sorts of things are managed" (19 Nov
2026). Its first version (Companion 0.14.0):

- **Lists every setting the tools read** (`settings list`): its value, and where that value comes from, in plain words (the
  default, the central file, this repository's own file, an environment variable).
- **Changes one in the central file** (`settings set`), and puts it back to the default (`--clear`). A repository's own file still
  wins, and the page says so beside any setting a repository overrides.
- **Keeps the Companion's own choices** (which repositories it shows, its look) where they already are, in its own settings, until
  a citizen called Setting needs them in one place.

## Open questions for the owner

- **Should a Product carry an ID of its own** (a short slug that never changes, beside the display name), so a rename in a
  changelog's title is never mistaken for a new product? Today a rename is read from the title, which works only while one
  changelog keeps one product.
- **Should Rules get IDs**, so a check, a commit message or a page can name one exactly?
- **Should a change to a Setting be an Event** on the timeline (who changed it, from what to what)?
- **Which of the principles above should become rules**, and in which file?
