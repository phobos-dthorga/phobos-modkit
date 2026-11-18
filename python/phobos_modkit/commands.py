"""Every command the kit has: the module that runs it and one line on what it does.

A module is imported only when its command runs, or when the manifest describes it.
"""
from __future__ import annotations

COMMANDS = {
    "crash-dump": (".crashdump_cli", "what a Windows crash dump says failed, whether a call loop ran away, and its methods from a full dump"),
    "windows-dumps": (".windows_dumps", "whether Windows keeps full crash dumps of a program, and asking it to"),
    "rimworld-log": (".games.rimworld.cli", "summarise a RimWorld Player.log and name the mods involved"),
    "rimworld-save": (".games.rimworld.save_cli", "answer questions about a RimWorld save from a fast index"),
    "rimworld-defs": (".games.rimworld.defs_cli", "which active mods define and patch each RimWorld Def"),
    "rimworld-settings": (".games.rimworld.settings_cli",
                          "the player's RimWorld mod settings, files left behind, changes since a snapshot"),
    "rimworld-patches": (".games.rimworld.patches_cli", "which active mods patch which methods with Harmony, from their metadata"),
    "rimworld-targets": (".games.rimworld.targets_cli", "whether every member our C# names by string still exists in the game and the mods"),
    "rimworld-perf": (".games.rimworld.perf_cli", "where a running RimWorld spends its time, by mod, method and part of the game loop"),
    "rimworld-startup": (".games.rimworld.startup_cli", "how long RimWorld takes to start, the costliest mods, what changed between launches"),
    "rimworld-readiness": (".games.rimworld.readiness_cli", "which active mods are ready for a game version, and which are likeliest to break"),
    "rimworld-archive": (".games.rimworld.archive_cli",
                         "keep every version of the game's assembly and of tied mods, and compare two of them"),
    "rimworld-upstream": (".games.rimworld.upstream_cli",
                          "whether an update or another author's source changed a method our code patches or names"),
    "rimworld-sources": (".games.rimworld.sources_cli",
                         "where each tied mod's public source lives, checked against its package ID"),
    "rimworld-textures": (".games.rimworld.textures_cli", "whether active mods' encoded textures match their pictures, and encoding those that don't"),
    "rimworld-workshop": (".games.rimworld.workshop_cli", "what players report about RimWorld mods on the Workshop lately"),
    "steam-workshop": (".steam.workshop_cli", "what players report about Workshop items lately, by ID or URL"),
    "steam-publish": (".steam.publish.cli", "release notes, staging and the owner-run Workshop uploader"),
    "release": (".release.cli", "changelog checks, version constants kept in step, history screen"),
    "code": (".code.cli", "find, outline and show C# declarations, and every line using a name"),
    "cleanup": (".cleanup_cli", "what the tools, builds and tests left behind; deletes only with --apply"),
    "changes": (".changes_cli", "what the changelogs say changed lately, and the code behind any one entry"),
    "installs": (".installs_cli", "what each installed mod would gain or lose by updating or going back to a backup; backs up, goes back, installs"),
    "rules": (".rules_cli", "the rules every repository shares, and whether a repository reads them"),
    "test-pass": (".testpass_cli", "what a repository's in-game test list is waiting for, from the game's notes and the owner's verdicts"),
    "art-audit": (".artaudit_cli", "every shipped image with its record and how it was made, and every borrowed picture"),
    "gate": (".gate.cli", "run a repository's checks before a commit and report only what failed"),
    "manifest": (".manifest", "every command, its reports and options, and what each one reads or changes"),
}
