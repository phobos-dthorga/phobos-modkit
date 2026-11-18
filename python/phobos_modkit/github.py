"""GitHub, read keyless, paced and cached: repository links in text, a repository's facts and files, and a search.

Game-free. Never logs in or sends a token: GitHub allows a keyless client 60 API calls an hour and 10 searches a minute,
so calls are paced and every answer is cached (in the kit's cache, as fetched pages). Raw files come from
raw.githubusercontent.com, outside the API's hourly count. The network is passed in, so tests never reach GitHub.
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


def http_get(url, timeout=TIMEOUT_SECONDS):
    """(status, body bytes, headers dict); HTTP errors return their status instead of raising."""
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/vnd.github+json"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.read(), dict(response.headers)
    except urllib.error.HTTPError as error:
        return error.code, error.read(), dict(error.headers or {})
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        raise GitHubError(f"GitHub could not be reached: {error}") from None


class Client:
    """Cached, paced reads. get(url) -> (status, body bytes, headers) is the network, passed in for tests."""

    def __init__(self, cache, get=http_get, sleep=time.sleep, clock=time.time, max_age_hours=MAX_AGE_HOURS, refresh=False):
        self.cache, self.get, self.clock = cache, get, clock
        self.max_age = max_age_hours * 3600
        self.refresh = refresh
        self.pacers = {kind: Pacer(sleep=sleep, pause=pause, backoff=0)
                       for kind, pause in (("search", SEARCH_PAUSE_SECONDS), ("api", API_PAUSE_SECONDS), ("raw", RAW_PAUSE_SECONDS))}
        self.fetched = 0
        self.reused = 0
        self.limited = None

    def _connect(self):
        self.cache.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.cache / INDEX_NAME)
        conn.execute("CREATE TABLE IF NOT EXISTS page (url TEXT PRIMARY KEY, fetched_at INTEGER, status INTEGER, body BLOB)")
        derived.write_meta(conn, {"kit_version": __version__, "source": "GitHub"})
        return conn

    def fetch(self, url, kind):
        """(status, body bytes), from the cache when fresh. Raises RateLimited when GitHub refuses for now."""
        now = int(self.clock())
        with closing(self._connect()) as conn:
            row = conn.execute("SELECT fetched_at, status, body FROM page WHERE url = ?", (url,)).fetchone()
            if row and not self.refresh and now - row[0] < self.max_age:
                self.reused += 1
                return row[1], row[2]
            if self.limited:
                raise RateLimited(self.limited)
            pacer = self.pacers[kind]
            pacer.wait()
            status, body, headers = self.get(url)
            lowered = {k.lower(): v for k, v in (headers or {}).items()}
            if status in (403, 429) and (lowered.get("x-ratelimit-remaining") == "0" or status == 429):
                reset = lowered.get("x-ratelimit-reset")
                when = time.strftime("%H:%M", time.localtime(int(reset))) if reset and reset.isdigit() else "later"
                self.limited = f"GitHub is limiting keyless requests from this computer until about {when}; run again then, and the cache keeps what is done."
                raise RateLimited(self.limited)
            self.fetched += 1
            if status in (200, 404):   # a missing file is an answer worth keeping too
                conn.execute("INSERT OR REPLACE INTO page VALUES (?, ?, ?, ?)", (url, now, status, body))
                conn.commit()
            return status, body

    def _json(self, url, kind):
        status, body = self.fetch(url, kind)
        if status == 404:
            return None
        if status != 200:
            raise GitHubError(f"GitHub answered HTTP {status} for {url}.")
        return json.loads(body.decode("utf-8", errors="replace"))

    def repository(self, name):
        """The repository's facts (full_name, html_url, pushed_at, archived, fork, license, default_branch), or None."""
        return self._json(f"{API}/repos/{name}", "api")

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
