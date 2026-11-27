"""windows-dumps: whether Windows keeps full crash dumps of one program, and asking it to.

    windows-dumps --program RimWorld              what Windows does now when the program crashes, and the commands to change it
    windows-dumps --program RimWorld --apply      ask for full dumps of that program only (needs an administrator window)
    windows-dumps --program RimWorld --off        stop: remove that program's own setting; Windows' defaults apply again

Windows Error Reporting writes a dump when a program crashes, if the registry key LocalDumps exists (Microsoft, "Collecting
User-Mode Dumps", https://learn.microsoft.com/windows/win32/wer/collecting-user-mode-dumps). A key under it named after one program
(RimWorld.exe) sets that program alone: DumpType 2 is a full dump, DumpCount how many are kept (the oldest is deleted), DumpFolder
where. The default is a small dump in %LOCALAPPDATA%\\CrashDumps, which proves the shape of a .NET crash but cannot name its methods;
a full one can (crash-dump reads it with dotnet-dump). A full dump is as large as the memory the program used when it crashed.

Reads the registry; writes only with --apply or --off, only that program's own key, and only from an administrator window.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import shutil
import sys

from .manifest import READS
from .report import Bullets, Code, Report, Table, envelope_text, home_redactor, keep, render_markdown

EXIT_OK, EXIT_FAILED, EXIT_USAGE = 0, 1, 2
LOCAL_DUMPS = r"SOFTWARE\Microsoft\Windows\Windows Error Reporting\LocalDumps"
FULL, MINI = 2, 1
DEFAULT_COUNT = 2
DUMP_TYPES = {0: "custom", 1: "small", 2: "full"}
DEFAULT_FOLDER = r"%LOCALAPPDATA%\CrashDumps"


class DumpsError(RuntimeError):
    pass


class Registry:
    """The few registry reads and writes this needs, through Python's winreg. Tests pass a stand-in."""

    def __init__(self, winreg=None):
        if winreg is None:
            try:
                import winreg as module
            except ImportError as missing:
                raise DumpsError("Crash dump settings are a Windows registry setting; this is not Windows.") from missing
            winreg = module
        self.w = winreg

    def _values(self, path):
        try:
            key = self.w.OpenKey(self.w.HKEY_LOCAL_MACHINE, path)
        except OSError:
            return None
        values = {}
        with key:
            i = 0
            while True:
                try:
                    name, value, _ = self.w.EnumValue(key, i)
                except OSError:
                    break
                values[name] = value
                i += 1
        return values

    def defaults(self):
        """LocalDumps' own values ({} when it has none), or None when the key is missing and Windows keeps no dumps."""
        return self._values(LOCAL_DUMPS)

    def program(self, exe):
        return self._values(LOCAL_DUMPS + "\\" + exe)

    def write(self, exe, count, folder):
        key = self.w.CreateKeyEx(self.w.HKEY_LOCAL_MACHINE, LOCAL_DUMPS + "\\" + exe, 0, self.w.KEY_WRITE)
        with key:
            self.w.SetValueEx(key, "DumpType", 0, self.w.REG_DWORD, FULL)
            self.w.SetValueEx(key, "DumpCount", 0, self.w.REG_DWORD, count)
            if folder:
                self.w.SetValueEx(key, "DumpFolder", 0, self.w.REG_EXPAND_SZ, folder)

    def remove(self, exe):
        self.w.DeleteKey(self.w.HKEY_LOCAL_MACHINE, LOCAL_DUMPS + "\\" + exe)


def _parser():
    p = argparse.ArgumentParser(prog="windows-dumps", description=__doc__.split("\n\n")[0],
                                formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__.split("\n\n", 1)[1])
    p.add_argument("--program", required=True, help="the program's file name, with or without .exe (RimWorld)")
    p.add_argument("--count", type=int, default=DEFAULT_COUNT, help=f"how many full dumps Windows keeps (default {DEFAULT_COUNT})")
    p.add_argument("--folder", help="where they go (default Windows' own, " + DEFAULT_FOLDER.replace("%", "%%") + ")")
    change = p.add_mutually_exclusive_group()
    change.add_argument("--apply", action="store_true", help="ask Windows for full dumps of this program (administrator window)")
    change.add_argument("--off", action="store_true", help="remove this program's own setting (administrator window)")
    p.add_argument("--json", action="store_true", help="print JSON instead of Markdown")
    p.add_argument("--no-redact", action="store_true", help="show the home folder instead of ~")
    return p


def exe_name(program):
    return program if program.lower().endswith(".exe") else program + ".exe"


def commands(exe, count, folder, off=False):
    """The PowerShell lines that make the same change, for an administrator window."""
    key = f"HKLM:\\{LOCAL_DUMPS}\\{exe}"
    if off:
        return [f"Remove-Item -Path '{key}' -Recurse"]
    lines = [f"New-Item -Path '{key}' -Force | Out-Null",
             f"New-ItemProperty -Path '{key}' -Name DumpType -PropertyType DWord -Value {FULL} -Force | Out-Null",
             f"New-ItemProperty -Path '{key}' -Name DumpCount -PropertyType DWord -Value {count} -Force | Out-Null"]
    if folder:
        lines.append(f"New-ItemProperty -Path '{key}' -Name DumpFolder -PropertyType ExpandString -Value '{folder}' -Force | Out-Null")
    return lines


