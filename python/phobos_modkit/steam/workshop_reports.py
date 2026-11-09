"""Reports over the Workshop cache, as phobos_modkit.report Reports."""
from __future__ import annotations

from datetime import datetime, timezone
import re

from ..query import Filters
from ..report import Report, Table

PROBLEM_WORDS = (r"crash\w*", r"error\w*", r"exception\w*", r"broken", r"bug\w*", r"not work\w*", r"doesn'?t work",
                 r"does not work", r"incompatib\w*", r"conflict\w*", r"red text", r"freez\w*", r"lag\w*", r"stutter\w*",
                 r"abandon\w*", r"outdated", r"no longer", r"null ?reference", r"stuck", r"corrupt\w*")
VERSION_TAG = re.compile(r"^\d+\.\d+$")
SNIPPET = 220
OPENING = 120
BBCODE_TAG = re.compile(r"\[/?[a-zA-Z*][^\]]*\]")
BARE_URL = re.compile(r"https?://\S+")
PER_ITEM = 5
NOTES = ("Comments are the newest ones Steam returns. Some authors delete bug reports from their comments, so few "
         "problem mentions does not mean few bugs.",
         "Only the uploader's own replies are marked; replies by other team members are not.")


def problem_pattern(game_version=None):
    words = list(PROBLEM_WORDS) + ([re.escape(game_version)] if game_version else [])
    return re.compile(r"\b(" + "|".join(words) + r")\b", re.IGNORECASE)


def date_text(stamp):
    return datetime.fromtimestamp(stamp, timezone.utc).strftime("%Y-%m-%d") if stamp else ""


def version_tags(tags):
    return ", ".join(t for t in (tags or "").split(",") if VERSION_TAG.match(t))


def _snippet(text):
    text = " ".join(text.split())
    return text if len(text) <= SNIPPET else text[:SNIPPET].rstrip() + "..."


def plain_text(bbcode):
    """A page's BBCode as one line of plain words: tags and bare image or link addresses removed."""
    return " ".join(BARE_URL.sub(" ", BBCODE_TAG.sub(" ", bbcode or "")).split())


def _opening(text):
    text = plain_text(text)
    return text if len(text) <= OPENING else text[:OPENING].rstrip() + "..."


def _items(conn, ids):
    marks = ",".join("?" * len(ids))
    rows = conn.execute(f"SELECT id, result, title, creator, time_updated, subscriptions, tags, comments_total, "
                        f"comments_fetched_at, comments_note FROM item WHERE id IN ({marks})", ids).fetchall() \
        if ids else []
    by_id = {r[0]: r for r in rows}
    return [by_id[i] for i in ids if i in by_id], [i for i in ids if i not in by_id]


def details(conn, ids, game_version=None):
    found, missing = _items(conn, ids)
    report = Report("Workshop items")
    rows = []
    for item_id, result, title, creator, updated, subs, tags, *_ in found:
        if result != 1:
            continue
        versions = version_tags(tags)
        declared = "" if not game_version else ("yes" if game_version in versions.split(", ") else "no")
        rows.append((item_id, title, date_text(updated), versions, declared, subs))
    headers = ["ID", "Title", "Updated", "Versions", f"Declares {game_version}" if game_version else "", "Subscribers"]
    if not game_version:
        headers, rows = headers[:4] + headers[5:], [r[:4] + r[5:] for r in rows]
    report.section("Items", Table(headers, rows))
    gone = [i for i, result, *_ in found if result != 1] + missing
    if gone:
        report.section("Not found", "Steam returned no public item for these IDs (removed, private or never "
                                    "existed): " + ", ".join(gone) + ".")
    return report


