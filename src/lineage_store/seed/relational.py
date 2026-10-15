"""Relational seed data reproducing PDF pages 4-10 (illustrative pilot data)."""

from __future__ import annotations

from datetime import date, datetime

SUB = "2026-06-30.v1"
PRIOR = "2026-03-31.v1"
CELL = "C07.00:Corporates:r0010:c0200"
FAMILY, ENTITY, BASIS = "COREP (EBA DPM)", "[LEGAL ENTITY]", "Solo"

TEMPLATES = [  # id, code, name, short, in_scope, coverage_label
    ("C01.00", "C 01.00", "Own funds", "Own funds", True, None),
    ("C02.00", "C 02.00", "Own funds requirements", "Own funds requirements", True, None),
    ("C03.00", "C 03.00", "Capital ratios", "Capital ratios", True, "Complete · via C 01/C 02"),
    ("C07.00", "C 07.00", "Credit risk — Standardised Approach", "Credit risk SA", True, None),
    ("C08.01", "C 08.01", "Credit risk — IRB", "Credit risk IRB", False, None),
    ("C34.01", "C 34.01", "Counterparty credit risk", "Counterparty credit risk", False, None),
    ("C16.00", "C 16.00", "Operational risk", "Operational risk", False, None),
    ("C26.00", "C 26.00", "Large exposures limits", "Large exposures", False, None),
    ("C47.00", "C 47.00", "Leverage ratio calculation", "Leverage ratio", False, None),
]

C07_COLS = [("0010", "Original exposure pre CCF"), ("0030", "(−) Value adj. & provisions"),
            ("0040", "Exposure net of value adj."), ("0200", "Exposure value"), ("0220", "RWEA")]
C07_ROWS = [("0010", "Total exposures"), ("0020", "of which: defaulted exposures"), ("0030", "of which: SME"),
            ("0040", "On-balance sheet exposures"), ("0050", "Off-balance sheet exposures")]
SHEETS = ["Corporates", "Institutions", "Retail", "Secured by immovable property", "Total"]

# sheet -> row -> values for cols 0010, 0030, 0040, 0200, 0220 (page 5 for Corporates; thinner elsewhere)
C07_VALUES = {
    "Corporates": {
        "0010": (1265.4, -21.6, 1243.8, 1240.5, 1118.9),
        "0020": (38.2, -14.1, 24.1, 23.7, 35.6),
        "0030": (412.6, -5.2, 407.4, 406.1, 297.2),
        "0040": (1061.9, -19.9, 1042.0, 1041.4, 962.0),
        "0050": (203.5, -1.7, 201.8, 199.1, 156.9),
    },
    "Institutions": {"0010": (640.2, -3.1, 637.1, 612.3, 248.6)},
    "Retail": {"0010": (960.5, -18.9, 941.6, 905.8, 612.4)},
    "Secured by immovable property": {"0010": (3250.7, -41.3, 3209.4, 3120.4, 1092.1)},
    "Total": {"0010": (6116.8, -84.9, 6031.9, 5879.0, 3072.0)},
}
COVERAGE = {  # (sheet, row, col) -> coverage; everything else not_in_scope
    ("Corporates", "0010", "0010"): "complete", ("Corporates", "0010", "0200"): "partial",
    ("Corporates", "0010", "0220"): "complete", ("Institutions", "0010", "0200"): "partial",
    ("Institutions", "0010", "0220"): "complete", ("Retail", "0010", "0200"): "complete",
    ("Retail", "0010", "0220"): "gap",
}
GAP_TEXT = "Collateral haircut table: source not yet mapped beyond staging. Feeds CRM step (hop 6)."
FEEDS = "This cell feeds C 02.00 (credit risk RWEA via c0220) and C 03.00 CET1 ratio."

C01 = "C01.00:Main:r0020:c0010"
C02 = "C02.00:Main:r0010:c0010"
C03 = "C03.00:Main:r0010:c0010"
CURRENT = {C01: 1458.7, C02: 9842.6, C03: 14.82}
PRIOR_VALUES = {C01: 1441.2, C02: 9715.3, C03: 14.83}

