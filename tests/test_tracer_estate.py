"""Tracer against a throwaway two-database estate (tracer_a main, tracer_b trading) + SQLite FX file.
Needs the WSL Postgres (like the other store tests); skips otherwise."""

import sqlite3
import time

import psycopg
import pytest
from fastapi.testclient import TestClient

from lineage_tracer import vault
from lineage_tracer.connectors import postgres

ADMIN = "host=127.0.0.1 port=5432 user=lineage password=lineage dbname={}"

DDL_B = """
SET search_path = public;
CREATE TABLE trade_sens (as_of date, risk_class text, sens_type text, ccy text, amount numeric, intragroup boolean);
INSERT INTO trade_sens VALUES
 ('2026-06-30','FX','DELTA','EUR',1000,false), ('2026-06-30','FX','DELTA','USD',500,false),
 ('2026-06-30','FX','DELTA','EUR',999,true), ('2026-06-30','COM','DELTA','USD',70,false);
"""
DDL_A = """
SET search_path = public;
CREATE EXTENSION IF NOT EXISTS postgres_fdw;
CREATE SERVER trading FOREIGN DATA WRAPPER postgres_fdw OPTIONS (host '127.0.0.1', port '5432', dbname 'tracer_b');
CREATE USER MAPPING FOR CURRENT_USER SERVER trading OPTIONS (user 'lineage', password 'lineage');
CREATE SCHEMA stg; CREATE SCHEMA dwh; CREATE SCHEMA rpt;
CREATE FOREIGN TABLE stg.ft_sens (as_of date, risk_class text, sens_type text, ccy text, amount numeric, intragroup boolean)
  SERVER trading OPTIONS (schema_name 'public', table_name 'trade_sens');
CREATE TABLE stg.ref_fx (ccy text, rate numeric, as_of date);
INSERT INTO stg.ref_fx VALUES ('EUR',1.1,'2026-06-30'), ('USD',1,'2026-06-30');
CREATE TABLE dwh.dw_sens (as_of date, risk_class text, sens_type text, amount_usd numeric);
CREATE FUNCTION dwh.load() RETURNS void LANGUAGE plpgsql AS $$
BEGIN
  DELETE FROM dwh.dw_sens;
  -- convert to USD, drop intragroup
  INSERT INTO dwh.dw_sens (as_of, risk_class, sens_type, amount_usd)
  SELECT s.as_of, s.risk_class, s.sens_type, SUM(s.amount * r.rate)
  FROM stg.ft_sens s JOIN stg.ref_fx r ON r.ccy = s.ccy AND r.as_of = s.as_of
  WHERE NOT s.intragroup GROUP BY 1, 2, 3;
END $$;
SELECT dwh.load();
CREATE VIEW rpt.facts AS SELECT 'GROUP-01'::text AS consolidation_group, risk_class, sens_type AS sensitivity_type, as_of,
  SUM(amount_usd) AS reported_value_usd FROM dwh.dw_sens GROUP BY risk_class, sens_type, as_of;
"""

OL = {"eventType": "COMPLETE", "eventTime": "2026-06-30T06:00:00Z", "run": {"runId": "11111111-1111-1111-1111-111111111111"},
      "job": {"name": "load_ref_fx"}, "inputs": [{"name": "market_data.fx_rates"}],
      "outputs": [{"name": "stg.ref_fx", "facets": {"columnLineage": {"fields": {
          "rate": {"inputFields": [{"name": "market_data.fx_rates", "field": "rate"}]}}}}}]}

CSV = b"consolidation_group,risk_class,sensitivity_type,reported_value_usd\nGROUP-01,COM,DELTA,70\nGROUP-01,FX,DELTA,1600\n"


