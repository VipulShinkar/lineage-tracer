"""Read-only SQLite metadata scanner: views and triggers in sqlite_master. A table nothing writes = system of record."""

from __future__ import annotations

import hashlib
import re
import sqlite3
from datetime import date
from pathlib import Path


def connect(path: str) -> sqlite3.Connection:
    if not Path(path).is_file():
        raise ValueError(f"no such sqlite file {path}")
    conn = sqlite3.connect(f"file:{Path(path).as_posix()}?mode=ro", uri=True, check_same_thread=False)
    conn.execute("PRAGMA query_only = ON")
    conn.execute("SELECT 1 FROM sqlite_master LIMIT 1")
    return conn


def columns(conn, schema: str, table: str) -> list[tuple[str, str]]:
    return [(r[1], r[2] or "") for r in conn.execute(f'PRAGMA table_info("{table}")')]


def entity_type(conn, schema: str, table: str) -> str:
    r = conn.execute("SELECT type FROM sqlite_master WHERE name = ?", (table,)).fetchone()
    return "view" if r and r[0] == "view" else "table"


def descriptions(conn, schema: str, table: str) -> tuple[str | None, dict[str, str]]:
    return None, {}  # SQLite has no comments


def resolve(conn, name: str, default_schema: str | None = None) -> tuple[str, str] | None:
    t = name.rpartition(".")[2].strip('"')
    return ("", t) if columns(conn, "", t) else None


def writers(conn, schema: str, table: str) -> list[dict]:
    out = []
    ver = lambda s: f"definition sha256 {hashlib.sha256(s.encode()).hexdigest()[:12]}… · captured {date.today().isoformat()}"  # noqa: E731
    for name, sql in conn.execute("SELECT name, sql FROM sqlite_master WHERE type = 'view' AND name = ?", (table,)):
        out.append({"kind": "view", "dialect": "sqlite", "sql": sql, "ref": f"sqlite: view {name}", "version": ver(sql)})
    for name, sql in conn.execute("SELECT name, sql FROM sqlite_master WHERE type = 'trigger' AND sql LIKE ?", (f"%{table}%",)):
        for m in re.finditer(rf"(insert\s+into|update)\s+\"?{re.escape(table)}\"?\b[^;]*", sql, re.I):
            out.append({"kind": "trigger", "dialect": "sqlite", "sql": m.group(0), "ref": f"sqlite: trigger {name}",
                        "version": ver(sql)})
    return out


def consumers(conn, schema: str, table: str) -> list[str]:
    return [n for (n,) in conn.execute("SELECT name FROM sqlite_master WHERE type = 'view' AND sql LIKE ? AND name <> ?",
                                       (f"%{table}%", table))]


def sum_value(conn, schema: str, table: str, col: str, filters: dict) -> float | None:
    have = {c for c, _ in columns(conn, schema, table)}
    f = {c: v for c, v in filters.items() if c in have}
    w = " AND ".join(f'CAST("{c}" AS TEXT) = ?' for c in f) or "1"
    agg = "count(*)" if col == "*" else f'sum("{col}")'
    r = conn.execute(f'SELECT {agg} FROM "{table}" WHERE {w}', list(f.values())).fetchone()[0]
    return None if r is None else float(r)
