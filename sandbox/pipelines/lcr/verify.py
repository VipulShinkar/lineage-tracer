"""Checks lcr_mart as lineage_ro: values recomputed from raw, read-only, pg_stat_statements and csvlog evidence. run() -> bool."""
import csv
import io
import sys
from datetime import date
from decimal import ROUND_HALF_UP, Decimal as D

import psycopg

DSN = "host=127.0.0.1 port=5432 user=lineage_ro password=lineage_ro dbname=lcr_mart"
TABLES = ("core.fact_hqla", "core.fact_outflow", "core.fact_inflow")


def q2(x):
    return D(x).quantize(D("0.01"), rounding=ROUND_HALF_UP)


def recompute(c):
    fx = dict(c.execute("SELECT ccy, rate_to_usd FROM raw.fx_rate WHERE rate_date = '2026-06-30'").fetchall())
    p = dict(c.execute("SELECT item_code, factor FROM raw.lcr_param").fetchall())
    res = {}
    for e, ccy, cp, op, ins, bal in c.execute("SELECT entity_code, ccy, cpty_type, is_operational, insured, balance FROM raw.deposit_account"):
        cat = ("RET_STABLE" if ins == "Y" else "RET_LESS_STABLE") if cp == "RETAIL" else \
              "WHOLESALE_OPERATIONAL" if op == "Y" else "FIN_NON_OPERATIONAL" if cp == "FIN" else "CORP_NON_OPERATIONAL"
        r = res.setdefault(e, dict(h=D(0), o=D(0), i=D(0)))
        r["o"] += q2(bal * fx[ccy]) * p[cat]
    lvl = {"L1_SOVEREIGN": "1", "L1_CENTRAL_BANK": "1", "L2A_GOV": "2A", "L2A_COVERED": "2A", "L2B_RMBS": "2B", "L2B_CORP_BOND": "2B"}
    for e, ac, ccy, mv, enc in c.execute("SELECT entity_code, asset_class, ccy, market_value, is_encumbered FROM raw.security_holding"):
        if ac in lvl and enc != "Y":
            res[e]["h"] += q2(mv * fx[ccy]) * (1 - p["HQLA_L" + lvl[ac]])
    for e, ft, ccy, amt, mat in c.execute("SELECT entity_code, flow_type, ccy, amount, maturity_date FROM raw.cashflow"):
        if date(2026, 6, 30) < mat <= date(2026, 7, 30):
            res[e]["o" if ft.startswith("OUT") else "i"] += q2(amt * fx[ccy]) * p[ft]
    out = {}
    for e, r in res.items():
        net = r["o"] - min(r["i"], D("0.75") * r["o"])
        out[e] = (q2(r["h"] / 10**6), q2(r["o"] / 10**6), q2(r["i"] / 10**6), q2(net / 10**6), q2(r["h"] / net * 100))
    return out


def run() -> bool:
    ok = True

    def check(name, cond, extra=""):
        nonlocal ok
        ok &= bool(cond)
        print(("PASS " if cond else "FAIL ") + "[lcr] " + name, extra)

    c = psycopg.connect(DSN, autocommit=True)
    one = lambda s: c.execute(s).fetchone()[0]  # noqa: E731
    for t in ("raw.deposit_account", "raw.security_holding", "raw.cashflow", "stg.deposit_account", "rpt.lcr_summary") + TABLES:
        check(f"select {t}", one(f"SELECT count(*) FROM {t}") > 0)
    check("~2000 deposits, ~300 securities", one("SELECT count(*) FROM raw.deposit_account") == 2000 and one("SELECT count(*) FROM raw.security_holding") == 300)
    rows = {r[0]: r[1:] for r in c.execute("SELECT entity, hqla_usd, outflows_usd, inflows_usd, net_outflows_usd, lcr_pct FROM rpt.v_lcr_summary")}
    check("view has 3 entities + GROUP", set(rows) == {"ENT-UK", "ENT-IN", "ENT-SG", "GROUP"})
    exp = recompute(c)
    for e, v in exp.items():
        check(f"{e} reproduces from raw", tuple(rows[e]) == v, f"lcr_pct={rows[e][4]}")
        check(f"{e} LCR plausible 120-180", 120 <= rows[e][4] <= 180)
    g = rows["GROUP"]
    check("GROUP = sum of entities", g[0] == sum(r[0] for e, r in rows.items() if e != "GROUP") and g[4] == q2(g[0] / g[3] * 100))
    for stmt in ("DELETE FROM raw.deposit_account", "INSERT INTO rpt.lcr_summary (entity) VALUES ('x')", "CREATE TABLE rpt.x (a int)"):
        try:
            c.execute(stmt)
            check("no write: " + stmt[:30], False)
        except psycopg.errors.InsufficientPrivilege:
            check("no write: " + stmt[:30], True)
    check("no stored procedures in etl/schemas", one("SELECT count(*) FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname IN ('raw','stg','core','rpt')") == 0)
    check("every table/view has a description", one("SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname IN ('raw','stg','core','rpt') AND c.relkind IN ('r','v') AND obj_description(c.oid,'pg_class') IS NULL") == 0)
    # pg_stat_statements: INSERT...SELECT of every pipeline target
    pss = [r[0] for r in c.execute("SELECT s.query FROM pg_stat_statements s JOIN pg_database d ON d.oid=s.dbid WHERE d.datname='lcr_mart' AND s.query ILIKE 'INSERT INTO%'")]
    targets = ["stg.deposit_account", "stg.security_holding", "stg.cashflow", "stg.lcr_param", "core.fact_hqla", "core.fact_outflow", "core.fact_inflow", "rpt.lcr_summary"]
    check("pg_stat_statements has INSERT...SELECT for every target", all(any(f"INSERT INTO {t}" in q and "SELECT" in q for q in pss) for t in targets))
    # csvlog via pg_read_file as lineage_ro
    files = [r[0] for r in c.execute("SELECT name FROM pg_ls_logdir() WHERE name LIKE '%.csv' ORDER BY modification")]
    check("lineage_ro lists csvlog files", bool(files), str(files[-1:]))
    seen = set()
    for f in files:
        text = one(f"SELECT pg_read_file('log/{f}')")
        for row in csv.reader(io.StringIO(text)):
            if len(row) > 22 and row[22] == "lcr_shell" and row[13].startswith("statement: INSERT INTO"):
                seen.add(row[13].split()[3])
    check("csvlog has INSERT...SELECT per target with application_name=lcr_shell", set(targets) <= seen, str(sorted(seen)))
    return ok


if __name__ == "__main__":
    sys.exit(0 if run() else 1)
