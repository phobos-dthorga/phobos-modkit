"""steam-reviews: what players say about a game, or one of its DLCs, on Steam, from its public pages, keyless (1.143.0).

    steam-reviews --app-id 294100                       the game: how many recommend it, all time and lately, and the newest reviews
    steam-reviews --app-id 294100 --match Royalty       the DLC of the game whose name holds the words, else the game itself

For D'thorga Companion's What players say on the game and its DLCs (the owner, 27 Nov 2026: "We can still have 'what players say'
for the actual vanilla game itself and the DLCs, it'll just be reviews instead"). Steam's JSON reviews feed (`appreviews`) now
sends every request to its front page, so this reads what a browser reads, as the Workshop comments are read:

- **How many recommend it**: the store's review histogram, monthly since release and daily for the last 30 days.
- **The newest reviews** (the game only): its community page's review cards, a few pages of the newest, keeping whether each
  recommends it, the hours on record, the day posted and the words. Reviewers' names and profiles are left out. A DLC has no review
  cards there, so a DLC gives its counts alone, and says so.
- **Which DLC**: the store's own list of the game's DLC, matched by name; their names are kept in the kit's cache for a week.

Reads only, keyless; nothing about the person is sent but what any page request carries.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import html
import json
import os
from pathlib import Path
import re
import sys
import time
import urllib.error
import urllib.request

from .. import cache as derived
from ..manifest import ONLINE
from ..report import Bullets, Report, envelope_text, home_redactor, keep, render_markdown
from .workshop import TIMEOUT_SECONDS, USER_AGENT

EXIT_OK, EXIT_FAILED, EXIT_USAGE = 0, 1, 2
STORE = "https://store.steampowered.com"
COMMUNITY = "https://steamcommunity.com"
PAGES = 5                      # newest review pages read, ten reviews each (agent default: 50, about 4 s)
MOST_PAGES = 10
SHOWN_AGAINST = 8              # newest reviews that do not recommend it, shown
SHOWN_FOR = 3                  # newest that do, shown for balance
MOST_WORDS = 600               # characters of a review kept
NAMES_FOR_DAYS = 7
PAUSE_SECONDS = 0.6            # between requests, to be gentle with Steam


class ReviewsError(RuntimeError):
    pass


def http_get(url, timeout=TIMEOUT_SECONDS):
    """The text of a page; Steam unreachable or an error status is a ReviewsError."""
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as error:
        raise ReviewsError(f"Steam answered {error.code} for {url}") from None
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        raise ReviewsError(f"Steam could not be reached: {error}") from None


def _json(text, what):
    try:
        return json.loads(text)
    except ValueError:
        raise ReviewsError(f"Steam's {what} was not what it used to send (a page, not data).") from None


def app_details(app_id, get=http_get):
    """(name, [DLC app ids]) from the store's own record of an app."""
    found = _json(get(f"{STORE}/api/appdetails?appids={app_id}&filters=basic"), "app record")
    entry = found.get(str(app_id)) or {}
    if not entry.get("success"):
        raise ReviewsError(f"Steam has no store record of app {app_id}.")
    data = entry.get("data") or {}
    return data.get("name") or str(app_id), [int(i) for i in data.get("dlc") or []]


def _names_file(environ=None):
    return derived.folder("steam-reviews", None, environ) / "names.json"


def dlc_names(dlc_ids, get=http_get, environ=None, now=None, pause=PAUSE_SECONDS, sleep=time.sleep):
    """{app id: name} for the DLC ids, from the kit's cache while a week old or younger, else the store."""
    now = now or time.time()
    path = _names_file(environ)
    try:
        kept = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        kept = {}
    names, fetched = {}, False
    for app_id in dlc_ids:
        known = kept.get(str(app_id))
        if known and now - known.get("at", 0) < NAMES_FOR_DAYS * 86400:
            names[app_id] = known["name"]
            continue
        if fetched:
            sleep(pause)
        try:
            names[app_id], _ = app_details(app_id, get)
        except ReviewsError:
            continue
        kept[str(app_id)] = {"name": names[app_id], "at": now}
        fetched = True
    if fetched:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(kept), encoding="utf-8")
    return names


def _words(text):
    return [w for w in re.split(r"[^a-z0-9]+", text.lower()) if w]


def matching_dlc(names, match):
    """The DLC whose name holds every word of `match`, the shortest such name first; None when none does."""
    wanted = _words(match or "")
    if not wanted:
        return None
    fits = [(len(name), app_id) for app_id, name in names.items() if all(w in _words(name) for w in wanted)]
    return min(fits)[1] if fits else None


def histogram(app_id, get=http_get):
    """{"all": [up, down], "recent": [up, down]}: every review by month since release, and the last 30 days by day."""
    found = _json(get(f"{STORE}/appreviewhistogram/{app_id}?l=english&review_score_preference=0"), "review counts")
    results = found.get("results") or {}
    def total(rows):
        return [sum(int(r.get("recommendations_up") or 0) for r in rows), sum(int(r.get("recommendations_down") or 0) for r in rows)]
    return {"all": total(results.get("rollups") or []), "recent": total(results.get("recent") or [])}


CARD = re.compile(r'class="apphub_Card ')
TITLE = re.compile(r'<div class="title">\s*(.*?)\s*</div>', re.S)
HOURS = re.compile(r'<div class="hours">\s*([\d.,]+)\s*hrs? on record', re.S)
POSTED = re.compile(r'<div class="date_posted">\s*(.*?)\s*</div>([\s\S]*?)</div>', re.S)


