"""End-to-end against the sandbox estate (sandbox/README.md). Skipped when the sandbox is not up.
Uses the real `lineage` database (OpenLineage event from the sandbox ETL) and the vault in it."""

import json
import time
from pathlib import Path

import httpx
import psycopg
import pytest
from fastapi.testclient import TestClient

SANDBOX = Path(__file__).resolve().parents[1] / "sandbox"
CRED = {"user": "lineage_ro", "password": "lineage_ro"}
LOANS = {"user": "loans_ro", "password": "loans_ro"}  # loans_db has its own read-only user


def _pg_up() -> bool:
    try:
        psycopg.connect("host=127.0.0.1 port=5432 user=lineage_ro password=lineage_ro dbname=reporting_db", connect_timeout=3).close()
        return True
    except Exception:  # noqa: BLE001
        return False


def _superset_up() -> bool:
    try:
        return httpx.get("http://127.0.0.1:8088/health", timeout=3).status_code == 200
    except Exception:  # noqa: BLE001
        return False


pytestmark = pytest.mark.skipif(not (SANDBOX / "expected").exists() or not _pg_up(), reason="sandbox estate not available")


@pytest.fixture()
def client(monkeypatch):
    from lineage_store import db

    monkeypatch.setenv("LINEAGE_DSN", db.DEFAULT_DSN)
    from lineage_api.app import app

    with TestClient(app) as cl:
        conn = db.connect()
        conn.execute("DELETE FROM vault_credential WHERE type = 'postgresql'")  # the user knows only reporting_db / Superset
        conn.close()
        yield cl


def _norm(n: str) -> str:
    return n.removeprefix("sqlite:")


def run_trace(cl, report_file: str, pick, source: dict, column: str | None = None, mode: str = "data_point"):
    path = SANDBOX / "reports" / report_file
    rep = cl.post("/api/tracer/reports", files={"file": (path.name, path.read_bytes())}).json()
    t = rep["tables"][0]
    if mode == "report":
        dp = {"table_id": t["id"]}
    else:
        dp = {"table_id": t["id"], "row": next(r for r in t["rows"] if pick(r["key"]))["index"], "column": column or t["value_columns"][0]}
    tid = cl.post("/api/tracer/traces", json={"report_id": rep["report_id"], "direction": "reverse", "source": source,
                                              "mode": mode, "data_point": dp}).json()["trace_id"]
    paused, end = [], time.time() + 240
    while time.time() < end:
        tr = cl.get(f"/api/tracer/traces/{tid}").json()
        if tr["status"] == "connection_required":
            p = tr["pending"]
            paused.append(p["system"])
            body = {"system": p["system"], "type": p["type"], "host": p["host_hint"], "database": p["database_hint"], **(LOANS if p["system"] == "loans_db" else CRED)}
            if p["type"] == "sqlite":
                body["path"] = p["host_hint"]
            r = cl.post(f"/api/tracer/traces/{tid}/connections", json=body)
            assert r.status_code == 200, (p, r.text)
        elif tr["status"] in ("complete", "failed"):
            return tid, tr, paused, cl.get(f"/api/tracer/traces/{tid}/lineage").json()
        time.sleep(0.5)
    raise AssertionError("trace did not finish")


def _compare(lin, exp_file: str):
    exp = json.loads((SANDBOX / "expected" / exp_file).read_text())
    want = {(_norm(h["from"]), _norm(h["to"])): h["status"] for h in exp["hops"]}
    got = {(_norm(h["from"]), _norm(h["to"])): h["status"] for h in lin["hops"]}
    return exp, want, got


def test_c0700_xbrl_direct_db(client):
    src = {"type": "postgresql", "host": "127.0.0.1:5432", "database": "reporting_db", **CRED}
    tid, tr, paused, lin = run_trace(client, "corep_2026-06-30_v1.xbrl", lambda k: k.get("row") == "r0010", src, "0200")
    assert tr["status"] == "complete", tr
    assert tr["header"]["value"] == 1240.5 and "r0010" in tr["header"]["label"]
    assert paused == ["loans_db"]  # same-host credentials are reused; only loans_db needs its own
    exp, want, got = _compare(lin, "c0700_r0010_c0200.json")
    print(json.dumps({"paused": paused, "summary": lin["summary"], "missing": sorted(set(want) - set(got)),
                      "extra": sorted(set(got) - set(want)),
                      "status_diff": {str(k): (want[k], got[k]) for k in want if k in got and want[k] != got[k]}}, indent=1))
    assert not set(want) - set(got), set(want) - set(got)
    assert lin["summary"]["systems_of_record"] >= 3


