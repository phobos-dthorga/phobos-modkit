"""RimWorld's Player.log: the 1.7 layout in full, and a basic reading of the older 1.6 layout.

The 1.7 layout (observed in RimWorld 1.7.5000 logs, November 2026):

- A header of "Key: value" lines after "=== Waylith log ===" (Started, Version, OS, Runtime, ...).
- Each message starts with a timestamp, a level padded to five characters and a [Category]:
  "2026-11-07 20:34:32.690  INFO [Verse] text" or "... ERROR [Verse] text".
- Later lines belong to that message until the next timestamp. Among them:
  - lines indented four spaces, "    at Type.Method(...) [0x1E9]": the stack that wrote the message;
  - lines indented three spaces, "   at Type.Method(...) in Some.dll:token 0x...": the exception's own trace,
    printed inside the message text;
  - "    - PREFIX some.harmony.id: Target <- Patch": a Harmony patch on the frame above it.
- Verse stops writing its own messages after a fixed number ("Reached max messages limit"); engine categories
  such as [NativeAllocationRuntime] carry on.

The 1.6 layout is Unity's standard player log: no times or levels, and "(Filename: ... Line: N)" after each
message. It is read in a basic way and has not been checked against a real 1.6 log.
"""
from __future__ import annotations

import re

from ...logs.model import Entry, Evidence, LogFile, Notice

LAYOUT_17 = "rimworld-1.7"
LAYOUT_16 = "rimworld-1.6"

TIMESTAMP = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3}) +([A-Z]+) (?:\[([^\]]*)\] ?)?(.*)$")
HEADER_START = "=== Waylith log ==="
HEADER_LINE = re.compile(r"^([A-Za-z][A-Za-z ]*):\s+(.*)$")
HEADER_KEPT = {"Started": "started", "Version": "version", "Runtime": "runtime"}  # never paths or the command line

LOGGER_FRAME = re.compile(r"^    at (\S.*?)(?: \[0x[0-9A-Fa-f]+\])?$")
EXCEPTION_FRAME = re.compile(r"^ {1,3}at (\S.*?)(?: in (\S+?\.dll):token \S+)?$")
HARMONY_PATCH = re.compile(r"^\s+- (PREFIX|POSTFIX|TRANSPILER|FINALIZER|ILMANIPULATOR|REVERSEPATCH)\s+([^:\s]+):")
SOURCE_LINE = re.compile(r"^\[Source: (.+)\]\s*$")
STACK_HEADER = re.compile(r"^\[(.+?) - Start of stack trace\]")  # also matches the joined headline
WORKSHOP_PATH = re.compile(r"[\\/]294100[\\/](\d{6,})(?=[\\/])")
LOCAL_MOD_PATH = re.compile(r"[\\/]RimWorld[\\/]Mods[\\/]([^\\/\r\n\"']+)[\\/]", re.IGNORECASE)
UNITY_FILENAME = re.compile(r"^\(Filename: .* Line: -?\d+\)\s*$")

LOADING_GAME = re.compile(r"^Loading game from file (.+?) with mods:\s*$")
LOADED_MOD = re.compile(r"^  - (\S+)(?: \((.+)\))?\s*$")
NOTED_SHOWN = 8  # mods listed by name per note in the save-loaded notice
MAX_MESSAGES = "Reached max messages limit"
ENGINE_LEAK_CATEGORY = "NativeAllocationRuntime"
# Held during play (seen 26 Oct 2026): "TempJob allocation ... has not been disposed after 4 frames".
TEMPJOB_HELD = re.compile(r"TempJob allocation .* has not been disposed")
# Reported at exit (seen 3 and 7 Nov 2026): "Persistent allocation 0x... (16384 bytes, align 8) was not freed before
# shutdown."
SHUTDOWN_HELD = re.compile(r"was not freed before shutdown")

