"""Sampled call stacks from a .NET program: read a trace, index it in SQLite, and say where the time went and who caused it.

The trace is Microsoft's `dotnet-trace` sampling profile, converted by that tool to speedscope's "evented" JSON: one timeline per
thread of frames opening and closing, each frame named `module!Namespace.Type.Method(arguments)`. The runtime marks what a thread
was doing with a leaf frame: `CPU_TIME` (running managed code) or `UNMANAGED_CODE_TIME` (in native code: the engine, the operating
system, or waiting). A method that Harmony rewrote appears as `module!dynamicClass.DMD<Namespace.Type::Method>`.

Nothing here names a game. A game adapter passes in who owns each module (`classify`) and the named phases of its main loop.

How time is attributed (stated in every report):
- **Caused by** is the innermost frame on the stack that belongs to a mod. A mod's code calling the game's code is the mod's time;
  a Harmony prefix or postfix is its own frame, so it counts for the mod that wrote it. Work a transpiler puts inside a game method,
  and code the compiler inlined into its caller, cannot be seen apart.
- **Spent in** is the frame the thread was in when sampled.
- Sampling sees about one stack per millisecond per thread, so a method that ran for less than that can be missed or over-counted
  by chance; totals over a recording of many seconds are reliable to a few percent.
"""
from __future__ import annotations

from collections import defaultdict
from contextlib import closing
from dataclasses import dataclass
import fnmatch
import json
from pathlib import Path
import re
import sqlite3

from . import cache as derived

INDEX_FORMAT = "1"
CPU_FRAME = "CPU_TIME"
NATIVE_FRAME = "UNMANAGED_CODE_TIME"
CPU, NATIVE, OTHER = "cpu", "native", "other"
MOD, GAME, ENGINE, RUNTIME, LIBRARY, UNKNOWN = "mod", "game", "engine", "runtime", "library", "unknown"
# When no mod is on a stack, the first of these kinds found on it names who the time belongs to.
FALLBACK_ORDER = (GAME, ENGINE, LIBRARY, UNKNOWN, RUNTIME)

_DMD = re.compile(r"^dynamicClass\.DMD<(?P<type>.+)::(?P<method>[^>]+)>")
_MODULE_SUFFIX = re.compile(r"\.(il|ni|dll|exe)$", re.IGNORECASE)
_EVENT = re.compile(r'\{\s*"type"\s*:\s*"(?P<kind>[OC])"\s*,\s*"frame"\s*:\s*(?P<frame>\d+)\s*,\s*"at"\s*:\s*(?P<at>[-+0-9.eE]+)\s*\}')
_EVENTS_KEY = re.compile(r'"events"\s*:\s*\[')
_FRAMES_KEY = re.compile(r'"shared"\s*:\s*\{\s*"frames"\s*:\s*(?=\[)')
_THREAD_ID = re.compile(r"\((\d+)\)")


class SamplingError(RuntimeError):
    pass


@dataclass(frozen=True)
class Owner:
    kind: str      # MOD, GAME, ENGINE, RUNTIME, LIBRARY or UNKNOWN
    name: str      # who: a mod's name, "RimWorld", ".NET", or the module for an unknown one


def split_frame(name):
    """(module, method without arguments, patched) for one frame name. Patched is True for a method Harmony rewrote."""
    module, sep, rest = name.partition("!")
    if not sep:
        return "", name, False
    module = _MODULE_SUFFIX.sub("", module)
    found = _DMD.match(rest)
    if found:
        return module, f"{found.group('type')}.{found.group('method')}", True
    return module, rest.split("(", 1)[0], False


def type_of(method):
    """Namespace.Type of Namespace.Type.Method."""
    return method.rsplit(".", 1)[0] if "." in method else ""


# ---- Reading a speedscope file into the index ----