@pytest.fixture(scope="module")
def estate(lineage_dsn, tmp_path_factory):
    adm = psycopg.connect(ADMIN.format("postgres"), autocommit=True)
    for d in ("tracer_a", "tracer_b"):
        adm.execute(f"DROP DATABASE IF EXISTS {d} WITH (FORCE)")
        adm.execute(f"CREATE DATABASE {d}")
    for d, ddl in (("tracer_b", DDL_B), ("tracer_a", DDL_A)):
        c = psycopg.connect(ADMIN.format(d), autocommit=True)
        c.execute(ddl)
        c.close()
    path = tmp_path_factory.mktemp("sq") / "market_data.db"
    s = sqlite3.connect(path)
    s.execute("CREATE TABLE fx_rates (ccy text, rate real, as_of text)")
    s.execute("INSERT INTO fx_rates VALUES ('EUR',1.1,'2026-06-30'), ('USD',1,'2026-06-30')")
    s.commit()
    s.close()
    from lineage_store import db, ingest_ol

    conn = db.connect(lineage_dsn)
    ingest_ol.ingest_event(conn, OL)
    yield str(path)
    conn.close()
    for d in ("tracer_a", "tracer_b"):
        adm.execute(f"DROP DATABASE IF EXISTS {d} WITH (FORCE)")
    adm.close()


def test_postgres_writer_detection(estate):
    c = postgres.connect("127.0.0.1:5432", "tracer_a", "lineage", "lineage")
    v = postgres.writers(c, "rpt", "facts")
    assert v[0]["kind"] == "view" and "sha256" in v[0]["version"]
    f = postgres.writers(c, "dwh", "dw_sens")
    assert f[0]["kind"] == "function" and "dwh.load lines" in f[0]["ref"] and f[0]["sql"].startswith("INSERT INTO dwh.dw_sens")
    fo = postgres.writers(c, "stg", "ft_sens")[0]
    assert fo["foreign"]["database"] == "tracer_b" and fo["foreign"]["table"] == "trade_sens"
    assert postgres.writers(c, "stg", "ref_fx") == []
    assert "rpt.facts" in postgres.consumers(c, "dwh", "dw_sens")
    with pytest.raises(psycopg.errors.ReadOnlySqlTransaction):
        c.execute("CREATE TABLE should_fail (x int)")
    loc = postgres.locate(c, "rpt", "facts", {"g": "GROUP-01", "risk_class": "FX", "sensitivity_type": "DELTA"},
                          "reported_value_usd", 1600.0, "2026-06-30", 0.01)
    assert loc["tied"] and loc["value_col"] == "reported_value_usd" and loc["filters"]["risk_class"] == "FX"


def _wait(cl, tid, want, secs=40):
    end = time.time() + secs
    while time.time() < end:
        t = cl.get(f"/api/tracer/traces/{tid}").json()
        if t["status"] in want:
            return t
        time.sleep(0.4)
    raise AssertionError(f"trace stuck: {t}")