# forward-lineage contributions of collateral_value to the SA-engine outputs (cell -> EUR m)
CONTRIB = {"C07.00:Corporates:r0010:c0200": -1.2, "C07.00:Corporates:r0010:c0220": -1.1,
           "C07.00:Institutions:r0010:c0200": -48.5, "C07.00:Institutions:r0010:c0220": -9.7,
           "C07.00:Retail:r0010:c0200": -14.2, "C07.00:Retail:r0010:c0220": -10.6}


def cell_id(sheet: str, row: str, col: str) -> str:
    return f"C07.00:{sheet.replace(' ', '_')}:r{row}:c{col}"


def c07_cells() -> list[tuple]:
    """(cell_id, sheet, row, col, value, coverage)"""
    out = []
    for sheet, rows in C07_VALUES.items():
        for row, vals in rows.items():
            for (col, _), v in zip(C07_COLS, vals):
                out.append((cell_id(sheet, row, col), sheet, row, col, v,
                            COVERAGE.get((sheet, row, col), "not_in_scope")))
    return out


HOPS = [  # n, chip, manual, from, to, mechanism, frequency, data_owner, system_owner, certified, open_dq, wf_step, note
    (1, "Loan orig. → staging", False, "Loan origination + Core banking", "stg_credit_facilities",
     "Automated file feed", "Daily · month-end run used", "[Credit risk data owner]", "[Loan origination system owner]",
     "04-Sep-2026 · quarterly", "None for this date", "source",
     "Facility and balance feeds landed as received; no facility dropped or added."),
    (2, "Collateral → staging", False, "Collateral system", "stg_collateral",
     "Automated file feed", "Daily · month-end run used", "[Collateral data owner]", "[Collateral system owner]",
     "04-Sep-2026 · quarterly", "1 open · valuation age (waived)", "source",
     "Collateral valuations landed as received. Haircut table is not yet sourced (known gap)."),
    (3, "Staging → warehouse", False, "stg_credit_facilities", "dw_exposure",
     "Automated batch load", "Daily · month-end run used", "[Credit risk data owner]", "[Risk warehouse owner]",
     "04-Sep-2026 · quarterly", "None for this date", "fx",
     "{excluded} intragroup facilities excluded by scope rule T3. Value {vin} → {vout} EUR m after FX (T2) and scope (T3)."),
    (4, "Warehouse → mart", False, "dw_exposure", "mart_sa_exposure",
     "Automated batch load", "Daily · month-end run used", "[Reg reporting data owner]", "[Risk warehouse owner]",
     "04-Sep-2026 · quarterly", "None for this date",  "mapping",
     "Exposures classified to SA exposure classes (T4); {excluded} records fall in other classes. Value {vin} → {vout} EUR m."),
    (5, "Adjustment", True, "mart_sa_exposure", "ADJ-2026-Q2-014",
     "Manual adjustment · EUC workbook", "Quarterly · month-end run used", "[Reg reporting data owner]", "[EUC owner]",
     "08-Jul-2026 · maker-checker", "None for this date", "manual",
     "One counterparty reclassified from Corporates to Institutions (T5). Value {vin} → {vout} EUR m."),
    (6, "SA engine", False, "mart_sa_exposure + dw_collateral_alloc", "SA engine: CCF, CRM",
     "Automated engine run", "Quarterly · month-end run used", "[Methodology owner]", "[Reg engine owner]",
     "04-Sep-2026 · quarterly", "None for this date", "ccf",
     "Credit conversion factors (T6) and collateral CRM (T7) applied. Value {vin} → {vout} EUR m."),
    (7, "XBRL", False, "SA engine: CCF, CRM", "C 07.00 r0010 c0200",
     "Automated XBRL generation", "Quarterly · on submission", "[Reg reporting data owner]", "[Reg engine owner]",
     "04-Sep-2026 · quarterly", "None for this date", "reported",
     "Engine output scaled and written to the XBRL instance; value unchanged."),
]

