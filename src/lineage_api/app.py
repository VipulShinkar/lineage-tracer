"""Lineage Explorer API (S01-S07). Run: uvicorn lineage_api.app:app --port 8000"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel

from datetime import datetime, timezone
from pathlib import Path

from lineage_store import audit, db, evidence, impact, ingest_ol, ingest_sql, packs, regulator, snapshot
from lineage_store.store import SECTOR_SHORT, LineageStore, NotFound, dfmt

from lineage_api.roles import Caller, caller, mask_counterparty, mask_key
from lineage_tracer import api as tracer_api, store as tracer_store


@asynccontextmanager
async def lifespan(app: FastAPI):
    conn = db.connect()
    try:
        db.apply_schema(conn)
        tracer_store.apply(conn)
    finally:
        conn.close()
    yield


app = FastAPI(title="Lineage Explorer API", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
                   allow_methods=["*"], allow_headers=["*"])


app.include_router(tracer_api.router)


@app.exception_handler(NotFound)
async def _not_found(_, exc: NotFound):
    return JSONResponse({"detail": exc.args[0]}, status_code=404)


@app.exception_handler(ValueError)
async def _bad_request(_, exc: ValueError):
    return JSONResponse({"detail": str(exc)}, status_code=400)


def store():
    conn = db.connect()
    try:
        yield LineageStore(conn)
    finally:
        conn.close()


S = Depends(store)
Sub = Query(None, description="submission id, e.g. 2026-06-30.v1")


@app.get("/api/contexts")
def contexts(st: LineageStore = S):
    return st.contexts()


@app.get("/api/templates")
def templates(sub: str | None = Sub, st: LineageStore = S):
    return st.templates(sub)


@app.get("/api/templates/{template}/grid")
def grid(template: str, sheet: str | None = None, sub: str | None = Sub, st: LineageStore = S):
    return st.grid(template, sheet, sub)


@app.get("/api/search")
def search(q: str = "", kind: str = "all", sub: str | None = Sub, st: LineageStore = S):
    return st.search(q, kind, sub)


@app.get("/api/cells/{cell_id}")
def cell(cell_id: str, sub: str | None = Sub, st: LineageStore = S):
    return st.cell(cell_id, sub)


@app.get("/api/cells/{cell_id}/lineage")
def lineage(cell_id: str, level: str = "dataset", direction: str = "reverse", sub: str | None = Sub, st: LineageStore = S):
    if direction != "reverse":
        raise HTTPException(400, "only direction=reverse is available in this phase")
    return st.reverse(cell_id, level, sub)


@app.get("/api/cells/{cell_id}/hops/{n}")
def hop(cell_id: str, n: int, sub: str | None = Sub, st: LineageStore = S):
    return st.hop(cell_id, n, sub)


@app.get("/api/cells/{cell_id}/transformations")
def transformations(cell_id: str, sub: str | None = Sub, st: LineageStore = S):
    return st.transformations(cell_id, sub)


@app.get("/api/mappings/{mapping_uid}")
def mapping(mapping_uid: str, version: str | None = None, compare: str | None = None, cell: str | None = None,
            sub: str | None = Sub, st: LineageStore = S):
    return st.mapping(mapping_uid, version, compare, sub)


@app.get("/api/cells/{cell_id}/waterfall")
def waterfall(cell_id: str, sub: str | None = Sub, st: LineageStore = S):
    return st.waterfall(cell_id, sub)


@app.get("/api/cells/{cell_id}/records")
def records(cell_id: str, group_by: str = "sector", compare: str | None = None, top: int = Query(5, ge=1, le=50),
            sub: str | None = Sub, who: Caller = Depends(caller), st: LineageStore = S):
    out = st.records(cell_id, group_by, compare, top, sub)
    for t in out["top"]:  # identifiers are masked for every role; only reveal returns them
        t["counterparty"] = mask_counterparty(t["counterparty"])
        t["source_key"] = mask_key(t["source_key"])
    out["masking"] = {"masked": True, "can_reveal": who.can_reveal}
    return out


@app.get("/api/records/{record_key}/trace")
def trace(record_key: str, sub: str | None = Sub, st: LineageStore = S):
    t = st.trace(record_key)
    key = mask_key(t["source_key"])
    steps = [{**s, "label": s["label"].format(source_key=key)} for s in t["steps"]]
    short = SECTOR_SHORT.get(t["sector"], t["sector"])
    return {"record_key": record_key, "title": f"{mask_counterparty(t['counterparty'])} · {t['product']} · {short}",
            "steps": steps}


class Reveal(BaseModel):
    reason: str


@app.post("/api/records/{record_key}/reveal")
def reveal(record_key: str, body: Reveal, who: Caller = Depends(caller), st: LineageStore = S):
    if not who.can_reveal:
        raise HTTPException(403, f"role {who.role} cannot reveal identifiers")
    if not body.reason.strip():
        raise HTTPException(422, "a reason is required")
    r = st.record(record_key)
    audit.append(st.conn, who.actor, who.role, "revealed an identifier", record_key, body.reason.strip())
    return {"counterparty": r["counterparty"], "source_key": r["source_key"]}


# ---------------------------------------------------------------- S08 regulator view + evidence packs
def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


@app.get("/api/cells/{cell_id}/regulator")
def regulator_view(cell_id: str, sub: str | None = Sub, who: Caller = Depends(caller), st: LineageStore = S):
    p = snapshot.get(st, cell_id, sub)
    sm = p["submission"]
    audit.append(st.conn, who.actor, who.role, "opened regulator view",
                 f"{packs.cell_label(p)} · {dfmt(datetime.fromisoformat(sm['ref_date']))} {sm['version']}")
    return regulator.view(st.conn, p)


class PackRequest(BaseModel):
    sections: list[str]
    format: str = "pdf"


@app.post("/api/cells/{cell_id}/evidence-pack")
def evidence_pack(cell_id: str, body: PackRequest, sub: str | None = Sub, who: Caller = Depends(caller),
                  st: LineageStore = S):
    return packs.create(st, cell_id, sub, body.sections, body.format, who.actor, who.role)


@app.get("/api/evidence-packs/{ref}")
def evidence_pack_file(ref: str, st: LineageStore = S):
    data, fmt = packs.load(st.conn, ref)
    return Response(data, media_type=packs.MEDIA[fmt], headers={"Content-Disposition": f'attachment; filename="{ref}.{fmt}"'})


@app.get("/api/adjustments/{adj_id}/evidence")
def adjustment_evidence(adj_id: str, who: Caller = Depends(caller), st: LineageStore = S):
    r = st.one("SELECT cell_id, submission_id FROM adjustment WHERE id = %s", (adj_id,))
    a = next((a for a in st.adjustments(*r) if a["id"] == adj_id), None) if r else None
    if not a:
        raise NotFound(f"unknown adjustment {adj_id}")
    return Response(evidence.adjustment_evidence_pdf(a, f"{who.actor} ({who.role})", _now()), media_type="application/pdf")


# ---------------------------------------------------------------- S09 governance
@app.get("/api/coverage")
def coverage(sub: str | None = Sub, st: LineageStore = S):
    return packs.coverage(st, sub)


@app.get("/api/audit")
def audit_log(limit: int = Query(50, ge=1, le=500), st: LineageStore = S):
    return {"chain_valid": audit.verify(st.conn), "retention": "7 years", "entries": audit.entries(st.conn, limit)}


# ---------------------------------------------------------------- S10-S12 forward impact
@app.get("/api/elements/{uid}/impact")
def element_impact(uid: str, sub: str | None = Sub, st: LineageStore = S):
    return impact.impact(st, uid, sub)


class WhatIf(BaseModel):
    haircut_pct: float
    incident_ref: str | None = None
    reason: str | None = None


@app.post("/api/elements/{uid}/what-if")
def element_what_if(uid: str, body: WhatIf, sub: str | None = Sub, st: LineageStore = S):
    if not 0 <= body.haircut_pct <= 100:
        raise ValueError("haircut_pct must be between 0 and 100")
    return impact.what_if(st, uid, body.haircut_pct, sub)


class ImpactReport(BaseModel):
    element_uid: str
    haircut_pct: float
    incident_ref: str | None = None


@app.post("/api/impact-report")
def impact_report(body: ImpactReport, sub: str | None = Sub, who: Caller = Depends(caller), st: LineageStore = S):
    el = impact.impact(st, body.element_uid, sub)["element"]
    w = impact.what_if(st, body.element_uid, body.haircut_pct, sub)
    pdf = evidence.impact_report_pdf(el, w, body.haircut_pct, body.incident_ref, f"{who.actor} ({who.role})", _now())
    audit.append(st.conn, who.actor, who.role, "exported impact report",
                 f"{el['name']} · {body.incident_ref or 'INC-[NUMBER]'} · haircut {body.haircut_pct:g}%")
    return Response(pdf, media_type="application/pdf", headers={"Content-Disposition": 'attachment; filename="impact-report.pdf"'})


# ---------------------------------------------------------------- ingestion
class SqlIngest(BaseModel):
    path: str | None = None
    content: str | None = None
    file_type: str | None = None


INPUT_DIR = Path(__file__).resolve().parents[2] / "input"


@app.post("/api/ingest/sql")
def ingest_sql_endpoint(body: SqlIngest, st: LineageStore = S):
    content, ftype = body.content, body.file_type
    if content is None:
        if not body.path:
            raise ValueError("path or content is required")
        f = Path(body.path)
        f = (INPUT_DIR.parent / f if not f.is_absolute() else f).resolve()
        if INPUT_DIR.resolve() not in f.parents:  # ponytail: only files under input/ can be read via the API
            raise ValueError("path must be inside the repository input/ directory")
        if not f.exists():
            raise NotFound(f"no such file {body.path}")
        content, ftype = f.read_text(encoding="utf-8-sig"), ftype or f.suffix.lstrip(".").lower()
    ftype = ftype or ("xml" if content.lstrip().startswith("<") else "sql")
    if ftype in ("xml", "dtsx"):
        r = ingest_sql.ingest_xml(st.conn, content)
    elif ftype == "sql":
        r = ingest_sql.ingest_sql(st.conn, content)
    else:
        raise ValueError("file_type must be sql or xml")
    return {"nodes_upserted": r["nodes_upserted"], "edges_upserted": r["edges_upserted"], "errors": r["errors"]}


@app.post("/api/ingest/openlineage")
def ingest_openlineage(event: dict, st: LineageStore = S):
    return ingest_ol.ingest_event(st.conn, event)
