"""Mini Informatica DTM (normal, non-pushdown mode): python pmrun.py <mapping.xml>

Reads source rows with plain SELECTs, evaluates the mapping (Source Qualifier, Lookup Procedure, Filter, Expression,
Aggregator) in Python, then DELETEs the target and writes it with parameterised INSERT ... VALUES (executemany).
Connections come from connections.xml next to the mapping (SOURCE/TARGET DBDNAME = connection name).
Expression functions implemented: IIF, ROUND, SUM, MAX, ISNULL (+ AND/OR/NOT, =, <>).
"""
import re
import sys
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

import psycopg
from lxml import etree

APP = "pmdtm"


# ------------------------------------------------------------------ expressions
class Agg:
    """SUM/MAX accumulate per call-site while rows stream, then return the totals on the final evaluation."""

    def __init__(self):
        self.acc, self.k, self.final = {}, 0, False

    def _agg(self, op, v):
        k, self.k = self.k, self.k + 1
        if self.final:
            return self.acc.get(k)
        if v is not None:
            self.acc[k] = v if k not in self.acc else op(self.acc[k], v)

    def SUM(self, v):
        return self._agg(lambda a, b: a + b, v)

    def MAX(self, v):
        return self._agg(max, v)


def ROUND(x, n=0):
    return None if x is None else Decimal(x).quantize(Decimal(1).scaleb(-int(n)), ROUND_HALF_UP)


FUNCS = {"IIF": lambda c, a, b: a if c else b, "ROUND": ROUND, "ISNULL": lambda x: x is None}


def compile_expr(text):
    py = text.replace("<>", "!=")
    py = re.sub(r"(?<![<>!=])=(?!=)", "==", py)  # ponytail: no string literals containing =/AND/OR/NOT
    py = re.sub(r"\bAND\b", "and", py, flags=re.I)
    py = re.sub(r"\bOR\b", "or", py, flags=re.I)
    py = re.sub(r"\bNOT\b", "not", py, flags=re.I)
    return compile(py, text, "eval")


def ev(code, env, agg=None):
    ns = dict(FUNCS)
    if agg:
        ns.update(SUM=agg.SUM, MAX=agg.MAX)
    return eval(code, {"__builtins__": {}}, {**ns, **env})  # noqa: S307 - expressions come from the mapping export


# ------------------------------------------------------------------ mapping engine
def run(path):
    path = Path(path)
    root = etree.parse(str(path)).getroot()
    conns = {c.get("NAME"): c for c in etree.parse(str(path.parent / "connections.xml")).getroot()}

    def connect(name):
        c = conns[name]
        return psycopg.connect(host=c.get("HOST"), port=c.get("PORT"), dbname=c.get("DBNAME"), user=c.get("USER"),
                               password=c.get("PASSWORD"), application_name=APP)

    def select(srcname, cols):
        s = root.find(f".//SOURCE[@NAME='{srcname}']")
        with connect(s.get("DBDNAME")) as cn:
            return cn.execute(f"SELECT {', '.join(cols)} FROM {s.get('OWNERNAME')}.{srcname}").fetchall()

    m = root.find(".//MAPPING")
    tx = {t.get("NAME"): t for t in m.findall("TRANSFORMATION")}
    inst = {i.get("NAME"): i for i in m.findall("INSTANCE")}
    cons = [(c.get("FROMINSTANCE"), c.get("FROMFIELD"), c.get("TOINSTANCE"), c.get("TOFIELD")) for c in m.findall("CONNECTOR")]
    out = {}  # instance -> {rid: {field: value}}

    def ports(t):
        return [(f.get("NAME"), f.get("PORTTYPE"), f.get("EXPRESSION"), f.get("EXPRESSIONTYPE")) for f in t.findall("TRANSFORMFIELD")]

    def attr(t, k):
        return next(a.get("VALUE") for a in t.findall("TABLEATTRIBUTE") if a.get("NAME") == k)

    def envs(name):
        """Row-aligned input environments for an instance: rid -> {inputport: value}, skipping rows dropped upstream."""
        ins = [c for c in cons if c[2] == name and inst[c[0]].get("TRANSFORMATION_TYPE") != "Source Definition"]
        rids = set.intersection(*(set(out[c[0]]) for c in ins))
        return {r: {c[3]: out[c[0]][r][c[1]] for c in ins} for r in sorted(rids)}

    order, done = [], set()  # topological order over the non-source instances
    while len(done) < len(inst):
        for n, i in inst.items():
            deps = {c[0] for c in cons if c[2] == n}
            if n not in done and deps <= done:
                done.add(n)
                order.append(n)
    for n in order:
        typ = inst[n].get("TRANSFORMATION_TYPE")
        if typ == "Source Qualifier":
            src = inst[n].find("ASSOCIATED_SOURCE_INSTANCE").get("NAME")
            cols = [p[0] for p in ports(tx[n])]
            out[n] = {i: dict(zip(cols, r)) for i, r in enumerate(select(src, cols))}
        elif typ == "Lookup Procedure":
            t = tx[n]
            lcols = [p[0] for p in ports(t) if p[1] == "LOOKUP/OUTPUT"]
            cond = [tuple(x.strip() for x in c.split("=")) for c in re.split(r"\s+AND\s+", attr(t, "Lookup condition"), flags=re.I)]
            src = attr(t, "Lookup table name")
            index = {}
            for r in select(src, lcols):
                row = dict(zip(lcols, r))
                index.setdefault(tuple(row[c[0]] for c in cond), row)  # "use first value"
            out[n] = {}
            for rid, env in envs(n).items():
                hit = index.get(tuple(env[c[1]] for c in cond), {})
                out[n][rid] = {c: hit.get(c) for c in lcols}
        elif typ == "Filter":
            code = compile_expr(attr(tx[n], "Filter Condition"))
            out[n] = {rid: env for rid, env in envs(n).items() if ev(code, env)}
        elif typ == "Expression":
            outs = [(p[0], compile_expr(p[2])) for p in ports(tx[n]) if "OUTPUT" in p[1]]
            out[n] = {}
            for rid, env in envs(n).items():
                row = dict(env)
                for pn, code in outs:
                    row[pn] = ev(code, row)
                out[n][rid] = row
        elif typ == "Aggregator":
            gb = [p[0] for p in ports(tx[n]) if p[3] == "GROUPBY"]
            aggs = [(p[0], compile_expr(p[2])) for p in ports(tx[n]) if p[1] == "OUTPUT"]
            groups = {}
            for env in envs(n).values():
                key = tuple(env[g] for g in gb)
                a = groups.setdefault(key, [Agg(), env])
                a[0].k = 0
                for _, code in aggs:
                    ev(code, env, a[0])
            out[n] = {}
            for i, (a, env) in enumerate(groups.values()):
                a.final, a.k = True, 0
                row = {g: env[g] for g in gb}
                row.update({pn: ev(code, env, a) for pn, code in aggs})
                out[n][i] = row
        elif typ == "Target Definition":
            tg = root.find(f".//TARGET[@NAME='{n}']")
            cols = [f.get("NAME") for f in tg.findall("TARGETFIELD")]
            rows = [[env[c] for c in cols] for env in envs(n).values()]
            table = f"{tg.get('OWNERNAME')}.{n}"
            with connect(tg.get("DBDNAME")) as cn:
                cn.execute(f"DELETE FROM {table}")
                with cn.cursor() as cur:
                    cur.executemany(f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join(['%s'] * len(cols))})", rows)
            print(f"{path.stem}: {len(rows)} rows -> {tg.get('DBDNAME')}.{table}")


if __name__ == "__main__":
    run(sys.argv[1])
