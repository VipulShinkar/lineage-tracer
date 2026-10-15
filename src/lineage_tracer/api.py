"""Tracer routes (docs/spec/tracer-api.md), mounted under /api/tracer."""

from __future__ import annotations

import re
import uuid

from fastapi import APIRouter, HTTPException, UploadFile
from psycopg.types.json import Json
from pydantic import BaseModel

from lineage_store import audit, db
from lineage_store.store import NotFound
from lineage_tracer import pack, report_reader, tracer, vault
from lineage_tracer.connectors import postgres, sqlite, superset

router = APIRouter(prefix="/api/tracer")


def _conn():
    return db.connect()


def _report(conn, rid: str) -> dict:
    r = conn.execute("SELECT report_id, file_name, payload FROM tracer_report WHERE report_id=%s", (rid,)).fetchone()
    if not r:
        raise NotFound(f"unknown report {rid}")
    return {"report_id": r[0], "file_name": r[1], **r[2]}


@router.post("/reports")
async def upload_report(file: UploadFile):
    data = await file.read()
    try:
        rep = report_reader.read_report(file.filename or "report", data)
    except ValueError as e:
        raise HTTPException(400, str(e))
    rid = uuid.uuid4().hex[:12]
    conn = _conn()
    try:
        conn.execute("INSERT INTO tracer_report (report_id, file_name, payload) VALUES (%s,%s,%s)",
                     (rid, rep["file_name"], Json({"meta": rep["meta"], "tables": rep["tables"]})))
        return {"report_id": rid, **rep}
    finally:
        conn.close()


@router.get("/reports/{rid}")
def get_report(rid: str):
    conn = _conn()
    try:
        return _report(conn, rid)
    finally:
        conn.close()


class DataPoint(BaseModel):
    table_id: str
    row: int | None = None       # data_point mode
    column: str | None = None


class Source(BaseModel):
    type: str
    name: str | None = None
    url: str | None = None
    host: str | None = None
    database: str | None = None
    path: str | None = None
    user: str | None = None
    password: str | None = None
    object: str | None = None


class TraceReq(BaseModel):
    report_id: str
    data_point: DataPoint
    direction: str = "reverse"
    mode: str = "data_point"      # "data_point" | "report" (trace every value column of the report)
    source: Source


@router.post("/traces")
def start_trace(body: TraceReq):
    conn = _conn()
    try:
        rep = _report(conn, body.report_id)
        return {"trace_id": tracer.start(conn, rep, {"data_point": body.data_point.model_dump(),
                                                     "source": body.source.model_dump(), "mode": body.mode})}
    finally:
        conn.close()


def _stats(state: dict, steps: list, nodes: dict) -> dict:
    sor = sum(n["kind"] == "sor" for n in nodes.values())
    q = len(state["queue"])
    return {"systems_connected": len(state["connected"]), "sor_reached": sor, "sor_known": sor + q, "branches_outstanding": q}


def _load(conn, tid: str):
    r = conn.execute("SELECT status, error, header, state FROM trace WHERE trace_id=%s", (tid,)).fetchone()
    if not r:
        raise NotFound(f"unknown trace {tid}")
    steps = [d for (d,) in conn.execute("SELECT data FROM trace_step WHERE trace_id=%s ORDER BY n", (tid,))]
    hops = [d for (d,) in conn.execute("SELECT data FROM trace_hop WHERE trace_id=%s ORDER BY n", (tid,))]
    return r[0], r[1], r[2], r[3], steps, hops


@router.get("/traces/{tid}")
def get_trace(tid: str):
    conn = _conn()
    try:
        status, error, header, state, steps, _ = _load(conn, tid)
        out = {"trace_id": tid, "status": status, "header": header, "stats": _stats(state, steps, state["nodes"]),
               "steps": steps}
        if error:
            out["error"] = error
        if status == "connection_required" and state.get("pending"):
            out["pending"] = state["pending"]
        return out
    finally:
        conn.close()


