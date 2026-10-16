"""Deterministic seed of lcr_mart.raw (3 entities, ~2,000 deposits, ~300 securities, cash flows, FX, LCR parameters).
Usage: .venv\\Scripts\\python sandbox\\pipelines\\lcr\\seed_raw.py"""
import random
from datetime import date, timedelta
from decimal import Decimal as D

import psycopg

DSN = "host=127.0.0.1 port=5432 user=etl_owner password=etl_owner dbname=lcr_mart"
rnd = random.Random(20260630)
ENT = {"ENT-UK": ("GBP", D("1.27"), 150), "ENT-IN": ("INR", D("0.012"), 125), "ENT-SG": ("SGD", D("0.74"), 175)}  # ccy, rate, target LCR %
FX = {"USD": D("1"), "GBP": D("1.27"), "INR": D("0.012"), "SGD": D("0.74"), "EUR": D("1.08")}
PARAM = {  # run-off / inflow rates and haircuts
    "RET_STABLE": D("0.05"), "RET_LESS_STABLE": D("0.10"), "WHOLESALE_OPERATIONAL": D("0.25"),
    "CORP_NON_OPERATIONAL": D("0.40"), "FIN_NON_OPERATIONAL": D("1.00"), "OUT_WHOLESALE_FUNDING": D("1.00"),
    "IN_LOAN_PERFORMING": D("0.50"), "IN_FIN": D("1.00"),
    "HQLA_L1": D("0"), "HQLA_L2A": D("0.15"), "HQLA_L2B": D("0.50"),
}
CPTY = ["RETAIL"] * 10 + ["SME"] * 4 + ["CORP"] * 4 + ["FIN"] * 2
CLASSES = [("L1_SOVEREIGN", "1"), ("L1_SOVEREIGN", "1"), ("L1_CENTRAL_BANK", "1"), ("L2A_GOV", "2A"), ("L2A_COVERED", "2A"),
           ("L2B_RMBS", "2B"), ("L2B_CORP_BOND", "2B"), ("CORP_BOND_LOW", "-"), ("EQUITY_NON_HQLA", "-")]
SCALE = {"RETAIL": 0.02, "SME": 0.3, "CORP": 1.5, "FIN": 2.5}  # mean USD m per account


def category(cp, op, ins):
    if cp == "RETAIL":
        return "RET_STABLE" if ins else "RET_LESS_STABLE"
    return "WHOLESALE_OPERATIONAL" if op else ("FIN_NON_OPERATIONAL" if cp == "FIN" else "CORP_NON_OPERATIONAL")


dep, sec, cf = [], [], []
n_dep = n_sec = 0
for code, (ccy, rate, target) in ENT.items():
    out_usd = in_usd = D(0)
    for _ in range(667 if code != "ENT-SG" else 666):
        n_dep += 1
        cp = rnd.choice(CPTY)
        op = rnd.random() < 0.3 and cp != "RETAIL"
        ins = rnd.random() < 0.6 if cp == "RETAIL" else False
        usd = D(str(round(rnd.lognormvariate(0, 0.8) * SCALE[cp] * 1e6, 2)))
        bal = (usd / rate).quantize(D("0.01"))
        dep.append((f"ACC{n_dep:05d}", code, cp, rnd.choice(["CURRENT", "SAVINGS", "TERM"]), ccy, bal, "Y" if op else "N", "Y" if ins else "N"))
        out_usd += bal * rate * PARAM[category(cp, op, ins)]
    base = date(2026, 6, 30)
    for k in range(40):  # cash flows: 25% beyond 30 days are ignored by the pipeline
        d = base + timedelta(days=rnd.randint(1, 40))
        ft = rnd.choice(["IN_LOAN_PERFORMING", "IN_LOAN_PERFORMING", "IN_FIN", "OUT_WHOLESALE_FUNDING"])
        usd = D(str(round(rnd.uniform(2, 14) * 1e6, 2)))
        cf.append((code, ft, ccy, (usd / rate).quantize(D("0.01")), d))
        if (d - base).days <= 30:
            if ft.startswith("OUT"):
                out_usd += usd * PARAM[ft]
            else:
                in_usd += usd * PARAM[ft]
    net = out_usd - min(in_usd, D("0.75") * out_usd)
    rows, w = [], D(0)
    for _ in range(100):
        n_sec += 1
        ac, lv = rnd.choice(CLASSES)
        mv = D(str(round(rnd.uniform(1, 10) * 1e6, 2)))
        enc = rnd.random() < 0.08
        rows.append([f"XS{n_sec:010d}", code, ac, ccy, mv, "Y" if enc else "N"])
        if lv != "-" and not enc:
            w += mv * (1 - PARAM[f"HQLA_L{lv}"])
    k = net * D(target) / 100 / w  # scale holdings so the entity lands on its target LCR
    for r in rows:
        r[4] = (r[4] * k / rate).quantize(D("0.01"))
        sec.append(tuple(r))

with psycopg.connect(DSN) as c, c.cursor() as cur:
    for t in ("deposit_account", "security_holding", "cashflow", "fx_rate", "lcr_param"):
        cur.execute(f"DELETE FROM raw.{t}")
    cur.executemany("INSERT INTO raw.deposit_account VALUES (%s,%s,%s,%s,%s,%s,%s,%s)", dep)
    cur.executemany("INSERT INTO raw.security_holding VALUES (%s,%s,%s,%s,%s,%s)", sec)
    cur.executemany("INSERT INTO raw.cashflow VALUES (%s,%s,%s,%s,%s)", cf)
    cur.executemany("INSERT INTO raw.fx_rate VALUES (%s,%s,%s)", [(k, "2026-06-30", v) for k, v in FX.items()])
    cur.executemany("INSERT INTO raw.lcr_param VALUES (%s,%s)", list(PARAM.items()))
print(f"seeded {len(dep)} deposits, {len(sec)} securities, {len(cf)} cashflows")
