"""Forward lineage (S10-S12): impact graph and what-if sizing, all driven by the graph."""

from __future__ import annotations

import re
from decimal import ROUND_HALF_UP, Decimal

from lineage_store.db import cypher
from lineage_store.store import LineageStore, NotFound

LANES = ["START", "STAGING", "WAREHOUSE", "REG ENGINE", "C 07.00 CELLS", "DEPENDENT CELLS"]
LANE_OF = {0: 1, 1: 1, 2: 2, 3: 2, 4: 3, 5: 3}  # vertex lane (first hop..engine) -> impact lane
CELL_SHORT = {"0200": "exposure value", "0220": "RWEA"}
DEPENDENT = {"C02.00": ("Total risk exposure amount", "C 02.00 · via RWEA"), "C03.00": ("CET1 ratio", "C 03.00 · via C 02.00")}
THRESHOLD_BPS = 10
METHOD = ("EUR millions. Estimates, not recalculated returns: method = linear propagation through recorded "
          "transformations; reviewed by methodology before use.")


def r1(x) -> Decimal:
    return Decimal(str(x)).quantize(Decimal("0.1"), ROUND_HALF_UP)


def forward_raw(st: LineageStore, starts: list[str], d: str):
    """(nodes {uid: props}, edges [(src, dst, props, is_dependency)], dependency level per dependent cell)."""
    reach = cypher(st.conn, "MATCH p=(s)-[:DERIVES*1..14]->(t) WHERE s.uid IN $u "
                   "WITH t, [r IN relationships(p) WHERE r.valid_from > $d OR r.valid_to < $d] AS bad "
                   "WHERE size(bad) = 0 RETURN DISTINCT t.uid", {"u": starts, "d": d})
    uids = list(dict.fromkeys(starts + sorted(reach)))
    levels: dict[str, int] = {}
    frontier = [u for u in uids if cypher(st.conn, "MATCH (n:ReportCell {uid: $u}) RETURN n.uid", {"u": u})]
    level = 0
    while frontier:
        level += 1
        nxt = [u for u in cypher(st.conn, "MATCH (a:ReportCell)-[:DEPENDS_ON]->(b:ReportCell) WHERE a.uid IN $u "
                                 "RETURN DISTINCT b.uid", {"u": frontier}) if u not in levels]
        for u in nxt:
            levels[u] = level
        uids += [u for u in nxt if u not in uids]
        frontier = nxt
    nodes = {p["uid"]: p for p in cypher(st.conn, "MATCH (n) WHERE n.uid IN $u RETURN properties(n)", {"u": uids})}
    edges = []
    for lab, dep in (("DERIVES", False), ("DEPENDS_ON", True)):
        rows = cypher(st.conn, f"MATCH (a)-[e:{lab}]->(b) WHERE a.uid IN $u AND b.uid IN $u AND e.valid_from <= $d "
                      "AND e.valid_to >= $d RETURN id(e), a.uid, b.uid, properties(e)", {"u": uids, "d": d}, cols=4)
        edges += [(a, b, p, dep) for _, a, b, p in sorted(rows)]
    return nodes, edges, levels


def _starts(st: LineageStore, uid: str) -> list[str]:
    row = cypher(st.conn, "MATCH (n {uid: $u}) RETURN properties(n)", {"u": uid})
    if not row:
        raise NotFound(f"unknown element {uid}")
    return st._start_points(uid, uid.split(":")[0]), row[0]


def cell_info(st: LineageStore, cell_id: str) -> dict:
    tpl, sheet, row, col = cell_id.split(":")
    code = st.one("SELECT code FROM template WHERE id = %s", (tpl,))[0]
    if tpl in DEPENDENT:
        label, ref = DEPENDENT[tpl]
        return {"node": code, "sub": label, "label": label, "ref": ref, "dependent": True}
    sheet = sheet.replace("_", " ")
    lab = f"{sheet} · {CELL_SHORT.get(col[1:], col[1:])}"
    return {"node": f"{code} · {col}", "sub": lab, "label": lab, "ref": f"{code} {row} {col}", "dependent": False}


