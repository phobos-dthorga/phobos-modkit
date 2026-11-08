"""Steam Workshop items: details from Steam's keyless Web API and the latest comments, cached in SQLite.

Endpoints (public, no key or login; checked 7 November 2026):

- Details: POST https://api.steampowered.com/ISteamRemoteStorage/GetPublishedFileDetails/v1/ with itemcount and
  publishedfileids[n], up to 100 at a time. Gives title, creator (SteamID64), times created and updated,
  subscriptions, visibility and tags (RimWorld's tags carry its versions, such as "1.7").
- Comments: POST https://steamcommunity.com/comment/PublishedFile_Public/render/<creator>/<item>/ with start and
  count. Gives JSON with total_count and comments_html, the markup the item's own comment pages show: each comment
  has its commenter's account number (data-miniprofile), a Unix timestamp (data-timestamp) and its text. A
  commenter is the item's creator when the account number is the creator's SteamID64 less 76561197960265728.

Steam limits quick reads of steamcommunity.com: about thirty requests in a row earned HTTP 429 (October 2026), and
on 7 November 2026 one wait of 90 s was not enough while 150 s was. So comment requests are spaced PAUSE_SECONDS
apart, and after a 429 the tool waits BACKOFF_SECONDS once, then stops asking and reports what it has.
"""
from __future__ import annotations

from contextlib import closing
from dataclasses import dataclass, field
import gzip
import html
import json
import os
import re
import sqlite3
import time
import urllib.error
import urllib.parse
import urllib.request

from .. import __version__
from .. import cache as derived

DETAILS_URL = "https://api.steampowered.com/ISteamRemoteStorage/GetPublishedFileDetails/v1/"
COMMENTS_URL = "https://steamcommunity.com/comment/PublishedFile_Public/render/{creator}/{item}/"
ITEM_URL = "https://steamcommunity.com/sharedfiles/filedetails/?id={item}"
USER_AGENT = "phobos-modkit (+https://github.com/phobos-dthorga/phobos-modkit)"
STEAMID64_BASE = 76561197960265728
DETAILS_BATCH = 100
COMMENTS_COUNT = 50
PAUSE_SECONDS = 8
BACKOFF_SECONDS = 150
TIMEOUT_SECONDS = 30
CACHE_FOLDER = "steam-workshop"
INDEX_NAME = "workshop.sqlite"
INDEX_FORMAT = "1"
ITEM_ID = re.compile(r"(?:[?&]id=|^)(\d{6,})")

TABLES = """
CREATE TABLE IF NOT EXISTS item (id TEXT PRIMARY KEY, fetched_at INTEGER NOT NULL, result INTEGER, title TEXT,
    creator TEXT, time_created INTEGER, time_updated INTEGER, subscriptions INTEGER, favorited INTEGER,
    visibility INTEGER, banned INTEGER, tags TEXT, comments_fetched_at INTEGER, comments_total INTEGER,
    comments_note TEXT);
CREATE TABLE IF NOT EXISTS comment (item_id TEXT NOT NULL, comment_id TEXT NOT NULL, author TEXT, account_id TEXT,
    timestamp INTEGER, by_creator INTEGER NOT NULL, text TEXT, PRIMARY KEY (item_id, comment_id));
"""


class WorkshopError(RuntimeError):
    pass


class RateLimited(WorkshopError):
    pass


class CommentsUnavailable(WorkshopError):
    """Steam does not show this item's comments to visitors who are not signed in; the message is Steam's reason."""


@dataclass
class Item:
    id: str
    result: int
    title: str = ""
    creator: str = ""
    time_created: int = 0
    time_updated: int = 0
    subscriptions: int = 0
    favorited: int = 0
    visibility: int = 0
    banned: int = 0
    tags: list = field(default_factory=list)
    description: str = ""   # the page's BBCode; kept in memory for publishing tools, not cached


@dataclass
class Comment:
    comment_id: str
    author: str
    account_id: str
    timestamp: int
    by_creator: bool
    text: str


# ---- HTTP ----

