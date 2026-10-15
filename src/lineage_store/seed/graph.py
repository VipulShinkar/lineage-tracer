"""Seed the AGE graph: the page-6 hop graph, reports/cells, rules, controls, forward-lineage contributions."""

from __future__ import annotations

from lineage_store import db
from lineage_store.db import cypher
from lineage_store.seed import relational as R

V, E = db.upsert_vertex, db.upsert_edge

# edges are created in this order; the first edge of each hop carries the numbered badge in the UI
HOP_EDGES = [  # src, dst, hop, rule_ids, extra props
    ("system:loan_origination", "dataset:stg_credit_facilities", 1, ["rule:T1"], {}),
    ("system:core_banking", "dataset:stg_credit_facilities", 1, ["rule:T1"], {}),
    ("system:collateral_system", "dataset:stg_collateral", 2, ["rule:T1"], {}),
    ("system:fx_rates", "dataset:stg_collateral", 2, [], {}),
    ("gap:haircut_table", "dataset:stg_collateral", 2, [], {"dashed": True}),
    ("dataset:stg_credit_facilities", "dataset:dw_exposure", 3, ["rule:T2", "rule:T3"], {}),
    ("dataset:stg_collateral", "dataset:dw_exposure", 3, [], {}),
    ("dataset:stg_collateral", "dataset:dw_collateral_alloc", 3, [], {}),
    ("dataset:dw_exposure", "dataset:mart_sa_exposure", 4, ["rule:T4"], {}),
    ("dataset:mart_sa_exposure", "adj:ADJ-2026-Q2-014", 5, ["rule:T5"], {}),
    ("adj:ADJ-2026-Q2-014", "job:sa_engine", 6, ["rule:T6", "rule:T7"], {}),
    ("dataset:dw_collateral_alloc", "job:sa_engine", 6, ["rule:T7"], {}),
]
RULE_NAMES = {"T1": "Pass-through", "T2": "FX conversion", "T3": "Scope filter (intragroup)",
              "T4": "Product to exposure class mapping", "T5": "Manual adjustment", "T6": "Credit conversion factor",
              "T7": "Credit risk mitigation, comprehensive method", "T8": "Scaling for XBRL"}


def _cell_label(cid: str) -> tuple[str, str]:
    tpl, sheet, row, col = cid.split(":")
    return f"{tpl[0]} {tpl[1:]} {row} {col}", sheet.replace("_", " ")


