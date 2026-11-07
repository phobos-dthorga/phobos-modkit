"""Helpers for reports that query the kit's SQLite indexes: user filters as safe LIKE clauses, counts and capped rows.

A user's filter text ignores case; * and ? are wildcards, and % and _ (common in game names) are ordinary characters.
"""
from __future__ import annotations


def like(pattern):
    """A SQL LIKE pattern from a user's text, for use with ESCAPE '\\'."""
    escaped = pattern.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return escaped.replace("*", "%").replace("?", "_")


class Filters:
    """WHERE clauses with parameters, built one filter at a time."""

    def __init__(self):
        self.clauses, self.params = [], []

    def text(self, column_sql, value, *more_columns):
        """Match the user's text against any of the columns."""
        if value:
            columns = (column_sql, *more_columns)
            self.clauses.append("(" + " OR ".join(f"{c} LIKE ? ESCAPE '\\'" for c in columns) + ")")
            self.params += [like(value)] * len(columns)

    def equal(self, column_sql, value):
        if value is not None:
            self.clauses.append(f"{column_sql} = ?")
            self.params.append(value)

    def raw(self, clause, *params):
        self.clauses.append(clause)
        self.params += params

    @property
    def where(self):
        return (" WHERE " + " AND ".join(self.clauses)) if self.clauses else ""


def count(conn, sql, params=()):
    """How many rows a query returns."""
    return conn.execute(f"SELECT COUNT(*) FROM ({sql})", params).fetchone()[0]


def rows(conn, sql, params, top):
    """The first top rows of a query, as tuples."""
    return [tuple(r) for r in conn.execute(f"{sql} LIMIT ?", (*params, top)).fetchall()]
