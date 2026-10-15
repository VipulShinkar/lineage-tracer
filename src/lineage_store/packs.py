"""Evidence pack lifecycle (immutable files + evidence_pack rows) and the S09 coverage dashboard."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone

from lineage_store import audit, evidence, regulator, snapshot
from lineage_store.store import LineageStore, NotFound, dfmt

MEDIA = {"pdf": "application/pdf",
         "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document"}


def cell_label(p: dict) -> str:
    h = p["cell_header"]
    return f"{h['template']} {h['row']} {h['col']}"


def create(st: LineageStore, cell_id: str, sub: str | None, sections: list[str], fmt: str, actor: str, role: str) -> dict:
    valid = [k for k, _ in regulator.SECTIONS]
    if fmt not in MEDIA:
        raise ValueError("format must be pdf or docx")
    if not sections or set(sections) - set(valid):
        raise ValueError(f"sections must be a non-empty subset of {valid}")
    p = snapshot.get(st, cell_id, sub)
    n = st.conn.execute("SELECT nextval('evidence_pack_seq')").fetchone()[0]
    ref = regulator.pack_ref(p["submission"]["ref_date"], n)
    now = datetime.now(timezone.utc)
    viewer = f"{actor} ({role})"
    ts = now.strftime("%Y-%m-%d %H:%M UTC")
    build = evidence.build_pdf if fmt == "pdf" else evidence.build_docx
    data = build(p, sections, ref, viewer, ts)
    name = f"{ref}.{fmt}"
    (evidence.evidence_dir() / name).write_bytes(data)
    sha = hashlib.sha256(data).hexdigest()
    st.conn.execute("INSERT INTO evidence_pack (ref, cell, format, file_path, sha256, watermark, created_by, created_at) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
                    (ref, cell_id, fmt, name, sha, f"{ref} · {viewer} · {ts}", actor, now))
    audit.append(st.conn, actor, role, "generated evidence pack", f"{ref} · {cell_label(p)}")
    return {"ref": ref, "sha256": sha, "download_url": f"/api/evidence-packs/{ref}", "created_at": now.isoformat()}


def load(conn, ref: str) -> tuple[bytes, str]:
    r = conn.execute("SELECT format, file_path FROM evidence_pack WHERE ref = %s", (ref,)).fetchone()
    if not r:
        raise NotFound(f"unknown evidence pack {ref}")
    path = evidence.evidence_dir() / r[1] if r[1] else None
    if not path or not path.exists():
        raise NotFound(f"file for {ref} is archived and not available")
    return path.read_bytes(), r[0]


def coverage(st: LineageStore, sub: str | None) -> dict:
    s = st.submission(sub)
    pilot = st.templates(sub)
    ps = pilot["pilot_scope"]
    by_t = []
    for t in pilot["templates"]:
        if not t["in_scope"]:
            continue
        c = t["coverage"]
        status = "Complete" if not c["partial"] and not c["gap"] else "Partial" + (f" · {c['gap']} gap" if c["gap"] else "")
        by_t.append({"template": t["code"], "name": t["name"] if t["id"] != "C07.00" else "Credit risk SA",
                     "cells": t["pilot_cells"], "complete": c["complete"], "partial": c["partial"], "gap": c["gap"],
                     "status": status})
    cert = [{"owner": o, "nodes": n, "pct": pct, "status": stt}
            for o, n, pct, stt in st.q("SELECT owner, nodes, pct, status FROM certification ORDER BY pos")]
    total = sum(c["nodes"] for c in cert)
    done = sum(c["nodes"] * c["pct"] // 100 for c in cert)  # whole nodes only
    breaks = sum(1 for (cid,) in st.q("SELECT DISTINCT cell_id FROM hop_value WHERE submission_id = %s", (s["id"],))
                 if not st.waterfall(cid, s["id"])["within_tolerance"])
    adj = st.q("SELECT count(*), count(*) FILTER (WHERE checker IS NOT NULL AND checker <> maker AND approved_on IS NOT NULL) "
               "FROM adjustment WHERE submission_id = %s", (s["id"],))[0]
    gaps = st.q("SELECT count(*), min(target_date) FROM gap WHERE status = 'opened'")[0]
    prefix = regulator.pack_ref(s["ref_date"].isoformat(), 0)[:-4]
    packs = st.one("SELECT count(*) FROM evidence_pack WHERE ref LIKE %s", (prefix + "%",))[0]
    refreshed = st.one("SELECT value FROM setting WHERE key = 'refreshed_at'")
    return {"refreshed_at": refreshed[0] if refreshed else datetime.now(timezone.utc).isoformat(timespec="minutes"),
            "kpis": {"cells_complete": f"{ps['complete']} / {ps['total']}",
                     "cells_note": f"{ps['partial']} partial · {ps['gap']} gap",
                     "hops_certified_pct": round(100 * done / total) if total else 0, "hops_note": f"{done} of {total} hops",
                     "unexplained_breaks": breaks, "adjustments_approved": f"{adj[1]} / {adj[0]}",
                     "open_gaps": gaps[0], "open_gaps_note": f"target {dfmt(gaps[1])}" if gaps[1] else "",
                     "evidence_packs": packs},
            "by_template": by_t, "certification": cert}
