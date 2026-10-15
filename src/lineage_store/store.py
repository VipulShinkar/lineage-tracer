"""LineageStore: all graph traversal (AGE/Cypher) and relational queries behind the API.

Everything is returned in the JSON shapes of docs/spec/api.md. Identifiers are returned unmasked;
masking is the API layer's job.
"""

from __future__ import annotations

import json
from decimal import Decimal

from lineage_store.db import cypher

LANES = ["FIRST HOP", "STAGING", "WAREHOUSE", "REG DATA MART", "ADJUSTMENTS", "REG ENGINE", "SUBMISSION"]
MINUS = "−"
SECTOR_SHORT = {"Real estate activities": "Real estate", "Wholesale and retail trade": "Wholesale",
                "Transport and storage": "Transport"}
WATERFALL = {  # step -> (label, sublabel, kind)
    "source": ("Source", "Hops 1–2 · in orig. ccy", "total"),
    "fx": ("FX to EUR", "T2 · hop 3", "delta"),
    "intragroup": ("Intragroup out", "T3 · hop 3", "delta"),
    "mapping": ("Class mapping", "T4 · hop 4", "delta"),
    "manual": ("Manual adj.", "T5 · hop 5", "manual"),
    "ccf": ("CCF", "T6 · hop 6", "delta"),
    "crm": ("CRM", "T7 · hop 6", "delta"),
    "reported": ("Reported", "Hop 7 · XBRL", "total"),
}
KIND_SUBTITLE = {"source": "Source system", "reference": "Reference data", "gap": "Known gap", "dataset": "Dataset",
                 "manual": "Manual adjustment", "calc": "Reg engine", "template": "Report template"}
RANK = {"field": 0, "rule": 1, "mapping": 2, "control": 3, "system": 4, "dataset": 5}
SEARCH_PREFIX = {"system": ("system:", "dataset:", "gap:"), "field": ("field:", "dataset:"), "rule": ("rule:",),
                 "mapping": ("mapping:",), "control": ("control:",)}


class NotFound(KeyError):
    pass


def r1(x, nd: int = 1) -> float:
    return round(float(x), nd) + 0.0


def dfmt(d) -> str:
    return d.strftime("%d-%b-%Y")


def signed(x) -> str:
    x = r1(x)
    return f"{MINUS if x < 0 else '+' if x > 0 else ''}{abs(x):,.1f}"


