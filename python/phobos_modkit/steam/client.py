"""Subscribing to Workshop items through the running Steam client, as RimSort does (1.77.0). Game-free.

Step 5 of D'thorga Companion's own mod manager (the owner, 22 Nov 2026: "Start step 5, subscribing through Steam"; their choice on
a question card: through Steam, at once, with the game's own Steam library). **No credentials are held or asked for**: Steamworks
speaks to the Steam client already running and signed in on this PC, as the game itself would.

How it works, from Valve's Steamworks flat API (steam_api_flat.h; the functions are those RimWorld 1.7's own steam_api64.dll
exports, read 22 Nov 2026):

- `SteamAPI_InitFlat` joins the running client as the game (the `SteamAppId` variable names it), so for as long as this runs Steam
  shows the person as playing the game. `SteamAPI_Shutdown` leaves at once afterwards.
- `ISteamUGC::SubscribeItem` / `UnsubscribeItem` each start a call; `ISteamUtils::IsAPICallCompleted` says when it is done, pumped
  by `SteamAPI_RunCallbacks`. Whether it worked is read back from `GetItemState` (1 subscribed, 4 installed, 8 needs an update,
  16 downloading, 32 waiting to download), not from the call's result structure, so no structure layout is assumed.
- `DownloadItem` asks for a subscribed item now, and `GetItemDownloadInfo` gives its bytes so far and in all.

**Agents never call this on the owner's account** (phobos-rimworld's rule for the Workshop): the tools subscribe only on the
person's own press. Tests hand in a stand-in library.
"""
from __future__ import annotations

import ctypes
import os
from pathlib import Path
import time

SUBSCRIBED, LEGACY, INSTALLED, NEEDS_UPDATE, DOWNLOADING, DOWNLOAD_PENDING = 1, 2, 4, 8, 16, 32
INIT_OK = 0
CALL_SECONDS = 30            # the longest one subscribe or unsubscribe call is waited for (agent default)
PUMP_SECONDS = 0.1
ERROR_TEXT = 1024            # SteamErrMsg's size
UGC_VERSIONS = ("SteamAPI_SteamUGC_v021", "SteamAPI_SteamUGC_v020", "SteamAPI_SteamUGC_v018", "SteamAPI_SteamUGC_v017")
UTILS_VERSIONS = ("SteamAPI_SteamUtils_v010", "SteamAPI_SteamUtils_v009")


class SteamError(RuntimeError):
    """Steam could not be asked, in words for the person who pressed."""


def state_words(state):
    if state & DOWNLOADING:
        return "downloading"
    if state & DOWNLOAD_PENDING:
        return "waiting to download"
    if state & SUBSCRIBED and state & INSTALLED:
        return "needs an update" if state & NEEDS_UPDATE else "installed"
    if state & SUBSCRIBED:
        return "subscribed"
    return "not subscribed"


class Library:
    """The flat Steamworks functions this module uses, bound with their types from a steam_api library."""

    def __init__(self, path):
        try:
            self.dll = ctypes.CDLL(str(path))
        except OSError as error:
            raise SteamError(f"The game's Steam library could not be loaded ({error}).") from error
        u64, boolean, ptr = ctypes.c_uint64, ctypes.c_bool, ctypes.c_void_p
        self._bind("SteamAPI_InitFlat", ctypes.c_int, [ctypes.c_char_p])
        self._bind("SteamAPI_Shutdown", None, [])
        self._bind("SteamAPI_RunCallbacks", None, [])
        self._bind("SteamAPI_IsSteamRunning", boolean, [])
        self._bind("SteamAPI_ISteamUGC_SubscribeItem", u64, [ptr, u64])
        self._bind("SteamAPI_ISteamUGC_UnsubscribeItem", u64, [ptr, u64])
        self._bind("SteamAPI_ISteamUGC_GetItemState", ctypes.c_uint32, [ptr, u64])
        self._bind("SteamAPI_ISteamUGC_DownloadItem", boolean, [ptr, u64, boolean])
        self._bind("SteamAPI_ISteamUGC_GetItemDownloadInfo", boolean, [ptr, u64, ctypes.POINTER(u64), ctypes.POINTER(u64)])
        self._bind("SteamAPI_ISteamUtils_IsAPICallCompleted", boolean, [ptr, u64, ctypes.POINTER(boolean)])
        self.ugc_accessor = self._first(UGC_VERSIONS)
        self.utils_accessor = self._first(UTILS_VERSIONS)

    def _bind(self, name, restype, argtypes):
        try:
            function = getattr(self.dll, name)
        except AttributeError as error:
            raise SteamError(f"The game's Steam library has no {name}: it may be too old or too new for the tools.") from error
        function.restype = restype
        function.argtypes = argtypes
        setattr(self, name, function)

    def _first(self, names):
        for name in names:
            function = getattr(self.dll, name, None)
            if function is not None:
                function.restype = ctypes.c_void_p
                function.argtypes = []
                return function
        raise SteamError("The game's Steam library has none of the interface versions the tools know.")

    # -- the calls, in plain Python terms

    def init(self):
        message = ctypes.create_string_buffer(ERROR_TEXT)
        result = self.SteamAPI_InitFlat(message)
        return result, message.value.decode("utf-8", errors="replace")

    def shutdown(self):
        self.SteamAPI_Shutdown()

    def pump(self):
        self.SteamAPI_RunCallbacks()

    def ugc(self):
        return self.ugc_accessor()

    def utils(self):
        return self.utils_accessor()

    def subscribe(self, ugc, item):
        return self.SteamAPI_ISteamUGC_SubscribeItem(ugc, item)

    def unsubscribe(self, ugc, item):
        return self.SteamAPI_ISteamUGC_UnsubscribeItem(ugc, item)

    def state(self, ugc, item):
        return int(self.SteamAPI_ISteamUGC_GetItemState(ugc, item))

    def download(self, ugc, item):
        return bool(self.SteamAPI_ISteamUGC_DownloadItem(ugc, item, True))

    def progress(self, ugc, item):
        done, total = ctypes.c_uint64(0), ctypes.c_uint64(0)
        if not self.SteamAPI_ISteamUGC_GetItemDownloadInfo(ugc, item, ctypes.byref(done), ctypes.byref(total)):
            return 0, 0
        return int(done.value), int(total.value)

    def completed(self, utils, call):
        failed = ctypes.c_bool(False)
        done = bool(self.SteamAPI_ISteamUtils_IsAPICallCompleted(utils, call, ctypes.byref(failed)))
        return done, bool(failed.value)


