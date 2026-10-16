"""Idempotent: drops the C90 stored procedures + C90-only foreign tables/servers, and forgets their old query-log entries."""
import psycopg

H = "host=127.0.0.1 port=5432 user=lineage password=lineage dbname="
DROPS = {
    "trading_db": [],
    "staging": ["DROP PROCEDURE IF EXISTS etl.sp_load_stg_sensitivity()", "DROP FOREIGN TABLE IF EXISTS fdw_trd.trade_sensitivity"],
    "dwh": ["DROP PROCEDURE IF EXISTS etl.sp_load_sensitivity_usd()", "DROP FOREIGN TABLE IF EXISTS fdw_stg.stg_sensitivity"],
    "frtb_engine": ["DROP PROCEDURE IF EXISTS etl.sp_calc_sbm_charge()", "DROP SCHEMA IF EXISTS fdw_dwh CASCADE", "DROP SERVER IF EXISTS srv_dwh CASCADE"],
    "reporting_db": ["DROP PROCEDURE IF EXISTS etl.sp_load_c90_facts()", "DROP FOREIGN TABLE IF EXISTS fdw_frtb.calc_sbm_charge"],
}
# C90-only objects (ref_fx_rates is shared with C 07.00, so its history is kept)
OLD = r"stg_sensitivity|dw_sensitivity_usd|calc_sbm_charge|c90_facts|trade_sensitivity|ref_risk_weight|sp_load_sensitivity_usd|sp_load_c90_facts"

for db, stmts in DROPS.items():
    with psycopg.connect(H + db, autocommit=True) as c:
        for s in stmts:
            c.execute(s)
        # a foreign server/schema left empty and unused is dropped too
        c.execute("SELECT pg_stat_statements_reset(userid, dbid, queryid) FROM pg_stat_statements "
                  "WHERE dbid = (SELECT oid FROM pg_database WHERE datname = current_database()) AND query ~ %s", (OLD,))
        print(f"{db}: C90 procedures/foreign tables dropped, old query-log entries cleared")
