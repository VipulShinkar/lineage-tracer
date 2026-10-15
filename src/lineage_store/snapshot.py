"""Immutable per-(submission, cell) lineage snapshots: regulator view and evidence packs are served from these."""

from __future__ import annotations

import hashlib
import json

from lineage_store.masking import mask_counterparty, mask_key
from lineage_store.store import LineageStore


def build(st: LineageStore, cell_id: str, sub_id: str) -> dict:
    s = st.submission(sub_id)
    if s["submitted_on"] is None:
        raise ValueError("snapshots exist only for submitted returns")
    recs = st.records(cell_id, "sector", None, 5, sub_id)
    for t in recs["top"]:  # snapshots never hold raw identifiers
        t["counterparty"], t["source_key"] = mask_counterparty(t["counterparty"]), mask_key(t["source_key"])
    return {
        "cell_header": st.cell_header(cell_id, sub_id),
        "submission": {"id": s["id"], "ref_date": s["ref_date"].isoformat(), "version": s["version"],
                       "submitted_on": s["submitted_on"].isoformat()},
        "lineage": st.reverse(cell_id, "dataset", sub_id),
        "hops": [st.hop(cell_id, n, sub_id) for n in range(1, 8)],
        "transformations": st.transformations(cell_id, sub_id),
        "waterfall": st.waterfall(cell_id, sub_id),
        "records": recs,
        "adjustments": st.adjustments(cell_id, sub_id),
    }


def get(st: LineageStore, cell_id: str, sub: str | None) -> dict:
    """Return the stored snapshot, materialising it on first access."""
    sid = st.submission(sub)["id"]
    q = "SELECT payload FROM lineage_snapshot WHERE submission_id = %s AND cell_id = %s"
    r = st.one(q, (sid, cell_id))
    if r:
        return r[0]
    payload = build(st, cell_id, sid)
    h = hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    st.conn.execute("INSERT INTO lineage_snapshot VALUES (%s,%s,%s::jsonb,%s) ON CONFLICT DO NOTHING",
                    (sid, cell_id, json.dumps(payload), h))
    return st.one(q, (sid, cell_id))[0]
