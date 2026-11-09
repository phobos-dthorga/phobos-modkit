"""Every command the kit has: the module that runs it and one line on what it does.

A module is imported only when its command runs, or when the manifest describes it.
"""
from __future__ import annotations

COMMANDS = {
    "crash-dump": (".crashdump_cli", "what a Windows crash dump says failed, and whether a call loop ran away"),
    "rimworld-log": (".games.rimworld.cli", "summarise a RimWorld Player.log and name the mods involved"),
    "rimworld-save": (".games.rimworld.save_cli", "answer questions about a RimWorld save from a fast index"),
    "rimworld-defs": (".games.rimworld.defs_cli", "which active mods define and patch each RimWorld Def"),
    "rimworld-settings": (".games.rimworld.settings_cli",
                          "the player's RimWorld mod settings, files left behind, changes since a snapshot"),
    "rimworld-patches": (".games.rimworld.patches_cli", "which active mods patch which methods with Harmony, from their metadata"),
    "rimworld-targets": (".games.rimworld.targets_cli", "whether every member our C# names by string still exists in the game and the mods"),
    "rimworld-startup": (".games.rimworld.startup_cli", "how long RimWorld takes to start, the costliest mods, what changed between launches"),
    "rimworld-readiness": (".games.rimworld.readiness_cli", "which active mods are ready for a game version, and which are likeliest to break"),
    "rimworld-workshop": (".games.rimworld.workshop_cli", "what players report about RimWorld mods on the Workshop lately"),
    "steam-workshop": (".steam.workshop_cli", "what players report about Workshop items lately, by ID or URL"),
    "steam-publish": (".steam.publish.cli", "release notes, staging and the owner-run Workshop uploader"),
    "release": (".release.cli", "changelog checks, version constants kept in step, history screen"),
    "code": (".code.cli", "find, outline and show C# declarations, and every line using a name"),
    "gate": (".gate.cli", "run a repository's checks before a commit and report only what failed"),
    "manifest": (".manifest", "every command, its reports and options, and what each one reads or changes"),
}