def parse_reviews(page):
    """The review cards of one community page: {recommended, hours, posted, words}; reviewers' names are not kept."""
    found = []
    for card in CARD.split(page)[1:]:
        title = TITLE.search(card)
        posted = POSTED.search(card)
        if not title or not posted:
            continue
        hours = HOURS.search(card)
        words = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", posted.group(2)))).strip()
        found.append({"recommended": title.group(1).strip().lower() == "recommended",
                      "hours": float(hours.group(1).replace(",", "")) if hours else None,
                      "posted": re.sub(r"^Posted:\s*", "", html.unescape(posted.group(1))).strip(),
                      "words": words[:MOST_WORDS] + ("…" if len(words) > MOST_WORDS else "")})
    return found


def newest_reviews(app_id, pages=PAGES, get=http_get, pause=PAUSE_SECONDS, sleep=time.sleep):
    """The newest reviews from the community page, `pages` of ten, newest first."""
    found = []
    for page in range(1, max(1, min(pages, MOST_PAGES)) + 1):
        if page > 1:
            sleep(pause)
        url = (f"{COMMUNITY}/app/{app_id}/homecontent/?userreviewsoffset={(page - 1) * 10}&p={page}&numperpage=10"
               f"&browsefilter=mostrecent&appid={app_id}&appHubSubSection=10&l=english&filterLanguage=default"
               "&searchText=&maxInappropriateScore=100")
        cards = parse_reviews(get(url))
        if not cards:
            break
        found.extend(cards)
    return found


def _share(pair):
    up, down = pair
    return round(100 * up / (up + down)) if up + down else None


def read(app_id, match=None, pages=PAGES, get=http_get, environ=None, sleep=time.sleep):
    """Everything the report shows, as data."""
    base_name, dlc_ids = app_details(app_id, get)
    target, name, is_dlc = app_id, base_name, False
    if match and dlc_ids:
        names = dlc_names(dlc_ids, get, environ, sleep=sleep)
        chosen = matching_dlc(names, match)
        if chosen is not None:
            target, name, is_dlc = chosen, names[chosen], True
    counts = histogram(target, get)
    reviews = [] if is_dlc else newest_reviews(target, pages, get, sleep=sleep)
    return {"app": target, "name": name, "game": app_id, "gameName": base_name, "dlc": is_dlc,
            "all": counts["all"], "recent": counts["recent"],
            "allShare": _share(counts["all"]), "recentShare": _share(counts["recent"]),
            "read": len(reviews), "reviews": reviews,
            "at": datetime.now(timezone.utc).isoformat(timespec="seconds")}


def build_report(data):
    report = Report(f"What players say about {data['name']}")
    all_up, all_down = data["all"]
    up, down = data["recent"]
    if data["allShare"] is not None:
        report.lines.append(f"All time: {data['allShare']}% of {all_up + all_down:,} reviews recommend it.")
    if data["recentShare"] is not None:
        report.lines.append(f"The last 30 days: {data['recentShare']}% of {up + down:,} recommend it.")
    else:
        report.lines.append("No reviews in the last 30 days.")
    if data["dlc"]:
        report.lines.append(f"Steam keeps no written reviews on a DLC's community page, so these counts are {data['name']}'s own; "
                            f"what players write is on {data['gameName']}'s page.")
        return report
    against = [r for r in data["reviews"] if not r["recommended"]][:SHOWN_AGAINST]
    for_it = [r for r in data["reviews"] if r["recommended"]][:SHOWN_FOR]
    report.lines.append(f"Read the newest {data['read']} reviews: {sum(1 for r in data['reviews'] if not r['recommended'])} do "
                        "not recommend it.")

    def line(r):
        hours = f", {r['hours']:g} h on record" if r["hours"] is not None else ""
        return f"{r['posted']}{hours}: {r['words'] or '(no words)'}"
    report.section("The newest that do not recommend it", Bullets([line(r) for r in against] or ["None among those read."]))
    if for_it:
        report.section("The newest that recommend it", Bullets([line(r) for r in for_it]))
    return report


def _parser():
    p = argparse.ArgumentParser(prog="steam-reviews", description=__doc__.split("\n\n")[0],
                                formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__.split("\n\n", 1)[1])
    p.add_argument("--app-id", type=int, required=True, help="the game's Steam app ID")
    p.add_argument("--match", help="a DLC of the game whose name holds these words (else the game itself)")
    p.add_argument("--pages", type=int, default=PAGES, help=f"pages of ten newest reviews to read (default {PAGES}, at most {MOST_PAGES})")
    p.add_argument("--json", action="store_true", help="print JSON instead of Markdown")
    p.add_argument("--no-redact", action="store_true", help="show the home folder instead of ~")
    return p


def main(argv=None, out=None, environ=None, get=http_get, sleep=time.sleep):
    out = out or sys.stdout
    environ = os.environ if environ is None else environ
    try:
        args = _parser().parse_args(list(sys.argv[1:] if argv is None else argv))
    except SystemExit as stop:
        return EXIT_USAGE if stop.code else EXIT_OK
    redact = keep if args.no_redact else home_redactor()
    try:
        data = read(args.app_id, args.match, args.pages, get, environ, sleep)
    except ReviewsError as error:
        report = Report("What players say: Steam could not be read")
        report.lines.append(str(error))
        out.write((envelope_text("steam-reviews", report, redact, {"ok": False, "refusal": str(error)}) if args.json
                   else render_markdown(report, redact)) + "\n")
        return EXIT_FAILED
    report = build_report(data)
    out.write((envelope_text("steam-reviews", report, redact, data) if args.json else render_markdown(report, redact)) + "\n")
    return EXIT_OK


MANIFEST = {"game": None, "parser": _parser, "effect": ONLINE,
            "note": "reads Steam's public store and community pages, keyless: review counts and the newest reviews"}
