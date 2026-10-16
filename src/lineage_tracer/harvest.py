"""Query-history harvester: copies pg_stat_statements of every known PostgreSQL system into `query_history`, so lineage
survives statement eviction / stats resets. Read-only on the source systems."""

from __future__ import annotations

import json
import re

import psycopg

from lineage_store import audit
from lineage_tracer import store, vault
from lineage_tracer.connectors import postgres

# statements that can move data (everything else - SET, SHOW, plain SELECTs - is noise for lineage)
KEEP = re.compile(r"^\s*(insert\s+into|merge\s+into|update|copy|call|create\s+(table|materialized)|with\b.*\binsert\b|select\b.*\binto\b)", re.I | re.S)


def run(conn) -> dict:
    store.apply(conn)
    out = {"systems": 0, "statements": 0, "errors": []}
    for r in conn.execute("SELECT system, host, database, secret FROM vault_credential WHERE type = 'postgresql'").fetchall():
        system, host, dbn, _ = r
        try:
            sec = vault.get(conn, "postgresql", host, dbn)
            c = postgres.connect(host, dbn, sec["user"], sec["password"])
        except Exception as e:  # noqa: BLE001 - incl. credentials that no longer decrypt
            out["errors"].append(f"{system}: could not connect: {type(e).__name__} {str(e)[:100]}")
            continue
        try:
            rows = c.execute("SELECT queryid::text, userid::text, query, calls FROM pg_stat_statements "
                             "WHERE dbid = (SELECT oid FROM pg_database WHERE datname = current_database())").fetchall()
        except psycopg.Error as e:
            out["errors"].append(f"{system}: pg_stat_statements not readable: {str(e).splitlines()[0][:100]}")
            continue
        finally:
            c.close()
        h, _, p = vault.norm_host(host).partition(":")
        n = 0
        for qid, uid, q, calls in rows:
            if not KEEP.match(q) or "pg_stat_statements" in q:
                continue
            conn.execute(
                "INSERT INTO query_history (db_host, db_port, dbname, queryid, userid, query, calls) VALUES (%s,%s,%s,%s,%s,%s,%s) "
                "ON CONFLICT (db_host, db_port, dbname, queryid, userid) DO UPDATE SET calls = GREATEST(query_history.calls, "
                "EXCLUDED.calls), last_seen = now(), query = EXCLUDED.query", (h, int(p), dbn, qid or "", uid, q, calls))
            n += 1
        out["systems"] += 1
        out["statements"] += n
    audit.append(conn, "tracer", "system", "harvested query history", "query_history", json.dumps(out)[:200])
    return out