EXCEPTION_TYPE = re.compile(r"\b((?:[A-Za-z_]\w*\.)*[A-Za-z_]\w*(?:Exception|Error))\b")
FINGERPRINT_FRAMES = 6  # top frames of an exception trace that identify it

# Namespace roots of the game, its engine and the runtime. Frames in them say nothing about a mod.
GAME_NAMESPACES = frozenset({
    "Verse", "RimWorld", "System", "UnityEngine", "Unity", "Mono", "MonoMod", "HarmonyLib", "Harmony",
    "Waylith", "Brutal", "RimWorldWaylith", "LudeonTK", "Microsoft", "Steamworks", "Internal", "Ionic", "NVorbis",
    "TMPro", "Interop",
})
# Assemblies of the game, its engine and the runtime (lower case, without .dll).
GAME_ASSEMBLIES = frozenset({
    "assembly-csharp", "assembly-csharp-firstpass", "mscorlib", "netstandard", "0harmony", "harmony",
    "rimworld", "rimworldwaylith", "waylith", "brutal",
})


def _game_assembly(name):
    stem = name[:-4] if name.lower().endswith(".dll") else name
    stem = stem.lower()
    return (stem in GAME_ASSEMBLIES or stem.startswith(("system.", "unityengine", "unity.", "mono.", "microsoft.",
                                                        "waylith.", "brutal.")))


def namespace_root(frame):
    """The first part of a stack frame's type name: "Verse" for "Verse.Root+<>c.<Start>b__10_1()".

    Harmony's patched copies of methods start with a dot (".Verse.Log.Error_Patch3"); the dot is dropped.
    Returns "" for frames with no readable type name, such as dynamic methods.
    """
    text = frame.lstrip(".")
    if text.startswith("DMD<") or text.startswith("("):
        return ""
    name = text.split("(", 1)[0]
    root = re.split(r"[.+:]", name, maxsplit=1)[0].strip()
    return root if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", root) else ""


def _headline(first, body):
    """The text that names a message.

    XML Extensions writes a bracketed "[<mod> - Start of stack trace]" first line, with the real message on the
    next line; both are kept so different messages from one mod stay apart.
    """
    if STACK_HEADER.match(first) and body:
        return f"{first} {body[0].strip()}"
    if not first.strip() and body:
        return body[0].strip()
    return first


def evidence_for(entry):
    """Every clue in one message about a mod's part in it, strongest kinds first, each once."""
    found = []

    def add(kind, value):
        clue = Evidence(kind, value)
        if value and clue not in found:
            found.append(clue)

    lines = [entry.headline] + entry.body
    for line in lines:
        match = SOURCE_LINE.match(line) or STACK_HEADER.match(line)
        if match:
            add("source", match.group(1).strip())
    for line in lines:
        for workshop_id in WORKSHOP_PATH.findall(line):
            add("file", f"workshop:{workshop_id}")
        for folder in LOCAL_MOD_PATH.findall(line):
            add("file", f"mods:{folder}")
    exception_frames = []
    for line in entry.body:
        if line.startswith("    at "):
            continue  # the logging stack, read below
        match = EXCEPTION_FRAME.match(line)
        if match:
            exception_frames.append(match)
    for match in exception_frames:
        assembly = match.group(2)
        if assembly and not _game_assembly(assembly):
            add("assembly", assembly)
    for match in exception_frames:
        root = namespace_root(match.group(1))
        if root and root not in GAME_NAMESPACES:
            add("namespace", root)
    if not exception_frames:
        for line in entry.body:
            match = LOGGER_FRAME.match(line)
            if not match:
                continue
            root = namespace_root(match.group(1))
            if root and root not in GAME_NAMESPACES:
                add("caller", root)
                break
    for line in entry.body:
        match = HARMONY_PATCH.match(line)
        if match:
            add("finalizer" if match.group(1) == "FINALIZER" else "patch", match.group(2))
    return sorted(found, key=lambda e: e.rank)