def http_post(url, data, timeout=TIMEOUT_SECONDS):
    """(status, body bytes) of a POST; HTTP errors return their status and body instead of raising."""
    request = urllib.request.Request(url, data=urllib.parse.urlencode(data).encode(),
                                     headers={"User-Agent": USER_AGENT, "Accept-Encoding": "gzip"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            status, body, encoding = response.status, response.read(), response.headers.get("Content-Encoding")
    except urllib.error.HTTPError as error:
        status, body, encoding = error.code, error.read(), error.headers.get("Content-Encoding")
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        raise WorkshopError(f"Steam could not be reached: {error}") from None
    if encoding == "gzip" or body[:2] == b"\x1f\x8b":
        body = gzip.decompress(body)
    return status, body


# ---- Parsing ----

def item_id(text):
    """A Workshop item ID from an ID or a Workshop URL; None when there is none."""
    match = ITEM_ID.search(str(text).strip())
    return match.group(1) if match else None


def parse_details(data):
    """Items from a GetPublishedFileDetails response (a dict)."""
    items = []
    for d in data.get("response", {}).get("publishedfiledetails", []):
        items.append(Item(str(d.get("publishedfileid")), int(d.get("result", 0)), d.get("title", ""),
                          str(d.get("creator", "")), int(d.get("time_created", 0)), int(d.get("time_updated", 0)),
                          int(d.get("subscriptions", 0)), int(d.get("favorited", 0)), int(d.get("visibility", 0)),
                          int(d.get("banned", 0)), [t.get("tag", "") for t in d.get("tags", [])],
                          d.get("description", "")))
    return items


COMMENT_START = re.compile(r'<div[^>]*class="commentthread_comment responsive_body_text[^"]*"[^>]*id="comment_(\d+)"')
AUTHOR = re.compile(r'class="[^"]*commentthread_author_link[^"]*"[^>]*data-miniprofile="(\d+)"[^>]*>\s*<bdi>(.*?)</bdi>',
                    re.S)
TIMESTAMP = re.compile(r'data-timestamp="(\d+)"')
TEXT = re.compile(r'<div class="commentthread_comment_text"[^>]*>(.*?)</div>\s*<div class="comment_footer_ctn"', re.S)
BREAK = re.compile(r"<br\s*/?>", re.I)
TAG = re.compile(r"<[^>]+>")


def _plain(fragment):
    text = TAG.sub("", BREAK.sub("\n", fragment))
    lines = [" ".join(line.split()) for line in html.unescape(text).splitlines()]
    return "\n".join(line for line in lines if line)


def parse_comments(comments_html, creator=""):
    """Comments from the render endpoint's comments_html, newest first, as Steam lists them."""
    creator_account = str(int(creator) - STEAMID64_BASE) if str(creator).isdigit() else ""
    starts = list(COMMENT_START.finditer(comments_html))
    found = []
    for n, start in enumerate(starts):
        block = comments_html[start.start(): starts[n + 1].start() if n + 1 < len(starts) else len(comments_html)]
        author, stamp, text = AUTHOR.search(block), TIMESTAMP.search(block), TEXT.search(block)
        account = author.group(1) if author else ""
        found.append(Comment(start.group(1), html.unescape(_plain(author.group(2))) if author else "", account,
                             int(stamp.group(1)) if stamp else 0, bool(account) and account == creator_account,
                             _plain(text.group(1)) if text else ""))
    return found


# ---- Fetching ----

class Pacer:
    """Spaces requests to one host and backs off once after a 429."""

    def __init__(self, sleep=time.sleep, clock=time.monotonic, pause=PAUSE_SECONDS, backoff=BACKOFF_SECONDS):
        self.sleep, self.clock, self.pause, self.backoff = sleep, clock, pause, backoff
        self.last = None
        self.backed_off = False

    def wait(self):
        if self.last is not None:
            remaining = self.pause - (self.clock() - self.last)
            if remaining > 0:
                self.sleep(remaining)
        self.last = self.clock()

    def call(self, request):
        """Run request() -> (status, body); on 429 wait once and retry, then raise RateLimited."""
        self.wait()
        status, body = request()
        if status == 429 and not self.backed_off:
            self.backed_off = True
            self.sleep(self.backoff)
            self.last = self.clock()
            status, body = request()
        if status == 429:
            raise RateLimited("Steam is limiting requests from this computer for now (HTTP 429).")
        return status, body


def fetch_details(ids, post=http_post):
    items = []
    for start in range(0, len(ids), DETAILS_BATCH):
        batch = ids[start:start + DETAILS_BATCH]
        data = {"itemcount": len(batch), **{f"publishedfileids[{i}]": v for i, v in enumerate(batch)}}
        status, body = post(DETAILS_URL, data)
        if status != 200:
            raise WorkshopError(f"Steam's details API answered HTTP {status}.")
        items += parse_details(json.loads(body.decode("utf-8", errors="replace")))
    return items


def fetch_comments(item, pacer, post=http_post, count=COMMENTS_COUNT):
    """(comments, total on Steam) for one item, the newest first."""
    url = COMMENTS_URL.format(creator=item.creator, item=item.id)
    status, body = pacer.call(lambda: post(url, {"start": 0, "count": count}))
    if status != 200:
        raise WorkshopError(f"Steam's comments for {item.id} answered HTTP {status}.")
    data = json.loads(body.decode("utf-8", errors="replace"))
    if not data.get("success"):
        # Seen 7 Nov 2026: "This profile is private." when the uploader's profile is private. The item's own comment
        # page then redirects to its main page, which is region-blocked here, so no keyless route remains.
        raise CommentsUnavailable(data.get("error") or "Steam gave no reason")
    return parse_comments(data.get("comments_html", ""), item.creator), int(data.get("total_count", 0))


# ---- The cache ----

def index_path(cache):
    return os.path.join(str(cache), INDEX_NAME)


def connect(cache):
    os.makedirs(str(cache), exist_ok=True)
    conn = sqlite3.connect(index_path(cache))
    conn.executescript(TABLES)
    columns = {row[1] for row in conn.execute("PRAGMA table_info(item)")}
    if "comments_note" not in columns:  # caches made before the column existed
        conn.execute("ALTER TABLE item ADD COLUMN comments_note TEXT")
    derived.write_meta(conn, {"index_format": INDEX_FORMAT, "kit_version": __version__, "source": "Steam Workshop"})
    conn.commit()  # an open write would lock the cache against every other connection
    return conn


def _save_item(conn, item, now):
    conn.execute("""INSERT INTO item (id, fetched_at, result, title, creator, time_created, time_updated, subscriptions,
                    favorited, visibility, banned, tags) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET fetched_at = excluded.fetched_at, result = excluded.result,
                    title = excluded.title, creator = excluded.creator, time_created = excluded.time_created,
                    time_updated = excluded.time_updated, subscriptions = excluded.subscriptions,
                    favorited = excluded.favorited, visibility = excluded.visibility, banned = excluded.banned,
                    tags = excluded.tags""",
                 (item.id, now, item.result, item.title, item.creator, item.time_created, item.time_updated,
                  item.subscriptions, item.favorited, item.visibility, item.banned, ",".join(item.tags)))


def _save_comments(conn, item_id, comments, total, now):
    conn.execute("DELETE FROM comment WHERE item_id = ?", (item_id,))
    conn.executemany("INSERT OR REPLACE INTO comment VALUES (?, ?, ?, ?, ?, ?, ?)",
                     [(item_id, c.comment_id, c.author, c.account_id, c.timestamp, int(c.by_creator), c.text)
                      for c in comments])
    conn.execute("UPDATE item SET comments_fetched_at = ?, comments_total = ?, comments_note = NULL WHERE id = ?",
                 (now, total, item_id))


def _save_unavailable(conn, item_id, reason, now):
    """Remember that Steam shows no comments for an item, so the next run within max-age does not ask again."""
    conn.execute("DELETE FROM comment WHERE item_id = ?", (item_id,))
    conn.execute("UPDATE item SET comments_fetched_at = ?, comments_total = NULL, comments_note = ? WHERE id = ?",
                 (now, reason, item_id))


@dataclass
class Refresh:
    """What one refresh did."""
    details_fetched: int = 0
    comments_fetched: int = 0
    reused: int = 0
    rate_limited: bool = False
    problems: list = field(default_factory=list)


def refresh(ids, cache, max_age_hours=24, comments=True, force=False, post=http_post, pacer=None,
            clock=time.time):
    """Bring the cache up to date for these items: details in batches, comments one item at a time, paced. Items
    fetched within max_age_hours are reused. Returns Refresh; never raises for one item's failure."""
    now = int(clock())
    oldest = now - int(max_age_hours * 3600)
    pacer = pacer or Pacer()
    done = Refresh()
    with closing(connect(cache)) as conn:
        known = {row[0]: row[1:] for row in conn.execute(
            "SELECT id, fetched_at, comments_fetched_at, creator, result FROM item")}
        stale = [i for i in ids if force or i not in known or known[i][0] < oldest]
        if stale:
            try:
                for item in fetch_details(stale, post):
                    _save_item(conn, item, now)
                    done.details_fetched += 1
            except WorkshopError as problem:
                done.problems.append(str(problem))
            conn.commit()
        if comments:
            rows = {row[0]: row[1:] for row in conn.execute(
                "SELECT id, comments_fetched_at, creator, result FROM item")}
            for i in ids:
                fetched, creator, result = rows.get(i, (None, "", 0))
                if result != 1 or not creator:
                    continue
                if not force and fetched is not None and fetched >= oldest:
                    done.reused += 1
                    continue
                try:
                    found, total = fetch_comments(Item(i, 1, creator=creator), pacer, post)
                except RateLimited as problem:
                    done.rate_limited = True
                    done.problems.append(str(problem))
                    break
                except CommentsUnavailable as reason:
                    _save_unavailable(conn, i, str(reason), now)
                    conn.commit()
                    done.comments_fetched += 1
                    continue
                except WorkshopError as problem:
                    done.problems.append(str(problem))
                    continue
                _save_comments(conn, i, found, total, now)
                conn.commit()
                done.comments_fetched += 1
    return done
