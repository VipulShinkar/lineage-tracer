"""Checks the estate as the read-only scanning user and recomputes every hop to show which reconcile."""
import sys

import psycopg

RO = "host=127.0.0.1 port=5432 user={u} password={u} dbname={d}"
DBS = ["loans_db", "collateral_db", "trading_db", "staging", "dwh", "sa_engine", "frtb_engine", "reporting_db"]
ok = True


def check(name, cond, extra=""):
    global ok
    ok &= bool(cond)
    print(("PASS " if cond else "FAIL ") + name, extra)


def q(db, sql):
    if db == "loans_db":
        return qa(db, sql, "loans_ro")
    return qa(db, sql, "lineage_ro")


def USER(db):
    return "loans_ro" if db == "loans_db" else "lineage_ro"


def qa(db, sql, user):
    with psycopg.connect(RO.format(u=USER(db), d=db), autocommit=True) as c:
        return c.execute(sql).fetchall()


try:
    psycopg.connect(RO.format(u="lineage_ro", d="loans_db"))
    check("lineage_ro cannot connect to loans_db", False)
except psycopg.OperationalError:
    check("lineage_ro cannot connect to loans_db", True)
# read-only user: SELECT everywhere, catalogs visible, no writes
tables = {"loans_db": "los.facility", "collateral_db": "col.collateral", "trading_db": "trd.trade_sensitivity",
          "staging": "public.stg_facilities", "dwh": "public.dw_exposure", "sa_engine": "public.calc_sa_exposure",
          "frtb_engine": "public.calc_sbm_charge", "reporting_db": "rpt.c0700_facts"}
for db, t in tables.items():
    check(f"select {db}.{t}", q(db, f"SELECT count(*) FROM {t}")[0][0] > 0)
    try:
        with psycopg.connect(RO.format(u=USER(db), d=db), autocommit=True) as c:
            c.execute(f"DELETE FROM {t}")
        check(f"no write {db}", False)
    except psycopg.errors.InsufficientPrivilege:
        check(f"no write {db}", True)
n = q("reporting_db", "SELECT count(*) FROM pg_stat_statements WHERE query ILIKE 'INSERT INTO%'")[0][0]
check("pg_stat_statements INSERT texts", n >= 10, f"({n})")
check("pg_proc.prosrc", q("dwh", "SELECT count(*) FROM pg_proc WHERE prosrc ILIKE '%INSERT INTO%'")[0][0] >= 3)
check("pg_views", q("reporting_db", "SELECT count(*) FROM pg_views WHERE viewname='v_corep_c90'")[0][0] == 1)
check("pg_foreign_server/table", q("dwh", "SELECT count(*) FROM pg_foreign_server s JOIN pg_foreign_table t ON t.ftserver=s.oid")[0][0] >= 3)  # C 07.00 only; C90 foreign tables dropped by Informatica setup
check("foreign table readable as lineage_ro", q("dwh", "SELECT count(*) FROM fdw_stg.stg_facilities")[0][0] > 0)

# report values
c90 = q("reporting_db", "SELECT consolidation_group,risk_class,sensitivity_type,reported_value_usd::text FROM rpt.v_corep_c90")
exp = ["3916.49", "1176.02", "0.45", "34.01", "2.26", "51.45", "3867.06", "257.27", "321.95", "9626.96"]
check("C90 view rows", [r[3] for r in c90] == exp)
g = {(r, c): v for r, c, v in q("reporting_db", "SELECT row_code,col_code,value::text FROM rpt.c0700_facts WHERE sheet='Corporates'")}
want = {"0010": ["1265.4", "1243.8", "1240.5", "1118.9"], "0040": ["1061.9", "1042.0", "1041.4", "962.0"], "0050": ["203.5", "201.8", "199.1", "156.9"]}
check("C 07.00 grid", all(g[(r, c)] == v for r, vs in want.items() for c, v in zip(["0010", "0040", "0200", "0220"], vs)))