def _cell_sort(st, cid):
    tpl, sheet, _, col = cid.split(":")
    pos = st.one("SELECT pos FROM sheet_def WHERE template = %s AND name = %s", (tpl, sheet.replace("_", " ")))
    return (tpl != "C07.00", tpl, pos[0] if pos else 0, col)


def impact(st: LineageStore, uid: str, sub: str | None) -> dict:
    s = st.submission(sub)
    starts, el = _starts(st, uid)
    nodes, edges, levels = forward_raw(st, starts, s["ref_date"].isoformat())
    kind = uid.split(":")[0]
    incoming = {}
    for a, b, p, dep in edges:
        incoming.setdefault(b, p)
    cells = sorted((u for u in nodes if u in levels or nodes[u]["kind"] == "anchor"), key=lambda c: _cell_sort(st, c))
    out_nodes = [{"uid": uid, "label": el["label"] if kind != "field" else el["label"], "kind": "start", "lane": 0,
                  "sublabel": "FIRST HOP" if el.get("lane") == 0 else "START"}]
    for u, p in sorted(nodes.items(), key=lambda kv: kv[1].get("lane", 0)):
        if u == uid or u in cells or p["kind"] == "anchor":
            continue
        inc = incoming.get(u, {})
        hop = inc.get("hop")
        rules = [r.split(":")[1] for r in inc.get("rule_ids", [])]
        label = p["sublabel"] if p["kind"] == "field" else p["label"]
        if p["kind"] == "calc" and rules == ["T7"]:
            label = "SA engine: CRM"
        sub_l = (f"HOP {hop}" + (f" · {rules[-1]}" if p["kind"] == "calc" and rules else "")) if hop else ""
        out_nodes.append({"uid": u, "label": label, "kind": "hop", "lane": LANE_OF.get(p.get("lane", 0), 2),
                          **({"sublabel": sub_l} if sub_l else {})})
    impacted = []
    for c in cells:
        info = cell_info(st, c)
        dep = info["dependent"]
        out_nodes.append({"uid": c, "label": info["node"], "sublabel": info["sub"], "kind": "dependent" if dep else "cell",
                          "lane": 5 if dep else 4})
        impacted.append({"cell_id": c, "label": info["label"], "ref": info["ref"]})
    ids = {n["uid"] for n in out_nodes}
    out_edges = [{"src": a, "dst": b} for a, b, _, _ in edges if a in ids and b in ids]
    out_edges += [{"src": uid, "dst": u} for u in starts if u != uid and u in ids]
    return {"element": {"uid": uid, "name": (f"{el['sublabel']}.{el['label']}" if kind == "field" else el["label"]),
                        "kind": kind},
            "stats": {"templates": len({c.split(":")[0] for c in cells}), "cells": len(cells), "entities": 1,
                      "dependency_levels": max(levels.values(), default=0)},
            "lanes": LANES, "nodes": out_nodes, "edges": out_edges, "impacted": impacted}


def _threshold(pct: Decimal) -> str:
    return "above" if pct >= 1 else "near" if pct >= Decimal("0.5") else "within"


