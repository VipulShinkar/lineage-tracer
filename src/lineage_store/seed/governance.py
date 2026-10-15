"""Governance seed (PDF page 12): certification, extra adjustments, prior evidence packs, audit history."""

from __future__ import annotations

import hashlib
from datetime import date, datetime

from lineage_store import audit
from lineage_store.seed import relational as R

CERTIFICATION = [("Credit risk data owner", 14, 100, "Certified 04-Nov"), ("Finance / GL data owner", 9, 100, "Certified 06-Nov"),
                 ("Collateral data owner", 8, 63, "Due 20-Nov"), ("Reg reporting (engine rules)", 12, 92, "Due 20-Nov"),
                 ("Treasury data owner", 7, 71, "Due 20-Nov")]

# other approved adjustments so that p12 shows 4 / 4 (cells outside the pilot scope)
EXTRA_ADJ = [("ADJ-2026-Q2-009", "C07.00:Total:r0010:c0200", -2.4), ("ADJ-2026-Q2-011", "C07.00:Total:r0010:c0220", 1.9),
             ("ADJ-2026-Q2-012", "C07.00:Secured_by_immovable_property:r0010:c0200", -5.6)]

Q2_PACKS = [("EP-2026-Q2-0036", R.C01), ("EP-2026-Q2-0037", R.C02), ("EP-2026-Q2-0038", R.C03),
            ("EP-2026-Q2-0039", "C07.00:Institutions:r0010:c0200"), ("EP-2026-Q2-0040", "C07.00:Institutions:r0010:c0220"),
            ("EP-2026-Q2-0041", "C07.00:Retail:r0010:c0200")]

AUDIT = [  # ts, actor, role, action, target, detail
    ("2026-10-30T15:40:00", "Collateral data owner", "data_owner", "opened gap record", "Haircut table · target 15-Dec-2026", None),
    ("2026-11-02T17:02:00", "Lineage admin", "admin", "changed metadata", "Hop 6 · T7 description updated (approved)", None),
    ("2026-11-04T09:30:00", "Credit risk data owner", "data_owner", "certified lineage", "14 nodes · Q4 cycle", None),
    ("2026-11-06T11:15:00", "GL data owner", "data_owner", "certified lineage", "9 nodes · Q4 cycle", None),
    ("2026-11-12T14:20:00", "Analyst [B]", "analyst", "exported drill-down (masked)", "C 07.00 Corporates · top 20", None),
    ("2026-11-12T16:48:00", "Analyst [B]", "analyst", "revealed an identifier", "CPTY-•••2764 · reason: supervisory query [REF]", None),
]


def seed(conn) -> None:
    ins = lambda sql, rows: conn.cursor().executemany(sql, rows)  # noqa: E731
    ins("INSERT INTO certification VALUES (%s,%s,%s,%s,%s)", [(i, *c) for i, c in enumerate(CERTIFICATION)])
    ins("INSERT INTO adjustment (id, submission_id, cell_id, amount, description, reason, maker, maker_at, checker,"
        " checker_at, euc, source, approved_on) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)", [
        (i, R.SUB, cell, amt, "Manual correction outside the pilot scope", "Data quality correction", "[Analyst A]",
         datetime(2026, 7, 6, 11, 0), "[Manager B]", datetime(2026, 7, 7, 10, 0), "EUC-0142",
         "Adjustments workbook v3 (EUC-0142, high risk)", date(2026, 7, 7)) for i, cell, amt in EXTRA_ADJ])
    packs = [("EP-2026-Q1-0017", R.CELL, "2026-05-14T10:00:00")] + [
        (ref, cell, f"2026-11-{5 + i:02d}T09:00:00") for i, (ref, cell) in enumerate(Q2_PACKS)]
    ins("INSERT INTO evidence_pack (ref, cell, format, file_path, sha256, watermark, created_by, created_at)"
        " VALUES (%s,%s,'pdf',NULL,%s,%s,'[Analyst B]',%s)",
        [(ref, cell, hashlib.sha256(ref.encode()).hexdigest(), f"{ref} · archived", ts) for ref, cell, ts in packs])
    ins("INSERT INTO setting VALUES (%s,%s)", [("refreshed_at", "2026-11-12T22:10:00")])
    ins("INSERT INTO cde_footprint VALUES (%s,%s,%s)", [(0, "drawn_balance", 10), (1, "fx_rate", 10),
                                                       (2, "product_code", 9), (3, "counterparty_type", 9),
                                                       (4, "collateral_value", 8)])
    conn.execute("ALTER SEQUENCE evidence_pack_seq RESTART 42")
    for ts, actor, role, action, target, detail in AUDIT:  # chronological, through the real hash chain
        audit.append(conn, actor, role, action, target, detail, ts=ts)
