"""Rebuilds the sandbox data estate from scratch (drops/recreates only the sandbox databases).

Usage: .venv\\Scripts\\python sandbox\\build.py
Steps: roles -> databases -> DDL -> seed systems of record -> run ETL once (after pg_stat_statements_reset)
       -> simulate the late collateral reload -> sanity-check the report values.
"""
import random
import sqlite3
import subprocess
import sys
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal as D
from pathlib import Path

import psycopg

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parent
HOST = "host=127.0.0.1 port=5432"
ADMIN = f"{HOST} user=lineage password=lineage"
ETL = f"{HOST} user=etl_owner password=etl_owner"
DBS = ["loans_db", "collateral_db", "trading_db", "staging", "dwh", "sa_engine", "frtb_engine", "reporting_db"]
SQLFILES = {"loans_db": "01_loans_db.sql", "collateral_db": "02_collateral_db.sql", "trading_db": "03_trading_db.sql",
            "staging": "04_staging.sql", "dwh": "05_dwh.sql", "sa_engine": "06_sa_engine.sql",
            "frtb_engine": "07_frtb_engine.sql", "reporting_db": "08_reporting_db.sql"}
rnd = random.Random(20260630)
Q = lambda x, n: D(x).quantize(D(1).scaleb(-n), rounding=ROUND_HALF_UP)  # noqa: E731

# ---------------------------------------------------------------- FX (sqlite system of record)
EUR30 = {"EUR": D("1"), "USD": D("0.9259"), "GBP": D("1.17"), "CHF": D("1.04"), "JPY": D("0.0058")}
CCYS = list(EUR30)
DATES = {date(2026, 6, 29): D("1.0021"), date(2026, 6, 30): D("1"), date(2026, 7, 1): D("0.9987")}


def fx_rows():
    rows = []
    for d, drift in DATES.items():
        eur = {c: (EUR30[c] if c == "EUR" else Q(EUR30[c] * drift, 8)) for c in CCYS}
        for c in CCYS:
            rows.append((c, d.isoformat(), float(eur[c]), float(Q(eur[c] / eur["USD"], 8))))
    return rows


def build_sqlite():
    p = ROOT / "data" / "market_data.db"
    p.parent.mkdir(exist_ok=True)
    p.unlink(missing_ok=True)
    c = sqlite3.connect(p)
    c.execute("CREATE TABLE fx_rates (ccy TEXT NOT NULL, rate_date TEXT NOT NULL, rate_to_eur REAL NOT NULL, rate_to_usd REAL NOT NULL, PRIMARY KEY (ccy, rate_date))")
    c.executemany("INSERT INTO fx_rates VALUES (?,?,?,?)", fx_rows())
    c.commit()
    c.close()


# ---------------------------------------------------------------- C 07.00 data
M = D(1_000_000)
T_ON = {"0010": D("1061.9"), "0040": D("1042.0"), "0200": D("1041.4"), "0220": D("962.0")}
T_OFF = {"0010": D("203.5"), "0040": D("201.8"), "0200": D("199.1"), "0220": D("156.9")}
CCF_COMMIT = D("0.939866")
facilities, collaterals = [], []
_n = [0]


def split(total_eur, n, lo=0.3, hi=3.0):
    w = [D(str(rnd.uniform(lo, hi))) for _ in range(n)]
    s = sum(w)
    return [total_eur * x / s for x in w]


def add_fac(ctype, product, ccy, drawn_eur, undrawn_eur, prov, rating, intra, rnd_dates=True):
    _n[0] += 1
    orig = date(2018, 1, 1) + timedelta(days=rnd.randint(0, 2000))
    facilities.append((f"FAC-{_n[0]:06d}", f"CP-{rnd.randint(10000, 99999)}", ctype, product, ccy,
                       Q(drawn_eur / EUR30[ccy], 2), Q(undrawn_eur / EUR30[ccy], 2), Q(prov, 6), rating, intra,
                       orig, orig + timedelta(days=rnd.randint(365, 3650))))
    return facilities[-1][0], drawn_eur


def ccy_pick(corp=True):
    return rnd.choices(CCYS, weights=[40, 25, 15, 10, 10] if corp else [70, 5, 25, 0, 0])[0]


def add_coll(fac_id, alloc_eur):
    ctype = rnd.choice(["CASH", "SECURITIES", "SECURITIES", "REAL_ESTATE", "GUARANTEE"])
    hc = {"CASH": D("0"), "SECURITIES": D("0.08"), "REAL_ESTATE": D("0.30"), "GUARANTEE": D("0.15")}[ctype]
    collaterals.append((f"COL-{len(collaterals) + 1:06d}", fac_id, ctype, "EUR", Q(alloc_eur / (1 - hc), 2), hc, date(2026, 6, 30)))