def what_if(st: LineageStore, uid: str, haircut_pct: float, sub: str | None) -> dict:
    s = st.submission(sub)
    d, sid = s["ref_date"].isoformat(), s["id"]
    starts, _ = _starts(st, uid)
    nodes, edges, levels = forward_raw(st, starts, d)
    value = lambda c: Decimal(st.one("SELECT value FROM cell_value WHERE cell_id = %s AND submission_id = %s", (c, sid))[0])  # noqa: E731
    h = Decimal(str(haircut_pct)) / 100

    contrib: dict[str, Decimal] = {}
    for a, b, p, dep in edges:
        if not dep and "contribution" in p and nodes.get(b, {}).get("kind") == "anchor":
            contrib[b] = contrib.get(b, Decimal(0)) + Decimal(str(p["contribution"]))
    est: dict[str, Decimal] = {}  # change per cell (1 dp), from_element per cell
    rows, frm = [], dict(contrib)
    for c in sorted(contrib, key=lambda c: _cell_sort(st, c)):
        est[c] = r1(-contrib[c] * h)

    formulas = {}
    for a, b, p, dep in edges:
        if dep:
            formulas.setdefault(b, []).append((a, p["formula"]))
    ratio = None
    for tgt, fl in sorted(formulas.items(), key=lambda kv: levels.get(kv[0], 0)):
        f = fl[0][1]
        if "Σ" in f:  # C02 = Σ RWEA: dependent change = sum of source changes
            srcs = [a for a, _ in fl if a in est]
            est[tgt] = sum((est[a] for a in srcs), Decimal(0))
            frm[tgt] = sum((frm[a] for a in srcs), Decimal(0))
        elif re.fullmatch(r"\w+ = \w+ / \w+", f):
            ratio = (tgt, f)

    def row(c: str) -> dict:
        info, rep = cell_info(st, c), value(c)
        chg = est[c]
        pct = (abs(chg) / rep * 100).quantize(Decimal("0.01"), ROUND_HALF_UP)
        return {"cell_id": c, "label": info["label"], "ref": info["ref"], "reported": float(r1(rep)),
                "from_element": float(r1(frm[c])), "estimated": float(r1(rep + chg)), "change": float(chg),
                "pct_of_cell": float(pct), "threshold": _threshold(pct)}
    rows = [row(c) for c in sorted(est, key=lambda c: _cell_sort(st, c))]

    out_ratio = None
    bps = Decimal(0)
    if ratio:
        tgt, f = ratio
        num_code, den_code = re.fullmatch(r"\w+ = (\w+) / (\w+)", f).groups()  # e.g. C01, C02 -> C01.00, C02.00
        num = next(iter(cypher(st.conn, "MATCH (n:ReportCell) WHERE n.uid STARTS WITH $p RETURN n.uid", {"p": num_code + "."})), None)
        den = next((c for c in est if c.startswith(den_code + ".")), None)
        if num and den:
            n_v, d_v = value(num), value(den)
            before, after = n_v / d_v * 100, n_v / (d_v + est[den]) * 100
            bps = (after - before) * 100
            out_ratio = {"cell_id": tgt, "label": "CET1 ratio (C 03.00)", "reported_pct": float(value(tgt)),
                         "estimated_pct": float(after.quantize(Decimal("0.01"), ROUND_HALF_UP)),
                         "change_bps": float(bps.quantize(Decimal("0.1"), ROUND_HALF_UP)), "threshold_bps": THRESHOLD_BPS}
    above = sum(1 for r in rows if r["threshold"] == "above")
    if abs(bps) >= THRESHOLD_BPS:
        decision = {"level": "resubmit", "title": "Consider resubmission",
                    "text": f"Capital ratio impact of {abs(bps):.1f} bps exceeds the {THRESHOLD_BPS} bps threshold. "
                            "Escalate to Regulatory Affairs and record the decision against the incident."}
    elif above:
        decision = {"level": "discuss", "title": "Discuss with Regulatory Affairs",
                    "text": f"{above} cell(s) move more than 1%. Capital ratio impact stays below {THRESHOLD_BPS} bps. "
                            "Record the decision against the incident."}
    else:
        decision = {"level": "none", "title": "No resubmission needed",
                    "text": "No cell moves more than 1% and the capital ratio impact stays below "
                            f"{THRESHOLD_BPS} bps. Record the assessment against the incident."}
    cde = [{"field": f, "cells": n, "of": 10} for f, n in st.q("SELECT field, cells FROM cde_footprint ORDER BY pos")]
    return {"rows": rows, "ratio": out_ratio, "decision": decision, "cde_footprint": cde, "method_note": METHOD}