def test_trace_pause_resume_complete(estate):
    from lineage_api.app import app

    with TestClient(app) as cl:
        conn = __import__("lineage_store.db", fromlist=["x"]).connect()
        conn.execute("DELETE FROM vault_credential WHERE database IN ('tracer_a','tracer_b') OR type = 'sqlite'")
        rep = cl.post("/api/tracer/reports", files={"file": ("r.csv", CSV)}).json()
        t0 = rep["tables"][0]
        row = next(r["index"] for r in t0["rows"] if r["key"]["risk_class"] == "FX")
        body = {"report_id": rep["report_id"], "direction": "reverse",
                "data_point": {"table_id": t0["id"], "row": row, "column": "reported_value_usd"},
                "source": {"type": "postgresql", "host": "127.0.0.1:5432", "database": "tracer_a", "user": "lineage",
                           "password": "lineage", "object": "rpt.facts"}}
        tid = cl.post("/api/tracer/traces", json=body).json()["trace_id"]
        # 1. tracer_b is on the same host: the credentials of tracer_a are reused, no pause
        # 2. only the SQLite FX file (found through OpenLineage) needs a connection; a bad path is rejected
        t = _wait(cl, tid, ("connection_required", "complete", "failed"))
        assert t["status"] == "connection_required" and t["pending"]["type"] == "sqlite", t
        assert "password" not in str(t)
        bad = cl.post(f"/api/tracer/traces/{tid}/connections", json={"system": "market_data", "type": "sqlite", "path": "nope.db"})
        assert bad.status_code == 400 and "could not connect" in bad.json()["detail"]
        assert cl.get(f"/api/tracer/traces/{tid}").json()["status"] == "connection_required"
        assert cl.post(f"/api/tracer/traces/{tid}/connections",
                       json={"system": "market_data", "type": "sqlite", "path": estate}).json() == {"ok": True}
        t = _wait(cl, tid, ("complete", "failed"))
        assert t["status"] == "complete", t
        assert t["stats"]["sor_reached"] == 2 and t["stats"]["branches_outstanding"] == 0
        lin = cl.get(f"/api/tracer/traces/{tid}/lineage").json()
        by = {(h["from"], h["to"]): h for h in lin["hops"]}
        h_view = by[("tracer_a.dwh.dw_sens", "tracer_a.rpt.facts")]
        assert h_view["status"] == "proven" and "Recalculated 1,600" in h_view["evidence"]["reconciliation"]
        h_fx = by[("tracer_b.public.trade_sens", "tracer_a.dwh.dw_sens")]
        assert h_fx["status"] == "proven" and "intragroup excluded" in h_fx["transformation"] \
            and "FX rate" in h_fx["transformation"] and "dwh.load lines" in h_fx["evidence"]["code"] \
            and "foreign table stg.ft_sens" in h_fx["evidence"]["code"]
        assert ("tracer_a.stg.ft_sens", "tracer_a.dwh.dw_sens") not in by  # foreign tables are windows, not hops
        assert by[("market_data.fx_rates", "tracer_a.stg.ref_fx")]["status"] == "code_derived"
        assert "using credentials of tracer_a" in h_fx["evidence"]["log"] or "credentials of tracer_a" in str(lin["hops"])
        assert "OpenLineage job load_ref_fx" in by[("market_data.fx_rates", "tracer_a.stg.ref_fx")]["evidence"]["log"]
        assert lin["summary"]["systems_of_record"] == 2 and "2 systems of record" in lin["summary"]["title"]
        assert {"system_of_record", "staging", "reporting_layer"} <= set(lin["lanes"])
        assert [h["n"] for h in lin["hops"]] == list(range(1, len(lin["hops"]) + 1))
        sor_nodes = {n["id"] for n in lin["nodes"] if n["kind"] == "sor"}
        assert lin["hops"][0]["from"] in sor_nodes and lin["hops"][-1]["to"] == "tracer_a.rpt.facts"
        pk = cl.post(f"/api/tracer/traces/{tid}/evidence-pack", json={"format": "pdf"}).json()
        assert pk["ref"].startswith("TRC-") and cl.get(pk["download_url"]).content.startswith(b"%PDF")
        assert any(s["system"] == "tracer_b" for s in cl.get("/api/tracer/systems").json())
        assert "password" not in str(cl.get("/api/tracer/systems").json())


def test_delete_systems(lineage_dsn):
    from lineage_api.app import app

    with TestClient(app) as cl:
        c = __import__("lineage_store.db", fromlist=["x"]).connect()
        vault.put(c, "del_me", "postgresql", "127.0.0.1:5432", "del_db", {"user": "u", "password": "p"})
        assert cl.delete("/api/tracer/systems/del_me").json() == {"removed": 1}
        assert cl.delete("/api/tracer/systems/del_me").status_code == 404
        vault.put(c, "del_me", "postgresql", "127.0.0.1:5432", "del_db", {"user": "u", "password": "p"})
        assert cl.delete("/api/tracer/systems").json()["removed"] >= 1
        assert cl.get("/api/tracer/systems").json() == []