def gen_facilities():
    # --- Corporates on-balance: solved so the C 07.00 grid hits the POC values exactly
    vR, vR_off = D("0.015"), D("0.010")
    crm_R, crm_U = D("0.4") * M, D("0.2") * M
    D_R = (T_ON["0220"] * M + crm_R) / (1 - vR)
    D_U = T_ON["0010"] * M - D_R
    vU = Q(1 - (T_ON["0040"] * M - (T_ON["0220"] * M + crm_R)) / D_U, 6)
    on_r = [add_fac("CORP", "TERM", ccy_pick(), x, D(0), vR, "RATED", False) for x in split(D_R, 170)]
    on_u = [add_fac("CORP", "TERM", ccy_pick(), x, D(0), vU, "UNRATED", False) for x in split(D_U, 60)]
    # collateral against large corporate on-balance facilities
    for pool, tot, k in ((on_r, crm_R, 14), (on_u, crm_U, 8)):
        big = sorted(pool, key=lambda t: -t[1])[: k * 2]
        for (fid, _), amt in zip(rnd.sample(big, k), split(tot, k, 0.8, 1.2)):
            add_coll(fid, amt)
    # --- Corporates off-balance
    U_R = T_OFF["0220"] * M / (1 - vR_off)
    U_U = T_OFF["0010"] * M - U_R
    vU_off = Q(1 - (T_OFF["0040"] * M - T_OFF["0220"] * M) / U_U, 6)
    assert Q((T_OFF["0200"] - T_OFF["0220"]) / (T_OFF["0040"] - T_OFF["0220"]), 6) == CCF_COMMIT
    for x in split(U_R, 40):
        add_fac("CORP", "GUAR", ccy_pick(), D(0), x, vR_off, "RATED", False)
    for x in split(U_U, 35):
        add_fac("CORP", "COMMIT", ccy_pick(), D(0), x, vU_off, "UNRATED", False)
    # --- other exposure classes (random, not part of the demo grid)
    for _ in range(400):
        f = add_fac("RETAIL", rnd.choice(["MORT", "TERM"]), ccy_pick(False), D(rnd.randint(50, 800) * 1000), D(rnd.randint(0, 60) * 1000),
                    D(str(rnd.uniform(0.002, 0.03))), "UNRATED", False)
        if rnd.random() < 0.5:
            add_coll(f[0], f[1] * D("0.4"))
    for _ in range(120):
        f = add_fac("INST", rnd.choice(["TERM", "COMMIT"]), ccy_pick(), D(rnd.randint(5, 80) * M), D(rnd.randint(0, 20) * M),
                    D(str(rnd.uniform(0.0, 0.01))), "RATED", False)
        if rnd.random() < 0.3:
            add_coll(f[0], f[1] * D("0.1"))
    for _ in range(40):
        add_fac("SOV", "TERM", ccy_pick(), D(rnd.randint(20, 400) * M), D(0), D("0"), "RATED", False)
    # --- exactly 251 intragroup facilities (excluded from the warehouse), incl. corporates
    mix = ["CORP"] * 80 + ["INST"] * 120 + ["SOV"] * 21 + ["RETAIL"] * 30
    for ct in mix:
        f = add_fac(ct, rnd.choice(["TERM", "COMMIT"]), ccy_pick(), D(rnd.randint(2, 90) * M), D(rnd.randint(0, 30) * M),
                    D(str(rnd.uniform(0, 0.02))), rnd.choice(["RATED", "UNRATED"]), True)
        if rnd.random() < 0.3:
            add_coll(f[0], f[1] * D("0.1"))
    assert sum(1 for f in facilities if f[9]) == 251


# ---------------------------------------------------------------- C90 data
W = {("COM", "DELTA"): "0.30", ("CSR_NS", "DELTA"): "0.50", ("EQ", "CURVATURE"): "1.00", ("EQ", "DELTA"): "0.25",
     ("EQ", "VEGA"): "0.55", ("FX", "CURVATURE"): "1.00", ("FX", "DELTA"): "0.15", ("FX", "VEGA"): "0.55", ("GIRR", "DELTA"): "0.02"}
C90 = [("COM", "DELTA", 40, "3916.49"), ("CSR_NS", "DELTA", 30, "1176.02"), ("EQ", "CURVATURE", 4, "0.45"),
       ("EQ", "DELTA", 25, "34.01"), ("EQ", "VEGA", 6, "2.26"), ("FX", "CURVATURE", 8, "51.45"),
       ("FX", "DELTA", 80, "3867.06"), ("FX", "VEGA", 25, "257.27"), ("GIRR", "DELTA", 40, "321.95")]