HOP_MAPPINGS = {
    1: [("facility_id", "facility_id", "Pass-through key"), ("drawn_balance", "drawn_balance", "Pass-through, original currency"),
        ("undrawn_limit", "undrawn_limit", "Pass-through, original currency"), ("currency_code", "currency_code", "Pass-through"),
        ("counterparty_id", "counterparty_id", "Pass-through"), ("intragroup_flag", "intragroup_flag", "Pass-through")],
    2: [("collateral_id", "collateral_id", "Pass-through key"), ("facility_id", "facility_id", "Pass-through, link to exposure"),
        ("collateral_value", "market_value_eur", "Pass-through (T1) — haircut not yet sourced"),
        ("collateral_type", "collateral_type", "Pass-through")],
    3: [("facility_id", "exposure_id", "Pass-through key — kept for record-level drill-down"),
        ("drawn_balance", "drawn_amount_eur", "FX conversion to EUR (T2)"),
        ("undrawn_limit", "undrawn_amount_eur", "FX conversion to EUR (T2)"),
        ("currency_code", "orig_currency", "Pass-through"),
        ("counterparty_id", "counterparty_id", "Join to counterparty master for sector and group"),
        ("intragroup_flag", "— (filter)", "Intragroup facilities excluded (T3)")],
    4: [("exposure_id", "exposure_id", "Pass-through key"), ("product_code", "exposure_class", "Mapped to SA exposure class (T4)"),
        ("drawn_amount_eur", "drawn_amount_eur", "Pass-through"), ("undrawn_amount_eur", "undrawn_amount_eur", "Pass-through"),
        ("counterparty_id", "counterparty_id", "Pass-through")],
    5: [("exposure_class", "exposure_class", "Reclassified Corporates → Institutions for one counterparty (T5)"),
        ("exposure_value_eur", "exposure_value_eur", "Adjusted by −18.3 EUR m (ADJ-2026-Q2-014)")],
    6: [("exposure_value_eur", "exposure_value", "Off-balance items × credit conversion factor (T6)"),
        ("allocated_value_eur", "collateral_value", "Eligible collateral reduces exposure value (T7) — haircut table gap")],
    7: [("exposure_value", "c0200", "Expressed in reporting unit and rounded for XBRL (T8)")],
}

# hop -> (records_in, records_out, run start, run end)
RUNS = {
    1: (48211, 48211, "2026-06-30 22:05", "2026-06-30 22:31"),
    2: (9874, 9874, "2026-06-30 22:35", "2026-06-30 22:50"),
    3: (48211, 47960, "2026-06-30 23:42", "2026-07-01 00:18"),
    4: (47960, 3419, "2026-07-01 00:30", "2026-07-01 00:55"),
    5: (3419, 3418, "2026-07-07 16:12", "2026-07-08 09:40"),
    6: (3418, 3418, "2026-07-09 02:00", "2026-07-09 03:10"),
    7: (3418, 3418, "2026-08-10 18:00", "2026-08-10 18:20"),
}

# seq, step, rule, hop, amount, kind
HOP_VALUES = [
    (1, "source", None, 2, 1312.0, "source"), (2, "T1", "rule:T1", 1, 0.0, "pass"),
    (3, "fx", "rule:T2", 3, -11.7, "delta"), (4, "intragroup", "rule:T3", 3, -11.9, "delta"),
    (5, "mapping", "rule:T4", 4, -26.3, "delta"), (6, "manual", "rule:T5", 5, -18.3, "manual"),
    (7, "ccf", "rule:T6", 6, -2.1, "delta"), (8, "crm", "rule:T7", 6, -1.2, "delta"),
    (9, "T8", "rule:T8", 7, 0.0, "pass"),
]

