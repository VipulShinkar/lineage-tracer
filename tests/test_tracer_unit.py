"""Tracer unit tests: no network, no sandbox. Postgres tests use a throwaway schema in lineage_test."""

import io
import os

import pytest

from lineage_tracer import report_reader, sql_lineage, vault

C90 = [("GROUP-01", "COM", "DELTA", "3916.49"), ("GROUP-01", "FX", "DELTA", "3867.06"), ("GROUP-01", "ALL", "ALL", "9626.96")]


def c90_pdf() -> bytes:
    import pymupdf

    doc = pymupdf.open()
    pg = doc.new_page()
    for i, t in enumerate(["COREP C90 Report;", "J P Morgan Bank,", "Date : 30 Jun 2026",
                           "Delivered to : Prudential Regulatory Authority"]):
        pg.insert_text((90, 100 + 26 * i), t, fontsize=10)
    xs = [100, 210, 290, 380]
    for x, h in zip(xs, ["consolidation_group", "risk_class", "sensitivity_type", "reported_value_usd"]):
        pg.insert_text((x, 260), h, fontsize=9)
    for r, row in enumerate(C90):
        for x, v in zip([xs[0] + 20, xs[1] + 20, xs[2] + 10, xs[3] + 20], row):
            pg.insert_text((x, 280 + 15 * r), v, fontsize=9)
    return doc.tobytes()


def test_pdf_c90():
    r = report_reader.read_report("c90.pdf", c90_pdf())
    m, t = r["meta"], r["tables"][0]
    assert m["title"] == "COREP C90 Report" and m["entity"] == "J P Morgan Bank" and m["ref_date"] == "2026-06-30"
    assert m["delivered_to"] == "Prudential Regulatory Authority" and m["return_type"] == "COREP"
    assert t["key_columns"] == ["consolidation_group", "risk_class", "sensitivity_type"]
    assert t["value_columns"] == ["reported_value_usd"] and t["unit"] == "USD"
    assert t["rows"][1]["key"]["risk_class"] == "FX" and t["rows"][1]["values"]["reported_value_usd"] == 3867.06


XBRL = b"""<?xml version="1.0"?><xbrli:xbrl xmlns:xbrli="http://www.xbrl.org/2003/instance" xmlns:c07="urn:c07"
 xmlns:xbrldi="http://xbrl.org/2006/xbrldi">
<xbrli:context id="k1"><xbrli:entity><xbrli:identifier scheme="x">LEI1</xbrli:identifier></xbrli:entity>
<xbrli:period><xbrli:instant>2026-06-30</xbrli:instant></xbrli:period>
<xbrli:scenario><xbrldi:explicitMember dimension="c07:ExposureClass">c07:Corporates</xbrldi:explicitMember></xbrli:scenario></xbrli:context>
<c07:r0010c0200 contextRef="k1" unitRef="EUR">1,240.5</c07:r0010c0200>
<c07:r0010c0220 contextRef="k1" unitRef="EUR">3.0</c07:r0010c0220></xbrli:xbrl>""".replace(b"1,240.5", b"1240.5")


def test_xbrl():
    r = report_reader.read_report("corep_2026-06-30_v1.xbrl", XBRL)
    t = r["tables"][0]
    assert r["meta"]["ref_date"] == "2026-06-30" and r["meta"]["version"] == "v1"
    assert t["key_columns"] == ["ExposureClass", "row"] and t["value_columns"] == ["0200", "0220"]
    assert t["rows"][0]["key"] == {"ExposureClass": "Corporates", "row": "r0010"} and t["rows"][0]["values"]["0200"] == 1240.5


def test_csv():
    r = report_reader.read_report("x.csv", b"Row,Item,0010\nr0010,Total,12.5\nr0020,Other,3\n")
    assert r["tables"][0]["key_columns"] == ["Row", "Item"] and r["tables"][0]["rows"][1]["values"] == {"0010": 3.0}


SQL = """INSERT INTO dwh.dw_s (as_of, risk_class, amt_usd)
SELECT s.as_of, s.risk_class, SUM(s.amt * r.rate) FROM stg.s s JOIN stg.fx r ON r.ccy = s.ccy
WHERE NOT s.is_intragroup GROUP BY 1, 2"""


def test_sql_lineage():
    w = sql_lineage.parse_writer(SQL)
    assert w.target == "dwh.dw_s" and set(w.sources) == {"stg.s", "stg.fx"}
    assert sql_lineage.leaf_columns(w, "amt_usd") == [("stg.s", "amt"), ("stg.fx", "rate")]
    assert sql_lineage.is_passthrough(w, "risk_class") and not sql_lineage.is_passthrough(w, "amt_usd")
    s = sql_lineage.summarize(w, "amt_usd")
    assert "FX rate r.rate" in s and "intragroup excluded" in s and "grouped by as_of, risk_class" in s


