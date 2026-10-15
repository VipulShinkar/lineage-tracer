"""Schema bootstrap for the tracer tables."""

from pathlib import Path


def apply(conn) -> None:
    conn.execute("SET search_path = public, ag_catalog")
    conn.execute((Path(__file__).parent / "schema.sql").read_text(encoding="utf-8"))
    conn.execute('SET search_path = ag_catalog, "$user", public')
