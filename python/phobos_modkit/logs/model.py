"""The data a log adapter produces and the triage works on."""
from __future__ import annotations

from dataclasses import dataclass, field

# Levels in reporting order. An adapter may use others; they sort after these.
LEVEL_ORDER = ("FATAL", "ERROR", "WARN", "UNKNOWN", "INFO", "DEBUG", "TRACE")

# Evidence kinds, strongest first: what each says about a mod's part in a message.
EVIDENCE_KINDS = (
    "source",     # the log line names the mod outright
    "file",       # a file path inside the mod's folder appears in the message
    "assembly",   # the mod's assembly appears in the exception's own stack trace
    "namespace",  # the mod's code namespace appears in the exception's own stack trace
    "caller",     # the mod's code is on the stack that wrote the message (no exception trace)
    "patch",      # the mod patches a method on the stack; involved, rarely the cause
    "finalizer",  # the mod's finalizer patch is on the stack; it can hide where an exception began
)


@dataclass(frozen=True)
class Evidence:
    """One clue about a mod's part in a message."""
    kind: str
    value: str
    mod: str = ""  # the mod's display name, when an index could resolve value

    @property
    def rank(self):
        return EVIDENCE_KINDS.index(self.kind) if self.kind in EVIDENCE_KINDS else len(EVIDENCE_KINDS)


@dataclass
class Entry:
    """One logged message: its first line and everything that follows until the next message."""
    line: int                      # 1-based line number of the first line
    level: str                     # FATAL, ERROR, WARN, INFO, ... or UNKNOWN when the log has no levels
    category: str                  # the logger's category, "" when none
    headline: str                  # the text that names the message (an adapter may join two lines)
    body: list = field(default_factory=list)       # every later line of the entry, as written
    time: str = ""                 # as written, "" when the log has no times
    evidence: list = field(default_factory=list)   # Evidence, strongest kind first, then in the order found
    fingerprint: str = ""          # the exception behind the message, when the adapter can tell; "" otherwise

    @property
    def line_count(self):
        return 1 + len(self.body)


@dataclass
class Notice:
    """A fact about the whole log that a reader should see before the message tables."""
    kind: str        # stable machine key
    text: str        # one complete English sentence or two
    data: dict = field(default_factory=dict)


@dataclass
class LogFile:
    """A parsed log: what the adapter found."""
    name: str
    layout: str                    # the adapter's name for the log's layout, e.g. "rimworld-1.7"
    entries: list
    header: dict = field(default_factory=dict)
    notices: list = field(default_factory=list)
    limits: list = field(default_factory=list)   # sentences on what this parse cannot see
    line_total: int = 0