def research(conn, ids, days=90, game_version=None, now=None, top=30):
    """Per item: when it was updated, which versions it declares, how lively its comments are, the uploader's latest
    reply, and the newest comments that mention problems."""
    now = int(now if now is not None else datetime.now(timezone.utc).timestamp())
    since = now - days * 86400
    pattern = problem_pattern(game_version)
    found, missing = _items(conn, ids)
    report = Report("Workshop research")
    summary, problems, replies, hidden = [], [], [], []
    for item_id, result, title, creator, updated, subs, tags, total, fetched, note in found:
        if result != 1:
            continue
        if note:
            hidden.append((title, item_id, note))
            summary.append((title, item_id, date_text(updated), version_tags(tags), subs, "not shown to visitors", "",
                            "", ""))
            continue
        comments = conn.execute("SELECT timestamp, author, by_creator, text FROM comment WHERE item_id = ? "
                                "ORDER BY timestamp DESC", (item_id,)).fetchall()
        recent = sum(1 for c in comments if c[0] >= since)
        flagged = [c for c in comments if pattern.search(c[3] or "")]
        by_uploader = [c for c in comments if c[2]]
        last_reply = date_text(by_uploader[0][0]) if by_uploader else ("none in these" if comments else "")
        shown = f"{len(comments)} of {total}" if fetched else "not fetched"
        summary.append((title, item_id, date_text(updated), version_tags(tags), subs, shown, recent, last_reply,
                        len(flagged)))
        problems += [(title, date_text(c[0]), c[1] + (" (uploader)" if c[2] else ""), _snippet(c[3]))
                     for c in flagged[:PER_ITEM]]
        replies += [(title, date_text(c[0]), _snippet(c[3])) for c in by_uploader[:2]]
    report.lines.append(f"Comment counts are for the last {days} days. Problem words: crashes, errors, exceptions, "
                        f"bugs, broken, not working, incompatible, conflicts, freezes, lag, abandoned, outdated"
                        + (f", and the game version {game_version}" if game_version else "") + ".")
    report.lines += list(NOTES)
    report.section("Items", Table(["Mod", "ID", "Updated", "Versions", "Subscribers", "Comments read",
                                   f"In {days} days", "Uploader's last reply", "Mention problems"], summary))
    report.section("Newest comments that mention problems", Table(["Mod", "Date", "By", "Comment"], problems[:top],
                                                                   len(problems), widths={3: SNIPPET + 10}))
    report.section("The uploader's latest replies", Table(["Mod", "Date", "Reply"], replies[:top], len(replies),
                                                         widths={2: SNIPPET + 10}))
    if hidden:
        report.section("Comments Steam does not show", "Steam shows these items' comments only to signed-in visitors, "
                       "so read them in the Steam client.", Table(["Mod", "ID", "Steam's reason"], hidden))
    gone = [i for i, result, *_ in found if result != 1] + missing
    if gone:
        report.section("Not found or not fetched", "No details for: " + ", ".join(gone) + ".")
    return report


def collection(conn, children, game_version=None, grep=None, top=30):
    """One section per collection: its items with their declared versions and the opening of each description.
    children is {collection ID: child IDs or None}; grep keeps the items whose title or description match."""
    report = Report("Workshop collections")
    if grep:
        report.lines.append(f"Showing the items whose title or description matches {grep!r} (* and ? are wildcards).")
    report.lines.append("Descriptions are the openings of the pages as their authors wrote them; version tags are the "
                        "authors' statements, not a test.")
    for collection_id, ids in children.items():
        title_row = conn.execute("SELECT title FROM item WHERE id = ?", (collection_id,)).fetchone()
        heading = f"{title_row[0]} ({collection_id})" if title_row and title_row[0] else collection_id
        if ids is None:
            report.section(heading, "Steam returned no public collection for this ID, or it was not fetched.")
            continue
        filters = Filters()
        filters.text("title", grep, "description")
        marks = ",".join("?" * len(ids))
        filters.raw(f"id IN ({marks})", *ids)
        rows = {r[0]: r[1:] for r in conn.execute(
            f"SELECT id, result, title, time_updated, tags, description FROM item{filters.where}", filters.params)}
        shown, gone = [], []
        for item_id in ids:
            if item_id not in rows:
                if not grep:
                    gone.append(item_id)
                continue
            result, title, updated, tags, description = rows[item_id]
            if result != 1:
                gone.append(item_id)
                continue
            versions = version_tags(tags)
            declared = "" if not game_version else ("yes" if game_version in versions.split(", ") else "no")
            shown.append((item_id, title, date_text(updated), versions, declared, _opening(description)))
        headers = ["ID", "Title", "Updated", "Versions", f"Declares {game_version}" if game_version else "", "Opening"]
        if not game_version:
            headers, shown = headers[:4] + headers[5:], [r[:4] + r[5:] for r in shown]
        matched = f"{len(shown):,} of {len(ids):,} items match" if grep else f"{len(ids):,} items"
        section = report.section(heading, matched + ".", Table(headers, shown[:top], len(shown),
                                                              widths={len(headers) - 1: OPENING + 10}))
        if gone:
            section.blocks.append("No public item for " + ", ".join(gone) + " (removed, private or not fetched).")
    return report


def comments(conn, item, top=50):
    """One item's cached comments in full, newest first."""
    row = conn.execute("SELECT title, comments_total FROM item WHERE id = ?", (item,)).fetchone()
    report = Report(f"Comments on {row[0] if row else item}")
    rows = conn.execute("SELECT timestamp, author, by_creator, text FROM comment WHERE item_id = ? "
                        "ORDER BY timestamp DESC", (item,)).fetchall()
    if row:
        report.lines.append(f"{len(rows)} of the {row[1] or 0:,} comments Steam holds, newest first.")
    report.section("Comments", Table(["Date", "By", "Comment"],
                                     [(date_text(t), a + (" (uploader)" if c else ""), x) for t, a, c, x in rows[:top]],
                                     len(rows), widths={2: 1200}))
    return report


def sql(conn, query, top=100):
    cursor = conn.execute(query)
    headers = [d[0] for d in cursor.description or []]
    rows = [tuple(r) for r in cursor.fetchmany(top + 1)]
    report = Report("Query")
    report.lines.append("Tables: item, comment, collection, meta.")
    if len(rows) > top:
        report.lines.append(f"Only the first {top:,} rows are shown; raise --top to see more.")
    report.section("Result", Table(headers, rows[:top]))
    return report