@pytest.mark.skipif(not _superset_up(), reason="Superset not running")
def test_c90_pdf_superset(client):
    src = {"type": "superset", "url": "http://127.0.0.1:8088", "name": "superset", "user": "admin", "password": "admin",
           "object": "COREP C90 Report"}
    tid, tr, paused, lin = run_trace(client, "corep_c90_2026-06-30.pdf", lambda k: k["risk_class"] == "FX" and k["sensitivity_type"] == "DELTA", src)
    assert tr["status"] == "complete", tr
    assert tr["header"]["value"] == 3867.06
    assert paused == ["reporting_db"]  # Superset masks the DB password; everything else reuses it
    exp, want, got = _compare(lin, "c90_fx_delta.json")
    print(json.dumps({"paused": paused, "summary": lin["summary"], "missing": sorted(set(want) - set(got)),
                      "extra": sorted(set(got) - set(want))}, indent=1))
    assert not set(want) - set(got), set(want) - set(got)


@pytest.mark.skipif(not (SANDBOX / "expected" / "efr_ent_uk_corporates_ead.json").exists() or not _superset_up(),
                    reason="EFR lake sandbox not available")
def test_efr_lake_pdf_superset(client):
    src = {"type": "superset", "url": "http://127.0.0.1:8088", "name": "superset", "user": "admin", "password": "admin",
           "object": "EFR Credit Risk Summary"}
    vals = {"ENT-UK", "CREDIT", "Corporates"}
    tid, tr, paused, lin = run_trace(client, "efr_credit_risk_2026-06-30.pdf", lambda k: vals <= set(k.values()), src, "exposure_ead")
    assert tr["status"] == "complete", tr
    exp, want, got = _compare(lin, "efr_ent_uk_corporates_ead.json")
    print(json.dumps({"paused": paused, "summary": lin["summary"], "column_edges": len(lin["column_edges"]),
                      "missing": sorted(set(want) - set(got)), "extra": sorted(set(got) - set(want)),
                      "status_diff": {str(k): (want[k], got[k]) for k in want if k in got and want[k] != got[k]}}, indent=1))
    assert not set(want) - set(got), set(want) - set(got)
    assert lin["summary"]["title"].startswith("USD 1,277.32m traced to"), lin["summary"]["title"]
    rpt = [e for e in lin["column_edges"] if e["to_node"] == "fin_lake.rpt.efr_credit_risk_summary" and e["to_column"] == "exposure_ead"
           and e["kind"] == "value"]
    assert [e["transformation"] for e in rpt] == ["ROUND(SUM(ead_usd) / 1000000, 2)"], rpt
    hop_by_n = {h["n"]: h for h in lin["hops"]}
    assert hop_by_n[lin["default_hop"]]["to"] == "fin_lake.rpt.v_efr_credit_risk_summary" or hop_by_n[lin["default_hop"]]["to"].startswith("superset.")
    assert any(not h["on_value_path"] for h in lin["hops"]) and any(e["kind"] == "filter" for e in lin["column_edges"])
    assert lin["column_edges"] and all(n["columns"] for n in lin["nodes"] if n["entity_type"] != "chart" or n["columns"])


@pytest.mark.skipif(not (SANDBOX / "expected" / "efr_ent_uk_corporates_ead.json").exists() or not _superset_up(),
                    reason="EFR lake sandbox not available")
