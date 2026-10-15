"""Append-only, hash-chained audit log: hash = sha256(prev_hash + canonical json of the row)."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

GENESIS = "0" * 64


def _hash(prev: str, row: dict) -> str:
    return hashlib.sha256((prev + json.dumps(row, sort_keys=True, separators=(",", ":"))).encode()).hexdigest()


def _body(ts, actor, role, action, target, detail) -> dict:
    return {"ts": ts, "actor": actor, "role": role, "action": action, "target": target, "detail": detail}


def append(conn, actor: str, role: str, action: str, target: str, detail: str | None = None, ts: str | None = None) -> int:
    ts = ts or datetime.now(timezone.utc).isoformat(timespec="microseconds")
    with conn.transaction():
        conn.execute("LOCK TABLE audit_log IN EXCLUSIVE MODE")
        r = conn.execute("SELECT hash FROM audit_log ORDER BY seq DESC LIMIT 1").fetchone()
        prev = r[0] if r else GENESIS
        h = _hash(prev, _body(ts, actor, role, action, target, detail))
        return conn.execute(
            "INSERT INTO audit_log (ts, actor, role, action, target, detail, prev_hash, hash) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s) RETURNING seq", (ts, actor, role, action, target, detail, prev, h)
        ).fetchone()[0]


def verify(conn) -> bool:
    prev = GENESIS
    for ts, actor, role, action, target, detail, p, h in conn.execute(
        "SELECT ts, actor, role, action, target, detail, prev_hash, hash FROM audit_log ORDER BY seq"
    ):
        if p != prev or h != _hash(prev, _body(ts, actor, role, action, target, detail)):
            return False
        prev = h
    return True


def entries(conn, limit: int = 50) -> list[dict]:
    rows = conn.execute(
        "SELECT seq, ts, actor, role, action, target, detail FROM audit_log ORDER BY seq DESC LIMIT %s", (limit,)
    ).fetchall()
    return [dict(zip(("seq", "ts", "actor", "role", "action", "target", "detail"), r)) for r in rows]