FACTORS = {"COM": ["CMDTY-WTI", "CMDTY-BRENT", "CMDTY-GOLD", "CMDTY-NG"], "CSR_NS": ["CSR-CORP-IG", "CSR-CORP-HY", "CSR-FIN-IG"],
           "EQ": ["EQ-SPX", "EQ-SX5E", "EQ-UKX", "EQ-NKY"], "GIRR": ["USD-SOFR-2Y", "EUR-ESTR-5Y", "GBP-SONIA-10Y", "JPY-TONA-5Y"]}
DESKS = {"COM": "Commodities", "CSR_NS": "Credit", "EQ": "Equity Derivatives", "FX": "FX Options", "GIRR": "Rates"}


def gen_trades():
    usd30 = {c: Q(Q(EUR30[c], 8) / EUR30["USD"], 8) for c in CCYS}  # same maths as fx_rows for 30-Jun
    out, k = [], 0
    for rc, st, n, target in C90:
        S = D(target) / D(W[(rc, st)])                       # required sum of USD sensitivities
        parts = split(S * D("0.7"), n - 1, 0.2, 3.0)
        rows, usd_sum = [], D(0)
        for u in parts:
            ccy = rnd.choices(CCYS, weights=[25, 35, 15, 10, 15])[0]
            nat = Q(u / usd30[ccy], 4)
            usd_sum += Q(nat * usd30[ccy], 6)
            rows.append((ccy, nat))
        ccy = rnd.choice(["USD", "EUR"])
        nat = Q((S - usd_sum) / usd30[ccy], 4)
        assert nat > 0
        rows.append((ccy, nat))
        charge = Q(sum(Q(a * usd30[c], 6) * D(W[(rc, st)]) for c, a in rows), 2)
        assert charge == D(target), (rc, st, charge, target)
        for ccy, nat in rows:
            k += 1
            fac = (f"{ccy}USD" if ccy != "USD" else "USDUSD") if rc == "FX" else rnd.choice(FACTORS[rc])
            out.append((f"TRD-{k:06d}", f"BK-{rc}-{rnd.randint(1, 3)}", DESKS[rc], "GROUP-01", rc, st, fac, ccy, nat, date(2026, 6, 30)))
    return out


# ---------------------------------------------------------------- orchestration
def run_sql(dsn, text):
    with psycopg.connect(dsn, autocommit=True) as c:
        c.execute(text)


def copy(dsn, table, cols, rows):
    with psycopg.connect(dsn) as c, c.cursor() as cur:
        with cur.copy(f"COPY {table} ({cols}) FROM STDIN") as cp:
            for r in rows:
                cp.write_row(r)


def facts_union():
    m = {("0040", "0010"): "g.orig_on", ("0040", "0040"): "g.adj_on", ("0040", "0200"): "g.ev_on", ("0040", "0220"): "g.ev_on_rated",
         ("0050", "0010"): "g.orig_off", ("0050", "0040"): "g.adj_off", ("0050", "0200"): "g.ev_off", ("0050", "0220"): "g.ev_off_rated"}
    for c in ("0010", "0040", "0200", "0220"):
        m[("0010", c)] = f"{m[('0040', c)]} + {m[('0050', c)]}"
    sel = [f"    SELECT 'C 07.00' AS template, g.exposure_class AS sheet, '{r}' AS row_code, '{c}' AS col_code,\n"
           f"           ROUND(({m[(r, c)]}) / 1000000, 1) AS value, g.as_of_date\n    FROM g"
           for r in ("0010", "0040", "0050") for c in ("0010", "0040", "0200", "0220")]
    return "\n    UNION ALL\n".join(sel)


def call(db, *procs):
    with psycopg.connect(f"{ETL} dbname={db}", autocommit=True) as c:
        for p in procs:
            c.execute(f"CALL {p}()")


