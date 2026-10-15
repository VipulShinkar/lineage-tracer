"""OpenLineage RunEvent intake: datasets/fields + DERIVES from the columnLineage facet, plus the custom facets
recordCounts / controlResult / manualAdjustment (stored as run / control_result / adjustment rows). Idempotent."""

from __future__ import annotations

from datetime import datetime

from lineage_store import db


def _dt(v: str | None):
    return datetime.fromisoformat(v.replace("Z", "+00:00")).replace(tzinfo=None) if v else None


def ingest_event(conn, ev: dict) -> dict:
    run_id = (ev.get("run") or {}).get("runId")
    job = (ev.get("job") or {}).get("name")
    if not run_id or not job:
        raise ValueError("RunEvent needs run.runId and job.name")
    stamp = {"recorded_at": ev.get("eventTime") or db.RECORDED}
    job_id, nodes, edges = f"job:{job}", 0, 0
    for out in ev.get("outputs") or []:
        tds = out["name"]
        fields = ((out.get("facets") or {}).get("columnLineage") or {}).get("fields") or {}
        nodes += db.upsert_vertex(conn, "Dataset", f"dataset:{tds}", label=tds, kind="dataset", lane=0, hidden=True, **stamp)
        for tcol, spec in fields.items():
            if db.upsert_vertex(conn, "Field", f"field:{tds}.{tcol}", label=tcol, sublabel=tds, kind="field", lane=0, **stamp):
                nodes += 1
                edges += db.upsert_edge(conn, "CONTAINS", f"dataset:{tds}", f"field:{tds}.{tcol}", **stamp)
            for src in spec.get("inputFields") or []:
                sds, scol = src["name"], src["field"]
                nodes += db.upsert_vertex(conn, "Dataset", f"dataset:{sds}", label=sds, kind="dataset", lane=0, hidden=True, **stamp)
                if src.get("namespace"):  # where the dataset lives; the Lineage Tracer uses it to find the upstream system
                    db.cypher(conn, "MATCH (n {uid: $u}) SET n.namespace = $ns RETURN 1", {"u": f"dataset:{sds}", "ns": src["namespace"]})
                if db.upsert_vertex(conn, "Field", f"field:{sds}.{scol}", label=scol, sublabel=sds, kind="field", lane=0, **stamp):
                    nodes += 1
                    edges += db.upsert_edge(conn, "CONTAINS", f"dataset:{sds}", f"field:{sds}.{scol}", **stamp)
                edges += db.upsert_edge(conn, "DERIVES", f"field:{sds}.{scol}", f"field:{tds}.{tcol}", job_id=job_id,
                                        transform_type=(src.get("transformations") or [{}])[0].get("type", "openlineage"),
                                        **stamp)
    facets = {**(ev.get("job") or {}).get("facets", {}), **(ev.get("run") or {}).get("facets", {})}
    sub = (conn.execute("SELECT id FROM submission ORDER BY ref_date DESC LIMIT 1").fetchone() or [None])[0]
    rc = facets.get("recordCounts")
    if rc:
        conn.execute(
            "INSERT INTO run (run_id, hop, job_id, submission_id, cutoff, started, ended, rerun, records_in, records_out) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (run_id) DO UPDATE SET records_in = EXCLUDED.records_in, "
            "records_out = EXCLUDED.records_out, ended = EXCLUDED.ended",
            (run_id, rc.get("hop", 0), job_id, rc.get("submission_id", sub), _dt(rc.get("cutoff")), _dt(rc.get("started")),
             _dt(rc.get("ended") or ev.get("eventTime")), bool(rc.get("rerun")), rc.get("in"), rc.get("out")))
    cr = facets.get("controlResult")
    if cr:
        conn.execute("INSERT INTO control (control_id, seq, code, hop, name) VALUES (%s, 999, %s, %s, %s) ON CONFLICT DO NOTHING",
                     (cr["control_id"], f"H{cr.get('hop', 0)}", cr.get("hop", 0), cr.get("name", cr["control_id"])))
        conn.execute("INSERT INTO control_result (control_id, submission_id, run_id, status, detail) VALUES (%s,%s,%s,%s,%s) "
                     "ON CONFLICT (control_id, submission_id) DO UPDATE SET status = EXCLUDED.status, detail = EXCLUDED.detail, "
                     "run_id = EXCLUDED.run_id",
                     (cr["control_id"], cr.get("submission_id", sub), run_id, cr["status"], cr.get("detail")))
    ma = facets.get("manualAdjustment")
    if ma:
        conn.execute(
            "INSERT INTO adjustment (id, submission_id, cell_id, amount, description, reason, maker, maker_at, checker, "
            "checker_at, euc, source, approved_on) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
            "ON CONFLICT (id) DO UPDATE SET amount = EXCLUDED.amount, description = EXCLUDED.description, "
            "checker = EXCLUDED.checker, checker_at = EXCLUDED.checker_at, approved_on = EXCLUDED.approved_on",
            (ma["id"], ma.get("submission_id", sub), ma.get("cell_id"), ma["amount"], ma.get("description"), ma.get("reason"),
             ma.get("maker"), _dt(ma.get("maker_at")), ma.get("checker"), _dt(ma.get("checker_at")), ma.get("euc"),
             ma.get("source"), _dt(ma.get("approved_on")).date() if ma.get("approved_on") else None))
    return {"run_id": run_id, "nodes_upserted": nodes, "edges_upserted": edges}
