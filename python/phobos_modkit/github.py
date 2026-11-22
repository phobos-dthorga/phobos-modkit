"""GitHub, read keyless, paced and cached: repository links in text, a repository's facts and files, and a search.

Game-free. Never logs in or sends a token: GitHub allows a keyless client 60 API calls an hour and 10 searches a minute,
so calls are paced and every answer is cached (in the kit's cache, as fetched pages). Raw files come from
raw.githubusercontent.com, outside the API's hourly count. The network is passed in, so tests never reach GitHub.

One hourly allowance for every tool (1.89.0): each API answer says how many calls are left this hour and when the hour turns,
and the reader keeps the latest in its cache, so every tool sees the same figure. A client made `automatic` (a look nobody
pressed for, such as D'thorga Companion's gate lights) asks nothing once AUTOMATIC_FLOOR or fewer are left, so a press always
has room; any client stops asking at none. A cached answer gone stale is asked for again with its ETag. **For a keyless client
GitHub counts the "not modified" answer as a call** (measured 23 Nov 2026: two such answers and one new one took the allowance
from 57 to 54; GitHub documents them free only for signed-in calls), so an ETag saves the download, not the call: a tool saves
calls by deciding when to ask. A client made `keep_last` gives the last answer it has, with its age in `stale`, when GitHub
cannot be reached or asked.
"""
from __future__ import annotations

from contextlib import closing
import json
import re
import sqlite3
import time
import urllib.error
import urllib.parse
import urllib.request

from . import __version__
from . import cache as derived
from .steam.workshop import Pacer

API = "https://api.github.com"
RAW = "https://raw.githubusercontent.com"
# A generic client name: GitHub asks every client for one, and nothing personal belongs in it.
USER_AGENT = "phobos-modkit"
TIMEOUT_SECONDS = 30
CACHE_FOLDER = "github"
INDEX_NAME = "github.sqlite"
MAX_AGE_HOURS = 24 * 7
SEARCH_PAUSE_SECONDS = 7      # 10 searches a minute for a keyless client
API_PAUSE_SECONDS = 1
RAW_PAUSE_SECONDS = 0.5
# An automatic look asks nothing once this many API calls or fewer are left this hour, keeping them for a press (agent default,
# D'thorga Companion docs/online.md).
AUTOMATIC_FLOOR = 15
# owner/repo in a GitHub address; the parts GitHub never uses as a repository name are left out after it.
LINK = re.compile(r"github\.com[/:]([A-Za-z0-9](?:[A-Za-z0-9-]{0,38}))/([A-Za-z0-9._-]+)", re.I)
NOT_OWNERS = {"orgs", "settings", "sponsors", "topics", "marketplace", "features", "about", "login", "users", "apps"}


class GitHubError(RuntimeError):
    pass


class RateLimited(GitHubError):
    pass


def links(text):
    """owner/repo for every GitHub repository address in text, in order of first appearance, without .git or what
    follows the repository (a wiki, a file, a release)."""
    found = []
    for owner, repo in LINK.findall(text or ""):
        repo = re.sub(r"\.git$", "", repo).rstrip(".")
        if owner.lower() in NOT_OWNERS or not repo:
            continue
        name = f"{owner}/{repo}"
        if name.lower() not in {f.lower() for f in found}:
            found.append(name)
    return found


def http_get(url, timeout=TIMEOUT_SECONDS, headers=None):
    """(status, body bytes, headers dict); HTTP errors (and 304, not modified) return their status instead of raising."""
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/vnd.github+json",
                                                   **(headers or {})})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.read(), dict(response.headers)
    except urllib.error.HTTPError as error:
        return error.code, error.read(), dict(error.headers or {})
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        raise GitHubError(f"GitHub could not be reached: {error}") from None