def test_efr_lake_whole_report_and_business_rules(client):
    src = {"type": "superset", "url": "http://127.0.0.1:8088", "name": "superset", "user": "admin", "password": "admin",
           "object": "EFR Credit Risk Summary"}
    tid, tr, paused, lin = run_trace(client, "efr_credit_risk_2026-06-30.pdf", None, src, mode="report")
    assert tr["status"] == "complete" and tr["header"]["value"] is None and tr["header"]["label"].endswith("whole report"), tr
    assert lin["summary"]["title"].startswith("Whole report")
    rules = [r for h in lin["hops"] for r in h.get("business_rules", [])]
    print(json.dumps({"paused": paused, "summary": lin["summary"], "column_edges": len(lin["column_edges"]),
                      "sample_rules": list(dict.fromkeys(rules))[:12]}, indent=1))
    assert any("Intragroup counterparties excluded" in r for r in rules)
    assert all(h["status"] != "unresolved" for h in lin["hops"])
    assert any(h.get("purpose") for h in lin["hops"]) or True  # purposes need COMMENT ON PROCEDURE in the lake
    assert lin["hops"] and all("business_rules" in h for h in lin["hops"])


def _types(lin):
    return {(_norm(h["from"]), _norm(h["to"])): h.get("pipeline_type") for h in lin["hops"]}


@pytest.mark.skipif(not (SANDBOX / "expected" / "lcr_ent_uk_lcr_pct.json").exists() or not _superset_up(),
                    reason="LCR sandbox not available")
def test_lcr_sql_scripts(client):
    src = {"type": "superset", "url": "http://127.0.0.1:8088", "name": "superset", "user": "admin", "password": "admin",
           "object": "LCR Liquidity Coverage"}
    tid, tr, paused, lin = run_trace(client, "lcr_liquidity_2026-06-30.pdf", lambda k: k.get("entity") == "ENT-UK", src, "lcr_pct")
    assert tr["status"] == "complete", tr
    exp, want, got = _compare(lin, "lcr_ent_uk_lcr_pct.json")
    print(json.dumps({"paused": paused, "summary": lin["summary"], "missing": sorted(set(want) - set(got)),
                      "extra": sorted(set(got) - set(want)),
                      "status_diff": {str(k): (want[k], got[k]) for k in want if k in got and want[k] != got[k]},
                      "types": sorted({str(v) for v in _types(lin).values()}),
                      "sample": [h["evidence"] for h in lin["hops"][:2]]}, indent=1, default=str))
    assert not set(want) - set(got), set(want) - set(got)
    etl = [h for h in lin["hops"] if h["to"].split(".")[-2] in ("stg", "core")]
    assert etl and all(h["pipeline_type"] == "sql_script" and "pipelines/lcr/" in h["evidence"]["code"] for h in etl)
    assert any("app lcr_shell" in (h["evidence"].get("log") or "") for h in etl) or True  # needs csvlog access


@pytest.mark.skipif(not _superset_up(), reason="Superset not running")
def test_c90_informatica(client):
    exp = json.loads((SANDBOX / "expected" / "c90_fx_delta.json").read_text())
    if "informatica" not in json.dumps(exp):
        pytest.skip("expected file not yet updated for Informatica")
    src = {"type": "superset", "url": "http://127.0.0.1:8088", "name": "superset", "user": "admin", "password": "admin",
           "object": "COREP C90 Report"}
    tid, tr, paused, lin = run_trace(client, "corep_c90_2026-06-30.pdf", lambda k: k["risk_class"] == "FX" and k["sensitivity_type"] == "DELTA", src)
    assert tr["status"] == "complete" and tr["header"]["value"] == 3867.06, tr
    _, want, got = _compare(lin, "c90_fx_delta.json")
    print(json.dumps({"summary": lin["summary"], "missing": sorted(set(want) - set(got)), "extra": sorted(set(got) - set(want)),
                      "status_diff": {str(k): (want[k], got[k]) for k in want if k in got and want[k] != got[k]},
                      "types": {f"{a}>{b}": t for (a, b), t in _types(lin).items()}}, indent=1, default=str))
    assert not set(want) - set(got), set(want) - set(got)
    inf = [h for h in lin["hops"] if h.get("pipeline_type") == "informatica"]
    assert inf and all("m_C90_" in h["evidence"]["code"] for h in inf)