for db_, rel_, col_ in (("loans_db", "los.facility", "drawn_balance"), ("reporting_db", "rpt.v_corep_c90", "reported_value_usd"), ("sa_engine", "public.calc_sa_exposure", "ev_on_eur")):
    d_ = q(db_, f"SELECT obj_description('{rel_}'::regclass, 'pg_class'), col_description('{rel_}'::regclass, (SELECT attnum FROM pg_attribute WHERE attrelid='{rel_}'::regclass AND attname='{col_}'))")[0]
    check(f"glossary {db_}.{rel_}.{col_}", all(d_), "")
# hop reconciliation (aggregate recompute from CURRENT upstream data)
def total(db, sql):
    return q(db, sql)[0][0]

hops = {
 "1 los.facility -> stg_facilities": (total("loans_db", "SELECT sum(drawn_balance+undrawn_limit) FROM los.facility"), total("staging", "SELECT sum(drawn_balance+undrawn_limit) FROM stg_facilities")),
 "2 col.collateral -> stg_collateral": (total("collateral_db", "SELECT sum(market_value) FROM col.collateral"), total("staging", "SELECT sum(market_value) FROM stg_collateral")),
 "3/4 stg_facilities+fx -> dw_exposure": (total("dwh", "SELECT sum(round(f.drawn_balance*fx.rate_to_eur,2)) FROM fdw_stg.stg_facilities f JOIN fdw_stg.ref_fx_rates fx ON fx.ccy=f.currency AND fx.rate_date='2026-06-30' WHERE NOT f.intragroup_flag"), total("dwh", "SELECT sum(drawn_eur) FROM dw_exposure")),
 "5 stg_collateral -> dw_collateral_alloc (expected MISMATCH)": (total("dwh", "SELECT sum(round(market_value*(1-haircut_pct),2)) FROM fdw_stg.stg_collateral"), total("dwh", "SELECT sum(allocated_value_eur) FROM dw_collateral_alloc")),
 "6 dw_exposure -> mart_sa_exposure": (total("dwh", "SELECT sum(drawn_eur) FROM dw_exposure"), total("dwh", "SELECT sum(on_bal_eur) FROM mart_sa_exposure")),
 "7 dw_collateral_alloc -> calc_sa_exposure (expected MISMATCH)": (total("sa_engine", "SELECT sum(LEAST(coalesce(a.c,0), round(m.on_bal_eur*(1-m.provision_pct),2))) FROM fdw_dwh.mart_sa_exposure m LEFT JOIN (SELECT facility_id, sum(allocated_value_eur) c FROM fdw_dwh.dw_collateral_alloc GROUP BY 1) a USING (facility_id)"), total("sa_engine", "SELECT sum(crm_eur) FROM calc_sa_exposure")),
 "8 mart_sa_exposure -> calc_sa_exposure (orig on+off)": (total("sa_engine", "SELECT sum(on_bal_eur+off_bal_eur) FROM fdw_dwh.mart_sa_exposure"), total("sa_engine", "SELECT sum(orig_on_eur+orig_off_eur) FROM calc_sa_exposure")),
 "9 calc_sa_exposure -> c0700 r0010 c0010": (total("reporting_db", "SELECT round(sum(orig_on_eur+orig_off_eur)/1e6,1) FROM fdw_sa.calc_sa_exposure WHERE exposure_class='Corporates'"), total("reporting_db", "SELECT value FROM rpt.c0700_facts WHERE sheet='Corporates' AND row_code='0010' AND col_code='0010'")),
 "C90 trade_sensitivity -> stg": (total("trading_db", "SELECT sum(sensitivity_amount) FROM trd.trade_sensitivity"), total("staging", "SELECT sum(sensitivity_amount) FROM stg_sensitivity")),
}
for k, (a, b) in hops.items():
    match = a == b
    check("hop " + k, match != ("MISMATCH" in k), f"recomputed={a} stored={b}")
sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent / "finlake"))
import verify as _lake  # noqa: E402  (sandbox/finlake/verify.py)
ok &= _lake.run()
import subprocess  # noqa: E402
for p_ in ("informatica", "spark", "lcr"):
    rc = subprocess.run([sys.executable, str(__import__("pathlib").Path(__file__).parent / "pipelines" / p_ / "verify.py")]).returncode
    check(f"pipelines/{p_}/verify.py", rc == 0)
print("ALL OK" if ok else "SOME FAILED")
raise SystemExit(0 if ok else 1)
