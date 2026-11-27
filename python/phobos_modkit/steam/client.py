"""Subscribing to Workshop items (1.77.0), and uploading them (1.98.0), through the running Steam client. Game-free.

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

Uploading (1.98.0, for D'thorga Companion's Publish page; the owner's choice of 23 Nov 2026: the Steam client by default):

- `CreateItem` makes a new item and answers with `CreateItemResult_t` (callback 3403): a result code, the new item's number and
  whether the person must first accept the Workshop legal agreement.
- `StartItemUpdate` opens a change to an item; `SetItemTitle`, `SetItemDescription`, `SetItemVisibility`, `SetItemTags`,
  `SetItemContent` (a folder) and `SetItemPreview` (a file) fill it in; `SubmitItemUpdate` sends it with its change note and
  answers with `SubmitItemUpdateResult_t` (3404). `GetItemUpdateProgress` says how far it has got.
- `AddDependency` sets a Required item, answering with `AddUGCDependencyResult_t` (3412).
- Answers are read with `ISteamUtils::GetAPICallResult` into structures laid out as Valve's headers lay them out: 8-byte packing
  on Windows, 4 on Linux and macOS. This is the one place the tools assume a structure's layout; a test holds it, and the first
  real upload confirms it.

**Agents never call this on the owner's account** (phobos-rimworld's rule for the Workshop): the tools subscribe and upload only
on the person's own press. Tests hand in a stand-in library.
"""
from __future__ import annotations

import ctypes
import os
from pathlib import Path
import sys
import time

SUBSCRIBED, LEGACY, INSTALLED, NEEDS_UPDATE, DOWNLOADING, DOWNLOAD_PENDING = 1, 2, 4, 8, 16, 32
INIT_OK = 0
CALL_SECONDS = 30            # the longest one subscribe or unsubscribe call is waited for (agent default)
PUMP_SECONDS = 0.1
ERROR_TEXT = 1024            # SteamErrMsg's size
UGC_VERSIONS = ("SteamAPI_SteamUGC_v021", "SteamAPI_SteamUGC_v020", "SteamAPI_SteamUGC_v018", "SteamAPI_SteamUGC_v017")
UTILS_VERSIONS = ("SteamAPI_SteamUtils_v010", "SteamAPI_SteamUtils_v009")

# Uploading (1.98.0): Valve's numbers, from the Steamworks headers (isteamugc.h, steamclientpublic.h).
RESULT_OK = 1                                  # EResult k_EResultOK
WORKSHOP_FILE_COMMUNITY = 0                    # EWorkshopFileType k_EWorkshopFileTypeCommunity
CREATE_ITEM_RESULT, SUBMIT_ITEM_RESULT, ADD_DEPENDENCY_RESULT = 3403, 3404, 3412
UPDATE_STATUS = {1: "Preparing the item", 2: "Preparing the files", 3: "Uploading the files", 4: "Uploading the cover",
                 5: "Steam is saving the change"}
UPLOAD_SECONDS = 3600        # the longest a create or an upload is waited for (agent default)
PACK = 4 if sys.platform in ("linux", "darwin") else 8


class CreateItemResult(ctypes.Structure):
    _pack_ = PACK
    _fields_ = [("result", ctypes.c_int32), ("item", ctypes.c_uint64), ("needs_agreement", ctypes.c_bool)]


class SubmitItemUpdateResult(ctypes.Structure):
    _pack_ = PACK
    _fields_ = [("result", ctypes.c_int32), ("needs_agreement", ctypes.c_bool), ("item", ctypes.c_uint64)]


class AddDependencyResult(ctypes.Structure):
    _pack_ = PACK
    _fields_ = [("result", ctypes.c_int32), ("parent", ctypes.c_uint64), ("child", ctypes.c_uint64)]


