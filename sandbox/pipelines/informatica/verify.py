"""Checks the Informatica-style C90 pipeline. Run: .venv\Scripts\python sandbox\pipelines\informatica\verify.py"""
import re
import sys
from pathlib import Path

import psycopg

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[2] / "src"))
from lineage_parser.xml import parse_xml_lineage  # noqa: E402

RO = "host=127.0.0.1 port=5432 user=lineage_ro password=lineage_ro dbname={}"
ok = True


def check(name, cond, extra=""):
    global ok
    ok &= bool(cond)
    print(("PASS " if cond else "FAIL ") + name, extra)


def q(db, sql):
    with psycopg.connect(RO.format(db), autocommit=True) as c:
        return c.execute(sql).fetchall()


# 1. reported values reproduce exactly
exp = ["3916.49", "1176.02", "0.45", "34.01", "2.26", "51.45", "3867.06", "257.27", "321.95", "9626.96"]
got = [r[0] for r in q("reporting_db", "SELECT reported_value_usd::text FROM rpt.v_corep_c90")]
check("C90 view values (COM DELTA 3916.49 ... FX DELTA 3867.06 ... ALL 9626.96)", got == exp, got)
check("FX/DELTA = 3867.06", q("reporting_db", "SELECT reported_value_usd::text FROM rpt.c90_facts WHERE risk_class='FX' AND sensitivity_type='DELTA'")[0][0] == "3867.06")
check("view still exists", q("reporting_db", "SELECT count(*) FROM pg_views WHERE viewname='v_corep_c90'")[0][0] == 1)

# 2. no C90 procedures / C90-only foreign tables remain
procs = {"staging": "sp_load_stg_sensitivity", "dwh": "sp_load_sensitivity_usd", "frtb_engine": "sp_calc_sbm_charge", "reporting_db": "sp_load_c90_facts"}
for db, p in procs.items():
    check(f"{db}: procedure {p} gone", q(db, f"SELECT count(*) FROM pg_proc WHERE proname='{p}'")[0][0] == 0)
ft = {"staging": "trade_sensitivity", "dwh": "stg_sensitivity", "frtb_engine": "dw_sensitivity_usd", "reporting_db": "calc_sbm_charge"}
for db, t in ft.items():
    check(f"{db}: foreign table {t} gone", q(db, f"SELECT count(*) FROM pg_foreign_table f JOIN pg_class c ON c.oid=f.ftrelid WHERE c.relname='{t}'")[0][0] == 0)
check("C 07.00 objects intact (dwh fdw_stg.stg_facilities, reporting fdw_sa.calc_sa_exposure)",
      q("dwh", "SELECT count(*) FROM fdw_stg.stg_facilities")[0][0] > 0 and q("reporting_db", "SELECT count(*) FROM fdw_sa.calc_sa_exposure")[0][0] > 0)

# 3. query log: only plain SELECT / INSERT ... VALUES (+ DELETE of the target) touch the C90 tables
C90 = re.compile(r"stg_sensitivity|dw_sensitivity_usd|calc_sbm_charge|c90_facts|trade_sensitivity|ref_risk_weight", re.I)
seen = {"SELECT": 0, "INSERT": 0}
for db in ("trading_db", "staging", "dwh", "frtb_engine", "reporting_db"):
    for (qt,) in q(db, "SELECT query FROM pg_stat_statements WHERE dbid=(SELECT oid FROM pg_database WHERE datname=current_database())"):
        if not C90.search(qt) or "pg_stat_statements" in qt or "pg_" in qt.lower().split("from")[-1][:12]:
            continue
        u = qt.strip().upper()
        good = (u.startswith("SELECT") and "FDW" not in u) or (u.startswith("INSERT") and " VALUES " in u and " SELECT " not in u) or u.startswith("DELETE FROM")
        check(f"{db}: log entry ok", good, "" if good else qt[:90])
        seen[u.split()[0]] = seen.get(u.split()[0], 0) + 1
check("query log has the mapping reads and writes", seen["SELECT"] >= 5 and seen["INSERT"] >= 4, seen)

# 4. the existing parser reads every mapping with column-level edges
for f in sorted(HERE.glob("m_C90_*.xml")):
    r = parse_xml_lineage(f.read_text(encoding="utf-8"))
    d = r.graph.to_dict()
    n_col = sum(1 for n in d["nodes"] if n["kind"] == "column")
    check(f"{f.name} parses ({r.format_detected}), {n_col} column nodes, {len(d['edges'])} edges", r.format_detected == "informatica" and n_col > 0 and not r.errors, r.errors)

print("\nALL OK" if ok else "\nFAILED")
sys.exit(0 if ok else 1)
