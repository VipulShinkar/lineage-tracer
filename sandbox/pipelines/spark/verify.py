"""Checks the Spark EFR pipeline. run() -> bool; also runnable standalone (.venv\Scripts\python)."""
import json
import sys
from pathlib import Path

import psycopg

ROOT = Path(__file__).resolve().parents[3]
EVENTS = ROOT / "sandbox" / "openlineage" / "spark" / "efr_events.ndjson"
LAKE = "host=127.0.0.1 port=5433 user=lineage_ro password=lineage_ro dbname=fin_lake"
TARGETS = ("stg.entity stg.counterparty stg.rating stg.loan stg.collateral stg.credit_limit stg.fx_rate core.dim_date core.dim_entity "
           "core.dim_counterparty core.dim_rating core.dim_product core.fact_exposure core.fact_limit rpt.efr_credit_risk_summary").split()


def run() -> bool:
    ok = True

    def check(name, cond, extra=""):
        nonlocal ok
        ok &= bool(cond)
        print(("PASS " if cond else "FAIL ") + "[spark] " + name, extra)

    c = psycopg.connect(LAKE, autocommit=True)
    one = lambda q: c.execute(q).fetchone()[0]  # noqa: E731
    uk = one("SELECT exposure_ead FROM rpt.v_efr_credit_risk_summary WHERE entity='ENT-UK' AND portfolio='Corporates'")
    check("ENT-UK Corporates exposure_ead = 1277.32", str(uk) == "1277.32", str(uk))
    check("rpt rows = 12 + GROUP", one("SELECT count(*) FROM rpt.v_efr_credit_risk_summary") == 13)
    check("group total EAD 5822.03", str(one("SELECT exposure_ead FROM rpt.v_efr_credit_risk_summary WHERE entity='GROUP'")) == "5822.03")
    check("no etl procedures in fin_lake", one("SELECT count(*) FROM pg_proc WHERE pronamespace='etl'::regnamespace") == 0)
    check("glossary comments kept", "Exposure at Default" in (one("SELECT col_description('core.fact_exposure'::regclass, (SELECT attnum FROM pg_attribute WHERE attrelid='core.fact_exposure'::regclass AND attname='ead_usd'))") or ""))
    check("raw FX restated, stg not (hop 2 unreconciled)",
          one("SELECT count(*) FROM raw.fx_rate r JOIN stg.fx_rate s USING (ccy) WHERE r.rate_date='2026-06-30' AND s.rate_date=DATE '2026-06-30' AND r.rate_to_usd::numeric <> s.rate_to_usd") == 2)
    evs = [json.loads(x) for x in EVENTS.read_text().splitlines() if x.strip()]
    done = [e for e in evs if e["eventType"] == "COMPLETE" and e.get("outputs")]
    names = sorted(e["outputs"][0]["name"] for e in done)
    check("one COMPLETE run per target table", names == sorted("fin_lake." + t for t in TARGETS) and len({e["run"]["runId"] for e in done}) == 15, str(len(done)))
    check("columnLineage on every run (except none)", all("columnLineage" in e["outputs"][0]["facets"] for e in done if e["inputs"]))
    ev = next(e for e in done if e["outputs"][0]["name"] == "fin_lake.core.fact_exposure")
    ins = {(i["name"], i["field"]) for i in ev["outputs"][0]["facets"]["columnLineage"]["fields"]["ead_usd"]["inputFields"]}
    need = {("fin_lake.stg.loan", "drawn_amt"), ("fin_lake.stg.loan", "undrawn_amt"), ("fin_lake.stg.fx_rate", "rate_to_usd"), ("fin_lake.core.dim_product", "ccf")}
    check("ead_usd column lineage inputs", need <= ins)
    check("dataset namespace", ev["outputs"][0]["namespace"] == "postgres://127.0.0.1:5433")
    sys.path.insert(0, str(ROOT / "src"))
    from lineage_store import db
    with db.connect() as g:
        src = db.cypher(g, "MATCH (a:Field)-[e:DERIVES]->(b:Field {uid:'field:fin_lake.core.fact_exposure.ead_usd'}) RETURN a.uid", {})
    check("ingested into lineage DB (DERIVES -> ead_usd)", {"field:fin_lake.stg.loan.drawn_amt", "field:fin_lake.stg.fx_rate.rate_to_usd", "field:fin_lake.core.dim_product.ccf"} <= set(src))
    return ok


if __name__ == "__main__":
    sys.exit(0 if run() else 1)
