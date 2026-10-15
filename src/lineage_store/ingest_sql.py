"""Design-time lineage: parse SQL with the built-in SQL parser and upsert Dataset/Field vertices + field-level DERIVES edges."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from lineage_parser.graph import NodeKind
from lineage_parser.sql.parser import parse_sql_lineage
from lineage_store import db

# known warehouse datasets -> lane (0 FIRST HOP, 1 STAGING, 2 WAREHOUSE, 3 REG DATA MART)
LANES = {"stg_": 1, "dw_": 2, "mart_": 3}


def _lane(dataset: str) -> int:
    return next((v for k, v in LANES.items() if dataset.startswith(k)), 0)


def ingest_sql(conn, content: str, hop_by_target: dict[str, int] | None = None, dialect: str = "postgres",
               recorded_at: str | None = None) -> dict:
    """Returns {nodes_upserted, edges_upserted, errors}. Datasets not already known become hidden first-hop
    datasets (reference / source tables); only the column-level edges are written."""
    res = parse_sql_lineage(content, dialect=dialect)
    return ingest_graph(conn, res.graph, hop_by_target, recorded_at, res.errors)


def ingest_xml(conn, content: str) -> dict:
    from lineage_parser.xml import parse_xml_lineage

    res = parse_xml_lineage(content)
    return ingest_graph(conn, res.graph.collapse_to_physical_columns(), None, None, res.errors)


def ingest_graph(conn, g, hop_by_target, recorded_at, errors) -> dict:
    hop_by_target = hop_by_target or {}
    stamp = {"recorded_at": recorded_at} if recorded_at else {"recorded_at": datetime.now(timezone.utc).isoformat()}
    nodes = edges = 0

    def split(node_id: str) -> tuple[str, str]:
        ds, col = node_id.removeprefix("table:").rsplit(".", 1)
        return ds, col

    for n in g.nodes.values():
        if n.kind == NodeKind.TABLE:
            ds = n.id.removeprefix("table:")
            lane = _lane(ds)
            nodes += db.upsert_vertex(conn, "Dataset", f"dataset:{ds}", label=ds, kind="dataset", lane=lane,
                                      hidden=(lane == 0), **stamp)
        elif n.kind == NodeKind.COLUMN:
            ds, col = split(n.id)
            lane = _lane(ds)
            nodes += db.upsert_vertex(conn, "Dataset", f"dataset:{ds}", label=ds, kind="dataset", lane=lane,
                                      hidden=(lane == 0), **stamp)
            if db.upsert_vertex(conn, "Field", f"field:{ds}.{col}", label=col, sublabel=ds, kind="field",
                                lane=lane, **stamp):
                nodes += 1
                edges += db.upsert_edge(conn, "CONTAINS", f"dataset:{ds}", f"field:{ds}.{col}", **stamp)

    for e in g.edges:
        s, t = g.nodes[e.source], g.nodes[e.target]
        if s.kind != NodeKind.COLUMN or t.kind != NodeKind.COLUMN:
            continue
        (sds, scol), (tds, tcol) = split(s.id), split(t.id)
        hop = hop_by_target.get(tds)
        extra = {"hop": hop, "job_id": f"job:hop{hop}"} if hop else {}
        edges += db.upsert_edge(conn, "DERIVES", f"field:{sds}.{scol}", f"field:{tds}.{tcol}",
                                transform_type="sql", **extra, **stamp)
    return {"nodes_upserted": nodes, "edges_upserted": edges, "errors": errors}


def ingest_path(conn, path: str | Path, hop_by_target: dict[str, int] | None = None) -> dict:
    """Ingest a single .sql file or every .sql file in a directory."""
    p = Path(path)
    files = sorted(p.glob("*.sql")) if p.is_dir() else [p]
    total = {"nodes_upserted": 0, "edges_upserted": 0, "errors": []}
    for f in files:
        r = ingest_sql(conn, f.read_text(encoding="utf-8-sig"), hop_by_target, recorded_at=db.RECORDED)
        total["nodes_upserted"] += r["nodes_upserted"]
        total["edges_upserted"] += r["edges_upserted"]
        total["errors"] += r["errors"]
    return total