def _frame_method(frame):
    """Verse.GenMapUI.DrawPawnLabel from "Verse.GenMapUI.DrawPawnLabel_Patch2(Pawn pawn, ...)"."""
    name = frame.split("(", 1)[0].lstrip(".").strip()
    return re.sub(r"_Patch\d+$", "", name)


def fingerprint(entry):
    """The exception's type and its top frames, or "" when the message carries no exception trace.

    Messages that differ in wording (a pawn's name, say) but share this come from one exception in one place.
    """
    frames = []
    for line in entry.body:
        if line.startswith("    at "):
            continue
        match = EXCEPTION_FRAME.match(line)
        if match:
            frames.append(_frame_method(match.group(1)))
            if len(frames) == FINGERPRINT_FRAMES:
                break
    if not frames:
        return ""
    found = EXCEPTION_TYPE.search(entry.headline)
    return f"{found.group(1) + ' ' if found else ''}at " + " < ".join(frames)


def _timed_entries(lines):
    """(header, entries) from a 1.7 log."""
    header = {}
    entries = []
    current = None
    for number, line in enumerate(lines, 1):
        match = TIMESTAMP.match(line)
        if match:
            time, level, category, text = match.groups()
            current = Entry(line=number, level=level, category=category or "", headline=text, time=time)
            entries.append(current)
        elif current is not None:
            current.body.append(line)
        else:
            kv = HEADER_LINE.match(line)
            if kv and kv.group(1) in HEADER_KEPT:
                header[HEADER_KEPT[kv.group(1)]] = kv.group(2).strip()
    return header, entries


def _unity_entries(lines):
    """Entries from a 1.6 (Unity) log: one per "(Filename: ...)" marker, or per blank-line block without them."""
    split_on_markers = any(UNITY_FILENAME.match(line) for line in lines)
    entries = []
    block, start = [], 0

    def flush():
        while block and not block[-1].strip():
            block.pop()
        if block:
            entries.append(Entry(line=start, level="UNKNOWN", category="", headline=block[0], body=block[1:]))

    for number, line in enumerate(lines, 1):
        boundary = UNITY_FILENAME.match(line) if split_on_markers else not line.strip()
        if boundary:
            flush()
            block, start = [], 0
            continue
        if not block and not line.strip():
            continue
        if not block:
            start = number
        block.append(line)
    flush()
    return entries


def _loads(entries):
    """Each "Loading game from file" message: (entry, save name, mod IDs, mods with a note such as
    "incompatible version")."""
    loads = []
    for entry in entries:
        match = LOADING_GAME.match(entry.headline)
        if not match:
            continue
        mods, noted = [], []
        for line in entry.body:
            item = LOADED_MOD.match(line)
            if not item:
                break
            mods.append(item.group(1))
            if item.group(2):
                noted.append((item.group(1), item.group(2)))
        loads.append((entry, match.group(1), mods, noted))
    return loads


