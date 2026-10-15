"""Checks the EFR lake as lineage_ro on port 5433 and recomputes each hop. run() -> bool; also runnable standalone."""
import sys

import psycopg

DSN = "host=127.0.0.1 port=5433 user=lineage_ro password=lineage_ro dbname=fin_lake"


def run() -> bool:
    ok = True

    def check(name, cond, extra=""):
        nonlocal ok
        ok &= bool(cond)
        print(("PASS " if cond else "FAIL ") + "[finlake] " + name, extra)

    c = psycopg.connect(DSN, autocommit=True)

    def one(sql):
        return c.execute(sql).fetchone()[0]

    for t in ("raw.loan_contract", "raw.fx_rate", "stg.loan", "stg.fx_rate", "core.fact_exposure", "core.fact_limit", "rpt.efr_credit_risk_summary"):
        check(f"select {t}", one(f"SELECT count(*) FROM {t}") > 0)
    for stmt in ("DELETE FROM raw.loan_contract", "INSERT INTO rpt.efr_credit_risk_summary (entity) VALUES ('x')", "CREATE TABLE rpt.x (a int)"):
        try:
            c.execute(stmt)
            check("no write: " + stmt[:30], False)
        except psycopg.errors.InsufficientPrivilege:
            check("no write: " + stmt[:30], True)
    check("pg_stat_statements INSERT texts", one("SELECT count(*) FROM pg_stat_statements WHERE query ILIKE 'INSERT INTO%'") >= 15)
    check("pg_proc.prosrc (etl)", one("SELECT count(*) FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname='etl' AND p.prosrc ILIKE '%INSERT INTO%'") >= 15)
    check("pg_views", one("SELECT count(*) FROM pg_views WHERE viewname='v_efr_credit_risk_summary'") == 1)
    check("every table/view in raw/stg/core/rpt has a description", one("SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname IN ('raw','stg','core','rpt') AND c.relkind IN ('r','v') AND obj_description(c.oid,'pg_class') IS NULL") == 0)
    check("glossary: ead_usd column comment", "Exposure at Default" in (one("SELECT col_description('core.fact_exposure'::regclass, (SELECT attnum FROM pg_attribute WHERE attrelid='core.fact_exposure'::regclass AND attname='ead_usd'))") or ""))
    check("glossary: procedure comment", one("SELECT obj_description('etl.sp_load_core_fact_exposure()'::regprocedure, 'pg_proc')") is not None)
    check("memory: shared_buffers=128MB", one("SHOW shared_buffers") == "128MB")
    # report values
    rows = c.execute("SELECT entity, portfolio, exposure_ead, rwa, expected_loss, limit_amount, utilisation_pct FROM rpt.v_efr_credit_risk_summary").fetchall()
    check("view has 12 + 1 rows", len(rows) == 13 and rows[-1][0] == "GROUP")
    tot = rows[-1]
    check("total row = sum of entity rows (exposure_ead)", abs(sum(r[2] for r in rows[:-1]) - tot[2]) < 0.06)
    uk = [r for r in rows if r[0] == "ENT-UK" and r[1] == "Corporates"][0]
    check("demo data point ENT-UK Corporates exposure_ead", str(uk[2]) == "1277.32", str(uk[2]))
    check("utilisation = ead / limit", all(abs(r[6] - r[2] / r[5] * 100) < 0.01 for r in rows))
    check("gl completeness view reconciles", one("SELECT count(*) FROM rpt.v_gl_completeness WHERE difference <> 0") == 0)
    # hop reconciliation from CURRENT upstream data
    hops = {
        "raw.loan_contract -> stg.loan": (one("SELECT sum(principal::numeric + accrued_int::numeric - impairment::numeric) FROM raw.loan_contract"), one("SELECT sum(drawn_amt) FROM stg.loan")),
        "raw.counterparty -> stg.counterparty (distinct ids)": (one("SELECT count(DISTINCT cpty_id) FROM raw.counterparty"), one("SELECT count(*) FROM stg.counterparty")),
        "raw.rating -> stg.rating": (one("SELECT count(DISTINCT cpty_id) FROM raw.rating"), one("SELECT count(*) FROM stg.rating")),
        "raw.collateral -> stg.collateral": (one("SELECT sum(market_value::numeric) FROM raw.collateral"), one("SELECT sum(market_value) FROM stg.collateral")),
        "raw.fx_rate -> stg.fx_rate (expected MISMATCH)": (one("SELECT sum(rate_to_usd::numeric) FROM raw.fx_rate"), one("SELECT sum(rate_to_usd) FROM stg.fx_rate")),
        "stg.* -> core.fact_exposure (ead)": (one("""SELECT sum(ROUND(ROUND(l.drawn_amt*fx.rate_to_usd,2) + p.ccf*ROUND(l.undrawn_amt*fx.rate_to_usd,2), 2))
            FROM stg.loan l JOIN stg.fx_rate fx ON fx.ccy=l.ccy AND fx.rate_date='2026-06-30'
            JOIN core.dim_product p ON p.product_code=l.product_code JOIN stg.counterparty c ON c.cpty_id=l.cpty_id WHERE NOT c.is_intragroup"""),
                                              one("SELECT sum(ead_usd) FROM core.fact_exposure")),
        "core.fact_exposure -> rpt (ENT-UK Corporates ead)": (one("""SELECT ROUND(sum(f.ead_usd)/1000000, 2) FROM core.fact_exposure f
            JOIN core.dim_entity e USING (entity_key) JOIN core.dim_counterparty c USING (cpty_key) WHERE e.entity_code='ENT-UK' AND c.portfolio='Corporates'"""),
                                                              one("SELECT exposure_ead FROM rpt.efr_credit_risk_summary WHERE entity='ENT-UK' AND portfolio='Corporates'")),
        "core.fact_limit -> rpt (limit total)": (one("SELECT ROUND(sum(limit_usd)/1000000, 2) FROM core.fact_limit"), one("SELECT sum(limit_amount) FROM rpt.efr_credit_risk_summary")),
    }
    for k, (a, b) in hops.items():
        check("hop " + k, (a == b) != ("MISMATCH" in k), f"recomputed={a} stored={b}")
    c.close()
    return ok


if __name__ == "__main__":
    good = run()
    print("ALL OK" if good else "SOME FAILED")
    sys.exit(0 if good else 1)