class StringArray(ctypes.Structure):
    """SteamParamStringArray_t: the tags handed to SetItemTags."""
    _fields_ = [("strings", ctypes.POINTER(ctypes.c_char_p)), ("count", ctypes.c_int32)]


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

    def bind_upload(self):
        """The upload functions, bound only when an upload needs them, so Subscribe works with an older library."""
        u64, u32, boolean, ptr, text, i32 = (ctypes.c_uint64, ctypes.c_uint32, ctypes.c_bool, ctypes.c_void_p,
                                             ctypes.c_char_p, ctypes.c_int)
        self._bind("SteamAPI_ISteamUGC_CreateItem", u64, [ptr, u32, i32])
        self._bind("SteamAPI_ISteamUGC_StartItemUpdate", u64, [ptr, u32, u64])
        for name in ("SetItemTitle", "SetItemDescription", "SetItemContent", "SetItemPreview"):
            self._bind(f"SteamAPI_ISteamUGC_{name}", boolean, [ptr, u64, text])
        self._bind("SteamAPI_ISteamUGC_SetItemVisibility", boolean, [ptr, u64, i32])
        # Newer libraries take a third argument (allow admin tags); an older one ignores it.
        self._bind("SteamAPI_ISteamUGC_SetItemTags", boolean, [ptr, u64, ctypes.POINTER(StringArray), boolean])
        self._bind("SteamAPI_ISteamUGC_SubmitItemUpdate", u64, [ptr, u64, text])
        self._bind("SteamAPI_ISteamUGC_GetItemUpdateProgress", i32, [ptr, u64, ctypes.POINTER(u64), ctypes.POINTER(u64)])
        self._bind("SteamAPI_ISteamUGC_AddDependency", u64, [ptr, u64, u64])
        self._bind("SteamAPI_ISteamUtils_GetAPICallResult", boolean, [ptr, u64, ptr, i32, i32, ctypes.POINTER(boolean)])
        return self

    # -- the calls, in plain Python terms

    def create_item(self, ugc, app_id):
        return self.SteamAPI_ISteamUGC_CreateItem(ugc, int(app_id), WORKSHOP_FILE_COMMUNITY)

    def start_update(self, ugc, app_id, item):
        return self.SteamAPI_ISteamUGC_StartItemUpdate(ugc, int(app_id), int(item))

    def set_text(self, ugc, handle, what, value):
        """what is Title, Description, Content (a folder) or Preview (a file)."""
        return bool(getattr(self, f"SteamAPI_ISteamUGC_SetItem{what}")(ugc, handle, str(value).encode("utf-8")))

    def set_visibility(self, ugc, handle, visibility):
        return bool(self.SteamAPI_ISteamUGC_SetItemVisibility(ugc, handle, int(visibility)))

    def set_tags(self, ugc, handle, tags):
        encoded = [str(t).encode("utf-8") for t in tags]
        array = StringArray((ctypes.c_char_p * len(encoded))(*encoded) if encoded else None, len(encoded))
        return bool(self.SteamAPI_ISteamUGC_SetItemTags(ugc, handle, ctypes.byref(array), False))

    def submit(self, ugc, handle, note):
        return self.SteamAPI_ISteamUGC_SubmitItemUpdate(ugc, handle, str(note).encode("utf-8"))

    def update_progress(self, ugc, handle):
        """(status number, bytes so far, bytes in all) of an upload under way."""
        done, total = ctypes.c_uint64(0), ctypes.c_uint64(0)
        status = self.SteamAPI_ISteamUGC_GetItemUpdateProgress(ugc, handle, ctypes.byref(done), ctypes.byref(total))
        return int(status), int(done.value), int(total.value)

    def add_dependency(self, ugc, parent, child):
        return self.SteamAPI_ISteamUGC_AddDependency(ugc, int(parent), int(child))

    def call_result(self, utils, call, structure, callback):
        """The finished call's answer as a structure, or None when Steam has none."""
        answer, failed = structure(), ctypes.c_bool(False)
        got = self.SteamAPI_ISteamUtils_GetAPICallResult(utils, call, ctypes.byref(answer), ctypes.sizeof(structure),
                                                         callback, ctypes.byref(failed))
        return answer if got and not failed.value else None

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

    def _wait(self, call, seconds=CALL_SECONDS, tick=None):
        if not call:
            return False
        ends = self.clock() + seconds
        while self.clock() < ends:
            self.library.pump()
            done, failed = self.library.completed(self.utils, call)
            if done:
                return not failed
            if tick:
                tick()
            self.sleep(PUMP_SECONDS)
        return False

    def answer(self, call, structure, callback, seconds=CALL_SECONDS, tick=None):
        """Wait for a call, then its answer as a structure; None when it failed, timed out or has none."""
        if not self._wait(call, seconds, tick):
            return None
        return self.library.call_result(self.utils, call, structure, callback)

    def state(self, item):
        return self.library.state(self.ugc, int(item))

    def subscribe(self, item):
        """Subscribes and asks for the download now; True when Steam then says it is subscribed."""
        self._wait(self.library.subscribe(self.ugc, int(item)))
        subscribed = bool(self.state(item) & SUBSCRIBED)
        if subscribed:
            self.library.download(self.ugc, int(item))
        return subscribed

    def download(self, item):
        """Asks Steam to download a subscribed item now, at high priority (1.147.0); True when Steam took the request."""
        return bool(self.library.download(self.ugc, int(item)))

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