SCHEMA = """
CREATE TABLE frame (id INTEGER PRIMARY KEY, name TEXT, module TEXT, method TEXT, patched INTEGER);
CREATE TABLE node (id INTEGER PRIMARY KEY, parent INTEGER, frame INTEGER);
CREATE TABLE thread (id INTEGER PRIMARY KEY, name TEXT, start_ms REAL, end_ms REAL, cpu_ms REAL, native_ms REAL);
CREATE TABLE sample (thread INTEGER, node INTEGER, kind TEXT, ms REAL);
CREATE TABLE owner (module TEXT PRIMARY KEY, kind TEXT, name TEXT);
CREATE TABLE counter (name TEXT, tags TEXT, mean REAL, max REAL, samples INTEGER);
"""


def _frames(text):
    found = _FRAMES_KEY.search(text)
    if not found:
        raise SamplingError("This is not a speedscope file from dotnet-trace: it has no shared frame list.")
    frames, _ = json.JSONDecoder().raw_decode(text, found.end())
    return [f.get("name", "") for f in frames]


def _profiles(text):
    """(header, start, end) of each profile's event list, where header is the profile without its events."""
    for found in _EVENTS_KEY.finditer(text):
        opening = text.rfind("{", 0, found.start())
        header = json.loads(text[opening:found.end()] + "]}")
        if header.get("type") != "evented":
            raise SamplingError(f"Profile {header.get('name')!r} is {header.get('type')!r}; only evented profiles are read.")
        closing_at = text.index("]", found.end())
        yield header, found.end(), closing_at


def index_speedscope(path, index, meta=None):
    """Build the index at `index` from a speedscope file; replaces any index there. Returns the number of threads read."""
    text = Path(path).read_text(encoding="utf-8")
    names = _frames(text)
    kept = {}                      # speedscope frame id -> our frame id, for frames that name a method
    pseudo = {}                    # speedscope frame id -> CPU or NATIVE for the runtime's leaf markers
    rows = []
    for i, name in enumerate(names):
        if name == CPU_FRAME:
            pseudo[i] = CPU
        elif name == NATIVE_FRAME:
            pseudo[i] = NATIVE
        elif "!" in name:
            module, method, patched = split_frame(name)
            kept[i] = len(rows)
            rows.append((len(rows), name, module, method, int(patched)))
    nodes = {}                     # (parent node, frame) -> node
    node_rows = []
    threads, samples = [], []
    for header, start, end in _profiles(text):
        thread = len(threads)
        totals = defaultdict(float)                # (node, kind) -> ms
        stack = []                                 # (speedscope frame, node at that depth)
        last = None
        for event in _EVENT.finditer(text, start, end):
            at = float(event.group("at"))
            if last is not None and stack and at > last:
                top = stack[-1][0]
                totals[(stack[-1][1], pseudo.get(top, OTHER))] += at - last
            last = at
            frame = int(event.group("frame"))
            if event.group("kind") == "O":
                node = stack[-1][1] if stack else -1
                if frame in kept:
                    key = (node, kept[frame])
                    node = nodes.get(key)
                    if node is None:
                        node = nodes[key] = len(node_rows)
                        node_rows.append((node, key[0], key[1]))
                stack.append((frame, node))
            elif stack:
                stack.pop()
        cpu = sum(v for (n, k), v in totals.items() if k == CPU)
        native = sum(v for (n, k), v in totals.items() if k == NATIVE)
        threads.append((thread, header.get("name", f"thread {thread}"), float(header.get("startValue", 0)),
                        float(header.get("endValue", 0)), cpu, native))
        samples.extend((thread, n, k, ms) for (n, k), ms in totals.items() if n >= 0)
    if not threads:
        raise SamplingError("The trace holds no thread timelines. Was the program running managed code while it was recorded?")
    index = Path(index)
    derived.remove(index)
    index.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(index)) as conn:
        conn.executescript(SCHEMA)
        conn.executemany("INSERT INTO frame VALUES (?, ?, ?, ?, ?)", rows)
        conn.executemany("INSERT INTO node VALUES (?, ?, ?)", node_rows)
        conn.executemany("INSERT INTO thread VALUES (?, ?, ?, ?, ?, ?)", threads)
        conn.executemany("INSERT INTO sample VALUES (?, ?, ?, ?)", samples)
        derived.write_meta(conn, {"index_format": INDEX_FORMAT, **(meta or {})})
        conn.commit()
    return len(threads)