def test_vault_roundtrip(conn):
    from lineage_tracer import store

    store.apply(conn)
    vault.put(conn, "tst", "postgresql", "localhost", "vault_test_db", {"user": "u", "password": "p@ss"})
    assert vault.get(conn, "postgresql", "127.0.0.1:5432", "vault_test_db") == {"user": "u", "password": "p@ss"}
    raw = conn.execute("SELECT secret FROM vault_credential WHERE database='vault_test_db'").fetchone()[0]
    assert b"p@ss" not in bytes(raw)
    assert all("secret" not in s and "password" not in str(s) for s in vault.systems(conn))
    conn.execute("DELETE FROM vault_credential WHERE database='vault_test_db'")


def test_same_host_other_port(conn):
    from lineage_tracer import store

    store.apply(conn)
    conn.execute("DELETE FROM vault_credential")
    vault.put(conn, "a", "postgresql", "127.0.0.1:5432", "a_db", {"user": "u", "password": "p"})
    assert [s for s, _ in vault.same_host(conn, "postgresql", "localhost:5433", "fin_lake")] == ["a"]
    assert vault.same_host(conn, "postgresql", "127.0.0.1:5432", "a_db") == []
    conn.execute("DELETE FROM vault_credential")


def test_business_rules_sample_statement():
    from lineage_tracer import business_rules as br

    sql = """INSERT INTO core.fact_exposure (entity_key, ead_usd)
    SELECT e.entity_key, ROUND(l.drawn_amt * fx.rate_to_usd + p.ccf * l.undrawn_amt * fx.rate_to_usd, 2)
    FROM stg.loan l JOIN stg.fx_rate fx ON fx.ccy = l.ccy AND fx.rate_date = DATE '2026-06-30'
    JOIN core.dim_product p ON p.product_code = l.product_code
    JOIN core.dim_entity e ON e.entity_code = l.entity_code
    WHERE NOT l.is_intragroup"""
    w = sql_lineage.parse_writer(sql)
    t = br.Terms({"ccf": "CCF", "ead_usd": "Exposure at Default", "drawn_amt": "drawn balance"})
    rules = br.hop_rules(w, "ead_usd", None, t, "2026-06-30", [])
    assert rules[0].startswith("Exposure at Default = drawn balance × rate_to_usd + CCF × undrawn_amt × rate_to_usd, rounded to 2 dp")
    assert any(r.startswith("Converted to USD at the 30-Jun-2026 FX rate (rate_to_usd matched on ccy") for r in rules)
    items = br.rule_items(w, "ead_usd", None, t, "2026-06-30", [])
    assert [x for x in br.rules_for(items, "core.dim_product")] == ["Looks up dim_product (matched on product_code)"] or         br.rules_for(items, "core.dim_product")[0].endswith("looked up from dim_product by product_code")
    assert not any("Exposure at Default" in x for x in br.rules_for(items, "core.dim_product"))
    assert br.rules_for(items, "stg.loan")[0].startswith("Exposure at Default = ")
    assert "Intragroup counterparties excluded" in br.rules_for(items, "stg.loan")
    assert "Intragroup counterparties excluded" in rules
    agg = sql_lineage.parse_writer("""INSERT INTO rpt.s (entity, exposure_ead) WITH f AS (SELECT entity, SUM(ead_usd) AS ead_usd FROM core.fe GROUP BY entity)
    SELECT entity, ROUND(ead_usd / 1000000, 2) FROM f""")
    assert br.column_rule(agg, "exposure_ead", None, br.Terms()) == "Sum of ead_usd, expressed in millions (÷1,000,000), rounded to 2 dp"
    assert "Summed by entity" in br.hop_rules(agg, "exposure_ead", None, br.Terms(), None, [])
    tot = sql_lineage.parse_writer("CREATE VIEW v AS SELECT entity, x FROM r UNION ALL SELECT 'GROUP' AS entity, SUM(x) AS x FROM r")
    assert "Total row GROUP = sum of the detail rows" in br.hop_rules(tot, "x", None, br.Terms(), None, [])


def test_business_term_and_cte_lookup():
    from lineage_tracer import business_rules as br, sql_lineage
    assert br.short("CCF: Credit Conversion Factor applied to undrawn commitments.") == "CCF"
    assert br.short("Units of USD per one unit of the currency.") is None
    sql = """INSERT INTO rpt.s (entity, limit_amount)
    WITH lim AS (SELECT l.entity_key, SUM(l.limit_usd) AS limit_usd FROM core.fact_limit l GROUP BY l.entity_key)
    SELECT x.entity, ROUND(l.limit_usd / 1000000, 2) FROM core.x x LEFT JOIN lim l ON l.entity_key = x.entity_key"""
    w = sql_lineage.parse_writer(sql)
    items = br.rule_items(w, "limit_amount", None, br.Terms({"limit_usd": "Limit (USD)"}), None, [])
    assert "Limit (USD) looked up from fact_limit by entity" in br.rules_for(items, "core.fact_limit")
    sql2 = "INSERT INTO t (a) SELECT 1 FROM s JOIN p ON p.k = s.k"
    items = br.rule_items(sql_lineage.parse_writer("INSERT INTO t (a) SELECT s.a + p.ccf + p.rw FROM s JOIN p ON p.k = s.k"), "a", None,
                          br.Terms({"ccf": "CCF", "rw": "base risk weight"}), None, [])
    assert any(x.endswith("looked up from p by k") and "CCF and" in x or "and CCF looked" in x for x, _ in items)
