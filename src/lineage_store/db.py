"""Postgres connection helper with Apache AGE session setup and a small Cypher wrapper."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

import psycopg

DEFAULT_DSN = "host=127.0.0.1 port=5432 user=lineage password=lineage dbname=lineage"
GRAPH = "lineage"


def dsn() -> str:
    return os.environ.get("LINEAGE_DSN", DEFAULT_DSN)


def connect(dsn_: str | None = None) -> psycopg.Connection:
    conn = psycopg.connect(dsn_ or dsn(), autocommit=True)
    conn.execute("LOAD 'age'")
    conn.execute('SET search_path = ag_catalog, "$user", public')
    return conn


def _lit(v) -> str:
    """Render a Python value as a Cypher literal (AGE cannot bind params inside a non-prepared cypher())."""
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return repr(v)
    if isinstance(v, (list, tuple)):
        return "[" + ", ".join(_lit(x) for x in v) + "]"
    if isinstance(v, dict):
        return "{" + ", ".join(f"{k}: {_lit(x)}" for k, x in v.items()) + "}"
    return "'" + str(v).replace("\\", "\\\\").replace("'", "\'") + "'"


_SUFFIX = re.compile(r"::(vertex|edge|path|numeric)\b")


def _parse(cell):
    if cell is None:
        return None
    return json.loads(_SUFFIX.sub("", cell))


def cypher(conn, query: str, params: dict | None = None, cols: int = 1) -> list:
    """Run a Cypher query on the lineage graph. `$name` tokens are replaced by escaped literals.
    Returns rows (tuples of parsed agtype values, or bare values when cols == 1)."""
    for k in sorted(params or {}, key=len, reverse=True):
        query = query.replace("$" + k, _lit(params[k]))
    as_ = ", ".join(f"c{i} agtype" for i in range(cols))
    sql = f"SELECT * FROM cypher('{GRAPH}', $cy$ {query} $cy$) AS ({as_})"
    rows = conn.execute(sql).fetchall()
    out = [tuple(_parse(c) for c in r) for r in rows]
    return [r[0] for r in out] if cols == 1 else out


RECORDED = "2026-09-30T00:00:00Z"
_BASE = {"version": 1, "valid_from": "2000-01-01", "valid_to": "9999-12-31"}


def upsert_vertex(conn, vlabel: str, uid: str, /, **props) -> bool:
    """Create the vertex if its uid is new. Returns True when created."""
    if cypher(conn, "MATCH (n {uid: $u}) RETURN n.uid", {"u": uid}):
        return False
    p = {"uid": uid, **_BASE, "recorded_at": RECORDED, **props}
    cypher(conn, f"CREATE (n:{vlabel} $p)".replace("$p", _lit(p)))
    return True


def upsert_edge(conn, elabel: str, src: str, dst: str, /, **props) -> bool:
    uid = props.pop("uid", f"e:{elabel}:{src}>{dst}")
    if cypher(conn, f"MATCH ()-[e:{elabel} {{uid: $u}}]->() RETURN e.uid", {"u": uid}):
        return False
    p = {"uid": uid, **_BASE, "recorded_at": RECORDED, **props}
    cypher(conn, f"MATCH (a {{uid: $s}}), (b {{uid: $t}}) CREATE (a)-[e:{elabel} {_lit(p)}]->(b) RETURN 1",
           {"s": src, "t": dst})
    return True


def apply_schema(conn) -> None:
    """Idempotent: tables must land in public (ag_catalog is first on the session search_path)."""
    conn.execute("SET search_path = public, ag_catalog")
    conn.execute((Path(__file__).parent / "schema.sql").read_text(encoding="utf-8"))
    conn.execute('SET search_path = ag_catalog, "$user", public')
