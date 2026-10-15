"""Deterministic seed: `python -m lineage_store.seed --reset [--dsn ...]`."""

from __future__ import annotations

from pathlib import Path

from lineage_store import db, ingest_sql
from lineage_store.seed import governance, graph, records, relational

PILOT_SQL = Path(__file__).resolve().parents[3] / "input" / "corep_pilot"
HOP_BY_TARGET = {"stg_collateral": 2, "dw_exposure": 3, "dw_collateral_alloc": 3, "mart_sa_exposure": 4}


def reset(conn) -> None:
    conn.execute("SELECT ag_catalog.drop_graph('lineage', true) FROM ag_catalog.ag_graph WHERE name = 'lineage'")
    conn.execute("DROP SEQUENCE IF EXISTS evidence_pack_seq")
    tables = [r[0] for r in conn.execute("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")]
    for t in tables:
        conn.execute(f'DROP TABLE IF EXISTS public."{t}" CASCADE')


def run(dsn: str | None = None, do_reset: bool = False) -> dict:
    conn = db.connect(dsn)
    try:
        if do_reset:
            reset(conn)
        db.apply_schema(conn)
        relational.insert_all(conn)
        graph.seed(conn)
        sql_res = ingest_sql.ingest_path(conn, PILOT_SQL, HOP_BY_TARGET)
        graph.seed_forward(conn)
        n = records.insert(conn)
        governance.seed(conn)
        return {"records": n, "sql": sql_res}
    finally:
        conn.close()