def modules(index):
    """Every module named in the index, sorted."""
    with closing(derived.open_read_only(index)) as conn:
        return [r[0] for r in conn.execute("SELECT DISTINCT module FROM frame ORDER BY module")]


def write_owners(index, owners):
    """Record who owns each module: {module: Owner}. Done once, when the recording is made, against that day's mod list."""
    with closing(sqlite3.connect(index)) as conn:
        conn.execute("DELETE FROM owner")
        conn.executemany("INSERT INTO owner VALUES (?, ?, ?)", [(m, o.kind, o.name) for m, o in sorted(owners.items())])
        conn.commit()


# ---- Counters ----

def read_counters(path):
    """dotnet-counters' JSON file as {(name, tags): [values]} in time order. Missing or empty gives {}."""
    path = Path(path)
    if not path.is_file() or path.stat().st_size == 0:
        return {}
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    values = defaultdict(list)
    for event in data.get("Events", []):
        try:
            values[(event["name"], event.get("tags") or "")].append(float(event["value"]))
        except (KeyError, TypeError, ValueError):
            continue
    return dict(values)


def write_counters(index, counters):
    with closing(sqlite3.connect(index)) as conn:
        conn.execute("DELETE FROM counter")
        conn.executemany("INSERT INTO counter VALUES (?, ?, ?, ?, ?)", [
            (name, tags, sum(v) / len(v), max(v), len(v)) for (name, tags), v in sorted(counters.items()) if v])
        conn.commit()


# ---- Reading an index back ----

@dataclass
class Share:
    cpu: float = 0.0
    native: float = 0.0

    @property
    def total(self):
        return self.cpu + self.native


