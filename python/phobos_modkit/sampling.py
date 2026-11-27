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
- **Callers** and **hot spots** (1.151.0) walk a stack upwards from a method, passing over .NET's and libraries' frames, to name
  the game, engine or mod method a piece of work belongs to, and the mods above it.
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

INDEX_FORMAT = "2"                 # 2 (1.151.0) keeps each thread's timeline; 1 is still read, without one
READABLE_FORMATS = ("1", "2")
LOOP_SHARE = 0.2                   # a method on the stack for a fifth of a thread's time or more is its loop, not a stretch of work
STALL_SHARE, STALL_SLACK_MS = 0.9, 2.0   # a deeper method covering 90% of a stretch, within 2 ms (about a sample), is its stall
CPU_FRAME = "CPU_TIME"
NATIVE_FRAME = "UNMANAGED_CODE_TIME"
CPU, NATIVE, OTHER = "cpu", "native", "other"
MOD, GAME, ENGINE, RUNTIME, LIBRARY, UNKNOWN = "mod", "game", "engine", "runtime", "library", "unknown"
# When no mod is on a stack, the first of these kinds found on it names who the time belongs to.
FALLBACK_ORDER = (GAME, ENGINE, LIBRARY, UNKNOWN, RUNTIME)

_DMD = re.compile(r"^dynamicClass\.DMD<(?P<type>.+)::(?P<method>[^>]+)>")
# Harmony 3 on .NET names a rewritten method after the original with a patch count, and the glue it adds for one by the original's
# Type:Method inside angle brackets (seen in a trace of RimWorld 1.7, 18 November 2026: "dynamicClass.Verse.TickManager.DoSingleTick_
# Patch6(pMT: ...)" and "dynamicClass.Glue:AbiFixup<Verse.AI.ThinkResult Verse.AI.Pawn_JobTracker:DetermineNextConstantThinkTreeJob(),...").
_PATCHED = re.compile(r"^dynamicClass\.(?P<method>[^(<>\s]+?)_Patch\d+$")
_GLUE = re.compile(r"^dynamicClass\.Glue:\w+<(?:[^\s:<>]+ )?(?P<type>[^\s:<>]+):(?P<method>[^(\s<>]+)\(")
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
    found = _GLUE.match(rest)
    if found:
        return module, f"{found.group('type')}.{found.group('method')}", True
    method = rest.split("(", 1)[0]
    found = _PATCHED.match(method)
    if found:
        return module, found.group("method"), True
    return module, method, False


def type_of(method):
    """Namespace.Type of Namespace.Type.Method."""
    return method.rsplit(".", 1)[0] if "." in method else ""


def method_matcher(pattern):
    """A test for a method's name (Namespace.Type.Method), case ignored. * and ? are wildcards and nothing else is: generic names
    hold brackets (List`1[System.__Canon].CopyTo). A name without wildcards matches itself, or the end of a name after a dot, so
    GenTypes.IsSealedWithCache finds Verse.GenTypes.IsSealedWithCache."""
    wanted = pattern.strip().lower()
    if "*" in wanted or "?" in wanted:
        found = re.compile("".join(".*" if c == "*" else "." if c == "?" else re.escape(c) for c in wanted), re.DOTALL)
        return lambda method: found.fullmatch(method.lower()) is not None
    return lambda method: (low := method.lower()) == wanted or low.endswith("." + wanted)


# ---- Reading a speedscope file into the index ----