DDL_LAKE = """
SET search_path = public;
DROP SCHEMA IF EXISTS tr_raw, tr_stg, tr_core, tr_rpt CASCADE;
CREATE SCHEMA tr_raw; CREATE SCHEMA tr_stg; CREATE SCHEMA tr_core; CREATE SCHEMA tr_rpt;
CREATE TABLE tr_raw.loans (id int, ccy text, drawn numeric, undrawn numeric, ccf numeric, note text);
INSERT INTO tr_raw.loans VALUES (1,'EUR',100,50,0.5,'a'), (2,'EUR',200,100,0.5,'b'), (3,'USD',10,10,1,'c');
CREATE TABLE tr_stg.stg_loans (id int, ccy text, drawn numeric, undrawn numeric, ccf numeric);
CREATE PROCEDURE tr_stg.load() LANGUAGE plpgsql AS $$
BEGIN
  DELETE FROM tr_stg.stg_loans;
  INSERT INTO tr_stg.stg_loans (id, ccy, drawn, undrawn, ccf) SELECT id, ccy, drawn, undrawn, ccf FROM tr_raw.loans;
END $$;
CREATE TABLE tr_core.core_exposure (id int, ccy text, ead numeric);
CREATE PROCEDURE tr_core.load() LANGUAGE plpgsql AS $$
BEGIN
  DELETE FROM tr_core.core_exposure;
  INSERT INTO tr_core.core_exposure (id, ccy, ead)
  SELECT s.id, s.ccy, s.drawn + s.ccf * s.undrawn FROM tr_stg.stg_loans s;
END $$;
CALL tr_stg.load(); CALL tr_core.load();
CREATE VIEW tr_rpt.v_summary AS WITH t AS (SELECT ccy, SUM(ead) AS ead FROM tr_core.core_exposure GROUP BY ccy)
  SELECT ccy, ROUND(ead * 2, 1) AS exposure_ead FROM t;
"""


def test_same_db_multi_schema_column_edges(lineage_dsn):
    from lineage_tracer import store
    from lineage_api.app import app
    from lineage_store import db

    conn = db.connect(lineage_dsn)
    store.apply(conn)
    conn.execute(DDL_LAKE)
    conn.execute("DELETE FROM vault_credential")
    with TestClient(app) as cl:
        rep = cl.post("/api/tracer/reports", files={"file": ("lake.csv", b"ccy,exposure_ead\nEUR,375\nUSD,20\n")}).json()
        t0 = rep["tables"][0]
        body = {"report_id": rep["report_id"], "direction": "reverse",
                "data_point": {"table_id": t0["id"], "row": 0, "column": "exposure_ead"},
                "source": {"type": "postgresql", "host": "127.0.0.1:5432", "database": "lineage_test", "user": "lineage",
                           "password": "lineage", "object": "tr_rpt.v_summary"}}
        tid = cl.post("/api/tracer/traces", json=body).json()["trace_id"]
        t = _wait(cl, tid, ("complete", "failed", "connection_required"))
        assert t["status"] == "complete", t
        lin = cl.get(f"/api/tracer/traces/{tid}/lineage").json()
    conn.execute("DROP SCHEMA tr_raw, tr_stg, tr_core, tr_rpt CASCADE")
    ids = {n["id"] for n in lin["nodes"]}
    assert {"lineage_test.tr_rpt.v_summary", "lineage_test.tr_core.core_exposure", "lineage_test.tr_stg.stg_loans",
            "lineage_test.tr_raw.loans"} <= ids
    assert all(h["status"] == "proven" for h in lin["hops"]), lin["hops"]
    es = {(e["from_node"].split(".", 1)[1], e["from_column"], e["to_node"].split(".", 1)[1], e["to_column"]): e["transformation"]
          for e in lin["column_edges"]}
    assert es[("tr_core.core_exposure", "ead", "tr_rpt.v_summary", "exposure_ead")] == "ROUND(SUM(ead) * 2, 1)"  # composed through the CTE
    assert es[("tr_stg.stg_loans", "drawn", "tr_core.core_exposure", "ead")] == "drawn + ccf * undrawn"
    assert es[("tr_stg.stg_loans", "ccf", "tr_core.core_exposure", "ead")] == "drawn + ccf * undrawn"
    assert es[("tr_raw.loans", "ccy", "tr_stg.stg_loans", "ccy")] == "pass-through"
    kinds = {(e["from_node"].split(".", 1)[1], e["from_column"], e["to_column"]): e["kind"] for e in lin["column_edges"]}
    assert kinds[("tr_stg.stg_loans", "drawn", "ead")] == "value"
    hop_by_n = {h["n"]: h for h in lin["hops"]}
    assert hop_by_n[lin["default_hop"]]["to"] == "lineage_test.tr_rpt.v_summary" and hop_by_n[lin["default_hop"]]["on_value_path"]
    assert all(h["on_value_path"] for h in lin["hops"]) and all(n["on_value_path"] for n in lin["nodes"])
    raw = next(n for n in lin["nodes"] if n["id"] == "lineage_test.tr_raw.loans")
    assert raw["service"] == "postgresql" and raw["schema"] == "tr_raw" and raw["name"] == "loans" and raw["entity_type"] == "table"
    cols = {c["name"]: c["in_path"] for c in raw["columns"]}
    assert cols["drawn"] and cols["ccy"] and not cols["note"]
    assert next(n for n in lin["nodes"] if n["name"] == "v_summary")["entity_type"] == "view"


