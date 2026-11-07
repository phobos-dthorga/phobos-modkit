"""Markdown pieces every report uses: safe table cells and whole tables."""
from __future__ import annotations

CELL_LIMIT = 140


def cell(value, limit=CELL_LIMIT):
    """One table cell: on one line, cut to limit characters, pipes escaped; None shows as empty."""
    if value is None:
        return ""
    if isinstance(value, float):
        value = f"{value:.4g}"
    elif isinstance(value, int) and not isinstance(value, bool):
        value = f"{value:,}" if abs(value) >= 1000 else str(value)
    text = " ".join(str(value).split())
    if len(text) > limit:
        text = text[:limit].rstrip() + "..."
    return text.replace("|", "\\|")


def table(headers, rows, limit=CELL_LIMIT):
    """Lines of a Markdown table."""
    lines = ["| " + " | ".join(cell(h, limit) for h in headers) + " |",
             "| " + " | ".join("---" for _ in headers) + " |"]
    lines += ["| " + " | ".join(cell(v, limit) for v in row) + " |" for row in rows]
    return lines