CONTROLS = [  # id, code, hop, name, hop_name, guards, also_hop, also_name, status, detail
    ("H1_loan_count", "H1", 1, "Loan feed record count", None, "dataset:stg_credit_facilities", 3, "Record count completeness",
     "pass", "48,211 received = 48,211 sent by source"),
    ("H1_core_count", "H1", 1, "Core banking feed record count", None, "dataset:stg_credit_facilities", None, None,
     "pass", "Balance feed 48,211 received = 48,211 sent"),
    ("H2_coll_count", "H2", 2, "Collateral feed record count", None, "dataset:stg_collateral", None, None,
     "pass", "9,874 received = 9,874 sent by source"),
    ("H2_coll_age", "H2", 2, "Collateral valuation age < 1 year", None, "field:stg_collateral.market_value_eur", None, None,
     "waived", "212 valuations older than 1 year · waived by collateral data owner until Q3 revaluation"),
    ("H3_gl_recon", "H3", 3, "GL reconciliation — drawn", "GL reconciliation — drawn balances", "dataset:dw_exposure", None, None,
     "pass", "Difference 0.02% · tolerance 0.10%"),
    ("H3_fx_avail", "H3", 3, "FX rate availability", "FX rate availability", "dataset:dw_exposure", None, None,
     "pass", "All 14 currencies had a 30-Jun rate"),
    ("H3_intragroup", "H3", 3, "Intragroup exclusion check", "Intragroup exclusion reasonableness", "dataset:dw_exposure", None, None,
     "pass", "251 records excluded · within expected range"),
    ("H4_unmapped", "H4", 4, "Unmapped products = 0", None, "dataset:mart_sa_exposure", None, None,
     "pass", "0 products without an exposure class"),
    ("H4_class_move", "H4", 4, "Class vs prior quarter movement", None, "dataset:mart_sa_exposure", None, None,
     "pass", "Corporates +4.7% vs 31-Mar · within ±10% band"),
    ("H5_maker_checker", "H5", 5, "Adjustment maker ≠ checker", None, "adj:ADJ-2026-Q2-014", None, None,
     "pass", "Maker [Analyst A] · checker [Manager B]"),
    ("H5_evidence", "H5", 5, "Adjustment evidence attached", None, "adj:ADJ-2026-Q2-014", None, None,
     "pass", "Licence register extract attached"),
    ("H6_engine_input", "H6", 6, "Engine input = mart output", None, "job:sa_engine", None, None,
     "pass", "3,418 records in = 3,418 out of hop 5"),
    ("H6_eba_rules", "H6", 6, "EBA validation rules", None, "job:sa_engine", None, None,
     "pass", "All applicable EBA validation rules passed"),
    ("H7_xbrl", "H7", 7, "XBRL = engine output", None, "job:sa_engine", None, None,
     "pass", "XBRL value equals engine output"),
]

RULES = [  # seq, uid, version, eff_from, eff_to, type, hop_label, description, owner, ref, manual
    (1, "rule:T1", "v1.0", None, None, "PASS-THROUGH", "Hop 1–2",
     "Balances, limits and collateral values copied as received from source systems; no change in value.",
     "Data owner", "Interface spec"),
    (2, "rule:T2", "v2.1", "2026-01-01", None, "FX CONVERSION", "Hop 3",
     "Amounts in 14 currencies converted to EUR using the ECB reference rate of 30-Jun-2026.",
     "Finance data lead", "FX policy §4"),
    (3, "rule:T3", "v1.4", None, None, "SCOPE FILTER", "Hop 3",
     "Facilities to other group entities excluded from this solo exposure class (251 facilities).",
     "Reg reporting policy", "Scope policy §2"),
    (4, "rule:T4", "v3.1", "2025-10-01", "2026-03-31", "MAPPING", "Hop 4",
     "Product and counterparty type mapped to SA exposure class; exposures to banks move to Institutions.",
     "Reg reporting policy", "CRR Art. 112"),
    (4, "rule:T4", "v3.2", "2026-04-01", None, "MAPPING", "Hop 4",
     "Product and counterparty type mapped to SA exposure class; exposures to banks move to Institutions.",
     "Reg reporting policy", "CRR Art. 112"),
    (5, "rule:T5", "Maker-checker approved", None, None, "MANUAL ADJUSTMENT", "Hop 5",
     "One counterparty reclassified from Corporates to Institutions after licence review (ADJ-2026-Q2-014).",
     "Reg reporting (EUC-0142)", "Open evidence"),
    (6, "rule:T6", "Engine rule v5.0", None, None, "DERIVATION", "Hop 6",
     "Off-balance sheet items multiplied by the credit conversion factor for their risk bucket.",
     "Methodology", "CRR Art. 111"),
    (7, "rule:T7", "Engine rule v5.0", None, None, "DERIVATION", "Hop 6",
     "Eligible financial collateral reduces exposure value (comprehensive method). Uses haircut table — known gap.",
     "Methodology", "CRR Art. 223"),
    (8, "rule:T8", "v1.0", None, None, "SCALING", "Hop 7",
     "Values expressed in the reporting unit and rounded for XBRL; no material effect.",
     "Reg reporting", "Reporting ITS"),
]