class Connection(BaseModel):
    system: str
    type: str
    host: str | None = None
    database: str | None = None
    path: str | None = None
    user: str = ""
    password: str = ""


@router.post("/traces/{tid}/connections")
def add_connection(tid: str, body: Connection):
    conn = _conn()
    try:
        _load(conn, tid)
        try:
            if body.type == "postgresql":
                postgres.connect(body.host or "", body.database or "", body.user, body.password).close()
            elif body.type == "sqlite":
                sqlite.connect(body.path or body.database or "").close()
            elif body.type == "superset":
                superset.login(body.host or "", body.user, body.password).close()
            else:
                raise ValueError(f"unknown system type {body.type}")
        except Exception as e:  # noqa: BLE001
            raise HTTPException(400, f"could not connect: {str(e).splitlines()[0][:200] if str(e) else type(e).__name__}")
        loc = body.path or body.database if body.type == "sqlite" else body.database
        vault.put(conn, body.system, body.type, body.host, loc, {"user": body.user, "password": body.password})
        audit.append(conn, "tracer", "system", f"connection stored for {body.system}", f"{body.type}:{body.system}", f"trace {tid}")
        tracer.resume(conn, tid, {**body.model_dump(), "path": body.path or (body.database if body.type == "sqlite" else None)})
        return {"ok": True}
    finally:
        conn.close()


def _value_path(edges: list[dict], default: dict | None) -> tuple[set, set]:
    """Walk the value edges backwards from the reported column: -> (hop numbers, (node, column) pairs) on the value path."""
    if not default:
        return set(), set()
    seen = {(e["to_node"], e["to_column"]) for e in edges if e["hop"] == default["n"] and e["kind"] == "value" and e["_path"]}
    todo, hops = list(seen), {default["n"]}
    while todo:
        n, c = todo.pop()
        for e in edges:
            if e["kind"] == "value" and (e["to_node"], e["to_column"]) == (n, c):
                hops.add(e["hop"])
                if (e["from_node"], e["from_column"]) not in seen:
                    seen.add((e["from_node"], e["from_column"]))
                    todo.append((e["from_node"], e["from_column"]))
    return hops, seen


def _derive_unit(edges: list[dict]) -> str | None:
    """No unit in the report: infer it from a currency suffix on a source column (ead_usd) and a /1000000 scaling."""
    cur = next((m.group(1).upper() for e in edges if e["kind"] == "value"
                if (m := re.search(r"_(usd|eur|gbp|chf|jpy)$", e["from_column"], re.I))), None)
    million = any(re.search(r"/ ?(1000000|1e6)", e["transformation"] or "") for e in edges)
    return cur and cur + (" m" if million else "")


def _col(c: list) -> tuple:
    """Column-edge entry as [src, tgt, transformation, in_path, kind]; traces stored before those fields have only [src, tgt]."""
    sc, tc, *rest = c
    tr, p, kind, rule = (rest + [None, True, "value", None][len(rest):])[:4]
    return sc, tc, tr, p, kind, rule