def main():
    print("== roles / databases")
    with psycopg.connect(f"{ADMIN} dbname=lineage", autocommit=True) as c:
        for role, extra in (("etl_owner", ""), ("lineage_ro", ""), ("loans_ro", "")):
            if not c.execute("SELECT 1 FROM pg_roles WHERE rolname=%s", (role,)).fetchone():
                c.execute(f"CREATE ROLE {role} LOGIN PASSWORD '{role}'")
            c.execute(f"ALTER ROLE {role} LOGIN PASSWORD '{role}'")
        c.execute("GRANT pg_read_all_data, pg_read_all_stats TO lineage_ro")
        for db in DBS:
            c.execute(f"DROP DATABASE IF EXISTS {db} WITH (FORCE)")
            c.execute(f"CREATE DATABASE {db} OWNER etl_owner")
            if db == "loans_db":  # own login; lineage_ro must not get in (pg_read_all_data does not bypass CONNECT)
                c.execute("REVOKE CONNECT ON DATABASE loans_db FROM PUBLIC, lineage_ro")
                c.execute("GRANT CONNECT ON DATABASE loans_db TO loans_ro")
            else:
                c.execute(f"GRANT CONNECT ON DATABASE {db} TO lineage_ro")
    for db in DBS:
        run_sql(f"{ADMIN} dbname={db}", "CREATE EXTENSION postgres_fdw; CREATE EXTENSION pg_stat_statements; "
                                        "GRANT USAGE ON FOREIGN DATA WRAPPER postgres_fdw TO etl_owner")

    print("== sqlite market_data + seed systems of record")
    build_sqlite()
    gen_facilities()
    trades = gen_trades()
    for db in DBS[:3]:
        run_sql(f"{ETL} dbname={db}", (ROOT / "sql" / SQLFILES[db]).read_text())
    run_sql(f"{ETL} dbname=loans_db", "GRANT USAGE ON SCHEMA los TO loans_ro; GRANT SELECT ON ALL TABLES IN SCHEMA los TO loans_ro")
    copy(f"{ETL} dbname=loans_db", "los.facility",
         "facility_id, counterparty_id, counterparty_type, product_code, currency, drawn_balance, undrawn_limit, provision_pct, rating_status, intragroup_flag, origination_date, maturity_date",
         facilities)
    copy(f"{ETL} dbname=collateral_db", "col.collateral",
         "collateral_id, facility_id, collateral_type, currency, market_value, haircut_pct, valuation_date", collaterals)
    copy(f"{ETL} dbname=trading_db", "trd.trade_sensitivity",
         "trade_id, book, desk, consolidation_group, risk_class, sensitivity_type, risk_factor, currency, sensitivity_amount, as_of_date", trades)

    print("== downstream DDL (foreign servers, tables, procedures)")
    for db in DBS[3:]:
        sql = (ROOT / "sql" / SQLFILES[db]).read_text().replace("-- @@FACTS@@", facts_union())
        run_sql(f"{ETL} dbname={db}", sql)

    print("== business glossary (catalog comments)")
    for part in (ROOT / "sql" / "09_glossary.sql").read_text().split("-- @@DB ")[1:]:
        db, _, body = part.partition(chr(10))
        run_sql(f"{ETL} dbname={db.strip()}", body)

    print("== ETL run (logged by pg_stat_statements)")
    run_sql(f"{ADMIN} dbname=lineage", "CREATE EXTENSION IF NOT EXISTS pg_stat_statements")
    run_sql(f"{ADMIN} dbname=staging", "SELECT pg_stat_statements_reset()")
    py = sys.executable
    call("staging", "etl.sp_load_stg_facilities", "etl.sp_load_stg_collateral", "etl.sp_load_stg_sensitivity")
    subprocess.run([py, str(ROOT / "etl" / "load_fx.py")], check=True)
    call("dwh", "etl.sp_load_exposure", "etl.sp_load_collateral_alloc", "etl.sp_load_mart_sa_exposure", "etl.sp_load_sensitivity_usd")
    call("sa_engine", "etl.sp_calc_sa_exposure")
    call("frtb_engine", "etl.sp_calc_sbm_charge")
    call("reporting_db", "etl.sp_load_c0700_facts", "etl.sp_load_c90_facts")

    print("== late collateral reload (makes hops stg_collateral->dw_collateral_alloc and dw_collateral_alloc->calc code-derived)")
    run_sql(f"{ADMIN} dbname=collateral_db", "UPDATE col.collateral SET market_value = ROUND(market_value * 1.5, 2)")  # revaluation at source
    call("staging", "etl.sp_load_stg_collateral")                       # reload: stg now agrees with source, dw does not
    run_sql(f"{ADMIN} dbname=dwh", "UPDATE public.dw_collateral_alloc SET allocated_value_eur = ROUND(allocated_value_eur * 0.5, 2)")
    run_sql(f"{ADMIN} dbname=staging",                                   # forget the administrator's manual statements
            "SELECT pg_stat_statements_reset((SELECT oid FROM pg_roles WHERE rolname='lineage'), 0, 0)")

    print("== check")
    with psycopg.connect(f"{ETL} dbname=reporting_db") as c:
        print(c.execute("SELECT * FROM rpt.v_corep_c90").fetchall())
        print(c.execute("SELECT row_code, col_code, value FROM rpt.c0700_facts WHERE sheet='Corporates' ORDER BY 1,2").fetchall())


if __name__ == "__main__":
    main()