class LineageStore:
    def __init__(self, conn):
        self.conn = conn

    def q(self, sql: str, args=()) -> list[tuple]:
        return self.conn.execute(sql, args).fetchall()

    def one(self, sql: str, args=()):
        r = self.conn.execute(sql, args).fetchone()
        return r

    # ---------------------------------------------------------------- context / navigation
    def submission(self, sub: str | None) -> dict:
        r = self.one("SELECT id, ref_date, version, submitted_on, prior_id FROM submission "
                     + ("WHERE id = %s" if sub else "ORDER BY ref_date DESC LIMIT 1"), (sub,) if sub else ())
        if not r:
            raise NotFound(f"unknown submission {sub}")
        return {"id": r[0], "ref_date": r[1], "version": r[2], "submitted_on": r[3], "prior_id": r[4]}

    def contexts(self) -> dict:
        rows = self.q("SELECT id, ref_date, version, submitted_on, family, entity, basis FROM submission ORDER BY ref_date DESC")
        return {
            "report_families": sorted({r[4] for r in rows}), "entities": sorted({r[5] for r in rows}),
            "bases": sorted({r[6] for r in rows}),
            "submissions": [{"id": r[0], "ref_date": r[1].isoformat(), "version": r[2],
                             "submitted_on": r[3].isoformat(), "label": f"{r[2]} · submitted {dfmt(r[3])}"} for r in rows]}

    def templates(self, sub: str | None) -> dict:
        self.submission(sub)
        counts: dict[str, dict[str, int]] = {}
        for tpl, cov, n in self.q("SELECT template, coverage, count(*) FROM cell_def GROUP BY 1, 2"):
            counts.setdefault(tpl, {})[cov] = n
        out, total = [], {"complete": 0, "partial": 0, "gap": 0}
        for tid, code, name, in_scope, note, override in self.q(
                "SELECT id, code, name, in_scope, scope_note, coverage_label FROM template ORDER BY pos"):
            c = {k: counts.get(tid, {}).get(k, 0) for k in total}
            n = sum(c.values())
            for k in total:
                total[k] += c[k]
            if not in_scope:
                label = "Not in scope yet"
            elif override:
                label = override
            elif n == 1:
                label = f"{next(k for k in c if c[k]).capitalize()} · 1 cell"
            else:
                label = " · ".join(f"{c[k]} {k}" for k in c if c[k])
            t = {"id": tid, "code": code, "name": name, "pilot_cells": n, "cells_total_in_scope": n,
                 "coverage": {**c, "label": label}, "in_scope": in_scope}
            if note:
                t["scope_note"] = note
            out.append(t)
        desc = ("C 07.00 Corporates (original exposure, exposure value, RWEA), Institutions and Retail (exposure value, "
                "RWEA) · C 01.00 CET1 · C 02.00 total risk exposure · C 03.00 CET1 ratio")
        return {"templates": out, "pilot_scope": {"total": sum(total.values()), **total, "description": desc},
                "recent_queries": [{"cell_id": r[0], "label": r[1]} for r in
                                   self.q("SELECT cell_id, label FROM recent_query ORDER BY pos")]}

    def grid(self, template: str, sheet: str | None, sub: str | None) -> dict:
        s = self.submission(sub)
        t = self.one("SELECT id, code, name FROM template WHERE id = %s", (template,))
        sheets = [r[0] for r in self.q("SELECT name FROM sheet_def WHERE template = %s ORDER BY pos", (template,))]
        if not t or not sheets:
            raise NotFound(f"no grid for template {template}")
        sheet = sheet or sheets[0]
        if sheet not in sheets:
            raise NotFound(f"unknown sheet {sheet}")
        cols = self.q("SELECT code, label FROM col_def WHERE template = %s ORDER BY pos", (template,))
        cells = {(r[0], r[1]): r for r in self.q(
            "SELECT d.row_code, d.col_code, d.cell_id, v.value, d.coverage FROM cell_def d JOIN cell_value v "
            "ON v.cell_id = d.cell_id AND v.submission_id = %s WHERE d.template = %s AND d.sheet = %s",
            (s["id"], template, sheet))}
        rows = []
        for code, label, bold in self.q("SELECT code, label, bold FROM row_def WHERE template = %s ORDER BY pos", (template,)):
            rc = [{"col": c, "cell_id": cells[(code, c)][2], "value": r1(cells[(code, c)][3], 2 if template == "C03.00" else 1),
                   "coverage": cells[(code, c)][4]} for c, _ in cols if (code, c) in cells]
            if rc:
                rows.append({"code": code, "label": label, "bold": bold, "cells": rc})
        return {"template": {"id": t[0], "code": t[1], "name": t[2]}, "sheets": sheets, "sheet": sheet,
                "columns": [{"code": c, "label": l} for c, l in cols], "rows": rows}

    # ---------------------------------------------------------------- cells
    def _cell(self, cell_id: str, sub: str | None):
        s = self.submission(sub)
        r = self.one(
            "SELECT d.cell_id, t.code, t.short_name, d.sheet, d.row_code, rd.label, d.col_code, cd.label, v.value, d.unit,"
            " d.coverage, d.coverage_note, d.dpm_id, d.definition, d.gap_summary, d.dependency_text "
            "FROM cell_def d JOIN template t ON t.id = d.template "
            "JOIN row_def rd ON rd.template = d.template AND rd.code = d.row_code "
            "JOIN col_def cd ON cd.template = d.template AND cd.code = d.col_code "
            "LEFT JOIN cell_value v ON v.cell_id = d.cell_id AND v.submission_id = %s WHERE d.cell_id = %s",
            (s["id"], cell_id))
        if not r:
            raise NotFound(f"unknown cell {cell_id}")
        return s, r

    def cell_header(self, cell_id: str, sub: str | None) -> dict:
        _, r = self._cell(cell_id, sub)
        return {"cell_id": r[0], "template": r[1], "template_name": r[2], "sheet": r[3], "row": f"r{r[4]}",
                "row_label": r[5], "col": f"c{r[6]}", "col_label": r[7],
                "value": r1(r[8] if r[8] is not None else 0, 2 if r[9] == "%" else 1), "unit": r[9],
                "coverage": r[10], "coverage_note": r[11]}

    def cell(self, cell_id: str, sub: str | None) -> dict:
        s, r = self._cell(cell_id, sub)
        lin = self.reverse(cell_id, "dataset", sub)["summary"]
        adj = self.adjustments(cell_id, s["id"])
        out = {"cell_header": self.cell_header(cell_id, sub), "dpm_id": r[12], "hops": lin["hops"],
               "first_hop_systems": self._sources(lin), "transformations": lin["transformations"],
               "manual_adjustments": {"count": len(adj), "total": r1(sum(a["amount"] for a in adj))},
               "business_definition": r[13]}
        if r[14]:
            out["gap_summary"] = r[14]
        return out

    @staticmethod
    def _sources(summary: dict) -> int:
        s = summary["first_hop_systems"]
        return int(s.split()[0]) if s else 0

    def adjustments(self, cell_id: str, sub_id: str) -> list[dict]:
        return [{"id": r[0], "amount": r1(r[1]), "description": r[2], "maker": r[3], "maker_at": r[4].isoformat(),
                 "checker": r[5], "checker_at": r[6].isoformat(), "source": r[7],
                 "evidence": {"label": r[8], "url": r[9]}, "approved_on": r[10].isoformat()}
                for r in self.q("SELECT id, amount, description, maker, maker_at, checker, checker_at, source, evidence_label,"
                                " evidence_url, approved_on FROM adjustment WHERE cell_id = %s AND submission_id = %s ORDER BY id",
                                (cell_id, sub_id))]

    # ---------------------------------------------------------------- graph: reverse lineage
    def _reverse_raw(self, cell_id: str, d: str) -> tuple[dict, list]:
        """Point-in-time reverse traversal over DERIVES. Returns ({uid: props}, [(src, dst, props)]) in edge-id order."""
        uids = cypher(self.conn,
                      "MATCH p=(c:ReportCell {uid: $cell})<-[:DERIVES*1..12]-(s) "
                      "WITH s, [r IN relationships(p) WHERE r.valid_from > $d OR r.valid_to < $d] AS bad "
                      "WHERE size(bad) = 0 RETURN DISTINCT s.uid", {"cell": cell_id, "d": d})
        uids = [cell_id] + sorted(uids)
        nodes = {p["uid"]: p for p in cypher(self.conn, "MATCH (n) WHERE n.uid IN $u RETURN properties(n)", {"u": uids})}
        edges = cypher(self.conn,
                       "MATCH (a)-[e:DERIVES]->(b) WHERE a.uid IN $u AND b.uid IN $u AND e.valid_from <= $d "
                       "AND e.valid_to >= $d RETURN id(e), a.uid, b.uid, properties(e)", {"u": uids, "d": d}, cols=4)
        return nodes, [(a, b, p) for _, a, b, p in sorted(edges)]

    def _field_edges(self, d: str) -> tuple[dict, list]:
        fields = {p["uid"]: p for p in cypher(self.conn, "MATCH (f:Field) RETURN properties(f)")}
        edges = cypher(self.conn, "MATCH (a:Field)-[e:DERIVES]->(b:Field) WHERE e.valid_from <= $d AND e.valid_to >= $d "
                       "RETURN id(e), a.uid, b.uid, properties(e)", {"d": d}, cols=4)
        return fields, [(a, b, p) for _, a, b, p in sorted(edges)]

    @staticmethod
    def _node(p: dict) -> dict:
        n = {"uid": p["uid"], "kind": p["kind"], "label": p["label"], "lane": p["lane"]}
        if p.get("sublabel"):
            n["sublabel"] = p["sublabel"]
        return n

    @staticmethod
    def _edge(src, dst, p: dict) -> dict:
        e = {"src": src, "dst": dst}
        if p.get("hop"):
            e["hop"] = p["hop"]
        if p.get("dashed"):
            e["dashed"] = True
        return e

    @staticmethod
    def _badges(edges: list[dict]) -> list[dict]:
        """Only the first edge of each hop keeps the numbered badge."""
        seen: set[int] = set()
        for e in edges:
            if "hop" in e:
                if e["hop"] in seen:
                    del e["hop"]
                else:
                    seen.add(e["hop"])
        return edges

    def reverse(self, cell_id: str, level: str, sub: str | None) -> dict:
        if level not in ("system", "dataset", "attribute"):
            raise ValueError("level must be system, dataset or attribute")
        s, _ = self._cell(cell_id, sub)
        d = s["ref_date"].isoformat()
        nodes, edges = self._reverse_raw(cell_id, d)
        visible = {u for u, p in nodes.items() if p["kind"] != "field" and not p.get("hidden")}
        base = [(a, b, p) for a, b, p in edges if a in visible and b in visible]
        order = list(dict.fromkeys([u for a, b, _ in base for u in (a, b)] + [cell_id]))  # by first appearance
        nodes = {u: nodes[u] for u in order + [u for u in nodes if u not in order]}

        if level == "dataset":
            out_nodes = [self._node(nodes[u]) for u in nodes if u in visible]
            out_edges = [self._edge(a, b, p) for a, b, p in base]
        elif level == "system":
            systems = {p["uid"]: p for p in cypher(self.conn, "MATCH (n:System) RETURN properties(n)")}
            to_sys = {u: nodes[u]["system_uid"] for u in visible if nodes[u]["kind"] == "dataset"}
            keep = {to_sys.get(u, u) for u in visible}
            out_nodes = [self._node(systems.get(u) or nodes[u]) for u in dict.fromkeys(to_sys.get(u, u) for u in visible if to_sys.get(u, u) in keep)]
            out_edges, seen = [], set()
            for a, b, p in base:
                a2, b2 = to_sys.get(a, a), to_sys.get(b, b)
                if a2 != b2 and (a2, b2) not in seen:
                    seen.add((a2, b2))
                    out_edges.append(self._edge(a2, b2, p))
        else:
            out_nodes, out_edges = self._attribute_view(nodes, base, visible, d)
        self._badges(out_edges)

        gaps = [n for n in nodes.values() if n["kind"] == "gap"]
        summary = self._summary(cell_id, s, nodes, base)
        cdep = self.one("SELECT dependency_text FROM cell_def WHERE cell_id = %s", (cell_id,))[0] or ""
        return {"cell_header": self.cell_header(cell_id, sub), "level": level, "lanes": LANES, "nodes": out_nodes,
                "edges": out_edges, "summary": summary, "known_gaps": self._known_gaps(gaps),
                "cell_dependencies": cdep}

    def _attribute_view(self, nodes, base, visible, d):
        datasets = {u for u in visible if nodes[u]["kind"] == "dataset"}
        fields, fedges = self._field_edges(d)
        ds_of = lambda f: "dataset:" + fields[f]["sublabel"]  # noqa: E731
        inc = [(a, b, p) for a, b, p in fedges if ds_of(b) in datasets]
        used = {x for a, b, _ in inc for x in (a, b)}
        out_nodes = [self._node(nodes[u]) for u in nodes if u in visible and u not in datasets]
        out_nodes += [self._node(fields[u]) for u in sorted(used, key=lambda u: (fields[u]["lane"], u))]
        out_edges = [self._edge(a, b, p) for a, b, p in inc]
        has_in = {b for _, b, _ in inc}
        has_out = {a for a, _, _ in inc}
        for a, b, p in base:
            if a not in datasets and b in datasets:
                mine = [f for f in used if ds_of(f) == b]
                pick = [f for f in mine if f not in has_in] or mine
                out_edges += [self._edge(a, f, p) for f in sorted(pick)]
            elif a in datasets and b not in datasets:
                mine = [f for f in used if ds_of(f) == a]
                pick = [f for f in mine if f not in has_out] or mine
                out_edges += [self._edge(f, b, p) for f in sorted(pick)]
            elif a not in datasets and b not in datasets:
                out_edges.append(self._edge(a, b, p))
        return out_nodes, out_edges

    def _summary(self, cell_id, s, nodes, base) -> dict:
        hops = {p["hop"] for _, _, p in base if p.get("hop")}
        rules = {r for _, _, p in base for r in p.get("rule_ids", [])}
        in_force = {r[0] for r in self.q(
            "SELECT DISTINCT rule_uid FROM rule_version WHERE COALESCE(effective_from, '0001-01-01') <= %s AND effective_to >= %s",
            (s["ref_date"], s["ref_date"]))}
        n_src = sum(1 for p in nodes.values() if p["kind"] == "source")
        n_ref = sum(1 for p in nodes.values() if p["kind"] == "reference")
        adj = self.adjustments(cell_id, s["id"])
        ctl = dict(self.q("SELECT status, count(*) FROM control_result WHERE submission_id = %s GROUP BY 1", (s["id"],)))
        ctl_txt = " · ".join(f"{ctl[k]} {k}" for k in ("pass", "waived", "fail") if ctl.get(k)) or "none"
        try:
            residual = self.waterfall(cell_id, s["id"])["residual"]
        except NotFound:
            residual = 0.0
        return {"hops": len(hops), "first_hop_systems": f"{n_src}" + (" + FX reference" if n_ref else "") if n_src else "",
                "transformations": len(rules & in_force),
                "manual_adjustments": f"{len(adj)} · {signed(sum(a['amount'] for a in adj))}" if adj else "0",
                "controls": ctl_txt, "unexplained_residual": residual}

    def _known_gaps(self, gap_nodes: list[dict]) -> list[dict]:
        out = []
        for g in gap_nodes:
            r = self.one("SELECT uid, title, description, owner, target_date, status FROM gap WHERE uid = %s", (g["uid"],))
            if r:
                out.append({"uid": r[0], "title": r[1], "description": r[2], "owner": r[3],
                            "target_date": r[4].isoformat(), "status": r[5]})
        return out

    # ---------------------------------------------------------------- hop detail
    def _hop_values(self, cell_id: str, sub_id: str) -> list[tuple]:
        return self.q("SELECT seq, step, rule_uid, hop, amount, kind FROM hop_value WHERE cell_id = %s AND submission_id = %s "
                      "ORDER BY seq", (cell_id, sub_id))

    def hop(self, cell_id: str, n: int, sub: str | None) -> dict:
        s, _ = self._cell(cell_id, sub)
        hops = self.q("SELECT n, chip, manual FROM hop ORDER BY n")
        h = self.one("SELECT from_label, to_label, mechanism, frequency, data_owner, system_owner, certified, open_dq, "
                     "waterfall_step, records_note FROM hop WHERE n = %s", (n,))
        if not h:
            raise NotFound(f"hop {n} does not exist (1..7)")
        run = self.one("SELECT run_id, cutoff, started, ended, rerun, records_in, records_out FROM run "
                       "WHERE hop = %s AND submission_id = %s", (n, s["id"]))
        vals = self._hop_values(cell_id, s["id"])
        base = sum(v[4] for v in vals if v[5] == "source")
        moves = [v for v in vals if v[5] in ("delta", "manual")]
        vin = base + sum(v[4] for v in moves if v[3] < n)
        vout = base + sum(v[4] for v in moves if v[3] <= n)
        rin, rout = (run[5], run[6]) if run else (0, 0)
        if run:
            st, en = run[2], run[3]
            actual = f"{st:%H:%M} → {en:%H:%M}" if st.date() == en.date() else f"{st:%H:%M} → {en:%d-%b %H:%M}"
        ctls = self.q(
            "SELECT c.control_id, CASE WHEN c.also_hop = %s THEN c.also_name ELSE COALESCE(c.hop_name, c.name) END, "
            "r.status, r.detail FROM control c JOIN control_result r ON r.control_id = c.control_id AND r.submission_id = %s "
            "WHERE c.hop = %s OR c.also_hop = %s ORDER BY c.seq", (n, s["id"], n, n))
        return {
            "cell_header": self.cell_header(cell_id, sub),
            "path": [{"n": r[0], "label": r[1], **({"manual": True} if r[2] else {})} for r in hops],
            "hop": {"n": n, "from": h[0], "to": h[1], "mechanism": h[2], "frequency": h[3],
                    "cutoff": run[1].strftime("%d-%b-%Y %H:%M") if run else "—",
                    "actual_run": actual if run else "—", "run_id": run[0] if run else "—", "rerun": bool(run and run[4])},
            "records": {"in": rin, "out": rout,
                        "note": h[9].format(excluded=f"{rin - rout:,}", vin=f"{vin:,.1f}", vout=f"{vout:,.1f}"),
                        "value_in": r1(vin), "value_out": r1(vout), "waterfall_step": h[8]},
            "ownership": {"data_owner": h[4], "system_owner": h[5], "certified": h[6], "open_dq_issues": h[7]},
            "mappings": [{"source_field": r[0], "target_field": r[1], "what_happens": r[2]} for r in self.q(
                "SELECT source_field, target_field, what_happens FROM hop_mapping WHERE hop = %s ORDER BY pos", (n,))],
            "controls": [{"id": r[0], "name": r[1], "status": r[2], "detail": r[3]} for r in ctls]}

    # ---------------------------------------------------------------- transformations & mappings
    def mapping(self, uid: str, version: str | None = None, compare: str | None = None, sub: str | None = None) -> dict:
        s = self.submission(sub)
        vers = self.q("SELECT version, effective_from, name FROM mapping_version WHERE mapping_uid = %s ORDER BY effective_from", (uid,))
        if not vers:
            raise NotFound(f"unknown mapping {uid}")
        if version is None:
            cur = self.one("SELECT version FROM mapping_version WHERE mapping_uid = %s AND effective_from <= %s "
                           "AND effective_to >= %s", (uid, s["ref_date"], s["ref_date"]))
            if not cur:
                raise NotFound("no mapping version in force on this date")
            version = cur[0]
        order = [v[0] for v in vers]
        if version not in order:
            raise NotFound(f"unknown version {version}")
        prev = compare or (order[order.index(version) - 1] if order.index(version) > 0 else None)
        rows = self.q("SELECT code, label, target FROM mapping_row WHERE mapping_uid = %s AND version = %s ORDER BY pos", (uid, version))
        prev_t = {}
        if prev:
            if prev not in order:
                raise NotFound(f"unknown version {prev}")
            prev_t = {r[0]: r[1] for r in self.q("SELECT code, target FROM mapping_row WHERE mapping_uid = %s AND version = %s", (uid, prev))}
        out_rows = [{"code": c, "label": l, "target": t, **({"changed": True} if prev and prev_t.get(c) != t else {})}
                    for c, l, t in rows]
        eff = next(v[1] for v in vers if v[0] == version)
        out = {"uid": uid, "name": vers[0][2], "version": version, "effective_from": eff.isoformat(), "rows": out_rows}
        if prev:
            out["previous_version"] = prev
            out["differs_in"] = sum(1 for r in out_rows if r.get("changed"))
        return out

    def transformations(self, cell_id: str, sub: str | None) -> dict:
        s, _ = self._cell(cell_id, sub)
        amounts = {v[2]: v[4] for v in self._hop_values(cell_id, s["id"]) if v[2]}
        rows = self.q(
            "SELECT rule_uid, version, effective_from, type, hop_label, description, owner, ref_label, ref_url, manual, "
            "adjustment_id, approved_on FROM rule_version WHERE COALESCE(effective_from, '0001-01-01') <= %s "
            "AND effective_to >= %s ORDER BY seq", (s["ref_date"], s["ref_date"]))
        out = []
        for uid, ver, ef, typ, hl, desc, owner, ref, url, manual, adj, appr in rows:
            t = {"id": uid.split(":")[1], "type": typ, "hop": hl, "amount": r1(amounts.get(uid, 0)), "description": desc,
                 "version": ver, "owner": owner, "reference": {"label": ref, **({"url": url} if url else {})}}
            if ef:
                t["effective_from"] = ef.isoformat()
            if manual:
                t.update(manual=True, adjustment_id=adj, approved_on=appr.isoformat())
            out.append(t)
        formula = cypher(self.conn, "MATCH ()-[e:DEPENDS_ON]->(b:ReportCell) WHERE b.uid STARTS WITH 'C03.00' "
                         "RETURN DISTINCT e.formula_text") or [""]
        return {"cell_header": self.cell_header(cell_id, sub), "as_of": s["ref_date"].isoformat(), "transformations": out,
                "mapping": self.mapping("mapping:product_to_class", None, None, sub),
                "dependency": {"text": "This cell’s RWEA (c0220) flows into C 02.00 total risk exposure amount, which is the "
                                       "denominator of the C 03.00 CET1 ratio. Numerator comes from C 01.00 CET1 capital.",
                               "formula": formula[0]}}

    # ---------------------------------------------------------------- waterfall
    def waterfall(self, cell_id: str, sub: str | None) -> dict:
        s, r = self._cell(cell_id, sub)
        vals = [v for v in self._hop_values(cell_id, s["id"]) if v[5] != "pass"]
        if not vals:
            raise NotFound("no waterfall data for this cell and submission")
        reported = Decimal(r[8])
        adj = self.adjustments(cell_id, s["id"])
        steps = []
        for _, step, rule, hop, amount, kind in vals:
            label, sub_l, k = WATERFALL[step]
            link = ({"type": "adjustment", "id": f"adj:{adj[0]['id']}"} if kind == "manual" and adj
                    else {"type": "rule", "id": rule} if rule else {"type": "hop", "id": str(hop)})
            steps.append({"key": step, "label": label, "sublabel": sub_l, "amount": r1(amount), "kind": k, "link": link})
        residual = reported - sum(Decimal(v[4]) for v in vals)
        steps.append({"key": "reported", "label": "Reported", "sublabel": WATERFALL["reported"][1], "amount": r1(reported),
                      "kind": "total", "link": {"type": "hop", "id": "7"}})
        res = r1(residual)
        ctl = self.q("SELECT c.code, c.name, r.status FROM control c JOIN control_result r ON r.control_id = c.control_id "
                     "AND r.submission_id = %s ORDER BY c.seq", (s["id"],))
        cnt = {k: sum(1 for c in ctl if c[2] == k) for k in ("pass", "waived", "fail")}
        out = {"cell_header": self.cell_header(cell_id, sub), "steps": steps, "residual": res, "tolerance": 0.1,
               "within_tolerance": abs(res) <= 0.1,
               "controls": {"summary": f"{cnt['pass']} pass · {cnt['waived']} waived · {cnt['fail']} fail",
                            "items": [{"hop": c[0], "name": c[1], "status": c[2]} for c in ctl]}}
        if adj:
            a = adj[0]
            out["adjustment"] = {k: a[k] for k in ("id", "amount", "description", "maker", "maker_at", "checker",
                                                    "checker_at", "source", "evidence")}
        return out

    # ---------------------------------------------------------------- records
    def records(self, cell_id: str, group_by: str, compare: str | None, top: int, sub: str | None) -> dict:
        s, r = self._cell(cell_id, sub)
        col = {"sector": "sector", "product": "product", "source_system": "source_system"}.get(group_by)
        if not col:
            raise ValueError("group_by must be sector, product or source_system")
        if compare and compare != s["prior_id"]:
            raise ValueError(f"compare must be the previous submission ({s['prior_id']})")
        rows = self.q(f"SELECT {col}, count(*), sum(value), COALESCE(sum(prior_value), 0) FROM record_contribution "
                      "WHERE submission_id = %s AND cell_id = %s GROUP BY 1", (s["id"], cell_id))
        groups = [{"key": k, "records": n, "current": r1(c), "compare": r1(p), "change": r1(Decimal(c) - Decimal(p))}
                  for k, n, c, p in rows]
        groups.sort(key=lambda g: (g["key"].startswith("Other"), -g["current"]))
        n_rec = sum(g["records"] for g in groups)
        cur = sum(Decimal(x[2]) for x in rows)
        prev = sum(Decimal(x[3]) for x in rows)
        top_rows = self.q("SELECT record_key, counterparty, sector, product, source_system, source_key, value "
                          "FROM record_contribution WHERE submission_id = %s AND cell_id = %s "
                          "ORDER BY value DESC, record_key LIMIT %s", (s["id"], cell_id, top))
        return {
            "cell_header": self.cell_header(cell_id, sub), "contributing_records": n_rec, "drilldown_total": r1(cur),
            "equals_reported": bool(n_rec) and abs(cur - Decimal(r[8])) < Decimal("0.05"), "groups": groups,
            "total": {"records": n_rec, "current": r1(cur), "compare": r1(prev), "change": r1(cur - prev)},
            "top": [{"record_key": k, "counterparty": cp, "sector_product": f"{SECTOR_SHORT.get(sec, sec)} · {prod}",
                     "source": src, "source_key": sk, "value": r1(v)} for k, cp, sec, prod, src, sk, v in top_rows]}

    def record(self, record_key: str) -> dict:
        r = self.one("SELECT record_key, counterparty, sector, product, source_system, source_key FROM record_contribution "
                     "WHERE record_key = %s", (record_key,))
        if not r:
            raise NotFound(f"unknown record {record_key}")
        return {"record_key": r[0], "counterparty": r[1], "sector": r[2], "product": r[3], "source_system": r[4],
                "source_key": r[5]}

    def trace(self, record_key: str) -> dict:
        rec = self.record(record_key)
        steps = self.q("SELECT hop, label, sublabel, amount, ccy FROM record_trace WHERE record_key = %s ORDER BY seq", (record_key,))
        if not steps:
            raise NotFound(f"no trace for record {record_key}")
        return {**rec, "steps": [{"hop": h, "label": l, "sublabel": sl, "amount": r1(a, 2), **({"ccy": c} if c else {})}
                                 for h, l, sl, a, c in steps]}

    # ---------------------------------------------------------------- search
    def _forward_cells(self, uids: list[str], d: str, dependents: bool = True) -> set[str]:
        """ReportCells reached forward from `uids` over DERIVES, then over cell-to-cell DEPENDS_ON."""
        cells: set[str] = set()
        if uids:
            cells |= set(cypher(self.conn,
                                "MATCH p=(s)-[:DERIVES*1..14]->(c:ReportCell) WHERE s.uid IN $u "
                                "WITH c, [r IN relationships(p) WHERE r.valid_from > $d OR r.valid_to < $d] AS bad "
                                "WHERE size(bad) = 0 RETURN DISTINCT c.uid", {"u": uids, "d": d}))
        frontier = set(cells) if dependents else set()
        while frontier:
            nxt = set(cypher(self.conn, "MATCH (a:ReportCell)-[:DEPENDS_ON]->(b:ReportCell) WHERE a.uid IN $u RETURN DISTINCT b.uid",
                             {"u": sorted(frontier)})) - cells
            cells |= nxt
            frontier = nxt
        return cells

    def _start_points(self, uid: str, kind: str) -> list[str]:
        if kind == "control":
            return cypher(self.conn, "MATCH (d)-[:GUARDED_BY]->(c {uid: $u}) RETURN d.uid", {"u": uid})
        if kind == "mapping":
            return [uid] + [x for r in cypher(self.conn, "MATCH (r)-[:APPLIES]->(m {uid: $u}) RETURN r.uid", {"u": uid})
                            for x in self._start_points(r, "rule")]
        if kind == "rule":
            return cypher(self.conn, "MATCH (a)-[e:DERIVES]->(b) WHERE $u IN e.rule_ids RETURN DISTINCT b.uid", {"u": uid})
        return [uid]

    def search(self, q: str, kind: str, sub: str | None) -> dict:
        s = self.submission(sub)
        if kind not in ("all", "system", "field", "rule", "mapping", "control", "record", "cell"):
            raise ValueError("bad kind")
        q = q.strip()
        if not q or kind == "record":  # record identifiers are never searchable (masking)
            return {"results": []}
        col = lambda k: f"ag_catalog.agtype_access_operator(properties, '\"{k}\"'::agtype)::text"  # noqa: E731
        base = f"SELECT properties::text FROM lineage._ag_label_vertex WHERE "
        rows = self.q(base + f"{col('label')} ILIKE %(p)s OR {col('uid')} ILIKE %(p)s OR {col('keywords')} ILIKE %(p)s",
                      {"p": f"%{q}%"})
        if not rows:  # typo tolerance: pg_trgm
            rows = self.q(base + f"word_similarity(%(q)s, {col('label')}) > 0.5 ORDER BY 1 LIMIT 60", {"q": q})
        found = []
        for (txt,) in rows:
            p = json.loads(txt)
            uid, k = p["uid"], p["kind"]
            typ = uid.split(":")[0]
            if k == "template" or typ == "job":
                continue
            if kind == "cell" and k != "anchor" or kind in SEARCH_PREFIX and not uid.startswith(SEARCH_PREFIX[kind]):
                continue
            found.append((RANK.get(typ, 6), uid, p))
        out = []
        for _, uid, p in sorted(found, key=lambda t: t[:2])[:25]:
            typ, k = uid.split(":")[0], p["kind"]
            cells = self._forward_cells(self._start_points(uid, typ), s["ref_date"].isoformat(), dependents=typ != "mapping")
            out.append({"uid": uid, "kind": "cell" if k == "anchor" else typ,
                        "name": f"{p['sublabel']}.{p['label']}" if typ == "field" else p["label"],
                        "subtitle": self._subtitle(uid, typ, k, p, s), "feeds_cells": len(cells),
                        "verb": "Guards" if typ == "control" else "Feeds"})
        return {"results": out}

    def _subtitle(self, uid, typ, k, p, s) -> str:
        if p.get("subtitle"):
            return p["subtitle"]
        if typ == "control":
            r = self.one("SELECT c.hop, r.status FROM control c JOIN control_result r ON r.control_id = c.control_id "
                         "AND r.submission_id = %s WHERE c.control_id = %s", (s["id"], uid.split(":")[1]))
            return f"Hop {r[0]} · {r[1]} on {dfmt(s['ref_date'])} run" if r else "Control"
        sub = p.get("sublabel", "")
        return {"field": f"Field · {sub}", "rule": f"Transformation · {sub}", "mapping": f"Mapping · {sub}",
                "anchor": f"Report cell · {sub}"}.get(k, KIND_SUBTITLE.get(k, typ.title()))