class Session:
    """The running Steam client, joined as one game for as long as the `with` lasts."""

    def __init__(self, library, app_id, environ=None, clock=time.monotonic, sleep=time.sleep):
        self.library = library
        self.app_id = int(app_id)
        self.environ = os.environ if environ is None else environ
        self.clock, self.sleep = clock, sleep
        self.ugc = self.utils = None

    def __enter__(self):
        # Steamworks reads which game it speaks for from these, in this process only.
        self.environ["SteamAppId"] = str(self.app_id)
        self.environ["SteamGameId"] = str(self.app_id)
        result, message = self.library.init()
        if result != INIT_OK:
            raise SteamError("Steam could not be reached: is it running and signed in? "
                             + (f"Steam said: {message}" if message else f"(code {result})"))
        self.ugc, self.utils = self.library.ugc(), self.library.utils()
        if not self.ugc or not self.utils:
            self.library.shutdown()
            raise SteamError("Steam answered, but without its Workshop: try again once Steam has finished starting.")
        return self

    def __exit__(self, *_):
        self.library.shutdown()

    def _wait(self, call):
        if not call:
            return False
        ends = self.clock() + CALL_SECONDS
        while self.clock() < ends:
            self.library.pump()
            done, failed = self.library.completed(self.utils, call)
            if done:
                return not failed
            self.sleep(PUMP_SECONDS)
        return False

    def state(self, item):
        return self.library.state(self.ugc, int(item))

    def subscribe(self, item):
        """Subscribes and asks for the download now; True when Steam then says it is subscribed."""
        self._wait(self.library.subscribe(self.ugc, int(item)))
        subscribed = bool(self.state(item) & SUBSCRIBED)
        if subscribed:
            self.library.download(self.ugc, int(item))
        return subscribed

    def unsubscribe(self, item):
        """Unsubscribes; True when Steam then says it is no longer subscribed."""
        self._wait(self.library.unsubscribe(self.ugc, int(item)))
        return not self.state(item) & SUBSCRIBED

    def progress(self, items):
        """(bytes so far, bytes in all, items installed) over the items, pumping Steam once."""
        self.library.pump()
        done = total = installed = 0
        for item in items:
            state = self.state(item)
            if state & INSTALLED and not state & (DOWNLOADING | DOWNLOAD_PENDING | NEEDS_UPDATE):
                installed += 1
                continue
            got, size = self.library.progress(self.ugc, int(item))
            done += got
            total += size
        return done, total, installed


def library_path(game_folder, names=("steam_api64.dll", "steam_api.dll", "libsteam_api.so", "libsteam_api.dylib")):
    """The game's own Steam library: the first of the usual names in its folder or one level down."""
    folder = Path(game_folder)
    for name in names:
        for candidate in [folder / name] + sorted(folder.glob(f"*/{name}")) + sorted(folder.glob(f"*/*/{name}")):
            if candidate.is_file():
                return candidate
    return None
