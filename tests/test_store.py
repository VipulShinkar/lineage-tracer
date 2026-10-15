import pytest

from lineage_api.roles import mask_counterparty, mask_key
from lineage_store import audit, db, ingest_sql
from lineage_store.store import LineageStore, NotFound

CELL = "C07.00:Corporates:r0010:c0200"


@pytest.fixture()
def st(conn):
    return LineageStore(conn)


def test_reverse_dataset_level_has_7_hops_and_all_first_hop_nodes(st):
    r = st.reverse(CELL, "dataset", "2026-06-30.v1")
    uids = {n["uid"] for n in r["nodes"]}
    assert {"system:loan_origination", "system:core_banking", "system:collateral_system",
            "system:fx_rates", "gap:haircut_table"} <= uids
    assert r["summary"]["hops"] == 7
    assert r["summary"]["first_hop_systems"] == "3 + FX reference"
    assert r["summary"]["transformations"] == 8
    assert r["summary"]["controls"] == "13 pass · 1 waived"
    assert r["summary"]["unexplained_residual"] == 0.0
    assert sorted(e["hop"] for e in r["edges"] if "hop" in e) == [1, 2, 3, 4, 5, 6, 7]
    assert any(e.get("dashed") for e in r["edges"])
    assert [g["uid"] for g in r["known_gaps"]] == ["gap:haircut_table"]


def test_attribute_level_uses_fields_from_sql_ingest(st, conn):
    r = st.reverse(CELL, "attribute", None)
    pairs = {(e["src"], e["dst"]) for e in r["edges"]}
    assert ("field:stg_credit_facilities.drawn_balance", "field:dw_exposure.drawn_amount_eur") in pairs
    assert ("field:collateral_master.collateral_value", "field:stg_collateral.market_value_eur") in pairs
    # every field-level edge was written by the SQL ingest
    kinds = db.cypher(conn, "MATCH (:Field)-[e:DERIVES]->(f:Field) WHERE f.uid STARTS WITH 'field:dw_exposure.' "
                            "RETURN DISTINCT e.transform_type")
    assert kinds == ["sql"]


def test_system_level_collapses_datasets(st):
    r = st.reverse(CELL, "system", None)
    assert {"system:staging", "system:risk_warehouse", "system:reg_data_mart"} <= {n["uid"] for n in r["nodes"]}
    assert not any(n["kind"] == "field" for n in r["nodes"])


def test_ingest_is_idempotent(conn):
    sql = open("input/corep_pilot/02_dw_exposure.sql", encoding="utf-8").read()
    r = ingest_sql.ingest_sql(conn, sql, {"dw_exposure": 3})
    assert r["nodes_upserted"] == 0 and r["edges_upserted"] == 0 and not r["errors"]


def test_point_in_time_filters_edges(st):
    nodes, edges = st._reverse_raw(CELL, "1999-01-01")
    assert list(nodes) == [CELL] and edges == []


def test_mapping_version_follows_reference_date(st):
    assert st.transformations(CELL, "2026-06-30.v1")["mapping"]["version"] == "3.2"
    assert st.transformations(CELL, "2026-03-31.v1")["mapping"]["version"] == "3.1"
    m = st.mapping("mapping:product_to_class", "3.2", "3.1")
    assert m["differs_in"] == 2 and [r["code"] for r in m["rows"] if r.get("changed")] == ["LN-BANK", "RCF-BANK"]
    t4 = {t["id"]: t for t in st.transformations(CELL, "2026-03-31.v1")["transformations"]}["T4"]
    assert t4["version"] == "v3.1"


def test_waterfall_computes_and_reconciles(st):
    w = st.waterfall(CELL, None)
    steps = w["steps"]
    assert [s["amount"] for s in steps] == [1312.0, -11.7, -11.9, -26.3, -18.3, -2.1, -1.2, 1240.5]
    assert round(sum(s["amount"] for s in steps[:-1]), 1) == steps[-1]["amount"] == 1240.5
    assert w["residual"] == 0.0 and w["within_tolerance"]
    assert w["controls"]["summary"] == "13 pass · 1 waived · 0 fail"
    assert len(w["controls"]["items"]) == 14
    assert w["adjustment"]["id"] == "ADJ-2026-Q2-014" and w["adjustment"]["amount"] == -18.3


