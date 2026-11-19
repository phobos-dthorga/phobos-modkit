"""A running program's memory, read from outside through the operating system: how much it holds, and what kind.

Two readings, neither of which stops, pauses or changes the program:

- **Figures** (`figures`): the memory the program has claimed (Windows' commit charge, "private bytes"), what of it sits in
  RAM now (the working set), and the machine's free RAM. Windows: `GetProcessMemoryInfo` and `GlobalMemoryStatusEx`
  (Microsoft, https://learn.microsoft.com/windows/win32/api/psapi/nf-psapi-getprocessmemoryinfo). Linux: `/proc/<pid>/status`
  and `/proc/meminfo` (the kernel's proc(5) manual page), where the anonymous resident memory plus swap stands in for private
  bytes.
- **The memory map** (`memory_map`, Windows only): every region of the program's address space, from `VirtualQueryEx`
  (https://learn.microsoft.com/windows/win32/api/memoryapi/nf-memoryapi-virtualqueryex), summed by kind: private memory
  (the program's own heaps, its runtime's heap, an engine's allocators, a graphics driver's buffers), loaded code files
  (images) and mapped files. Private memory is also summed by **block** (the allocation each region was carved from), so a
  block that keeps growing shows itself between two maps. Code files and mapped files are named by their file name only,
  never their folder. This is the view Microsoft's VMMap shows on screen (Sysinternals).

Asking for these needs only the rights any program of the same user has (`PROCESS_QUERY_INFORMATION`, `PROCESS_VM_READ`); no
memory of the program is read. Nothing here names a game.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import os
from pathlib import Path
import sys

PRIVATE, IMAGE, MAPPED = "private", "image", "mapped"
KINDS = (PRIVATE, IMAGE, MAPPED)
NO_FILE = "(no file)"           # a mapped section without a file: shared memory, or a driver's section
BLOCKS_KEPT = 40                # the largest private blocks a map keeps; the rest are summed


class MemoryError_(RuntimeError):
    """The program could not be read: it has gone, or the system refused."""


@dataclass(frozen=True)
class Figures:
    private: int            # bytes the program has claimed (commit charge); on Linux anonymous resident + swap
    working_set: int        # bytes of it in RAM now
    peak_working_set: int   # the most it ever had in RAM (0 where the system does not keep it)
    free_ram: int           # the machine's RAM free for programs
    total_ram: int


@dataclass(frozen=True)
class Region:
    base: int
    allocation: int          # the base of the allocation (block) it was carved from
    size: int
    committed: bool
    kind: str                # PRIVATE, IMAGE or MAPPED
    file: str = ""           # an image's or mapped file's name, without its folder


@dataclass
class Map:
    committed: dict = field(default_factory=dict)      # {kind: bytes committed}
    reserved: dict = field(default_factory=dict)       # {kind: bytes reserved but not committed}
    blocks: list = field(default_factory=list)         # [(allocation base, committed, size of the whole block)], largest first
    blocks_rest: int = 0                               # committed bytes in private blocks beyond the ones kept
    files: dict = field(default_factory=dict)          # {(kind, file name): committed bytes} for images and mapped files
    sizes: dict = field(default_factory=dict)          # {size class: [blocks, committed bytes]} of private blocks
    regions: int = 0


MB = 1 << 20
# Private blocks by the size of the whole block (reserved), smallest first: (label, upper bound in bytes, exclusive).
SIZE_CLASSES = (("under 1 MB", MB), ("1-16 MB", 16 * MB), ("16-64 MB", 64 * MB), ("64-256 MB", 256 * MB),
                ("256 MB-1 GB", 1024 * MB), ("1-16 GB", 16384 * MB), ("16 GB and over", None))


def size_class(block_size):
    return next(label for label, bound in SIZE_CLASSES if bound is None or block_size < bound)


def summarise(regions, keep=BLOCKS_KEPT):
    """A Map from regions: committed and reserved bytes by kind, private memory by block and by block size, code and mapped
    files by name."""
    result = Map(committed={k: 0 for k in KINDS}, reserved={k: 0 for k in KINDS})
    blocks = {}
    for region in regions:
        result.regions += 1
        if region.committed:
            result.committed[region.kind] += region.size
        else:
            result.reserved[region.kind] += region.size
        if region.kind == PRIVATE:
            entry = blocks.setdefault(region.allocation, [0, 0])
            entry[1] += region.size
            if region.committed:
                entry[0] += region.size
        elif region.committed:
            key = (region.kind, region.file or NO_FILE)
            result.files[key] = result.files.get(key, 0) + region.size
    ordered = sorted(((base, c, s) for base, (c, s) in blocks.items() if c), key=lambda b: (-b[1], b[0]))
    result.sizes = {label: [0, 0] for label, _ in SIZE_CLASSES}
    for _, committed, whole in ordered:
        entry = result.sizes[size_class(whole)]
        entry[0] += 1
        entry[1] += committed
    result.blocks = ordered[:keep]
    result.blocks_rest = sum(c for _, c, _ in ordered[keep:])
    return result


def file_name(device_path):
    """The file name from a Windows device path such as \\Device\\HarddiskVolume3\\Games\\x.dll; never its folders."""
    return device_path.replace("/", "\\").rsplit("\\", 1)[-1] if device_path else ""


# ---- Linux ----

def parse_status(text):
    """{field: bytes} from /proc/<pid>/status, for the fields given in kB."""
    values = {}
    for line in text.splitlines():
        key, _, rest = line.partition(":")
        parts = rest.split()
        if len(parts) == 2 and parts[1] == "kB" and parts[0].isdigit():
            values[key.strip()] = int(parts[0]) * 1024
    return values


def linux_figures(status_text, meminfo_text):
    status, meminfo = parse_status(status_text), parse_status(meminfo_text)
    return Figures(private=status.get("RssAnon", 0) + status.get("VmSwap", 0), working_set=status.get("VmRSS", 0),
                   peak_working_set=status.get("VmHWM", 0), free_ram=meminfo.get("MemAvailable", 0),
                   total_ram=meminfo.get("MemTotal", 0))


# ---- Windows ----

def _windows():
    import ctypes
    from ctypes import wintypes

    class MemoryCounters(ctypes.Structure):
        _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD), ("PeakWorkingSetSize", ctypes.c_size_t),
                    ("WorkingSetSize", ctypes.c_size_t), ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPagedPoolUsage", ctypes.c_size_t), ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaNonPagedPoolUsage", ctypes.c_size_t), ("PagefileUsage", ctypes.c_size_t),
                    ("PeakPagefileUsage", ctypes.c_size_t), ("PrivateUsage", ctypes.c_size_t)]

    class MemoryStatus(ctypes.Structure):
        _fields_ = [("dwLength", wintypes.DWORD), ("dwMemoryLoad", wintypes.DWORD), ("ullTotalPhys", ctypes.c_uint64),
                    ("ullAvailPhys", ctypes.c_uint64), ("ullTotalPageFile", ctypes.c_uint64), ("ullAvailPageFile", ctypes.c_uint64),
                    ("ullTotalVirtual", ctypes.c_uint64), ("ullAvailVirtual", ctypes.c_uint64),
                    ("ullAvailExtendedVirtual", ctypes.c_uint64)]

    class BasicInformation(ctypes.Structure):
        _fields_ = [("BaseAddress", ctypes.c_void_p), ("AllocationBase", ctypes.c_void_p), ("AllocationProtect", wintypes.DWORD),
                    ("PartitionId", wintypes.WORD), ("RegionSize", ctypes.c_size_t), ("State", wintypes.DWORD),
                    ("Protect", wintypes.DWORD), ("Type", wintypes.DWORD)]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    psapi = ctypes.WinDLL("psapi", use_last_error=True)
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.VirtualQueryEx.restype = ctypes.c_size_t
    kernel32.VirtualQueryEx.argtypes = [wintypes.HANDLE, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t]
    kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD]
    psapi.GetMappedFileNameW.restype = wintypes.DWORD
    psapi.GetMappedFileNameW.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.LPWSTR, wintypes.DWORD]
    kernel32.GlobalMemoryStatusEx.argtypes = [ctypes.c_void_p]
    return ctypes, wintypes, kernel32, psapi, MemoryCounters, MemoryStatus, BasicInformation


QUERY_INFORMATION, VM_READ = 0x0400, 0x0010
MEM_COMMIT, MEM_FREE = 0x1000, 0x10000
TYPES = {0x20000: PRIVATE, 0x1000000: IMAGE, 0x40000: MAPPED}
STILL_ACTIVE = 259


class Process:
    """An open handle to a running program, for reading its memory figures and map again and again. Use with `with`."""

    def __init__(self, pid, platform=None):
        self.pid = int(pid)
        self.platform = platform or sys.platform
        self.handle = None
        if self.platform == "win32":
            self._api = _windows()
            kernel32 = self._api[2]
            self.handle = kernel32.OpenProcess(QUERY_INFORMATION | VM_READ, False, self.pid)
            if not self.handle:
                raise MemoryError_(f"Program {self.pid} could not be opened (Windows error {self._api[0].get_last_error()}): "
                                   "it may have closed, or it runs as another user.")
        elif not Path(f"/proc/{self.pid}/status").is_file():
            raise MemoryError_(f"Program {self.pid} is not running (no /proc/{self.pid}/status).")

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def close(self):
        if self.handle:
            self._api[2].CloseHandle(self.handle)
            self.handle = None

    def running(self):
        if self.platform != "win32":
            return Path(f"/proc/{self.pid}/status").is_file()
        ctypes, wintypes, kernel32 = self._api[0], self._api[1], self._api[2]
        code = wintypes.DWORD()
        return bool(kernel32.GetExitCodeProcess(self.handle, ctypes.byref(code))) and code.value == STILL_ACTIVE

    def figures(self):
        if self.platform != "win32":
            try:
                return linux_figures(Path(f"/proc/{self.pid}/status").read_text(), Path("/proc/meminfo").read_text())
            except OSError as gone:
                raise MemoryError_(f"Program {self.pid} could not be read: {gone}") from gone
        ctypes, _, kernel32, psapi, MemoryCounters, MemoryStatus, _ = self._api
        counters = MemoryCounters()
        counters.cb = ctypes.sizeof(counters)
        if not psapi.GetProcessMemoryInfo(self.handle, ctypes.byref(counters), counters.cb):
            raise MemoryError_(f"Program {self.pid}'s memory could not be read (Windows error {ctypes.get_last_error()}).")
        status = MemoryStatus()
        status.dwLength = ctypes.sizeof(status)
        kernel32.GlobalMemoryStatusEx(ctypes.byref(status))
        return Figures(private=counters.PrivateUsage, working_set=counters.WorkingSetSize,
                       peak_working_set=counters.PeakWorkingSetSize, free_ram=status.ullAvailPhys, total_ram=status.ullTotalPhys)

    def regions(self):
        """Every region of the address space that is not free. Windows only."""
        if self.platform != "win32":
            raise MemoryError_("The memory map is read on Windows only.")
        ctypes, wintypes, kernel32, psapi, _, _, BasicInformation = self._api
        info = BasicInformation()
        size = ctypes.sizeof(info)
        names, buffer = {}, ctypes.create_unicode_buffer(1024)
        address, found = 0, []
        while kernel32.VirtualQueryEx(self.handle, ctypes.c_void_p(address), ctypes.byref(info), size):
            base, length = info.BaseAddress or 0, info.RegionSize
            if info.State != MEM_FREE:
                kind = TYPES.get(info.Type, PRIVATE)
                allocation = info.AllocationBase or 0
                name = ""
                if kind != PRIVATE:
                    if allocation not in names:
                        got = psapi.GetMappedFileNameW(self.handle, ctypes.c_void_p(allocation), buffer, len(buffer))
                        names[allocation] = file_name(buffer.value[:got]) if got else ""
                    name = names[allocation]
                found.append(Region(base, allocation, length, info.State == MEM_COMMIT, kind, name))
            following = base + length
            if following <= address:
                break
            address = following
        return found


def figures(pid, platform=None):
    with Process(pid, platform) as process:
        return process.figures()


def memory_map(pid, platform=None):
    with Process(pid, platform) as process:
        return summarise(process.regions())


def own_pid():
    return os.getpid()
