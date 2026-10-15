"""Rebuilds the EFR financial lake (cluster finlake, port 5433, database fin_lake) from scratch.
Usage: .venv\\Scripts\\python sandbox\\finlake\\build.py"""
import random
from datetime import datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal as D
from pathlib import Path

import psycopg

ROOT = Path(__file__).resolve().parent
HOST = "host=127.0.0.1 port=5433"
ADMIN = f"{HOST} user=lineage password=lineage"
ETL = f"{HOST} user=etl_owner password=etl_owner dbname=fin_lake"
rnd = random.Random(20260630)
Q = lambda x, n=2: D(x).quantize(D(1).scaleb(-n), rounding=ROUND_HALF_UP)  # noqa: E731
M = D(1_000_000)
T_NEW = datetime(2026, 7, 1, 6, 0, tzinfo=timezone.utc)
T_OLD = T_NEW - timedelta(days=30)

ENT = [("ENT-UK", "[LEGAL ENTITY] UK", "GB", "GBP"), ("ENT-IN", "[LEGAL ENTITY] India", "IN", "INR"), ("ENT-SG", "[LEGAL ENTITY] Singapore", "SG", "SGD")]
USD30 = {"USD": D("1"), "GBP": D("1.27"), "INR": D("0.012"), "SGD": D("0.74"), "EUR": D("1.08")}
DRIFT = {"2026-06-29": D("1.002"), "2026-06-30": D("1"), "2026-07-01": D("0.998")}
SECT = ["SOV"] * 25 + ["BNK"] * 45 + ["CORP"] * 220 + ["RET"] * 110
PORT = {"SOV": "Sovereigns", "BNK": "Banks", "CORP": "Corporates", "RET": "Retail"}
GRADES = {"SOV": ["AAA", "AA", "A", "BBB"], "BNK": ["AA", "A", "BBB", "BB"], "CORP": ["A", "BBB", "BBB", "BB", "B", "CCC"], "RET": ["BBB", "BB", "B"]}
CCF = {"RCF": D("0.5"), "TRADE": D("0.2")}
SCALE = {"SOV": 12, "BNK": 8, "CORP": 3, "RET": 0.15}


def run(dsn, sql):
    with psycopg.connect(dsn, autocommit=True) as c:
        c.execute(sql)


def copy(table, rows):
    with psycopg.connect(ETL) as c, c.cursor() as cur:
        with cur.copy(f"COPY {table} FROM STDIN") as cp:
            for r in rows:
                cp.write_row(r)


def gen():
    B = "B20260630"
    t = {k: [] for k in ("entity", "counterparty", "rating", "loan_contract", "collateral", "credit_limit", "fx_rate", "gl_balance")}
    for code, name, ctry, _ in ENT:
        t["entity"].append((code, name, ctry, "GROUP-01", B, T_NEW))
    cps = []
    for i in range(400):
        sec = SECT[i]
        cid = f"CP{i + 1:05d}"
        intra = "Y" if (sec in ("BNK", "CORP") and rnd.random() < 0.17) else "N"
        cps.append((cid, sec, intra))
        t["counterparty"].append((cid, f"Counterparty {i + 1} {sec}", rnd.choice(["GB", "IN", "SG", "US", "DE", "FR", "JP"]), sec, intra, B, T_NEW))
        if i < 10:  # stale duplicate delivery, superseded by the row above
            t["counterparty"].append((cid, f"Old name {i + 1}", "XX", sec, "N", "B20260531", T_OLD))
        if rnd.random() < 0.85:
            g = rnd.choice(GRADES[sec])
            t["rating"].append((cid, g.lower() if rnd.random() < 0.1 else g, "2025-11-15", "AGENCY-A", B, T_NEW))
            if rnd.random() < 0.4:  # older, superseded rating
                t["rating"].append((cid, rnd.choice(GRADES[sec]), "2024-10-01", "AGENCY-A", "B20250101", T_OLD))
    for ccy, base in USD30.items():
        for d, dr in DRIFT.items():
            t["fx_rate"].append((ccy, d, str(Q(base * dr, 6)), B, T_NEW))
    est = {}
    prin = {}
    for k in range(1500):
        ent = rnd.choices(ENT, weights=[45, 30, 25])[0]
        cid, sec, intra = rnd.choice(cps)
        prod = rnd.choices(["TERM", "RCF", "GUAR", "TRADE"], weights=[55, 25, 10, 10])[0]
        ccy = ent[3] if rnd.random() < 0.6 else "USD"
        usd = D(str(rnd.lognormvariate(0, 0.9) * SCALE[sec])) * M
        if prod == "GUAR":
            pr, un = D(0), usd
        elif prod == "TERM":
            pr, un = usd, D(0)
        else:
            f = D(str(rnd.uniform(0.3, 0.8)))
            pr, un = usd * f, usd * (1 - f)
        r = USD30[ccy]
        pr_n, un_n = Q(pr / r), Q(un / r)
        acc, imp = Q(pr_n * D("0.004")), Q(pr_n * D(str(rnd.choice([0, 0, 0.005, 0.02]))))
        st = datetime(2020, 1, 1) + timedelta(days=rnd.randint(0, 2000))
        t["loan_contract"].append((f"LN{k + 1:06d}", ent[0].lower() if rnd.random() < 0.05 else ent[0], cid,
                                   prod.lower() if rnd.random() < 0.05 else prod, ccy, str(pr_n), str(un_n), str(acc), str(imp),
                                   st.date().isoformat(), (st + timedelta(days=rnd.randint(365, 3650))).date().isoformat(), B, T_NEW))
        prin[(ent[0], ccy)] = prin.get((ent[0], ccy), D(0)) + pr_n
        if intra == "N":
            ead = ((pr_n + acc - imp) + CCF.get(prod, D(1)) * un_n) * r
            est[(ent[0], PORT[sec])] = est.get((ent[0], PORT[sec]), D(0)) + ead
        if rnd.random() < 0.4:
            for j in range(rnd.randint(1, 2)):
                t["collateral"].append((f"CO{len(t['collateral']) + 1:06d}", f"LN{k + 1:06d}", rnd.choice(["CASH", "SECURITIES", "REAL_ESTATE"]), ccy,
                                        str(Q(pr_n * D(str(rnd.uniform(0.1, 0.5))))), B, T_NEW))
    for (e, p), v in est.items():  # limits sized so utilisation lands at 55-95 percent
        sec = {v_: k_ for k_, v_ in PORT.items()}[p]
        ent = next(x for x in ENT if x[0] == e)
        lim = v / D(str(rnd.uniform(0.55, 0.95))) / USD30[ent[3]]
        t["credit_limit"].append((e, sec, str(Q(lim / 1000, 2) * 1000), ent[3], B, T_NEW))
    for (e, ccy), v in prin.items():
        t["gl_balance"].append((e, "1100-LOANS", ccy, str(v), "2026-06-30", B, T_NEW))
        t["gl_balance"].append((e, "2000-DEPOSITS", ccy, str(Q(v * D("1.4"))), "2026-06-30", B, T_NEW))
    return t