def test_hop3_detail_matches_pdf(st):
    h = st.hop(CELL, 3, None)
    assert (h["records"]["in"], h["records"]["out"]) == (48211, 47960)
    assert (h["records"]["value_in"], h["records"]["value_out"]) == (1312.0, 1288.4)
    assert h["hop"]["actual_run"] == "23:42 → 01-Jul 00:18" and len(h["controls"]) == 4
    with pytest.raises(NotFound):
        st.hop(CELL, 8, None)


def test_records_totals_and_compare(st):
    r = st.records(CELL, "sector", None, 5, None)
    assert r["contributing_records"] == 3418 and r["drilldown_total"] == 1240.5 and r["equals_reported"]
    assert r["total"] == {"records": 3418, "current": 1240.5, "compare": 1184.3, "change": 56.2}
    g = {x["key"]: x for x in r["groups"]}
    assert (g["Manufacturing"]["records"], g["Manufacturing"]["current"], g["Manufacturing"]["compare"]) == (812, 402.1, 391.4)
    assert (g["Energy"]["records"], g["Energy"]["change"]) == (143, 10.7)
    assert [t["value"] for t in r["top"]] == [42.8, 37.5, 31.2, 28.9, 25.4]
    assert [x["key"] for x in r["groups"]][-1] == "Other sectors"


def test_generator_is_deterministic():
    from lineage_store.seed import records

    assert records.generate() == records.generate()


def test_trace_of_cpty_2764(st):
    t = st.trace("REC-000005")
    assert len(t["steps"]) == 7 and t["steps"][0]["amount"] == 27.6 and t["steps"][0]["ccy"] == "USD"
    assert t["steps"][1]["amount"] == 25.4


def test_masking():
    assert mask_counterparty("CPTY-00012764") == "CPTY-•••2764"
    assert mask_key("LOS-FAC-00123458") == "LOS-FAC-00••••58"
    assert mask_key("CBS-ACC-71234502") == "CBS-ACC-7•••••02"


def test_grid_and_templates(st):
    g = st.grid("C07.00", "Corporates", None)
    assert len(g["rows"]) == 5 and all(len(r["cells"]) == 5 for r in g["rows"])
    assert g["rows"][0]["cells"][3]["value"] == 1240.5
    inst = st.grid("C07.00", "Institutions", None)["rows"][0]["cells"]
    assert {c["col"]: c["value"] for c in inst}["0200"] == 612.3
    t = st.templates(None)
    assert len(t["templates"]) == 9 and sum(x["in_scope"] for x in t["templates"]) == 4
    assert t["pilot_scope"] == {"total": 10, "complete": 7, "partial": 2, "gap": 1, "description": t["pilot_scope"]["description"]}


def test_forward_cells_from_collateral_value(st):
    cells = st._forward_cells(["field:collateral_master.collateral_value"], "2026-06-30")
    assert len(cells) == 8 and {c.split(":")[0] for c in cells} == {"C07.00", "C02.00", "C03.00"}
    contrib = db.cypher(st.conn, "MATCH (:Job {uid: 'job:sa_engine'})-[e:DERIVES]->(c:ReportCell) "
                                 "WHERE e.contribution IS NOT NULL RETURN c.uid, e.contribution", cols=2)
    assert sorted(v for _, v in contrib) == sorted([-1.2, -1.1, -48.5, -9.7, -14.2, -10.6])


def test_audit_chain_validates_and_detects_tampering(conn):
    audit.append(conn, "[Tester]", "analyst", "test event", "x", "one")
    audit.append(conn, "[Tester]", "analyst", "test event", "y", None)
    assert audit.verify(conn)
    with pytest.raises(Exception, match="append-only"):
        conn.execute("UPDATE audit_log SET detail = 'tampered' WHERE seq = (SELECT min(seq) FROM audit_log)")
    first = conn.execute("SELECT actor FROM audit_log ORDER BY seq LIMIT 1").fetchone()[0]
    conn.execute("ALTER TABLE audit_log DISABLE TRIGGER audit_log_no_change")
    try:
        conn.execute("UPDATE audit_log SET actor = 'evil' WHERE seq = (SELECT min(seq) FROM audit_log)")
        assert not audit.verify(conn)
        conn.execute("UPDATE audit_log SET actor = %s WHERE seq = (SELECT min(seq) FROM audit_log)", (first,))
        assert audit.verify(conn)
    finally:
        conn.execute("ALTER TABLE audit_log ENABLE TRIGGER audit_log_no_change")