def _store_trace(conn, tid, nodes, hops, header):
    from psycopg.types.json import Jsonb

    state = {"queue": [], "seen": {}, "nodes": {n["id"]: n for n in nodes}, "connected": [], "pending": None, "ctx": {}}
    conn.execute("DELETE FROM trace WHERE trace_id = %s", (tid,))
    conn.execute("INSERT INTO trace (trace_id, report_id, label, status, header, state) VALUES (%s,'r','l','complete',%s,%s)",
                 (tid, Jsonb(header), Jsonb(state)))
    conn.execute("DELETE FROM trace_hop WHERE trace_id = %s", (tid,))
    for h in hops:
        conn.execute("INSERT INTO trace_hop VALUES (%s,%s,%s)", (tid, h["n"], Jsonb({"status": "proven", "attribute_held_in": [],
                     "sourced_from": [], "transformation": "", "consumed_by": "", "evidence": {}, **h})))


def test_lineage_endpoint_old_and_odd_node_ids(lineage_dsn):
    """Superset chart ids, SQLite ids with dots and traces stored before column edges existed must all render."""
    from lineage_api.app import app
    from lineage_store import db

    conn = db.connect(lineage_dsn)
    n = lambda i, o, sysn, kind="intermediate", lane="staging": {"id": i, "system": sysn, "object": o, "lane": lane, "kind": kind}  # noqa: E731
    c90 = [n("superset.COREP C90 Report", "COREP C90 Report", "superset", "anchor", "report_tool"),
           n("reporting_db.rpt.v_corep_c90", "rpt.v_corep_c90", "reporting_db", lane="reporting_layer"),
           n("market_data.db.fx_rates", "fx_rates", "market_data.db", "sor", "system_of_record")]
    old = [{"n": 1, "from": c90[2]["id"], "to": c90[1]["id"], "cols": [["rate", "rate"]]},          # pre-column-edge format
           {"n": 2, "from": c90[1]["id"], "to": c90[0]["id"], "cols": [["v", "v", "pass-through", True, "value"]]}]
    _store_trace(conn, "t_c90_shape", c90, old, {"value": 3867.06, "unit": "USD", "label": "C90"})
    c07 = [n("reporting_db.rpt.c0700_facts", "rpt.c0700_facts", "reporting_db", "anchor", "reporting_layer"),
           n("loans_db.los.facility", "los.facility", "loans_db", "sor", "system_of_record")]
    _store_trace(conn, "t_c07_shape", c07, [{"n": 1, "from": c07[1]["id"], "to": c07[0]["id"], "cols": []}],
                 {"value": 1240.5, "unit": "EUR m", "label": "C 07.00"})
    with TestClient(app) as cl:
        a = cl.get("/api/tracer/traces/t_c90_shape/lineage")
        assert a.status_code == 200, a.text
        a = a.json()
        assert a["default_hop"] == 2 and {e["kind"] for e in a["column_edges"]} == {"value"}
        fx = next(x for x in a["nodes"] if x["id"] == "market_data.db.fx_rates")
        assert fx["name"] == "fx_rates" and fx["service"] == "postgresql" and fx["columns"] == []
        b = cl.get("/api/tracer/traces/t_c07_shape/lineage")
        assert b.status_code == 200 and b.json()["summary"]["title"] == "EUR 1,240.5m traced to 1 system of record"
    conn.execute("DELETE FROM trace WHERE trace_id IN ('t_c90_shape','t_c07_shape')")
    conn.execute("DELETE FROM trace_hop WHERE trace_id IN ('t_c90_shape','t_c07_shape')")