def main():
    print("== roles / database")
    with psycopg.connect(f"{ADMIN} dbname=postgres", autocommit=True) as c:
        for role in ("etl_owner", "lineage_ro"):
            if not c.execute("SELECT 1 FROM pg_roles WHERE rolname=%s", (role,)).fetchone():
                c.execute(f"CREATE ROLE {role} LOGIN PASSWORD '{role}'")
            c.execute(f"ALTER ROLE {role} LOGIN PASSWORD '{role}'")
        c.execute("GRANT pg_read_all_data, pg_read_all_stats TO lineage_ro")
        c.execute("DROP DATABASE IF EXISTS fin_lake WITH (FORCE)")
        c.execute("CREATE DATABASE fin_lake OWNER etl_owner")
    run(f"{ADMIN} dbname=fin_lake", "CREATE EXTENSION pg_stat_statements")
    print("== model + seed raw")
    run(ETL, (ROOT / "sql" / "01_model.sql").read_text())
    run(ETL, (ROOT / "sql" / "02_glossary.sql").read_text())
    for name, rows in gen().items():
        copy(f"raw.{name}", rows)
        print(f"   raw.{name}: {len(rows)}")
    print("== ETL run (logged by pg_stat_statements)")
    run(f"{ADMIN} dbname=fin_lake", "SELECT pg_stat_statements_reset()")
    procs = [f"stg_{n}" for n in ("entity", "counterparty", "rating", "loan", "collateral", "credit_limit", "fx_rate")] + \
            [f"core_{n}" for n in ("dim_date", "dim_entity", "dim_counterparty", "dim_rating", "dim_product", "fact_exposure", "fact_limit")] + ["rpt_efr"]
    with psycopg.connect(ETL, autocommit=True) as c:
        for p in procs:
            c.execute(f"CALL etl.sp_load_{p}()")
    print("== late FX restatement in raw (stg.fx_rate is not reloaded -> hop raw.fx_rate -> stg.fx_rate becomes code-derived)")
    run(f"{ADMIN} dbname=fin_lake", "UPDATE raw.fx_rate SET rate_to_usd = ROUND(rate_to_usd::numeric * 1.015, 6)::text "
                                    "WHERE ccy IN ('GBP', 'INR') AND rate_date = '2026-06-30'")
    run(f"{ADMIN} dbname=fin_lake", "SELECT pg_stat_statements_reset((SELECT oid FROM pg_roles WHERE rolname='lineage'), 0, 0)")
    print("== check")
    with psycopg.connect(f"{HOST} user=lineage_ro password=lineage_ro dbname=fin_lake") as c:
        for r in c.execute("SELECT * FROM rpt.v_efr_credit_risk_summary").fetchall():
            print("  ", r)


if __name__ == "__main__":
    main()
