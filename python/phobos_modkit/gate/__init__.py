"""gate: run a repository's checks before a commit and report only what failed.

A repository lists its checks in config/gate.json: stages run in order; inside a stage, steps that share a lane run one
after another and lanes run side by side. A step may be repeated for every file a glob finds ("each"), so a new test
project is checked without anyone remembering to add it. Each step's output goes through a parser for its tool
(MSBuild, dotnet test, unittest, cargo) that keeps the errors, failed tests and counts and drops the rest; the full output
of a failed step is kept in the kit's cache, to read only when the summary is not enough.

    python -m phobos_modkit gate                    every step; exit 0 only when all pass
    python -m phobos_modkit gate --list             the steps, expanded, without running them
    python -m phobos_modkit gate --only "build *"   steps whose name matches (wildcards * and ?)

The guide is docs/gate.md.
"""