COMMENTS = """
COMMENT ON COLUMN tr_core.core_exposure.ead IS 'Exposure at Default: Drawn plus converted undrawn.';
COMMENT ON PROCEDURE tr_core.load() IS 'Builds the exposure fact from staged loans';
COMMENT ON TABLE tr_raw.loans IS 'Loan contracts as delivered by the loan system';
COMMENT ON COLUMN tr_raw.loans.ccf IS 'CCF';
"""


def test_report_mode_glossary_and_business_rules(lineage_dsn):
    from lineage_api.app import app
    from lineage_store import db
    from lineage_tracer import store

    conn = db.connect(lineage_dsn)
    store.apply(conn)
    conn.execute(DDL_LAKE)
    conn.execute(COMMENTS)
    conn.execute("DELETE FROM vault_credential")
    with TestClient(app) as cl:
        rep = cl.post("/api/tracer/reports", files={"file": ("lake.csv", b"ccy,exposure_ead\nEUR,750\nUSD,40\n")}).json()
        body = {"report_id": rep["report_id"], "direction": "reverse", "mode": "report",
                "data_point": {"table_id": rep["tables"][0]["id"]},
                "source": {"type": "postgresql", "host": "127.0.0.1:5432", "database": "lineage_test", "user": "lineage",
                           "password": "lineage", "object": "tr_rpt.v_summary"}}
        tid = cl.post("/api/tracer/traces", json=body).json()["trace_id"]
        t = _wait(cl, tid, ("complete", "failed", "connection_required"))
        assert t["status"] == "complete" and t["header"]["value"] is None and t["header"]["label"].endswith("whole report"), t
        lin = cl.get(f"/api/tracer/traces/{tid}/lineage").json()
    conn.execute("DROP SCHEMA tr_raw, tr_stg, tr_core, tr_rpt CASCADE")
    assert lin["summary"]["title"].startswith("Whole report") and lin["summary"]["unresolved"] == 0
    assert all(h["status"] == "proven" for h in lin["hops"]), [(h["from"], h["status"], h["evidence"].get("reconciliation")) for h in lin["hops"]]
    # totals are reconciled, not a single row
    assert any("tr_rpt.v_summary" in h["to"] and "Recalculated 790" in h["evidence"]["reconciliation"] for h in lin["hops"])
    by = {h["to"].rsplit(".", 1)[-1]: h for h in lin["hops"]}
    assert by["core_exposure"]["purpose"] == "Builds the exposure fact from staged loans"
    assert "Exposure at Default = drawn + ccf × undrawn" in by["core_exposure"]["business_rules"][0]
    assert any(r.startswith("Summed by") for r in by["v_summary"]["business_rules"])
    raw = next(n for n in lin["nodes"] if n["name"] == "loans")
    assert raw["description"] == "Loan contracts as delivered by the loan system"
    assert next(c for c in raw["columns"] if c["name"] == "ccf")["description"] == "CCF"
    assert any(e.get("business_rule", "").startswith("Exposure at Default") for e in lin["column_edges"])