class Client:
    """Cached, paced reads. get(url) -> (status, body bytes, headers) is the network, passed in for tests."""

    def __init__(self, cache, get=http_get, sleep=time.sleep, clock=time.time, max_age_hours=MAX_AGE_HOURS, refresh=False,
                 automatic=False, keep_last=False):
        self.cache, self.get, self.clock = cache, get, clock
        self.max_age = max_age_hours * 3600
        self.refresh = refresh
        self.automatic, self.keep_last = automatic, keep_last
        self.pacers = {kind: Pacer(sleep=sleep, pause=pause, backoff=0)
                       for kind, pause in (("search", SEARCH_PAUSE_SECONDS), ("api", API_PAUSE_SECONDS), ("raw", RAW_PAUSE_SECONDS))}
        self.fetched = 0
        self.reused = 0
        self.revalidated = 0     # stale answers GitHub said were unchanged (304)
        self.stale = []          # fetched_at of each last answer given because GitHub could not be reached or asked
        self.limited = None

    def _connect(self):
        self.cache.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.cache / INDEX_NAME)
        conn.execute("CREATE TABLE IF NOT EXISTS page (url TEXT PRIMARY KEY, fetched_at INTEGER, status INTEGER, body BLOB)")
        if "etag" not in {column[1] for column in conn.execute("PRAGMA table_info(page)")}:   # caches made before 1.87.0
            conn.execute("ALTER TABLE page ADD COLUMN etag TEXT")
        conn.execute("CREATE TABLE IF NOT EXISTS allowance (id INTEGER PRIMARY KEY CHECK (id = 1), remaining INTEGER, "
                     "size INTEGER, reset INTEGER, seen_at INTEGER)")
        derived.write_meta(conn, {"kit_version": __version__, "source": "GitHub"})
        return conn

    def allowance(self):
        """{remaining, size, reset, seen_at, turned} from GitHub's last API answer to any tool, or None before the first.
        `turned` is true when the hour it speaks of has passed, so the figure no longer holds."""
        with closing(self._connect()) as conn:
            row = conn.execute("SELECT remaining, size, reset, seen_at FROM allowance WHERE id = 1").fetchone()
        if not row:
            return None
        return {"remaining": row[0], "size": row[1], "reset": row[2], "seen_at": row[3],
                "turned": bool(row[2]) and row[2] <= int(self.clock())}

    def _note_allowance(self, conn, headers, now):
        """Keeps the hourly allowance an API answer reports (the core one; searches have their own)."""
        remaining, size, reset = (headers.get(k) for k in ("x-ratelimit-remaining", "x-ratelimit-limit", "x-ratelimit-reset"))
        if headers.get("x-ratelimit-resource", "core") != "core" or not (remaining or "").isdigit():
            return
        conn.execute("INSERT OR REPLACE INTO allowance VALUES (1, ?, ?, ?, ?)",
                     (int(remaining), int(size) if (size or "").isdigit() else None,
                      int(reset) if (reset or "").isdigit() else None, now))
        conn.commit()

    @staticmethod
    def _until(reset):
        return time.strftime("%H:%M", time.localtime(int(reset))) if reset else "later"

    def _may_ask(self, conn, kind, now):
        """Raises RateLimited when this call must not be made: GitHub refused already in this run, none are left this hour, or
        an automatic look would dip into what is kept for a press."""
        if self.limited:
            raise RateLimited(self.limited)
        if kind != "api":
            return
        row = conn.execute("SELECT remaining, reset FROM allowance WHERE id = 1").fetchone()
        if not row or row[0] is None or not row[1] or row[1] <= now:
            return
        if row[0] <= 0:
            self.limited = (f"No keyless GitHub calls are left from this computer this hour; they come back at about "
                            f"{self._until(row[1])}.")
            raise RateLimited(self.limited)
        if self.automatic and row[0] <= AUTOMATIC_FLOOR:
            self.limited = (f"Only {row[0]} keyless GitHub calls are left this hour, kept for a press; looking again by itself "
                            f"after about {self._until(row[1])}.")
            raise RateLimited(self.limited)

    def fetch(self, url, kind, max_age=None):
        """(status, body bytes), from the cache when fresh (max_age seconds overrides the client's for one call). Raises
        RateLimited when GitHub refuses for now, unless the client keeps the last answer and has one."""
        now = int(self.clock())
        fresh_for = self.max_age if max_age is None else max_age
        with closing(self._connect()) as conn:
            row = conn.execute("SELECT fetched_at, status, body, etag FROM page WHERE url = ?", (url,)).fetchone()
            if row and not self.refresh and now - row[0] < fresh_for:
                self.reused += 1
                return row[1], row[2]
            try:
                self._may_ask(conn, kind, now)
                self.pacers[kind].wait()
                if row and row[3]:
                    status, body, headers = self.get(url, headers={"If-None-Match": row[3]})
                else:
                    status, body, headers = self.get(url)
            except GitHubError:
                if row and self.keep_last:
                    self.stale.append(row[0])
                    return row[1], row[2]
                raise
            lowered = {k.lower(): v for k, v in (headers or {}).items()}
            if kind != "raw":
                self._note_allowance(conn, lowered, now)
            if status == 304 and row:
                self.revalidated += 1
                conn.execute("UPDATE page SET fetched_at = ? WHERE url = ?", (now, url))
                conn.commit()
                return row[1], row[2]
            if status in (403, 429) and (lowered.get("x-ratelimit-remaining") == "0" or status == 429):
                reset = lowered.get("x-ratelimit-reset") or ""
                self.limited = (f"GitHub is limiting keyless requests from this computer until about "
                                f"{self._until(reset if reset.isdigit() else None)}; run again then, and the cache keeps what is done.")
                if row and self.keep_last:
                    self.stale.append(row[0])
                    return row[1], row[2]
                raise RateLimited(self.limited)
            self.fetched += 1
            if status in (200, 404):   # a missing file is an answer worth keeping too
                conn.execute("INSERT OR REPLACE INTO page (url, fetched_at, status, body, etag) VALUES (?, ?, ?, ?, ?)",
                             (url, now, status, body, lowered.get("etag")))
                conn.commit()
            return status, body

    def _json(self, url, kind, max_age=None):
        status, body = self.fetch(url, kind, max_age)
        if status == 404:
            return None
        if status != 200:
            raise GitHubError(f"GitHub answered HTTP {status} for {url}.")
        return json.loads(body.decode("utf-8", errors="replace"))

    def repository(self, name):
        """The repository's facts (full_name, html_url, pushed_at, archived, fork, license, default_branch), or None."""
        return self._json(f"{API}/repos/{name}", "api")

    def runs(self, name, branch, count=20, max_age=None):
        """The repository's newest Actions runs on a branch, newest first (GitHub's own fields: name, event, status,
        conclusion, head_sha, created_at, updated_at, html_url, path); [] when there are none or no such repository."""
        url = f"{API}/repos/{name}/actions/runs?branch={urllib.parse.quote(branch)}&per_page={count}"
        return (self._json(url, "api", max_age) or {}).get("workflow_runs", [])

    def tree(self, name, branch):
        """Every path in the repository at branch; [] when it cannot be listed."""
        data = self._json(f"{API}/repos/{name}/git/trees/{urllib.parse.quote(branch)}?recursive=1", "api")
        return [entry["path"] for entry in (data or {}).get("tree", []) if entry.get("type") == "blob"]

    def raw(self, name, ref, path):
        """A file's text at ref, or None when there is no such file."""
        status, body = self.fetch(f"{RAW}/{name}/{urllib.parse.quote(ref)}/{urllib.parse.quote(path)}", "raw")
        return body.decode("utf-8-sig", errors="replace") if status == 200 else None

    def search(self, query, count=3):
        """The full names of the best few repositories for a query."""
        data = self._json(f"{API}/search/repositories?q={urllib.parse.quote(query)}&per_page={count}", "search")
        return [item["full_name"] for item in (data or {}).get("items", [])[:count]]