MAPPING_UID = "mapping:product_to_class"
MAPPING_ROWS = [  # code, label, v3.2 target, v3.1 target
    ("TL-CORP", "Term loan — corporate", "Corporates", "Corporates"),
    ("RCF-CORP", "Revolving credit facility", "Corporates", "Corporates"),
    ("RCF-SME", "Revolving facility — SME", "Corporates", "Corporates"),
    ("TF-GUAR", "Trade finance guarantee", "Corporates", "Corporates"),
    ("LN-BANK", "Interbank loan", "Institutions", "Corporates"),
    ("RCF-BANK", "Facility to credit institution", "Institutions", "Corporates"),
]


def insert_all(conn) -> None:
    ins = lambda sql, rows: conn.cursor().executemany(sql, rows)  # noqa: E731
    ins("INSERT INTO submission VALUES (%s,%s,%s,%s,%s,%s,%s,%s)", [
        (SUB, "2026-06-30", "v1", "2026-08-11", FAMILY, ENTITY, BASIS, PRIOR),
        (PRIOR, "2026-03-31", "v1", "2026-05-11", FAMILY, ENTITY, BASIS, None)])
    ins("INSERT INTO template VALUES (%s,%s,%s,%s,%s,%s,%s,%s)", [
        (i, c, n, s, pos, sc, None if sc else "After Day 60", lab) for pos, (i, c, n, s, sc, lab) in enumerate(TEMPLATES)])
    ins("INSERT INTO sheet_def VALUES (%s,%s,%s)", [("C07.00", s, i) for i, s in enumerate(SHEETS)] +
        [(t, "Main", 0) for t in ("C01.00", "C02.00", "C03.00")])
    ins("INSERT INTO col_def VALUES (%s,%s,%s,%s)", [("C07.00", c, l, i) for i, (c, l) in enumerate(C07_COLS)] + [
        ("C01.00", "0010", "Amount", 0), ("C02.00", "0010", "Amount", 0), ("C03.00", "0010", "Ratio (%)", 0)])
    ins("INSERT INTO row_def VALUES (%s,%s,%s,%s,%s)", [("C07.00", c, l, c == "0010", i) for i, (c, l) in enumerate(C07_ROWS)] + [
        ("C01.00", "0020", "Common Equity Tier 1 capital", True, 0),
        ("C02.00", "0010", "Total risk exposure amount", True, 0), ("C03.00", "0010", "CET1 capital ratio", True, 0)])

    col_label = dict(C07_COLS)
    cells, values = [], []
    for cid, sheet, row, col, v, cov in c07_cells():
        note = {"partial": "1 known gap", "gap": "No lineage beyond staging", "complete": ""}.get(cov, "")
        definition = (f"Exposure value after conversion factors and credit risk mitigation, for exposures classified as {sheet}."
                      if col == "0200" else f"{col_label[col]} for exposures classified as {sheet}.")
        cells.append((cid, "C07.00", sheet, row, col, cov, note, "[DPM datapoint ID]", definition,
                      GAP_TEXT if cov in ("partial", "gap") else None, FEEDS if cov != "not_in_scope" else None, "EUR m"))
        values.append((cid, SUB, v))
        values.append((cid, PRIOR, 1184.3 if cid == CELL else round(v * 0.955, 1)))
    for cid, tpl, row, col, defn, dep, unit in [
        (C01, "C01.00", "0020", "0010", "Common Equity Tier 1 capital after regulatory deductions.",
         "This cell is the numerator of the C 03.00 CET1 ratio.", "EUR m"),
        (C02, "C02.00", "0010", "0010", "Total risk exposure amount: the sum of risk-weighted exposure amounts.",
         "This cell is the denominator of the C 03.00 CET1 ratio.", "EUR m"),
        (C03, "C03.00", "0010", "0010", "CET1 capital ratio = CET1 capital divided by total risk exposure amount.", None, "%")]:
        cells.append((cid, tpl, "Main", row, col, "complete", "", "[DPM datapoint ID]", defn, None, dep, unit))
        values.append((cid, SUB, CURRENT[cid]))
        values.append((cid, PRIOR, PRIOR_VALUES[cid]))
    ins("INSERT INTO cell_def (cell_id, template, sheet, row_code, col_code, coverage, coverage_note, dpm_id, definition,"
        " gap_summary, dependency_text, unit) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)", cells)
    ins("INSERT INTO cell_value VALUES (%s,%s,%s)", values)
    ins("INSERT INTO recent_query VALUES (%s,%s,%s)", [
        (0, CELL, "C 07.00 · Corporates · Exposure value"), (1, C03, "C 03.00 · CET1 ratio"),
        (2, C01, "C 01.00 · Common Equity Tier 1 capital")])

    ins("INSERT INTO hop VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)", HOPS)
    ins("INSERT INTO hop_mapping VALUES (%s,%s,%s,%s,%s)",
        [(h, i, *m) for h, ms in HOP_MAPPINGS.items() for i, m in enumerate(ms)])
    ins("INSERT INTO run VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)", [
        (f"RUN-20260630-H{h}", h, f"job:hop{h}", SUB, "2026-06-30 23:00", s, e, False, rin, rout)
        for h, (rin, rout, s, e) in RUNS.items()])
    ins("INSERT INTO hop_value VALUES (%s,%s,%s,%s,%s,%s,%s,%s)", [(CELL, SUB, *hv) for hv in HOP_VALUES])
    ins("INSERT INTO control VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
        [(c[0], i, c[1], c[2], c[3], c[4], c[5], c[6], c[7]) for i, c in enumerate(CONTROLS)])
    ins("INSERT INTO control_result VALUES (%s,%s,%s,%s,%s)",
        [(c[0], SUB, f"RUN-20260630-H{c[2]}", c[8], c[9]) for c in CONTROLS])
    ins("INSERT INTO adjustment VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)", [(
        "ADJ-2026-Q2-014", SUB, CELL, -18.3,
        "Counterparty [CPTY-•••4821] reclassified from Corporates to Institutions after banking licence confirmed. "
        "One-off, not recurring.", "Banking licence confirmed", "[Analyst A]", datetime(2026, 7, 7, 16, 12),
        "[Manager B]", datetime(2026, 7, 8, 9, 40), "EUC-0142", "Adjustments workbook v3 (EUC-0142, high risk)",
        "Licence register extract", "/api/adjustments/ADJ-2026-Q2-014/evidence", date(2026, 7, 8))])
    ins("INSERT INTO rule_version (seq, rule_uid, version, effective_from, effective_to, type, hop_label, description,"
        " owner, ref_label, manual, adjustment_id, approved_on, ref_url) VALUES"
        " (%s,%s,%s,%s,COALESCE(%s::date,'9999-12-31'),%s,%s,%s,%s,%s,%s,%s,%s,%s)", [
        (seq, uid, ver, ef, et, typ, hl, desc, owner, ref, uid == "rule:T5",
         "ADJ-2026-Q2-014" if uid == "rule:T5" else None, "2026-07-08" if uid == "rule:T5" else None,
         "/api/adjustments/ADJ-2026-Q2-014/evidence" if uid == "rule:T5" else None)
        for seq, uid, ver, ef, et, typ, hl, desc, owner, ref in RULES])
    ins("INSERT INTO mapping_version (mapping_uid, version, effective_from, effective_to, name) VALUES"
        " (%s,%s,%s,COALESCE(%s::date,'9999-12-31'),%s)", [
        (MAPPING_UID, "3.1", "2025-10-01", "2026-03-31", "product → exposure class"),
        (MAPPING_UID, "3.2", "2026-04-01", None, "product → exposure class")])
    ins("INSERT INTO mapping_row VALUES (%s,%s,%s,%s,%s,%s)",
        [(MAPPING_UID, v, code, label, t32 if v == "3.2" else t31, i)
         for i, (code, label, t32, t31) in enumerate(MAPPING_ROWS) for v in ("3.1", "3.2")])
    ins("INSERT INTO gap VALUES (%s,%s,%s,%s,%s,%s)", [(
        "gap:haircut_table", "Collateral haircut table — unmapped", GAP_TEXT, "Collateral data owner",
        "2026-12-15", "opened")])