def _describe(values, defaults):
    kind = DUMP_TYPES.get(values.get("DumpType", defaults.get("DumpType", MINI)), "unknown")
    count = values.get("DumpCount", defaults.get("DumpCount", 10))
    folder = values.get("DumpFolder", defaults.get("DumpFolder", DEFAULT_FOLDER))
    return kind, count, folder


def _free(folder, environ):
    expanded = folder.replace("%LOCALAPPDATA%", environ.get("LOCALAPPDATA", "%LOCALAPPDATA%"))
    probe = Path(expanded)
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    try:
        return shutil.disk_usage(probe).free
    except OSError:
        return None


def build_report(exe, registry, args, environ, outcome=None):
    defaults, own = registry.defaults(), registry.program(exe)
    report = Report(f"windows-dumps: {exe}")
    if outcome:
        report.lines.append(outcome)
    if defaults is None:
        report.lines.append("**Windows keeps no crash dumps on this PC** (no LocalDumps key). Asking for one program's creates it, "
                            "which also turns on small dumps of every program in its default folder.")
        defaults = {}
    else:
        kind, count, folder = _describe({}, defaults)
        report.lines.append(f"Windows keeps {kind} dumps of every program that crashes, the newest {count} of each, in {folder}.")
    if own is None:
        report.lines.append(f"**{exe} has no setting of its own**, so a crash leaves the default dump above.")
    else:
        kind, count, folder = _describe(own, defaults)
        report.lines.append(f"**{exe} has its own: {kind} dumps, the newest {count}, in {folder}.**")
    wanted = commands(exe, args.count, args.folder, off=args.off)
    full = own is not None and own.get("DumpType") == FULL
    if not (args.apply or args.off):
        if full:
            report.lines.append("Nothing to do: a crash will leave a full dump that crash-dump can name the methods in.")
        else:
            free = _free(args.folder or DEFAULT_FOLDER, environ)
            report.section("To ask for full dumps", Bullets([
                "**Run this tool again with --apply from an administrator window**, or paste these lines into PowerShell opened "
                "with Run as administrator:",
            ]), Code(commands(exe, args.count, args.folder), "powershell"), Bullets([
                f"Each full dump is as large as the memory {exe} used when it crashed (Task Manager's Memory column); Windows "
                f"keeps the newest {args.count} and deletes older ones." + (f" {free / 1e9:,.0f} GB is free there now." if free else ""),
                "Undo it any time with --off: small dumps carry on as before.",
            ]))
    elif args.off and own is None:
        report.lines.append("Nothing to remove.")
    report.section("What it changes", Table(["Setting", "Meaning"], [
        ("DumpType 2", "a full dump: all of the program's memory, so its methods can be named"),
        (f"DumpCount {args.count}", "how many Windows keeps for this program; the oldest goes first"),
        ("DumpFolder", f"where; Windows' own default is {DEFAULT_FOLDER}"),
    ]))
    return report, wanted


def main(argv=None, environ=None, out=None, registry=None):
    out = out or sys.stdout
    environ = os.environ if environ is None else environ
    try:
        args = _parser().parse_args(list(sys.argv[1:] if argv is None else argv))
    except SystemExit as stop:
        return EXIT_USAGE if stop.code else EXIT_OK
    redact = keep if args.no_redact else home_redactor()
    exe, code = exe_name(args.program), EXIT_OK
    try:
        if not 1 <= args.count <= 20:
            raise DumpsError("--count must be between 1 and 20.")
        registry = registry or Registry()
        outcome = None
        if args.apply or args.off:
            try:
                if args.apply:
                    registry.write(exe, args.count, args.folder)
                    outcome = f"**Done: Windows will keep full dumps of {exe}.** Nothing changes until it next crashes."
                elif registry.program(exe) is not None:
                    registry.remove(exe)
                    outcome = f"**Done: {exe}'s own setting is removed.** Windows' default dumps apply to it again."
            except PermissionError:
                code = EXIT_FAILED
                outcome = ("**Not changed: this needs an administrator window.** Open PowerShell with Run as administrator and run "
                           "the lines below there, or this same command.")
        report, wanted = build_report(exe, registry, args, environ, outcome)
        if code == EXIT_FAILED:
            report.section("The lines to run as administrator", Code(wanted, "powershell"))
    except DumpsError as error:
        report, code = Report("windows-dumps: error", [str(error)]), EXIT_FAILED
    out.write((envelope_text("windows-dumps", report, redact) if args.json else render_markdown(report, redact)) + "\n")
    return code


MANIFEST = {"game": None, "parser": _parser, "effect": READS,
            "note": "--apply and --off write the one registry key for the program named; they need an administrator window.",
            "question": "Will Windows keep a crash dump that can name the methods?", "scope": "machine"}
