# Rules for building code, in every Phobos and D'thorga repository

Read before setting up or changing how a repository builds code, and before adding a project or a build script. The rules for
every session are in [every-session.md](every-session.md); how this folder works is in [README.md](README.md).

## The same code builds to the same bytes

- **Building the same code twice gives the same file, byte for byte, whatever the commit, the clock or the folder** (owner, 19 Nov
  2026, after D'thorga Companion read every mod as changed: .NET had stamped the git commit into every assembly, so any commit,
  even to the docs, changed every rebuilt file by about 100 bytes). A file that differs then always means its code, or code it
  is built against, changed. Comparing an install with the repository, checking what an update brings, and keeping backups all
  rest on that.
- **Nothing that changes from build to build goes into what is built**: no commit hash, build time, build number, machine or
  user name, or full path to the folder it was built in. **The version a player or the game reads stays**: the mod's own version
  number, set by hand, is part of the code.
- **The commit belongs beside the file, never in it**: in the install record (phobos-modkit's installs), the changelog, the
  release notes or the tag.
- **.NET (C#)**: in the repository's `Directory.Build.props`, so every project has it:

  ```xml
  <Deterministic>true</Deterministic>
  <IncludeSourceRevisionInInformationalVersion>false</IncludeSourceRevisionInInformationalVersion>
  ```

  The second is the one that matters: the .NET SDK turns it on by itself, adding `+<commit>` to every assembly's informational
  version. `Deterministic` is on by default too, and is set so a reader sees it was meant.
- **Other toolchains**: the same rule in their own terms. A build script never stamps the commit or the time into what it
  builds; a toolchain's own stamp is turned off where it has one.
- **A repository that ships nothing built** (Lua, XML, data only) has nothing to do here.

**How to check** (done on 19 Nov 2026 in phobos-rimworld, where Water Tap came out the same at two commits): build a project,
keep a copy of what it built, build it again as if at another commit (for .NET, `-p:SourceRevisionId=` with any other 40-character
value), and compare the two files. Any byte that differs is a stamp left to remove. Build into a copy of the output, never over
an installed mod.

Following it on 19 Nov 2026: phobos-rimworld and this kit. Not yet: phobos-ostranauts (33 projects), phobos-scope and phobos-log;
each takes it up when it is next worked on.