SCHEMA = """
CREATE TABLE frame (id INTEGER PRIMARY KEY, name TEXT, module TEXT, method TEXT, patched INTEGER);
CREATE TABLE node (id INTEGER PRIMARY KEY, parent INTEGER, frame INTEGER);
CREATE TABLE thread (id INTEGER PRIMARY KEY, name TEXT, start_ms REAL, end_ms REAL, cpu_ms REAL, native_ms REAL);
CREATE TABLE sample (thread INTEGER, node INTEGER, kind TEXT, ms REAL);
CREATE TABLE owner (module TEXT PRIMARY KEY, kind TEXT, name TEXT);
CREATE TABLE counter (name TEXT, tags TEXT, mean REAL, max REAL, samples INTEGER);
CREATE TABLE span (thread INTEGER, start_ms REAL, end_ms REAL, node INTEGER, kind TEXT);
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
    threads, samples, spans = [], [], []
    for header, start, end in _profiles(text):
        thread = len(threads)
        totals = defaultdict(float)                # (node, kind) -> ms
        stack = []                                 # (speedscope frame, node at that depth)
        last = None
        open_span = None                           # [start, end, node, kind] of the thread's timeline so far
        for event in _EVENT.finditer(text, start, end):
            at = float(event.group("at"))
            if last is not None and stack and at > last:
                top = stack[-1][0]
                node, kind = stack[-1][1], pseudo.get(top, OTHER)
                totals[(node, kind)] += at - last
                if open_span and open_span[1] == last and open_span[2] == node and open_span[3] == kind:
                    open_span[1] = at
                else:
                    if open_span and open_span[2] >= 0:
                        spans.append((thread, *open_span))
                    open_span = [last, at, node, kind]
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
        if open_span and open_span[2] >= 0:
            spans.append((thread, *open_span))
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
        conn.executemany("INSERT INTO span VALUES (?, ?, ?, ?, ?)", spans)
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

    def add(self, kind, ms):
        if kind == CPU:
            self.cpu += ms
        else:
            self.native += ms


# Owners whose frames are passed over when asking "which game, engine or mod method was this, really": .NET's own code and the
# libraries a mod calls (Harmony), which do work on someone else's behalf.
PASS_OVER = (RUNTIME, LIBRARY)
NO_MOD = Owner(MOD, "")             # the key for "no mod on the stack" in the tables below

# What .NET's own threads do, for any .NET program (1.151.0): a game adapter lists its engine's threads first. Each is (name,
# patterns over Namespace.Type.Method); a thread takes the name whose methods hold most of its sampled time, at least ROLE_SHARE.
# Read from the owner's RimWorld recordings of 17 and 18 November 2026: Harmony's MonoMod puts its own hook round every compile,
# and the hook's thread showed as "Harmony" until named.
DOTNET_THREADS = [
    ("compiling code (the JIT), through Harmony's hook", ["MonoMod.Core.Interop.CoreCLR*.InvokeCompileMethod",
                                                         "*JitHookDelegateHolder.CompileMethodHook"]),
    ("the runtime's counters, read for this recording", ["System.Diagnostics.Tracing.CounterGroup.PollForValues",
                                                         "System.Diagnostics.Metrics.AggregationManager.CollectWorker"]),
    ("the finalizer", ["System.GC.RunFinalizers"]),
    (".NET's thread pool", ["System.Threading.PortableThreadPool*", "System.Threading.ThreadPoolWorkQueue.Dispatch",
                            "System.Threading.TimerQueue*"]),
]
ROLE_SHARE = 0.3


class Callers:
    """How the stacks running one method reach it, totalled (Recording.callers): each table is {key: Share}."""

    def __init__(self):
        self.total = Share()
        self.targets = defaultdict(Share)       # (method, Owner): the methods the name matched
        self.direct = defaultdict(Share)        # (method, Owner) just above it, or ("", None) at a thread's start
        self.owned = defaultdict(Share)         # (method, Owner): the first method above that is not .NET's or a library's
        self.inner = defaultdict(Share)         # Owner: the innermost mod above it, NO_MOD when none
        self.outer = defaultdict(Share)         # Owner: the outermost mod above it, NO_MOD when none
        self.leaf = defaultdict(Share)          # (method, Owner): where the thread was, at or below it
        self.nodes = defaultdict(Share)         # the stack's node where the method was met, for the timeline


class HotSpot:
    """Time in one game or engine method, or in .NET and library code it called (Recording.hot_spots)."""

    def __init__(self):
        self.total = Share()
        self.leaf = defaultdict(Share)          # (method, Owner) where the thread was
        self.caller = defaultdict(Share)        # (method, Owner): the first method above it not .NET's or a library's
        self.mods = defaultdict(Share)          # Owner: the innermost mod above it, NO_MOD when none


class Recording:
    """One indexed recording, read whole into memory: frames, the stack tree, time per stack and the owners of modules."""

    def __init__(self, index):
        self.index = Path(index)
        with closing(derived.open_read_only(self.index)) as conn:
            self.meta = dict(conn.execute("SELECT key, value FROM meta"))
            if self.meta.get("index_format") not in READABLE_FORMATS:
                raise SamplingError(f"{self.index} was built by another version of this tool; record again.")
            self.has_timeline = bool(conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'span'").fetchone())
            # Split again from the name, so a recording indexed by an older version reads names this one knows (Harmony 3's).
            self.frames = {r[0]: (r[1], *split_frame(r[1])) for r in conn.execute("SELECT id, name FROM frame")}
            self.parent, self.frame_of = {}, {}
            for node, parent, frame in conn.execute("SELECT id, parent, frame FROM node"):
                self.parent[node], self.frame_of[node] = parent, frame
            self.threads = {r[0]: r[1:] for r in conn.execute("SELECT id, name, start_ms, end_ms, cpu_ms, native_ms FROM thread")}
            self.samples = conn.execute("SELECT thread, node, kind, ms FROM sample").fetchall()
            self.owners = {r[0]: Owner(r[1], r[2]) for r in conn.execute("SELECT module, kind, name FROM owner")}
            self.counters = {(r[0], r[1]): (r[2], r[3], r[4]) for r in conn.execute("SELECT name, tags, mean, max, samples FROM counter")}
        self._type_owner = None
        self._labels = {}
        self._outer = {}
        self._spans = {}

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

    def thread_role(self, thread, roles):
        """The name in roles [(name, [patterns])] whose methods hold the most of a thread's sampled time, at least ROLE_SHARE of it;
        the first listed wins a tie. None when no name holds that much."""
        tests = [(name, [method_matcher(p) for p in patterns]) for name, patterns in roles]
        held, whole, memo = defaultdict(float), 0.0, {}
        for node, _, ms in self.thread_samples(thread):
            whole += ms
            if node not in memo:
                methods = [self.frames[f][2] for f in self.path(node)]
                memo[node] = [name for name, matchers in tests if any(m(method) for method in methods for m in matchers)]
            for name in memo[node]:
                held[name] += ms
        if not whole or not held:
            return None
        order = {name: i for i, (name, _) in enumerate(roles)}
        best = min(held, key=lambda name: (-held[name], order[name]))
        return best if held[best] >= ROLE_SHARE * whole else None

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

    def outermost_mod(self, node):
        """The first mod frame on the stack from the root, or None: the mod whose code led to the work."""
        if node in self._outer:
            return self._outer[node]
        chain = []
        while node >= 0 and node not in self._outer:
            chain.append(node)
            node = self.parent[node]
        found = self._outer[node] if node >= 0 else None
        for current in reversed(chain):
            if found is None:
                own = self.owner_of_frame(self.frame_of[current])
                if own.kind == MOD:
                    found = own
            self._outer[current] = found
        return found

    def mod_calls(self, samples):
        """{(outer mod, inner mod): Share} where one mod's code led into another's: the outermost and innermost mods differ."""
        result = defaultdict(Share)
        for node, kind, ms in samples:
            outer, inner = self.outermost_mod(node), self.label(node)
            if outer is None or inner.kind != MOD or outer == inner:
                continue
            share = result[(outer, inner)]
            if kind == CPU:
                share.cpu += ms
            else:
                share.native += ms
        return dict(result)

    def path(self, node):
        frames = []
        while node >= 0:
            frames.append(self.frame_of[node])
            node = self.parent[node]
        frames.reverse()
        return frames

    def nodes_up(self, node):
        """The stack's nodes from the one sampled up to the thread's start: innermost first."""
        found = []
        while node >= 0:
            found.append(node)
            node = self.parent[node]
        return found

    def method_at(self, node):
        """(method, Owner) of a stack's node."""
        frame = self.frame_of[node]
        return self.frames[frame][2], self.owner_of_frame(frame)

    def _first_owned(self, nodes):
        """The first of nodes (innermost first) whose owner is not .NET or a library, or None."""
        return next((n for n in nodes if self.owner_of_frame(self.frame_of[n]).kind not in PASS_OVER), None)

    # Where a method is reached from

    def callers(self, samples, matches):
        """Callers of the method `matches(name)` picks, from samples: what called it, the first game, engine or mod method above it,
        the mods above it and where the thread was below it. A method on a stack twice (recursion) counts from its outermost call."""
        found, memo = Callers(), {}
        for node, kind, ms in samples:
            site = memo.get(node, False)
            if site is False:
                site = memo[node] = self._call_site(node, matches)
            if site is None:
                continue
            target, direct, owned, inner, outer, leaf, at = site
            for table, key in ((found.targets, target), (found.direct, direct), (found.owned, owned), (found.inner, inner),
                               (found.outer, outer), (found.leaf, leaf), (found.nodes, at)):
                table[key].add(kind, ms)
            found.total.add(kind, ms)
        return found

    def _call_site(self, node, matches):
        ups = self.nodes_up(node)
        at = next((i for i in range(len(ups) - 1, -1, -1) if matches(self.frames[self.frame_of[ups[i]]][2])), None)
        if at is None:
            return None
        above = ups[at + 1:]
        owned = self._first_owned(above)
        inner = self.label(above[0]) if above else None
        outer = self.outermost_mod(above[0]) if above else None
        return (self.method_at(ups[at]), self.method_at(above[0]) if above else ("", None),
                self.method_at(owned) if owned is not None else ("", None),
                inner if inner is not None and inner.kind == MOD else NO_MOD, outer or NO_MOD, self.method_at(ups[0]), ups[at])

    def hot_spots(self, samples):
        """{(method, Owner): HotSpot} for game and engine methods: the time the thread spent in each, or in .NET and library code it
        called, with where the thread was, what called it and the mods above it. Caused by gives this time to the innermost mod
        above, a little to each; put back together, one slow game method that many mods call stands out."""
        found, memo = defaultdict(HotSpot), {}
        for node, kind, ms in samples:
            site = memo.get(node, False)
            if site is False:
                site = memo[node] = self._hot_site(node)
            if site is None:
                continue
            anchor, leaf, caller, mod = site
            spot = found[anchor]
            spot.total.add(kind, ms)
            spot.leaf[leaf].add(kind, ms)
            spot.caller[caller].add(kind, ms)
            spot.mods[mod].add(kind, ms)
        return dict(found)

    def _hot_site(self, node):
        ups = self.nodes_up(node)
        at = self._first_owned(ups)
        if at is None or self.owner_of_frame(self.frame_of[at]).kind not in (GAME, ENGINE):
            return None                    # a mod's own work: its busiest methods already show it
        above = ups[ups.index(at) + 1:]
        caller = self._first_owned(above)
        mod = self.label(at)
        return (self.method_at(at), self.method_at(ups[0]), self.method_at(caller) if caller is not None else ("", None),
                mod if mod.kind == MOD else NO_MOD)

    # The timeline (index format 2)

    def spans(self, thread):
        """[(start ms, end ms, node, kind)] of a thread in time order: what its stack was from one sample to the next. [] for an
        index without a timeline."""
        if not self.has_timeline:
            return []
        if thread not in self._spans:
            with closing(derived.open_read_only(self.index)) as conn:
                self._spans[thread] = conn.execute("SELECT start_ms, end_ms, node, kind FROM span WHERE thread = ? ORDER BY start_ms",
                                                   (thread,)).fetchall()
        return self._spans[thread]

    def windows(self, thread, width_ms, key):
        """[(window start ms, {key(node): Share})]: a thread's time in windows of width_ms, each span cut at the windows' edges."""
        found = defaultdict(lambda: defaultdict(Share))
        memo = {}
        for start, end, node, kind in self.spans(thread):
            if node not in memo:
                memo[node] = key(node)
            label = memo[node]
            at = start
            while at < end:
                window = int(at // width_ms)
                upto = min(end, (window + 1) * width_ms)
                found[window][label].add(kind, upto - at)
                at = upto
        return [(window * width_ms, dict(found[window])) for window in sorted(found)]

    def stretches(self, thread, keep, loop_share=LOOP_SHARE):
        """{(method, Owner): (longest ms, its start ms, how many stretches, its depth on the stack)}: how long each method stayed on a
        thread's stack with no sample outside it, for frames where keep(method, Owner). A method on the stack for loop_share of the
        thread's time or more is its loop, left out. Back-to-back calls with no sample between them look like one stretch. Nested
        methods of one stall share its start and length; the depth tells the innermost (`innermost_stretches`)."""
        spans = self.spans(thread)
        if not spans:
            return {}
        whole = sum(end - start for start, end, _, _ in spans)
        on_stack = defaultdict(float)
        paths = {}
        for start, end, node, _ in spans:
            if node not in paths:
                paths[node] = list(reversed(self.nodes_up(node)))
            for n in paths[node]:
                on_stack[n] += end - start
        loops = {n for n, ms in on_stack.items() if ms >= loop_share * whole}
        kept = {}
        found = {}
        opened = []                               # [(node, since)] root first, the frames open now
        last_end = None

        def close(upto, at):
            while len(opened) > upto:
                depth = len(opened)
                node, since = opened.pop()
                if node in loops:
                    continue
                key = kept.get(node)
                if key is None:
                    method, owner = self.method_at(node)
                    key = kept[node] = (method, owner) if keep(method, owner) else False
                if key is False:
                    continue
                length = at - since
                longest, began, count, deep = found.get(key, (0.0, 0.0, 0, 0))
                found[key] = (length, since, count + 1, depth) if length > longest else (longest, began, count + 1, deep)

        for start, end, node, _ in spans:
            if last_end is not None and start > last_end:
                close(0, last_end)                    # a gap in the samples ends every stretch
            path = paths[node]
            same = 0
            while same < len(opened) and same < len(path) and opened[same][0] == path[same]:
                same += 1
            close(same, start)
            opened.extend((n, start) for n in path[same:])
            last_end = end
        close(0, last_end)
        return found

    @staticmethod
    def innermost_stretches(found, min_ms):
        """[((method, Owner), (longest, start, count, depth), callers above it)] longest first: of the methods whose longest
        stretches are one stall, only the innermost, with how many methods above it shared it. A method is a caller in a deeper
        method's stall when the deeper one lies inside its stretch (a sample's width either side) and covers STALL_SHARE of it."""
        candidates = sorted(((key, value) for key, value in found.items() if value[0] >= min_ms), key=lambda kv: (-kv[1][3], kv[0][0]))
        kept, above = [], {}
        for key, value in candidates:
            length, start, _, depth = value
            owner = next((k for k, v in kept if v[3] > depth and v[1] >= start - STALL_SLACK_MS
                          and v[1] + v[0] <= start + length + STALL_SLACK_MS and v[0] >= STALL_SHARE * length), None)
            if owner is None:
                kept.append((key, value))
                above[key] = 0
            else:
                above[owner] += 1
        return sorted(((key, value, above[key]) for key, value in kept), key=lambda row: (-row[1][0], row[0][0]))

    def stall_owners(self, thread, node, start_ms, length_ms):
        """{Owner: ms}: who caused the time inside one stall, from every span of it under node."""
        found = defaultdict(float)
        end_ms = start_ms + length_ms
        for begin, end, leaf, _ in self.spans(thread):
            if end <= start_ms or begin >= end_ms:
                continue
            if node in self.nodes_up(leaf):
                found[self.label(leaf)] += min(end, end_ms) - max(begin, start_ms)
        return dict(found)

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
