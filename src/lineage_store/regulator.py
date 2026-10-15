"""Regulator view (S08): plain-English narrative and stages generated deterministically from snapshot facts."""

from __future__ import annotations

from datetime import date

from lineage_store.store import dfmt, signed

WORDS = {1: "one", 2: "two", 3: "three", 4: "four", 5: "five", 6: "six"}
SECTIONS = [("cover", "Cover sheet and sign-off block"), ("narrative", "Plain-English narrative"),
            ("diagram", "Hop diagram"), ("sourcing", "Sourcing at each hop"),
            ("transformations", "Transformations with versions"), ("waterfall", "Value waterfall"),
            ("adjustments", "Manual adjustments and approvals"), ("controls", "Control results"),
            ("contributors", "Top contributors (masked)"), ("limitations", "Known limitations")]


def _steps(p: dict) -> dict:
    return {s["key"]: s["amount"] for s in p["waterfall"]["steps"]}


def stages(p: dict) -> list[dict]:
    s = _steps(p)
    prepared = s["source"] + s.get("fx", 0) + s.get("intragroup", 0)
    classified = prepared + s.get("mapping", 0)
    adjusted = classified + s.get("manual", 0)
    n_adj = len(p["adjustments"])
    src = p["lineage"]["summary"]["first_hop_systems"].replace(" + FX reference", " systems + FX rates")
    return [
        {"label": "Source systems", "value": round(s["source"], 1), "note": src},
        {"label": "Prepared", "value": round(prepared, 1), "note": "EUR, intragroup removed"},
        {"label": "Classified", "value": round(classified, 1), "note": "Exposure-class mapping"},
        {"label": "Adjusted", "value": round(adjusted, 1), "note": f"{n_adj} manual, approved", "manual": bool(n_adj)},
        {"label": "Reported", "value": p["waterfall"]["steps"][-1]["amount"], "note": "After CCF and collateral"},
    ]


def narrative(p: dict) -> str:
    s, h = _steps(p), p["cell_header"]
    d = date.fromisoformat(p["submission"]["ref_date"])
    srcs = [n["label"].lower() for n in p["lineage"]["nodes"] if n["kind"] == "source"]
    srcs = [f"the {x}" if x.endswith("system") else x for x in srcs]
    names = ", ".join(srcs[:-1]) + f" and {srcs[-1]}" if len(srcs) > 1 else "".join(srcs)
    parts = [
        f"The {h['value']:,.1f}m EUR reported for {h['sheet']} {h['col_label'].lower()} starts in "
        f"{WORDS.get(len(srcs), len(srcs))} source systems: {names}.",
        f"Balances were loaded on {d.day} {d:%B}, converted to euro at the ECB reference rate, and exposures to other "
        f"group entities were removed ({signed(s.get('fx', 0) + s.get('intragroup', 0))}m).",
        f"Products were mapped to exposure classes, moving bank exposures to Institutions ({signed(s.get('mapping', 0))}m).",
    ]
    if "manual" in s:
        parts.append("One counterparty was reclassified by hand to Institutions after its banking licence was confirmed "
                     f"({signed(s['manual'])}m, approved by a separate checker).")
    parts.append("The calculation engine then applied conversion factors and eligible collateral "
                 f"({signed(s.get('ccf', 0) + s.get('crm', 0))}m).")
    res = p["waterfall"]["residual"]
    parts.append("Every movement is explained; no unexplained difference remains." if res == 0
                 else f"An unexplained difference of {res:,.1f}m remains.")
    return " ".join(parts)


def limitations(p: dict) -> list[dict]:
    crm = _steps(p).get("crm", 0)
    out = []
    for g in p["lineage"]["known_gaps"]:
        owner = g["owner"][0].lower() + g["owner"][1:]
        out.append({"text": f"The haircut table used when recognising collateral ({signed(crm)}m effect) is not yet "
                            f"traced beyond staging. Owner: {owner}. Target date: {dfmt(date.fromisoformat(g['target_date']))}."})
    return out


def stats(p: dict) -> dict:
    items = p["waterfall"]["controls"]["items"]
    return {"hops": p["lineage"]["summary"]["hops"], "transformations": p["lineage"]["summary"]["transformations"],
            "manual_adjustments": len(p["adjustments"]),
            "controls_passed": f"{sum(1 for i in items if i['status'] == 'pass')} / {len(items)}",
            "unexplained": p["waterfall"]["residual"], "records": p["records"]["contributing_records"]}


def pack_ref(ref_date: str, n: int) -> str:
    d = date.fromisoformat(ref_date)
    return f"EP-{d.year}-Q{(d.month - 1) // 3 + 1}-{n:04d}"


def next_ref(conn, ref_date: str) -> str:
    n = conn.execute("SELECT CASE WHEN is_called THEN last_value + 1 ELSE last_value END FROM evidence_pack_seq").fetchone()[0]
    return pack_ref(ref_date, n)


def view(conn, p: dict) -> dict:
    last = conn.execute("SELECT ref, created_at FROM evidence_pack WHERE cell = %s ORDER BY created_at DESC, ref DESC LIMIT 1",
                        (p["cell_header"]["cell_id"],)).fetchone()
    ev = {"next_ref": next_ref(conn, p["submission"]["ref_date"]), "linked_request": "[REF]",
          "sections": [{"key": k, "label": l, "default": True} for k, l in SECTIONS], "formats": ["pdf", "docx"]}
    if last:
        ev["last_pack"] = {"ref": last[0], "created_on": last[1].date().isoformat()}
    return {"cell_header": p["cell_header"], "narrative": narrative(p), "stages": stages(p), "stats": stats(p),
            "limitations": limitations(p), "evidence": ev}