class Recording:
    """One indexed recording, read whole into memory: frames, the stack tree, time per stack and the owners of modules."""

    def __init__(self, index):
        self.index = Path(index)
        with closing(derived.open_read_only(self.index)) as conn:
            self.meta = dict(conn.execute("SELECT key, value FROM meta"))
            if self.meta.get("index_format") != INDEX_FORMAT:
                raise SamplingError(f"{self.index} was built by another version of this tool; record again.")
            self.frames = {r[0]: r[1:] for r in conn.execute("SELECT id, name, module, method, patched FROM frame")}
            self.parent, self.frame_of = {}, {}
            for node, parent, frame in conn.execute("SELECT id, parent, frame FROM node"):
                self.parent[node], self.frame_of[node] = parent, frame
            self.threads = {r[0]: r[1:] for r in conn.execute("SELECT id, name, start_ms, end_ms, cpu_ms, native_ms FROM thread")}
            self.samples = conn.execute("SELECT thread, node, kind, ms FROM sample").fetchall()
            self.owners = {r[0]: Owner(r[1], r[2]) for r in conn.execute("SELECT module, kind, name FROM owner")}
            self.counters = {(r[0], r[1]): (r[2], r[3], r[4]) for r in conn.execute("SELECT name, tags, mean, max, samples FROM counter")}
        self._type_owner = None
        self._labels = {}

    # Threads

    def main_thread(self):
        """The thread that spent most time running managed code: a game's main loop."""
        return min(self.threads, key=lambda t: (-self.threads[t][3], t))

    def duration_ms(self, thread):
        _, start, end, _, _ = self.threads[thread]
        return max(end - start, 0.0)

    def thread_label(self, thread):
        name = self.threads[thread][0]
        found = _THREAD_ID.search(name)
        return f"thread {found.group(1)}" if found else name

    # Owners

    def owner_of_frame(self, frame):
        _, module, method, patched = self.frames[frame]
        if patched:
            # A rewritten method's module is whatever Harmony gave it; its type says whose method it is.
            return self._owner_of_type(type_of(method)) or Owner(GAME, self.meta.get("game_name", "the game"))
        return self.owners.get(module) or Owner(UNKNOWN, module or "?")

    def _owner_of_type(self, type_name):
        if self._type_owner is None:
            self._type_owner = {}
            for _, module, method, patched in self.frames.values():
                if not patched and module in self.owners:
                    self._type_owner.setdefault(type_of(method), self.owners[module])
        return self._type_owner.get(type_name)

    def label(self, node):
        """Who caused the time at a stack: the innermost mod frame on it, else the first kind of FALLBACK_ORDER on it."""
        if node in self._labels:
            return self._labels[node]
        chain = []
        while node >= 0 and node not in self._labels:
            chain.append(node)
            node = self.parent[node]
        inherited = self._labels[node] if node >= 0 else None
        for current in reversed(chain):
            own = self.owner_of_frame(self.frame_of[current])
            if own.kind == MOD:
                result = own
            elif inherited is None:
                result = own
            elif inherited.kind == MOD:
                result = inherited
            else:
                result = own if FALLBACK_ORDER.index(own.kind) < FALLBACK_ORDER.index(inherited.kind) else inherited
            self._labels[current] = inherited = result
        return inherited

    def path(self, node):
        frames = []
        while node >= 0:
            frames.append(self.frame_of[node])
            node = self.parent[node]
        frames.reverse()
        return frames

    # Aggregates

    def thread_samples(self, thread):
        return [(node, kind, ms) for t, node, kind, ms in self.samples if t == thread]

    def by_owner(self, samples):
        """{Owner: Share} for samples."""
        result = defaultdict(Share)
        for node, kind, ms in samples:
            share = result[self.label(node)]
            if kind == CPU:
                share.cpu += ms
            else:
                share.native += ms
        return dict(result)

    def phase_of(self, node, phases, cache):
        """The first phase (label, patterns) whose pattern matches a frame on the stack, walking from the root."""
        if node in cache:
            return cache[node]
        parent = self.parent[node]
        above = self.phase_of(parent, phases, cache) if parent >= 0 else None
        result = above
        if above is None:
            method = self.frames[self.frame_of[node]][2]
            for label, patterns in phases:
                if any(fnmatch.fnmatchcase(method, p) for p in patterns):
                    result = label
                    break
        cache[node] = result
        return result

    def by_phase(self, samples, phases):
        cache, result = {}, defaultdict(Share)
        for node, kind, ms in samples:
            share = result[self.phase_of(node, phases, cache)]
            if kind == CPU:
                share.cpu += ms
            else:
                share.native += ms
        return dict(result)

    def in_phase(self, samples, phases, wanted):
        cache = {}
        return [s for s in samples if self.phase_of(s[0], phases, cache) == wanted]

    def self_methods(self, samples):
        """{(method, Owner, patched): Share} by the method the thread was in when sampled."""
        result = defaultdict(Share)
        for node, kind, ms in samples:
            frame = self.frame_of[node]
            _, _, method, patched = self.frames[frame]
            share = result[(method, self.owner_of_frame(frame), bool(patched))]
            if kind == CPU:
                share.cpu += ms
            else:
                share.native += ms
        return dict(result)

    def inclusive_methods(self, samples, keep):
        """{(method, Owner, patched): Share} counting each method once per stack it is on, for frames where keep(Owner, patched)."""
        result = defaultdict(Share)
        memo = {}
        for node, kind, ms in samples:
            if node not in memo:
                seen = set()
                for frame in self.path(node):
                    _, _, method, patched = self.frames[frame]
                    owner = self.owner_of_frame(frame)
                    if keep(owner, bool(patched)):
                        seen.add((method, owner, bool(patched)))
                memo[node] = seen
            for key in memo[node]:
                if kind == CPU:
                    result[key].cpu += ms
                else:
                    result[key].native += ms
        return dict(result)

    def counter(self, name, tags=""):
        """(mean, max, samples) of one counter, or None. Name without its unit, e.g. dotnet.gc.pause.time."""
        for (full, found_tags), value in self.counters.items():
            if full.split(" (", 1)[0] == name and found_tags == tags:
                return value
        return None

    def counters_named(self, name):
        """{tags: (mean, max, samples)} of one counter across its tags."""
        return {tags: value for (full, tags), value in self.counters.items() if full.split(" (", 1)[0] == name}