def _lineage(conn, tid: str) -> dict:
    status, _, header, state, _, hops = _load(conn, tid)
    nodes = list(state["nodes"].values())
    used = {n["lane"] for n in nodes}
    for h in hops:
        for k in ("from", "to"):
            if h[k] not in state["nodes"]:  # unresolved placeholder endpoints
                nodes.append({"id": h[k], "system": h[k].split(".")[0], "object": h[k], "lane": "staging", "kind": "intermediate"})
                state["nodes"][h[k]] = nodes[-1]
                used.add("staging")
    edges_ = [{"from_node": h["from"], "from_column": sc, "to_node": h["to"], "to_column": tc, "hop": h["n"],
               "transformation": tr, "kind": kind, "_path": p, **({"business_rule": rule} if rule else {})}
              for h in hops for sc, tc, tr, p, kind, rule in map(_col, h.get("cols") or [])]
    anchor = next((n["id"] for n in nodes if n["kind"] == "anchor"), None)
    default = max((h for h in hops if h["to"] == anchor), key=lambda h: h["n"], default=None)
    vhops, vcols = _value_path(edges_, default)
    ends = {(e["from_node"], e["from_column"]) for e in edges_ if e["_path"]} | {(e["to_node"], e["to_column"]) for e in edges_ if e["_path"]}
    for n in nodes:  # catalog details; in_path = on the traced lineage, on_value_path = feeds the reported value
        n.setdefault("service", "postgresql")
        n.setdefault("name", n["object"].rsplit(".", 1)[-1])
        n.setdefault("entity_type", "table")
        n.setdefault("schema", n["object"].rsplit(".", 1)[0] if "." in n["object"] else None)
        path = set(n.pop("path_cols", []))
        n["columns"] = [{**c, "in_path": c["name"] in path or (n["id"], c["name"]) in ends} for c in n.get("columns", [])]
        n["on_value_path"] = any(v[0] == n["id"] for v in vcols) or n["id"] == anchor
    clean = [{**{k: v for k, v in h.items() if k not in ("recon", "cols")}, "on_value_path": h["n"] in vhops} for h in hops]
    sor = sum(n["kind"] == "sor" for n in nodes)
    v = header.get("value")
    unit, derived = header.get("unit"), _derive_unit(edges_)
    if derived and (not unit or (unit == derived.split()[0] and derived.endswith(" m"))):
        unit = derived
    header = {**header, "unit": unit} if unit else header
    if v is None:
        amt = f"Whole report ({len(state['ctx'].get('value_names', []))} value columns)"
    else:
        amt = (f"{unit[:-2]} {v:,.2f}".rstrip("0").rstrip(".") + "m") if unit and unit.endswith(" m") else f"{unit or ''} {v:,.2f}".strip()
    return {"header": header,
            "summary": {"hops": len(hops), "proven": sum(h["status"] == "proven" for h in hops),
                        "code_derived": sum(h["status"] == "code_derived" for h in hops),
                        "unresolved": sum(h["status"] == "unresolved" for h in hops), "systems_of_record": sor,
                        "title": f"{amt} traced to {sor} system{'s' if sor != 1 else ''} of record"},
            "lanes": [x for x in tracer.LANES if x in used], "nodes": nodes,
            "edges": [{"from": h["from"], "to": h["to"], "hop": h["n"], "status": h["status"]} for h in hops],
            "hops": clean, "default_hop": default["n"] if default else None,
            "column_edges": [{k: v for k, v in e.items() if k != "_path"} for e in edges_]}


@router.get("/traces/{tid}/lineage")
def get_lineage(tid: str):
    conn = _conn()
    try:
        return _lineage(conn, tid)
    finally:
        conn.close()


class PackReq(BaseModel):
    format: str = "pdf"


@router.post("/traces/{tid}/evidence-pack")
def evidence_pack(tid: str, body: PackReq):
    conn = _conn()
    try:
        return pack.create(conn, tid, _lineage(conn, tid), body.format)
    finally:
        conn.close()


@router.get("/traces")
def list_traces():
    conn = _conn()
    try:
        return [{"trace_id": t, "label": lbl, "status": st, "created_at": c.isoformat()} for t, lbl, st, c in conn.execute(
            "SELECT trace_id, label, status, created_at FROM trace ORDER BY created_at DESC LIMIT 50")]
    finally:
        conn.close()


@router.get("/systems")
def systems():
    conn = _conn()
    try:
        return vault.systems(conn)
    finally:
        conn.close()


@router.delete("/systems")
def clear_systems():
    conn = _conn()
    try:
        n = vault.delete(conn)
        audit.append(conn, "tracer", "system", "cleared saved connections", "vault", f"{n} removed")
        return {"removed": n}
    finally:
        conn.close()


@router.delete("/systems/{system}")
def delete_system(system: str):
    conn = _conn()
    try:
        n = vault.delete(conn, system)
        if not n:
            raise NotFound(f"unknown system {system}")
        audit.append(conn, "tracer", "system", "removed saved connection", system)
        return {"removed": n}
    finally:
        conn.close()