def _notices(entries):
    notices = []
    for entry, save, mods, noted in _loads(entries):
        text = f"Save \"{save}\" loaded at {entry.time or 'line ' + str(entry.line)} with {len(mods):,} mods."
        by_note = {}
        for pid, note in noted:
            by_note.setdefault(note, []).append(pid)
        for note, pids in sorted(by_note.items(), key=lambda kv: -len(kv[1])):
            listed = ", ".join(pids[:NOTED_SHOWN])
            more = f" and {len(pids) - NOTED_SHOWN} more" if len(pids) > NOTED_SHOWN else ""
            text += f" {len(pids):,} marked \"{note}\": {listed}{more}."
        notices.append(Notice("save-loaded", text, {"save": save, "line": entry.line, "time": entry.time,
                                                    "mods": len(mods), "noted": [list(n) for n in noted]}))
    stop = next((e for e in entries if e.category in ("Verse", "") and e.headline.startswith(MAX_MESSAGES)), None)
    if stop is not None:
        after = [e for e in entries if e.line > stop.line]
        by_category = {}
        for e in after:
            by_category[e.category or "(none)"] = by_category.get(e.category or "(none)", 0) + 1
        listed = ", ".join(f"{n:,} [{c}]" for c, n in sorted(by_category.items(), key=lambda kv: -kv[1]))
        text = (f"The game stopped writing its own messages at {stop.time} (line {stop.line:,}): \"{MAX_MESSAGES}\". "
                f"Anything the game reported after that is missing from this log.")
        if listed:
            text += f" Engine messages carried on: {listed}."
        notices.append(Notice("logging-stopped", text, {"line": stop.line, "time": stop.time,
                                                        "after": by_category}))
    engine = [e for e in entries if e.category == ENGINE_LEAK_CATEGORY]
    in_play = [e for e in engine if TEMPJOB_HELD.search(e.headline)]
    at_shutdown = [e for e in engine if SHUTDOWN_HELD.search(e.headline)]
    if in_play:
        text = (f"{len(in_play):,} warnings that the engine held a temporary allocation for several frames, from "
                f"{in_play[0].time} to {in_play[-1].time}. In one diagnosed case (October 2026) a steady stream of "
                f"them followed an exception repeated every frame, and the memory came back only when the game "
                f"restarted.")
        notices.append(Notice("engine-allocations-held", text, {"count": len(in_play), "first": in_play[0].time,
                                                                "last": in_play[-1].time}))
    if at_shutdown:
        text = (f"{len(at_shutdown):,} engine allocations were still held when the game shut down, reported at "
                f"{at_shutdown[0].time}. They are counted at exit; the count alone names no mod.")
        notices.append(Notice("engine-allocations-at-shutdown", text, {"count": len(at_shutdown),
                                                                       "time": at_shutdown[0].time}))
    finalized = sorted({e.value for entry in entries for e in entry.evidence if e.kind == "finalizer"})
    if finalized:
        text = (f"Harmony finalizer patches appear on failing stacks ({', '.join(finalized[:8])}). A finalizer that "
                f"rethrows an exception can make it look as if it began in the patched method; read those traces "
                f"with care.")
        notices.append(Notice("finalizers", text, {"harmonyIds": finalized}))
    return notices


def comparison_notices(current, previous):
    """Notices that explain a comparison: when only one of the two runs loaded a save, most messages from play
    appear as new or gone for that reason alone."""
    loaded = lambda log: any(n.kind == "save-loaded" for n in log.notices)
    if loaded(current) == loaded(previous):
        return []
    without = previous if loaded(current) else current
    side = "new" if without is previous else "gone"
    text = (f"{without.name} loaded no save, so messages from play show as {side} in the comparison for that "
            f"reason alone.")
    return [Notice("comparison-uneven", text, {"withoutSave": without.name})]


def parse(text, name="Player.log"):
    """A LogFile from the text of a RimWorld log, in whichever layout it uses."""
    lines = text.splitlines()
    timed = (lines and lines[0].startswith(HEADER_START)) or any(TIMESTAMP.match(l) for l in lines[:2000])
    if timed:
        header, entries = _timed_entries(lines)
        layout, limits = LAYOUT_17, []
    else:
        header, entries = {}, _unity_entries(lines)
        layout = LAYOUT_16
        limits = ["This log has the 1.6 layout: no times or levels, so every message is listed as UNKNOWN. The "
                  "reading of this layout has not been checked against a real 1.6 log."]
    header = {"game": "RimWorld", **header}
    for entry in entries:
        entry.headline = _headline(entry.headline, entry.body)
        entry.evidence = evidence_for(entry)
        entry.fingerprint = fingerprint(entry)
    log = LogFile(name=name, layout=layout, entries=entries, header=header, limits=limits, line_total=len(lines))
    log.notices = _notices(entries)
    return log
