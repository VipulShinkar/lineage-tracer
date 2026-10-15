"""Lineage Tracer orchestrator: breadth-first discovery from the report's data point towards systems of record.

Frontier item = one table in one system plus the attribute (value column) and the key filters that identify the
data point there. For each item: connect (vault), find what writes the table (foreign table / view / function /
query log / OpenLineage), derive column lineage with sqlglot, enqueue the source tables. A system without working
credentials pauses the trace (`connection_required`); `resume` continues from the persisted queue."""

from __future__ import annotations

import os
import re
import threading
import uuid
from urllib.parse import urlparse

import psycopg
import sqlglot
from psycopg.types.json import Jsonb
from sqlglot import exp

from lineage_parser.graph import LineageGraph, NodeKind
from lineage_store import audit, db, ingest_sql
from lineage_store.store import NotFound
from lineage_tracer import business_rules, reconcile, sql_lineage, vault
from lineage_tracer.connectors import postgres, sqlite, superset

CON = {"postgresql": postgres, "sqlite": sqlite}
LANES = ["system_of_record", "staging", "warehouse", "data_mart", "calc_engine", "reporting_layer", "report_tool"]
_threads: dict[str, threading.Thread] = {}


def lane_of(system: str, schema: str, table: str) -> str:
    a = f"{system}.{schema}.{table}".lower()
    if "mart" in table.lower():
        return "data_mart"
    for rx, lane in (("staging|stg", "staging"), ("engine|calc", "calc_engine"), ("dwh|warehouse|dw_", "warehouse"),
                     ("report|rpt", "reporting_layer")):
        if re.search(rx, a):
            return lane
    return "warehouse"


def obj(i: dict) -> str:
    return f"{i['schema']}.{i['table']}" if i.get("schema") else i["table"]


def node_id(i: dict) -> str:
    return f"{i['system']}.{obj(i)}"


def ref(i: dict) -> dict:
    return {k: i.get(k) for k in ("system", "type", "host", "database", "path", "schema", "table")}


def syskey(i: dict) -> tuple:
    return vault.key(i["type"], i.get("host"), i.get("path") if i["type"] == "sqlite" else i.get("database"))


def start(conn, report: dict, req: dict) -> str:
    """Create the trace row from POST /traces and launch it in the background."""
    dp, mode = req["data_point"], req.get("mode") or "data_point"
    tbl = next((t for t in report["tables"] if t["id"] == dp["table_id"]), None)
    if tbl is None:
        raise ValueError("table not found in the report")
    meta, src = report["meta"], dict(req["source"])
    unit = tbl.get("unit")
    if mode == "report":
        vals = tbl["value_columns"]
        label = f"{meta.get('title') or 'Report'} · whole report"
        value = None
        sums = {c: sum(r["values"].get(c) or 0 for r in tbl["rows"]) for c in vals}
        pick = {"keys": {}, "value_name": vals[0], "value": None, "value_names": vals, "key_names": tbl["key_columns"],
                "totals": sums, "nrows": len(tbl["rows"]),
                "rows": [{"key": r["key"], "value": r["values"].get(vals[0])} for r in tbl["rows"][:300]]}
    elif mode == "data_point":
        row = next((r for r in tbl["rows"] if r["index"] == dp.get("row")), None)
        col = dp.get("column")
        if not row or row["values"].get(col) is None:
            raise ValueError("data point not found in the report")
        tn = re.sub(r"[^a-z0-9]", "", (meta.get("template") or "").lower())
        parts = [meta.get("template") or meta.get("title", "Report")] + [v for v in row["key"].values()
                                                                        if re.sub(r"[^a-z0-9]", "", v.lower()) != tn]
        if len(tbl["value_columns"]) > 1:
            parts[-1] += f" c{col}" if col.isdigit() else f" {col}"
        label, value = " · ".join(parts), row["values"][col]
        pick = {"keys": row["key"], "value_name": col, "value": value, "value_names": [col], "nrows": 1}
    else:
        raise ValueError("mode must be data_point or report")
    header = {"direction": "reverse", "template": meta.get("template"), "label": label, "value": value,
              "unit": unit, "ref_date": meta.get("ref_date"), "mode": mode}
    typ = src["type"]
    if typ not in ("superset", "postgresql", "sqlite"):
        raise ValueError("source.type must be superset, postgresql or sqlite")
    host = src.get("url") if typ == "superset" else src.get("host")
    dbname = src.get("path") if typ == "sqlite" else src.get("database")
    name = src.get("name") or dbname or typ
    if src.get("user") or typ == "sqlite":
        vault.put(conn, name, typ, host, dbname, {"user": src.get("user"), "password": src.get("password")})
    elif vault.get(conn, typ, host, dbname) is None:
        raise ValueError("source credentials are required")
    tid = uuid.uuid4().hex[:12]
    state = {"queue": [], "seen": {}, "nodes": {}, "connected": [], "pending": None, "started": False,
             "ctx": {**pick, "mode": mode, "unit": unit, "ref_date": meta.get("ref_date"), "title": meta.get("title"),
                     "template": meta.get("template"), "tol": 0.05 if unit == "EUR m" else 0.01},
             "source": {"type": typ, "host": host, "database": dbname, "name": name, "object": src.get("object")}}
    conn.execute("INSERT INTO trace (trace_id, report_id, label, status, header, state) VALUES (%s,%s,%s,'running',%s,%s)",
                 (tid, report["report_id"], label, Jsonb(header), Jsonb(state)))
    audit.append(conn, "tracer", "system", "started trace", tid, f"{label} · source {typ}:{name}")
    launch(tid)
    return tid