def seed(conn) -> None:
    # first hop
    for uid, label, kind in [("loan_origination", "Loan origination", "source"), ("core_banking", "Core banking", "source"),
                             ("collateral_system", "Collateral system", "source"),
                             ("fx_rates", "FX rates (ECB ref.)", "reference")]:
        V(conn, "System", f"system:{uid}", label=label, kind=kind, lane=0)
    V(conn, "Gap", "gap:haircut_table", label="Haircut table — unmapped", kind="gap", lane=0)
    for uid, label, lane in [("staging", "Staging", 1), ("risk_warehouse", "Risk warehouse", 2), ("reg_data_mart", "Reg data mart", 3)]:
        V(conn, "System", f"system:{uid}", label=label, kind="dataset", lane=lane)
    for name, lane, system in [("stg_credit_facilities", 1, "staging"), ("stg_collateral", 1, "staging"),
                               ("dw_exposure", 2, "risk_warehouse"), ("dw_collateral_alloc", 2, "risk_warehouse"),
                               ("mart_sa_exposure", 3, "reg_data_mart")]:
        V(conn, "Dataset", f"dataset:{name}", label=name, kind="dataset", lane=lane, hidden=False,
          system_uid=f"system:{system}")
        E(conn, "CONTAINS", f"system:{system}", f"dataset:{name}")
    V(conn, "Adjustment", "adj:ADJ-2026-Q2-014", label="ADJ-2026-Q2-014", sublabel="MANUAL · EUC", kind="manual", lane=4)
    V(conn, "Job", "job:sa_engine", label="SA engine: CCF, CRM", kind="calc", lane=5)

    # reports and cells
    for tid, code, _, short, in_scope, _ in R.TEMPLATES:
        if in_scope:
            V(conn, "ReportTemplate", f"template:{tid}", label=code, sublabel=short, kind="template")
    cells = [(c[0], c[5]) for c in R.c07_cells() if c[5] != "not_in_scope"] + [(R.C01, "complete"), (R.C02, "complete"), (R.C03, "complete")]
    for cid, _ in cells:
        label, sheet = _cell_label(cid)
        V(conn, "ReportCell", cid, label=label, sublabel=sheet, kind="anchor", lane=6)
        E(conn, "CONTAINS", f"template:{cid.split(':')[0]}", cid)

    # rules, mapping, controls, gap
    for seq, uid, ver, ef, et, typ, hl, desc, owner, ref in R.RULES:
        if seq == 4 and ver == "v3.1":
            continue
        t = uid.split(":")[1]
        V(conn, "Rule", uid, label=f"{t} · {RULE_NAMES[t]}", sublabel=ver, kind="rule",
          subtitle=f"SA engine · hop 6 · engine rule v5.0" if t == "T7" else f"{typ.title()} · {hl.lower()} · {ver}",
          keywords="collateral_value collateral haircut" if t == "T7" else "")
    V(conn, "Mapping", R.MAPPING_UID, label="product → exposure class", sublabel="v3.2", kind="mapping")
    E(conn, "APPLIES", "rule:T4", R.MAPPING_UID)
    # collateral eligibility mapping: hidden from the hop graph, links straight to the 6 collateral-sensitive cells
    V(conn, "Mapping", "mapping:collateral_eligibility", label="Collateral type → eligibility", sublabel="v2.0",
      kind="mapping", hidden=True, subtitle="Regulatory data mart · hop 4", keywords="collateral_value")
    for c in R.CONTROLS:
        V(conn, "Control", f"control:{c[0]}", label=c[3], sublabel=c[1], kind="control")
    E(conn, "HAS_GAP", "dataset:stg_collateral", "gap:haircut_table")

    # page-6 dataset-level DERIVES edges (hop badge = hop, job_id = job:hopN)
    for src, dst, hop, rules, extra in HOP_EDGES:
        E(conn, "DERIVES", src, dst, hop=hop, job_id=f"job:hop{hop}", rule_ids=rules, **extra)

    # SA engine -> report cells (hop 7); contribution = effect of collateral_value on the cell
    for cid, _ in cells:
        if cid.startswith("C07.00"):
            if cid in R.CONTRIB:  # engine outputs; the pre-CCF original exposure comes straight from the mart
                E(conn, "DERIVES", "job:sa_engine", cid, hop=7, job_id="job:hop7", rule_ids=["rule:T8"],
                  contribution=R.CONTRIB[cid])
            else:
                E(conn, "DERIVES", "dataset:mart_sa_exposure", cid, hop=7, job_id="job:hop7", rule_ids=["rule:T8"])

    # cell-to-cell dependencies
    for cid, _ in cells:
        if cid.startswith("C07.00") and cid.endswith("c0220") and cid in R.CONTRIB:
            E(conn, "DEPENDS_ON", cid, R.C02, formula="C02 = Σ RWEA", formula_text="C 02.00 TREA = Σ RWEA (C 07.00 c0220)")
    E(conn, "DEPENDS_ON", R.C01, R.C03, formula="C03 = C01 / C02",
      formula_text="C 03.00 CET1 ratio = C 01.00 CET1 ÷ C 02.00 TREA")
    E(conn, "DEPENDS_ON", R.C02, R.C03, formula="C03 = C01 / C02",
      formula_text="C 03.00 CET1 ratio = C 01.00 CET1 ÷ C 02.00 TREA")

    for cid in R.CONTRIB:
        E(conn, "DERIVES", "mapping:collateral_eligibility", cid)


def seed_forward(conn) -> None:
    """Forward-lineage links that need the field vertices created by the SQL ingest."""
    E(conn, "CONTAINS", "system:collateral_system", "dataset:collateral_master")
    for c in R.CONTROLS:  # controls guard their datasets / fields (fields exist only after the ingest)
        E(conn, "GUARDED_BY", c[5], f"control:{c[0]}")
    for uid, kw, sub in [("field:stg_collateral.market_value_eur", "collateral_value",
                          "Staging · hop 2 · pass-through of the field above"),
                         ("field:collateral_master.collateral_value", "",
                          "Collateral system · first hop · owner: collateral data owner"),
                         ("control:H2_coll_age", "collateral_value", "")]:
        cypher(conn, "MATCH (n {uid: $u}) SET n.keywords = $k, n.subtitle = $s RETURN 1", {"u": uid, "k": kw, "s": sub})
    E(conn, "DERIVES", "field:dw_collateral_alloc.allocated_value_eur", "job:sa_engine", hop=6, job_id="job:hop6",
      rule_ids=["rule:T7"])
