"""Deterministic record-level drill-down for the pilot cell (PDF page 10)."""

from __future__ import annotations

import random
from decimal import Decimal

from lineage_store.seed.relational import CELL, SUB

# sector -> (records, 30-Jun total, 31-Mar total)
SECTORS = {
    "Manufacturing": (812, "402.1", "391.4"),
    "Real estate activities": (604, "288.7", "270.2"),
    "Wholesale and retail trade": (911, "214.9", "206.3"),
    "Energy": (143, "131.6", "120.9"),
    "Transport and storage": (287, "97.4", "95.1"),
    "Other sectors": (661, "105.8", "100.4"),
}
PRODUCTS = {"term loan": "TL-CORP", "revolving facility": "RCF-CORP", "SME revolving facility": "RCF-SME",
            "trade guarantee": "TF-GUAR"}
# counterparty, sector, product, source, source_key, value, prior value
TOP = [
    ("CPTY-00001107", "Energy", "term loan", "Loan orig.", "LOS-FAC-00123431", "42.80", "39.60"),
    ("CPTY-00003390", "Real estate activities", "revolving facility", "Core banking", "CBS-ACC-71234502", "37.50", "35.20"),
    ("CPTY-00000815", "Manufacturing", "term loan", "Loan orig.", "LOS-FAC-00123477", "31.20", "29.00"),
    ("CPTY-00005521", "Wholesale and retail trade", "trade guarantee", "Core banking", "CBS-GTE-40098719", "28.90", "27.90"),
    ("CPTY-00012764", "Transport and storage", "term loan", "Loan orig.", "LOS-FAC-00123458", "25.40", "24.70"),
]
SECTOR_SHORT = {"Real estate activities": "Real estate", "Wholesale and retail trade": "Wholesale",
                "Transport and storage": "Transport"}
CENT = Decimal("0.01")


def _split(rng: random.Random, total: Decimal, weights: list[float]) -> list[Decimal]:
    """Split `total` proportionally to weights in cents; the last item absorbs the rounding."""
    s = sum(weights)
    vals = [(Decimal(str(w / s)) * total).quantize(CENT) for w in weights]
    vals[-1] = total - sum(vals[:-1])
    return vals


def generate() -> list[tuple]:
    rng = random.Random(20260630)
    used = {t[0] for t in TOP}
    rows: list[tuple] = []  # (record_key, cpty, sector, product, source, source_key, value, prior)

    def key() -> str:
        return f"REC-{len(rows) + 1:06d}"

    for t in TOP:
        rows.append((key(), t[0], t[1], t[2], t[3], t[4], Decimal(t[5]), Decimal(t[6])))

    for sector, (n, cur, prev) in SECTORS.items():
        fixed = [t for t in TOP if t[1] == sector]
        n_rest = n - len(fixed)
        cur_rest = Decimal(cur) - sum(Decimal(t[5]) for t in fixed)
        prev_rest = Decimal(prev) - sum(Decimal(t[6]) for t in fixed)
        w = [rng.lognormvariate(0, 0.9) for _ in range(n_rest)]
        cur_v = _split(rng, cur_rest, w)
        prev_v = _split(rng, prev_rest, [x * rng.uniform(0.85, 1.05) for x in w])
        for c, p in zip(cur_v, prev_v):
            cp = f"CPTY-{rng.randint(1000, 99999999):08d}"
            while cp in used:
                cp = f"CPTY-{rng.randint(1000, 99999999):08d}"
            used.add(cp)
            product = rng.choices(list(PRODUCTS), [45, 30, 15, 10])[0]
            if product == "trade guarantee" or rng.random() < 0.3:
                src, skey = "Core banking", (f"CBS-GTE-{rng.randint(10**7, 10**8 - 1)}" if product == "trade guarantee"
                                             else f"CBS-ACC-{rng.randint(10**7, 10**8 - 1)}")
            else:
                src, skey = "Loan orig.", f"LOS-FAC-00{rng.randint(100000, 999999)}"
            rows.append((key(), cp, sector, product, src, skey, c, p))
    return rows


def insert(conn) -> int:
    rows = generate()
    conn.cursor().executemany(
        "INSERT INTO record_contribution (submission_id, cell_id, record_key, counterparty, sector, product,"
        " source_system, source_key, value, prior_value) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
        [(SUB, CELL, k, cp, sec, prod, src, sk, v, p) for k, cp, sec, prod, src, sk, v, p in rows])
    trace = []
    for k, cp, sec, prod, src, sk, v, _ in rows[: len(TOP)]:
        usd = cp == "CPTY-00012764"
        first = Decimal("27.60") if usd else v
        code = PRODUCTS[prod]
        sysname = "Loan origination" if src == "Loan orig." else "Core banking"
        for seq, (hop, label, sub, amt, ccy) in enumerate([
            ("H1", f"{sysname} · facility {{source_key}}", "Drawn balance as received", first, "USD" if usd else "EUR"),
            ("H3", "Converted to EUR (T2)", "ECB reference rate 30-Jun-2026" if usd else "Already in EUR · no conversion", v, "EUR"),
            ("H3", "Scope check (T3)", "Not intragroup · kept", v, None),
            ("H4", "Mapped to Corporates (T4)", f"Product {code} · mapping v3.2", v, None),
            ("H5", "No manual adjustment", "Not in ADJ-2026-Q2-014 scope", v, None),
            ("H6", "CCF / CRM (T6, T7)", "On-balance · no eligible collateral", v, None),
            ("H7", "Contribution to reported cell", "C 07.00 r0010 c0200", v, None)]):
            trace.append((k, seq, hop, label, sub, amt, ccy))
    conn.cursor().executemany("INSERT INTO record_trace VALUES (%s,%s,%s,%s,%s,%s,%s)", trace)
    return len(rows)