def launch(tid: str) -> None:
    t = threading.Thread(target=run, args=(tid,), daemon=True)
    _threads[tid] = t
    t.start()


def run(tid: str) -> None:
    conn = db.connect()
    tr = Tracer(conn, tid)
    try:
        tr.loop()
    except Exception as e:  # noqa: BLE001
        tr.fail(f"{type(e).__name__}: {e}")
    finally:
        for c in tr.cons.values():
            try:
                c.close()
            except Exception:  # noqa: BLE001
                pass
        conn.close()


class Tracer:
    def __init__(self, conn, tid: str):
        self.conn, self.tid, self.cons = conn, tid, {}
        r = conn.execute("SELECT state, header FROM trace WHERE trace_id = %s", (tid,)).fetchone()
        self.s, self.header = r
        self.ctx = self.s["ctx"]
        self.steps = [d for (d,) in conn.execute("SELECT data FROM trace_step WHERE trace_id=%s ORDER BY n", (tid,))]
        self.hops = [d for (d,) in conn.execute("SELECT data FROM trace_hop WHERE trace_id=%s ORDER BY n", (tid,))]

    # ---------------------------------------------------------------- persistence
    def save(self, status: str = "running", error: str | None = None) -> None:
        c = self.conn
        c.execute("UPDATE trace SET state=%s, status=%s, error=%s WHERE trace_id=%s", (Jsonb(self.s), status, error, self.tid))
        c.execute("DELETE FROM trace_step WHERE trace_id=%s", (self.tid,))
        c.execute("DELETE FROM trace_hop WHERE trace_id=%s", (self.tid,))
        for st in self.steps:
            c.execute("INSERT INTO trace_step VALUES (%s,%s,%s)", (self.tid, st["n"], Jsonb(st)))
        for h in self.hops:
            c.execute("INSERT INTO trace_hop VALUES (%s,%s,%s)", (self.tid, h["n"], Jsonb(h)))

    def fail(self, msg: str) -> None:
        self.save("failed", msg)
        audit.append(self.conn, "tracer", "system", "trace failed", self.tid, msg[:200])

    # ---------------------------------------------------------------- model helpers
    def add_node(self, i: dict, lane: str | None = None, kind: str = "intermediate") -> str:
        nid = node_id(i)
        n = self.s["nodes"].setdefault(nid, {"id": nid, "system": i["system"], "object": obj(i),
                                             "lane": lane or lane_of(i["system"], i.get("schema") or "", i["table"]),
                                             "kind": kind})
        if lane:
            n["lane"], n["kind"] = lane, kind
        return nid

    def add_step(self, i: dict, held: str, consumed: str | None) -> dict:
        st = {"n": len(self.steps) + 1, "system": i["system"], "system_type": i["type"], "attribute_held_in": [held],
              "sourced_from": [], "consumed_by": [consumed] if consumed else [], "status": "scanning"}
        self.steps.append(st)
        i["step"] = st["n"]
        return st

    def add_hop(self, frm: str, to: str, status: str, held: list, sourced: list, transformation: str, consumed: str,
                evidence: dict, recon: dict | None = None, cols: list | None = None) -> dict:
        h = {"n": len(self.hops) + 1, "status": status, "from": frm, "to": to, "attribute_held_in": held,
             "sourced_from": sourced, "transformation": transformation, "consumed_by": consumed, "evidence": evidence,
             "recon": recon, "cols": cols or []}
        self.hops.append(h)
        return h

    def enqueue(self, i: dict, parent: dict) -> None:
        """Add the item unless its table was already seen (then only extend the attribute list)."""
        key = f"{syskey(i)}|{obj(i)}"
        seen = self.s["seen"].get(key)
        if seen:
            st = self.steps[seen - 1]
            h = f"{i['table']}.{i['value_col']}"
            if h not in st["attribute_held_in"]:
                st["attribute_held_in"].append(h)
            i["step"] = seen
            for q in self.s["queue"]:
                if q.get("step") == seen:
                    q["columns"] = list(dict.fromkeys((q.get("columns") or [q["value_col"]]) + (i.get("columns") or [])))
            return
        self.add_step(i, f"{i['table']}.{i['value_col']}", obj(parent))
        self.s["seen"][key] = i["step"]
        self.s["queue"].append(i)

    # ---------------------------------------------------------------- connections
    def cred(self, i: dict) -> dict | None:
        if i["type"] == "sqlite":
            return vault.get(self.conn, "sqlite", None, i.get("path")) if i.get("path") else None
        if i["type"] == "superset" or not i.get("host") or not i.get("database"):
            return None
        return vault.get(self.conn, i["type"], i["host"], i["database"])

    def connect(self, i: dict):
        k = syskey(i)
        if k in self.cons:
            return self.cons[k]
        cr, other = self.cred(i), None
        if cr is None and i["type"] == "postgresql" and i.get("host") and i.get("database"):
            # no credentials for this system: try those of other systems on the same host, most recent first
            for other_sys, sec in vault.same_host(self.conn, i["type"], i["host"], i["database"]):
                try:
                    c = postgres.connect(i["host"], i["database"], sec["user"], sec["password"])
                except psycopg.Error:
                    continue
                vault.put(self.conn, i["system"], i["type"], i["host"], i["database"], sec)
                cr, other = sec, other_sys
                break
            else:
                return None
        elif cr is None:
            return None
        if other is None:
            c = (postgres.connect(i["host"], i["database"], cr["user"], cr["password"]) if i["type"] == "postgresql"
                 else sqlite.connect(i["path"]))
        else:
            note = f"connected using credentials of {other}"
            self.s.setdefault("reuse", {})[i["system"]] = note
            audit.append(self.conn, "tracer", "system", f"connected to {i['system']} using credentials of {other}",
                         f"{i['type']}:{i['system']}", f"trace {self.tid}")
        self.cons[k] = c
        if list(k) not in self.s["connected"]:
            self.s["connected"].append(list(k))
            audit.append(self.conn, "tracer", "system", f"connected to {i['system']}", f"{i['type']}:{i['system']}",
                         f"trace {self.tid}")
        return c

    def pause(self, i: dict, why: str | None = None) -> None:
        parent = i.get("parent")
        msg = (f"{parent['table']}.{parent['value_col']} is sourced from {obj(i)} on {i['system']}. "
               if parent else f"The report source {i['system']} needs credentials. ") + \
              "Read-only connection details are required to continue." + (f" ({why})" if why else "")
        self.s["pending"] = {"system": i["system"], "type": i["type"], "host_hint": i.get("host") or i.get("path"),
                             "database_hint": i.get("database"), "phase": "connect", "message": msg}
        self.steps[i["step"] - 1]["status"] = "connection_required"
        self.save("connection_required")

    # ---------------------------------------------------------------- main loop
    def loop(self) -> None:
        s = self.s
        if not s["started"]:
            self.start_source()
            s["started"] = True
        while s["queue"]:
            i = s["queue"][0]
            try:
                c = self.connect(i)
            except (psycopg.Error, ValueError, OSError) as e:
                return self.pause(i, f"could not connect: {str(e).splitlines()[0][:120]}")
            if c is None:
                return self.pause(i)
            s["pending"] = None
            self.steps[i["step"] - 1]["status"] = "scanning"
            s["queue"].pop(0)
            try:
                self.process(i, c)
            except Exception as e:  # noqa: BLE001 - one bad table must not sink the trace
                if i.get("first"):
                    raise
                self.steps[i["step"] - 1]["status"] = "failed"
                self.add_hop(f"{i['system']}.(unknown source)", self.add_node(i), "unresolved", [obj(i)], [], f"Scan failed: {str(e).splitlines()[0][:160]}", obj(i), {})
            self.save()
        self.finish()

    def start_source(self) -> None:
        src, ctx = self.s["source"], self.ctx
        first = {"system": src["name"], "type": src["type"], "host": src["host"], "database": src["database"],
                 "schema": None, "table": src["object"], "first": True, "filters": {}, "value_col": None}
        if src["type"] == "superset":
            cr = vault.get(self.conn, "superset", src["host"], None)
            c = superset.login(src["host"], cr["user"], cr["password"])
            self.cons[("superset", src["host"], "")] = c
            audit.append(self.conn, "tracer", "system", f"connected to {src['name']}", f"superset:{src['name']}", f"trace {self.tid}")
            title = src["object"] or ctx["title"]
            ch = superset.find_chart(c, title)
            so = superset.chart_source(c, ch["id"])
            if so["database"]["backend"] != "postgresql":
                raise ValueError(f"Superset database backend {so['database']['backend']} is not supported")
            t0 = sqlglot.parse_one(so["sql"], dialect="postgres").find(exp.Table) if so["sql"] else None
            sch, tname = (t0.db or None, t0.name) if t0 else (so["schema"], so["table"])
            db_ = so["database"]
            first.update(system=db_["name"], type="postgresql", host=f"{db_['host']}:{db_['port']}", database=db_["name"],
                         schema=sch, table=tname)
            try:
                rows_ = superset.chart_rows(c, ch["id"])
                confirmed = all(superset.confirm(rows_, r["key"], r["value"], ctx["tol"]) for r in ctx["rows"] if r["value"] is not None) \
                    if ctx["mode"] == "report" else superset.confirm(rows_, ctx["keys"], ctx["value"], ctx["tol"])
            except Exception:  # noqa: BLE001
                confirmed = False
            first["chart"] = {"title": so["chart"], "id": ch["id"], "dataset": so["dataset"], "confirmed": confirmed,
                              "sql": so["sql"]}
            sup = {"system": src["name"], "type": "superset", "schema": None, "table": so["chart"]}
            nid = self.add_node(sup, "report_tool", "anchor")
            self.s["nodes"][nid].update(service="superset", name=so["chart"], entity_type="chart", columns=so["columns"],
                                        path_cols=ctx["value_names"], description=so["description"])
            st = self.add_step(sup, f"{so['chart']} · {ctx['value_name']}", f"Report {ctx['title']}")
            st["status"], st["sourced_from"] = "identified", [f"{first['system']}.{so['dataset']}"]
            first["chart_node"] = nid
        if first["type"] == "sqlite":
            first["path"], first["schema"] = src["database"], ""
        self.add_step(first, f"{first['table'] or ctx['title']}.{ctx['value_name']}",
                      first["chart"]["title"] if "chart" in first else f"Report {ctx['title']}")
        self.s["seen"][f"{syskey(first)}|{first['table']}"] = first["step"]
        self.s["queue"].append(first)

    # ---------------------------------------------------------------- one frontier item
    def process(self, i: dict, c) -> None:
        mod = CON[i["type"]]
        step = self.steps[i["step"] - 1]
        notes: list[str] = []
        if i.get("first"):
            self.locate_first(i, c, mod, notes)
        elif i["type"] == "postgresql" or i["type"] == "sqlite":
            i["stored"] = self.stored(i, c, mod)
        tdesc, cdesc = mod.descriptions(c, i.get("schema") or "", i["table"])
        nid = self.add_node(i, "reporting_layer" if i.get("first") else None, "anchor" if i.get("first") and not i.get("chart") else "intermediate")
        self.s["nodes"][nid].update(
            service=i["type"], database=i.get("database"), schema=i.get("schema") or None, name=i["table"],
            entity_type=mod.entity_type(c, i.get("schema") or "", i["table"]),
            description=tdesc,
            columns=[{"name": n, "data_type": t, **({"description": cdesc[n]} if n in cdesc else {})}
                     for n, t in mod.columns(c, i.get("schema") or "", i["table"])],
            path_cols=list(dict.fromkeys((i.get("columns") or [i["value_col"]]) + list(i["filters"]) + i.get("keycols", []))))
        if i.get("chart"):
            self.chart_hop(i, nid, notes)
        step["attribute_held_in"] = list(dict.fromkeys(step["attribute_held_in"]))
        try:
            step["consumed_by"] = list(dict.fromkeys(step["consumed_by"] + mod.consumers(c, i.get("schema") or "", i["table"])[:4]))
        except Exception:  # noqa: BLE001
            pass
        ws = mod.writers(c, i.get("schema") or "", i["table"])
        made = 0
        for wr in ws:
            made += self.from_writer(i, c, mod, wr, nid)
        if not made:
            ol = self.openlineage(i)
            if ol:
                made = self.from_openlineage(i, nid, ol)
        if made:
            step["status"] = "identified"
            step["sourced_from"] = [h["from"] for h in self.hops if h["to"] == nid]
        elif not ws:
            self.add_node(i, "system_of_record", "sor")
            step["status"], step["sourced_from"], step["sourced_from_is_sor"] = "identified", ["System of record"], True
        else:
            step["status"] = "unresolved"
            self.add_hop(f"{i['system']}.(unknown source)", nid, "unresolved", [obj(i)], [], "Writers were found but none could be parsed for this attribute.",
                         obj(i), {"code": "; ".join(w["ref"] for w in ws)})

    def stored(self, i: dict, c, mod) -> float | None:
        """Sum of the traced column under the item's filters; a non-numeric column (a join key or label) is
        reconciled by row count instead (agg = count)."""
        try:
            numeric = dict(mod.columns(c, i.get("schema") or "", i["table"])).get(i["value_col"], "").startswith(postgres.NUMERIC + ("real", "float"))
            if not numeric:
                i["agg"] = "count"
            return mod.sum_value(c, i.get("schema") or "", i["table"], i["value_col"] if numeric else "*", i["filters"])
        except Exception:  # noqa: BLE001
            return None

    def locate_first(self, i: dict, c, mod, notes: list) -> None:
        ctx = self.ctx
        if not i["table"]:
            i["schema"], i["table"] = self.find_report_table(c)
        else:
            r = mod.resolve(c, i["table"], i.get("schema"))
            if not r:
                raise ValueError(f"{i['table']} not found in {i['system']}")
            i["schema"], i["table"] = r
        if i["type"] != "postgresql":
            raise ValueError("a SQLite report source is not supported; use Superset or PostgreSQL")
        if ctx["mode"] == "report":
            return self.locate_report(i, c, notes)
        loc = postgres.locate(c, i["schema"], i["table"], ctx["keys"], ctx["value_name"], ctx["value"], ctx["ref_date"], ctx["tol"])
        i.update(filters=loc["filters"], value_col=loc["value_col"], stored=loc["stored"], tied=loc["tied"])
        notes += loc["notes"]
        st = self.steps[i["step"] - 1]
        st["attribute_held_in"] = [f"{i['table']}.{i['value_col']}"]

    def locate_report(self, i: dict, c, notes: list) -> None:
        """Whole-report mode: map every reported value column to a numeric column and compare column totals."""
        ctx = self.ctx
        cols = postgres.columns(c, i["schema"], i["table"])
        types, byn = dict(cols), {postgres._norm(n): n for n, _ in cols}
        name_map = {v: byn[postgres._norm(v)] for v in ctx["value_names"]
                    if postgres._norm(v) in byn and types[byn[postgres._norm(v)]].startswith(postgres.NUMERIC)}
        if not name_map:
            raise ValueError(f"no reported value column matches a numeric column of {i['schema']}.{i['table']}")
        notes += [f"report column {v} not found in {i['table']}" for v in ctx["value_names"] if v not in name_map]
        keycols = [byn[postgres._norm(k)] for k in ctx["key_names"] if postgres._norm(k) in byn]
        dcols = [n for n, t in cols if t.startswith(("date", "timestamp")) and re.search(r"date|as_?of|period|cob", n, re.I)]
        tol = ctx["tol"] * max(1, ctx["nrows"])
        best = None
        for f in ([{dcols[0]: ctx["ref_date"]}] if dcols and ctx["ref_date"] else []) + [{}]:
            tot = {v: postgres.sum_value(c, i["schema"], i["table"], d, f) for v, d in name_map.items()}
            tied = all(t is not None and abs(t - ctx["totals"][v]) <= tol for v, t in tot.items())
            best = best or (f, tot, tied)
            if tied:
                best = (f, tot, tied)
                break
        f, tot, tied = best
        first = next(iter(name_map.values()))
        i.update(filters=f, value_col=first, columns=list(name_map.values()), keycols=keycols, name_map=name_map,
                 stored=tot[next(iter(name_map))], tied=tied)
        if not tied:
            notes.append("column totals differ from the report: " + "; ".join(
                f"{v} {t} vs {ctx['totals'][v]}" for v, t in tot.items() if t is None or abs(t - ctx["totals"][v]) > tol))
        self.steps[i["step"] - 1]["attribute_held_in"] = [f"{i['table']}.{d}" for d in name_map.values()][:6]

    def find_report_table(self, c) -> tuple[str, str]:
        ctx = self.ctx
        toks = {re.sub(r"[^a-z0-9]", "", (ctx["template"] or "").lower())} | \
               {t for t in re.findall(r"[a-z0-9]{3,}", (ctx["title"] or "").lower()) if t not in ("corep", "report")}
        toks.discard("")
        best = None
        for sch, t in c.execute("SELECT n.nspname, c.relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
                                "WHERE c.relkind IN ('r','v','m','p') AND n.nspname <> ALL(%s)", (list(postgres.SYSTEM),)):
            name = re.sub(r"[^a-z0-9]", "", f"{sch}{t}".lower())
            score = sum(tok in name for tok in toks) + (0.5 if "fact" in name else 0)
            if score and (best is None or score > best[0]):
                best = (score, sch, t)
        if not best:
            raise ValueError("could not find the report table; pass source.object")
        return best[1], best[2]

    def chart_hop(self, i: dict, nid: str, notes: list) -> None:
        ch, ctx = i.pop("chart"), self.ctx
        ok = ch["confirmed"] and i.get("tied")
        rec = (f"Superset chart data re-run returned all {ctx['nrows']} reported rows; column totals of {obj(i)} agree with the report"
               if ctx["mode"] == "report" else
               f"Superset chart data re-run returned {ctx['value']:,} for the selected keys; "
               f"{obj(i)}.{i['value_col']} sums to {i['stored']}") if ok else \
              "Not reconciled: " + ("; ".join(notes) or ("chart data re-run did not confirm the value" if not ch["confirmed"]
                                                         else "stored value differs from the report"))
        h = self.add_hop(nid, i["chart_node"], "proven" if ok else "code_derived", [ch["title"]], [f"{obj(i)}.{i['value_col']}"],
                     f"Superset dataset '{ch['dataset']}' is " + ("a virtual dataset over SQL" if ch["sql"] else "a physical table")
                     + "; the chart displays it as a table.", f"Report {ctx['title']}",
                     {"code": f"Superset chart {ch['id']} '{ch['title']}' → dataset {ch['dataset']}", "sql": ch["sql"],
                      "reconciliation": rec}, None,
                     [[d, v, "pass-through", True, "value", None] for v, d in (i.get("name_map") or {ctx["value_name"]: i["value_col"]}).items()])
        h["business_rules"] = [f"Displayed as a table in Superset chart '{ch['title']}'"]

    # ---------------------------------------------------------------- writers -> hops
    def from_writer(self, i: dict, c, mod, wr: dict, nid: str) -> int:
        if wr["kind"] == "foreign":
            return self.from_foreign(i, wr, nid)
        cols = [x for x, _ in mod.columns(c, i.get("schema") or "", i["table"])]
        w = sql_lineage.parse_writer(wr["sql"], cols, wr["dialect"])
        if w is None:
            return 0
        sch = self.schema_for(c, mod, w, i)
        by_src: dict[str, list[str]] = {}
        # the key filters matter too: they pull in the dimension tables that decide which rows belong to the data point
        for col in ((i.get("columns") or [i["value_col"]])[:12] + [f for f in list(i["filters"]) + i.get("keycols", []) if f in w.out_cols]):
            for tname, scol in sql_lineage.leaf_columns(w, col, sch, i["filters"]):
                by_src.setdefault(tname, [])
                if scol not in by_src[tname]:
                    by_src[tname].append(scol)
        joined = {t: cs for t, cs in sql_lineage.filter_columns(w).items() if t not in by_src}
        by_src.update(joined)  # sources that only decide which rows qualify (join keys, WHERE) still belong to the lineage
        if not by_src:
            return 0
        gid = f"w{len(self.hops)}"
        recon = {"kind": "select", "group": gid, "target": ref(i), "value_col": i["value_col"], "filters": i["filters"],
                 "stored": i.get("stored"), "select": sql_lineage.select_sql(w), "out_cols": w.out_cols} \
            if w.select is not None and len(w.out_cols) == len(w.select.selects) else None
        if recon and i.get("agg"):
            recon["checks"] = recon["full"] = [["*", i.get("stored")]]
        elif recon and self.ctx["mode"] == "report":  # whole report: reconcile the totals of every traced numeric column
            types_ = dict(mod.columns(c, i.get("schema") or "", i["table"]))
            numeric = [x for x in (i.get("columns") or [i["value_col"]])[:10] if types_.get(x, "").startswith(postgres.NUMERIC)]
            recon["checks"] = recon["full"] = [[x, self.stored({**i, "value_col": x}, c, mod)] for x in numeric]
        text, made = sql_lineage.summarize(w, i["value_col"], i["filters"]), 0
        traced = set(i.get("columns") or [i["value_col"]]) | set(i["filters"]) | set(i.get("keycols", []))
        leaves = {col: sql_lineage.leaf_columns(w, col, sch, i["filters"]) for col in w.out_cols[:60]}
        gl: dict[str, str] = {}  # glossary terms of the columns this statement touches
        for nm in [(i.get("schema") or "", i["table"])] + [mod.resolve(c, x, i.get("schema")) for x in w.sources]:
            if nm:
                gl.update({k: business_rules.short(v) for k, v in mod.descriptions(c, *nm)[1].items() if business_rules.short(v)})
        terms = business_rules.Terms(gl)
        items = business_rules.rule_items(w, i["value_col"], i["filters"], terms, self.ctx["ref_date"], sorted(traced))
        crule = {col: business_rules.column_rule(w, col, i["filters"], terms) for col in leaves}
        for tname, scols in by_src.items():
            r = mod.resolve(c, tname, i.get("schema"))
            if not r:
                self.add_hop(f"{i['system']}.{tname}", nid, "unresolved", [f"{obj(i)}.{i['value_col']}"], [f"{tname}.{x}" for x in scols],
                             f"{text} Source table {tname} was not found in {i['system']}.", obj(i), {"code": wr["ref"], "sql": wr["sql"]})
                made += 1
                continue
            code, rc = wr["ref"], recon
            if recon and len(by_src) > 1 and not i.get("agg"):  # several sources: reconcile on a column only this source feeds, when there is one
                cs = self.exclusive_cols(c, mod, w, i, tname, sch)
                if cs:
                    rc = {**recon, "checks": [[x, self.stored({**i, "value_col": x}, c, mod)] for x in cs]}
            if rc:
                rc = {**rc, "group": f"{gid}:{tname}", **({"full": recon.get("full") or [[x, self.stored({**i, "value_col": x}, c, mod)] for x in (i.get("columns") or [i["value_col"]])[:6]]}
                                                                       if len(by_src) > 1 else {})}
            nxt = {"system": i["system"], "type": i["type"], "host": i.get("host"), "database": i.get("database"),
                   "path": i.get("path"), "schema": r[0], "table": r[1], "filters": self.carry(w, i["filters"], tname),
                   "keycols": self.carry_keys(w, i.get("keycols", []), tname), "parent": {"table": i["table"], "value_col": i["value_col"]}}
            fw = mod.writers(c, r[0], r[1]) if i["type"] == "postgresql" else []
            if fw and fw[0]["kind"] == "foreign":  # a foreign table is a window, not a system: link to the remote table
                f = fw[0]["foreign"]
                nxt.update(system=f["database"], host=f"{f['host']}:{f['port']}", database=f["database"], schema=f["schema"],
                           table=f["table"])
                code = f"{wr['ref']} · read through foreign table {r[0]}.{r[1]} ({fw[0]['ref'].split(': ', 1)[-1]})"
            nxt["columns"] = self.numeric_first(c, mod, r, scols)
            nxt["value_col"] = nxt["columns"][0]
            self.enqueue(nxt, i)
            h = self.add_hop(node_id(nxt), nid, "code_derived", [f"{obj(i)}.{i['value_col']}"], [f"{obj(nxt)}.{x}" for x in scols[:4]],
                         text, obj(i), {"code": code, "sql": wr["sql"][:2500], "version": wr.get("version"), "log": wr.get("log")},
                         rc, [[lc, col, sql_lineage.compact(w, col, i["filters"]), col in traced, "value", crule.get(col)]
                              for col, lv in leaves.items() for t, lc in lv if t == tname]
                         + [[x, i["value_col"], "join/filter on " + x, True, "filter", business_rules.filter_edge_rule(w, x, terms)]
                            for x in joined.get(tname, [])])
            h["purpose"], h["statement_rules"] = wr.get("purpose"), [x for x, _ in items]
            h["business_rules"] = business_rules.rules_for(items, tname)
            self.add_node(nxt)
            made += 1
        return made

    def schema_for(self, c, mod, w, i) -> dict | None:
        """{schema: {table: {col: type}}} for the statement's sources so sqlglot can place unqualified columns."""
        out: dict = {}
        for name in w.sources:
            r = mod.resolve(c, name, i.get("schema"))
            if not r or ("." in name) != all("." in x for x in w.sources):
                return None
            cols = {k: (v or "text") for k, v in mod.columns(c, r[0], r[1])}
            if "." in name:
                out.setdefault(r[0], {})[r[1]] = cols
            else:
                out[r[1]] = cols
        return out or None

    def exclusive_cols(self, c, mod, w, i: dict, source: str, sch) -> list[str]:
        """Numeric columns of the target whose lineage comes from `source` alone: replaying the statement must reproduce
        all of them for this hop to count as reconciled, whatever the other sources did."""
        types = dict(mod.columns(c, i.get("schema") or "", i["table"]))
        cands = [k for k, t in types.items() if t.startswith(postgres.NUMERIC) and k not in i["filters"]][:25]
        return [k for k in cands if {t for t, _ in sql_lineage.leaf_columns(w, k, sch, i["filters"])} == {source}][:8]

    def numeric_first(self, c, mod, r, scols: list[str]) -> list[str]:
        """Numeric columns carry the traced value; non-numeric ones only matter if nothing else is left."""
        types = dict(mod.columns(c, r[0], r[1]))
        return [x for x in scols if types.get(x, "").startswith(postgres.NUMERIC)] or scols[:6]

    def carry_keys(self, w, keycols: list, source: str) -> list:
        """Report-mode key columns that pass straight through the statement from `source`."""
        out = []
        for col in keycols:
            if col in w.out_cols and sql_lineage.is_passthrough(w, col):
                lv = sql_lineage.leaf_columns(w, col)
                if len(lv) == 1 and lv[0][0] == source:
                    out.append(lv[0][1])
        return out

    def carry(self, w, filters: dict, source: str) -> dict:
        """Key filters that pass straight through the statement from `source` keep applying upstream."""
        out = {}
        for col, v in filters.items():
            if col in w.out_cols and sql_lineage.is_passthrough(w, col):
                lv = sql_lineage.leaf_columns(w, col, None, filters)
                if len(lv) == 1 and lv[0][0] == source:
                    out[lv[0][1]] = v
        return out

    def from_foreign(self, i: dict, wr: dict, nid: str) -> int:
        """The traced table itself is a foreign table (e.g. the report source): link straight to the remote table."""
        f = wr["foreign"]
        nxt = {"system": f["database"], "type": "postgresql", "host": f"{f['host']}:{f['port']}", "database": f["database"],
               "schema": f["schema"], "table": f["table"], "value_col": i["value_col"], "columns": [i["value_col"]],
               "filters": i["filters"], "parent": {"table": i["table"], "value_col": i["value_col"]}}
        self.enqueue(nxt, i)
        self.add_node(nxt)
        recon = {"kind": "foreign", "target": ref(i), "stored": i.get("stored"), "filters": i["filters"],
                 "source": ref(nxt), "source_col": "*" if i.get("agg") else i["value_col"]}
        h = self.add_hop(node_id(nxt), nid, "code_derived", [f"{obj(i)}.{i['value_col']}"], [f"{obj(nxt)}.{i['value_col']}"],
                     f"Foreign table {obj(i)} reads {f['schema']}.{f['table']} on {f['database']} through foreign server "
                     f"{f['server']}; no transformation.", obj(i), {"code": wr["ref"], "version": wr["version"]}, recon,
                     [[i["value_col"], i["value_col"], "pass-through", True, "value", None]])
        h["business_rules"] = ["Read as-is through a foreign table; no transformation"]
        return 1

    # ---------------------------------------------------------------- OpenLineage
    def openlineage(self, i: dict) -> list[dict]:
        """OpenLineage jobs already ingested that wrote this table's column: [{job, dataset, field, namespace, run}]."""
        t, col = i["table"], i["value_col"]
        try:
            rows = db.cypher(self.conn, "MATCH (s:Field)-[e:DERIVES]->(t:Field) WHERE e.job_id IS NOT NULL "
                             "AND NOT e.job_id STARTS WITH 'job:hop' RETURN s.uid, t.uid, e.job_id", cols=3)
        except Exception:  # noqa: BLE001
            return []
        out = []
        for s, tg, job in rows:
            ds = tg.removeprefix("field:").rsplit(".", 1)[0]
            if tg.rsplit(".", 1)[1] == col and (ds == t or ds.endswith("." + t)):
                sds, sf = s.removeprefix("field:").rsplit(".", 1)
                ns = db.cypher(self.conn, "MATCH (d:Dataset {uid: $u}) RETURN d.namespace", {"u": f"dataset:{sds}"})
                run = self.conn.execute("SELECT run_id FROM run WHERE job_id = %s ORDER BY ended DESC NULLS LAST LIMIT 1",
                                        (job,)).fetchone()
                out.append({"job": job.removeprefix("job:"), "dataset": sds, "field": sf, "namespace": (ns or [None])[0] or "",
                            "run": run[0] if run else None})
        return out

    def upstream(self, o: dict, i: dict) -> dict:
        """Frontier item for an OpenLineage input dataset. Location comes from its namespace; a sqlite file that exists
        on this host needs no credentials and is registered automatically."""
        parts, ns = o["dataset"].split("."), o["namespace"]
        base = {"value_col": o["field"], "columns": [o["field"]],
                "filters": {k: v for k, v in i["filters"].items() if k != o["field"]},
                "parent": {"table": i["table"], "value_col": i["value_col"]}}
        if ns.startswith("postgres") and len(parts) == 3:
            return {**base, "system": parts[0], "type": "postgresql", "host": urlparse(ns).netloc, "database": parts[0],
                    "schema": parts[1], "table": parts[2]}
        path = ns.split("://", 1)[1] if ns.startswith("sqlite:") else None
        if path and re.match(r"^/[A-Za-z]:", path):
            path = path[1:]
        found = path if path and os.path.isfile(path) else next(
            (f[0] for p in parts[:-1] if p and (f := vault.find_sqlite(self.conn, p))), None)
        if found:
            vault.put(self.conn, os.path.basename(found), "sqlite", None, found, {})
            return {**base, "system": os.path.basename(found), "type": "sqlite", "path": found, "schema": "", "table": parts[-1]}
        return {**base, "system": os.path.basename(path or "") or ".".join(parts[:-1]) or parts[-1], "type": "sqlite",
                "path": path, "schema": "", "table": parts[-1], "unknown": True}

    def from_openlineage(self, i: dict, nid: str, ol: list[dict]) -> int:
        o = ol[0]  # one upstream dataset per attribute is enough for the trace
        nxt = self.upstream(o, i)
        self.enqueue(nxt, i)
        self.add_node(nxt)
        log = f"OpenLineage job {o['job']}" + (f" · run {o['run']}" if o["run"] else "")
        recon = {"kind": "openlineage", "target": ref(i), "stored": i.get("stored"), "filters": i["filters"],
                 "source": ref(nxt), "source_col": o["field"]}
        h = self.add_hop(node_id(nxt), nid, "code_derived", [f"{obj(i)}.{i['value_col']}"], [f"{obj(nxt)}.{o['field']}"],
                     f"Loaded by ETL job {o['job']} from {o['dataset']}.{o['field']} (column lineage reported by OpenLineage).",
                     obj(i), {"log": log, "code": f"OpenLineage job {o['job']}"}, recon,
                     [[o["field"], i["value_col"], "pass-through", True, "value", None]])
        h["business_rules"] = [f"Loaded by ETL job {o['job']}; the transformation is only known from OpenLineage"]
        return 1

    # ---------------------------------------------------------------- resume / finish
    def finish(self) -> None:
        tol = self.ctx["tol"]
        cache: dict = {}

        def connect(r):
            try:
                return self.connect({**r, "step": 0}) if r.get("type") in CON else None
            except Exception:  # noqa: BLE001
                return None

        for h in sorted(self.hops, key=lambda x: -x["n"]):  # upstream hops first
            rc = h.get("recon")
            if not rc or h["status"] == "unresolved":
                continue
            k = rc.get("group") or h["n"]
            if k not in cache:
                cache[k] = reconcile.check(rc, connect, tol)
            h["status"], h["evidence"]["reconciliation"] = cache[k]
            if h["status"] == "proven" and rc.get("full"):
                # several sources feed one statement: if replaying it does not reproduce the traced value, the source
                # whose own load does not reconcile upstream carries the doubt; the others stay proven on their own columns
                fk = ("full", rc["group"].split(":")[0])
                if fk not in cache:
                    cache[fk] = reconcile.check({**rc, "checks": rc["full"]}, connect, tol)
                if cache[fk][0] != "proven" and any(x["status"] != "proven" for x in self.hops if x["to"] == h["from"]):
                    h["status"] = "code_derived"
                    h["evidence"]["reconciliation"] += (" · replaying the statement does not reproduce the traced value "
                                                        "and this source's own load does not reconcile upstream")
        for h in self.hops:  # record on the evidence which hops were read with borrowed credentials
            note = self.s.get("reuse", {}).get(h["from"].split(".")[0])
            if note:
                h["evidence"]["log"] = " · ".join(x for x in (h["evidence"].get("log"), f"{h['from'].split('.')[0]}: {note}") if x)
        self.renumber()
        self.s["pending"] = None
        self.persist_graph()
        self.save("complete")
        audit.append(self.conn, "tracer", "system", "trace complete", self.tid,
                     f"{len(self.hops)} hops · {sum(n['kind'] == 'sor' for n in self.s['nodes'].values())} systems of record")

    def renumber(self) -> None:
        """Number hops source -> report (as POC screen 3): by the depth of the node a hop feeds, longest path from a
        system of record; ties by lane, then name. Steps keep discovery order."""
        into: dict[str, list[str]] = {}
        for h in self.hops:
            into.setdefault(h["to"], []).append(h["from"])
        depth: dict[str, int] = {}

        def d(n: str, seen: tuple = ()) -> int:
            if n not in depth:
                depth[n] = 0 if n in seen or not into.get(n) else 1 + max(d(x, seen + (n,)) for x in into[n])
            return depth[n]

        lane = lambda n: LANES.index(self.s["nodes"].get(n, {}).get("lane", "staging"))  # noqa: E731
        self.hops.sort(key=lambda h: (d(h["to"]), lane(h["to"]), h["to"], h["from"]))
        for n, h in enumerate(self.hops, 1):
            h["n"] = n

    def persist_graph(self) -> None:
        g = LineageGraph()
        for h in self.hops:
            for sc, tc, *_ in h["cols"]:
                s_, t_ = f"table:{h['from']}.{sc}", f"table:{h['to']}.{tc}"
                g.add_node(s_, NodeKind.COLUMN, sc)
                g.add_node(t_, NodeKind.COLUMN, tc)
                g.add_edge(s_, t_)
        try:
            ingest_sql.ingest_graph(self.conn, g, None, None, [])
        except Exception:  # noqa: BLE001 - the explorer repository is a convenience, never fail the trace on it
            pass


def resume(conn, tid: str, req: dict) -> None:
    """Called after a connection was validated and stored: patch unknown systems, then continue the trace."""
    row = conn.execute("SELECT state, status FROM trace WHERE trace_id=%s", (tid,)).fetchone()
    if not row:
        raise NotFound(f"unknown trace {tid}")
    state, status = row
    if status != "connection_required":
        return
    for i in state["queue"][:1]:  # the item the user is answering
        if i.get("unknown"):
            i.update(type=req["type"], host=req.get("host"), database=req.get("database"), path=req.get("path"), unknown=False)
            if req["type"] == "postgresql":
                i["schema"] = i["schema"] or "public"
            conn.execute("UPDATE trace_step SET data = data || %s WHERE trace_id=%s AND n=%s",
                         (Jsonb({"system_type": req["type"]}), tid, i["step"]))
    conn.execute("UPDATE trace SET state=%s, status='running' WHERE trace_id=%s", (Jsonb(state), tid))
    launch(tid)
