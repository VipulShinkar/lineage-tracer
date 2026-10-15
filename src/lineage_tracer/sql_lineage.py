"""Column-level lineage + plain-English summary for one writing statement (INSERT..SELECT, CREATE VIEW AS,
UPDATE, MERGE). Table/column resolution reuses sqlglot (as lineage_parser.sql.parser does)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import sqlglot
from sqlglot import exp
from sqlglot.lineage import lineage


@dataclass
class Writer:
    target: str
    kind: str                      # insert | view | update | merge
    stmt: exp.Expression
    select: exp.Expression | None = None   # Select or UNION
    out_cols: list[str] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)   # physical source tables, as written


def _qname(t: exp.Table) -> str:
    return ".".join(p for p in (t.db, t.name) if p)


def parse_writer(sql: str, target_cols: list[str] | None = None, dialect: str = "postgres") -> Writer | None:
    """`target_cols` = catalog column order, used for `INSERT INTO t SELECT ...` without a column list."""
    try:
        stmt = sqlglot.parse_one(sql, dialect=dialect)
    except Exception:  # noqa: BLE001
        return None
    sel = None
    if isinstance(stmt, exp.Create):
        tgt, kind, sel = stmt.this, "view", stmt.expression
    elif isinstance(stmt, exp.Insert):
        tgt, kind, sel = stmt.this, "insert", stmt.expression
    elif isinstance(stmt, exp.Update):
        tgt, kind = stmt.this, "update"
    elif isinstance(stmt, exp.Merge):
        tgt, kind = stmt.this, "merge"
    else:
        return None
    cols: list[str] = []
    if isinstance(tgt, exp.Schema):  # INSERT INTO t (a, b)
        cols, tgt = [c.name for c in tgt.expressions], tgt.this
    if not isinstance(tgt, exp.Table):
        return None
    if sel is not None and not isinstance(sel, (exp.Select, exp.SetOperation)):
        sel = None
    w = Writer(_qname(tgt), kind, stmt, sel)
    cte = {c.alias_or_name for c in stmt.find_all(exp.CTE)}
    w.sources = list(dict.fromkeys(_qname(t) for t in stmt.find_all(exp.Table)
                                   if _qname(t) != w.target and t.name not in cte))
    if sel is not None:
        w.out_cols = sel.named_selects if kind == "view" else (cols or target_cols or sel.named_selects)
    return w


def _with_ctes(w: Writer, s: exp.Select) -> exp.Select:
    cte = w.stmt.args.get("with_") or (w.select.args.get("with_") if w.select is not None else None)
    if cte is not None and not s.args.get("with_"):
        s.set("with_", cte.copy())
    return s


def select_sql(w: Writer) -> str | None:
    """The SELECT with its CTEs, runnable read-only."""
    return _with_ctes(w, w.select.copy()).sql(dialect="postgres") if w.select is not None else None


def _branches(e: exp.Expression) -> list[exp.Expression]:
    return _branches(e.left) + _branches(e.right) if isinstance(e, exp.SetOperation) else [e]


def _eff(w: Writer, filters: dict | None) -> exp.Expression:
    """For a UNION, the branch(es) whose literal columns agree with the data point's filters
    (e.g. col_code = '0200' selects one branch); otherwise the whole select."""
    if not isinstance(w.select, exp.SetOperation) or not filters:
        return w.select
    norm = lambda v: re.sub(r"[^a-z0-9]", "", str(v).lower())  # noqa: E731
    keep = []
    for b in _branches(w.select):
        lit = {p.alias.lower(): norm(p.this.name) for p in b.selects if isinstance(p, exp.Alias) and isinstance(p.this, exp.Literal)}
        if all(norm(v) == lit[c.lower()] for c, v in filters.items() if c.lower() in lit):
            keep.append(b)
    return keep[0] if len(keep) == 1 else w.select


def _proj(w: Writer, col: str, filters: dict | None = None) -> exp.Expression | None:
    sel = _eff(w, filters)
    if sel is None or col not in w.out_cols or len(w.out_cols) != len(sel.selects):
        return None
    p = sel.selects[w.out_cols.index(col)]
    return p.this if isinstance(p, exp.Alias) else p


def leaf_columns(w: Writer, col: str, schema: dict | None = None, filters: dict | None = None) -> list[tuple[str, str]]:
    """[(source table as written, source column)] feeding `col`. `schema` = {db: {table: {col: type}}} lets sqlglot
    resolve unqualified columns."""
    if w.kind in ("update", "merge"):
        tabs = {t.alias_or_name: _qname(t) for t in w.stmt.find_all(exp.Table)}
        one = w.sources[0] if len(w.sources) == 1 else None
        for a in w.stmt.find_all(exp.EQ):
            if isinstance(a.this, exp.Column) and a.this.name == col and isinstance(a.parent, exp.Update):
                return list(dict.fromkeys((tabs.get(c.table, one), c.name) for c in a.expression.find_all(exp.Column)
                                          if tabs.get(c.table, one)))
        return []
    p = _proj(w, col, filters)
    if p is None:
        return []
    eff = _eff(w, filters)
    q = _with_ctes(w, eff.copy())
    name = "__t"
    if isinstance(q, exp.Select):
        q.set("expressions", [exp.alias_(p.copy(), name)])
    else:  # UNION kept whole: lineage by the first branch's output name
        name = q.named_selects[w.out_cols.index(col)]
    try:
        node = lineage(name, q.sql(dialect="postgres"), dialect="postgres", schema=schema)
        out = [(_qname(n.source), n.name.split(".")[-1]) for n in node.walk()
               if isinstance(n.source, exp.Table) and not n.downstream]
    except Exception:  # noqa: BLE001 - naive fallback
        tabs = {t.alias_or_name: _qname(t) for t in eff.find_all(exp.Table)}
        one = w.sources[0] if len(w.sources) == 1 else None
        out = [(tabs.get(c.table, one), c.name) for c in p.find_all(exp.Column) if tabs.get(c.table, one)]
    return list(dict.fromkeys(out))


def is_passthrough(w: Writer, col: str) -> bool:
    p = _proj(w, col)
    while isinstance(p, (exp.Cast, exp.Paren)):
        p = p.this
    return isinstance(p, exp.Column)


_AGG = {"SUM": "Sums", "AVG": "Averages", "COUNT": "Counts", "MAX": "Takes the maximum of", "MIN": "Takes the minimum of"}


def _cond_text(c: exp.Expression) -> str:
    t = c.sql()
    if re.search(r"intra_?group", t, re.I):
        neg = isinstance(c, exp.Not) or re.search(r"(=\s*(false|'N'|'no'|0)\b|<>\s*'?(Y|true|1)|is not true|is false)", t, re.I)
        return "intragroup excluded" if neg else f"restricted to intragroup rows ({t})"
    return f"filtered to {t}"


def _group_name(w: Writer, g: exp.Expression) -> str:
    if isinstance(g, exp.Literal) and g.is_int and 0 < int(g.name) <= len(w.select.selects):
        return w.select.selects[int(g.name) - 1].alias_or_name
    return g.sql()


def filter_columns(w: Writer) -> dict[str, list[str]]:
    """Columns used to join, filter or group rows (JOIN ... ON, WHERE, GROUP BY), per source table: {table as written: [cols]}.
    Unqualified columns are attributed only when the statement has a single source."""
    if w.select is None:
        return {}
    tabs = {t.alias_or_name: _qname(t) for t in w.select.find_all(exp.Table)}
    conds = [j.args["on"] for j in w.select.find_all(exp.Join) if j.args.get("on") is not None]
    conds += [x.this for x in w.select.find_all(exp.Where)]
    conds += [x for g in w.select.find_all(exp.Group) for x in g.expressions]
    out: dict[str, list[str]] = {}
    for cond in conds:
        for c in cond.find_all(exp.Column):
            t = tabs.get(c.table, w.sources[0] if len(w.sources) == 1 and not c.table else None)
            if t in w.sources and c.name not in out.setdefault(t, []):
                out[t].append(c.name)
    return out


def _inline(expr: exp.Expression, sel: exp.Expression, ctes: dict, depth: int = 0) -> exp.Expression:
    """Replace columns that come from a CTE or subquery by that projection's expression (recursively), so the
    transformation reads from physical columns: ROUND(ead / 1000000, 2) over SUM(f.ead_usd) AS ead -> ROUND(SUM(ead_usd) / 1000000, 2)."""
    if depth > 6 or not isinstance(sel, exp.Select):
        return expr
    src: dict[str, exp.Expression] = {}
    for node in [sel.args.get("from_") or sel.args.get("from")] + [j for j in sel.args.get("joins") or []]:
        t = node.this if node is not None else None
        if isinstance(t, exp.Subquery) and isinstance(t.this, exp.Select):
            src[t.alias_or_name] = t.this
        elif isinstance(t, exp.Table):
            src[t.alias_or_name] = ctes.get(t.name)
    for col in list(expr.find_all(exp.Column)):
        for inner in ([src.get(col.table)] if col.table in src else list(src.values())):
            hit = next((x for x in getattr(inner, "selects", []) if x.alias_or_name == col.name), None)                 if isinstance(inner, exp.Select) else None
            if hit is not None:
                new = _inline((hit.this if isinstance(hit, exp.Alias) else hit).copy(), inner, ctes, depth + 1)
                if isinstance(new, exp.Binary) and isinstance(col.parent, exp.Binary):
                    new = exp.paren(new)
                if col is expr:
                    return new
                col.replace(new)
                break
    return expr


def composed(w: Writer, col: str, filters: dict | None = None) -> exp.Expression | None:
    """The column expression composed through CTEs/subqueries, unqualified, without pure type casts."""
    p = _proj(w, col, filters)
    if p is None:
        return None
    ctes = {c.alias_or_name: c.this for c in w.stmt.find_all(exp.CTE)}
    q = _inline(p.copy(), _eff(w, filters), ctes)
    q = q.transform(lambda n: n.this if isinstance(n, exp.Cast) else exp.column(n.name) if isinstance(n, exp.Column) else n)
    for par in list(q.find_all(exp.Paren)):  # parentheses only where a binary operand needs them
        if not (isinstance(par.this, exp.Binary) and isinstance(par.parent, exp.Binary)):
            par.replace(par.this)
    return q


def compact(w: Writer, col: str, filters: dict | None = None) -> str:
    """`drawn_usd + ccf * undrawn_usd`, `ROUND(SUM(ead_usd) / 1000000, 2)`, `pass-through`."""
    if w.kind in ("update", "merge"):
        return w.kind
    q = composed(w, col, filters)
    if q is None:
        return "derived"
    return "pass-through" if isinstance(q, exp.Column) else " ".join(q.sql(dialect="postgres").split())[:160]


def summarize(w: Writer, col: str, filters: dict | None = None) -> str:
    """Plain-English description of how `col` is produced."""
    if w.kind in ("update", "merge"):
        return f"{w.kind.upper()} statement on {w.target} using {', '.join(w.sources) or 'no other table'}."
    p = _proj(w, col, filters)
    if p is None:
        return f"Loaded into {w.target}.{col} by a {w.kind} statement."
    parts: list[str] = []
    agg = next(p.find_all(exp.AggFunc), None)
    if agg is not None:
        grp = _eff(w, filters).args.get("group")
        parts.append(f"{_AGG.get(agg.key.upper(), agg.key.title() + ' of')} {agg.this.sql() if agg.this else '*'}"
                     + (f" grouped by {', '.join(_group_name(w, g) for g in grp.expressions)}" if grp else ""))
    elif isinstance(p, exp.Column):
        parts.append(f"Copied from {p.sql()}")
    else:
        parts.append(f"Calculated as {p.sql()}")
    fx = [c.sql() for c in p.find_all(exp.Column) if re.search(r"rate|fx", c.name, re.I)]
    if fx:
        parts.append(f"converted using FX rate {fx[0]}")
    for case in p.find_all(exp.Case):
        parts.append(f"mapped through a CASE with {len(case.args.get('ifs') or [])} branches")
        break
    eff = _eff(w, filters)
    if isinstance(eff, exp.SetOperation):
        parts.append(f"assembled from {len(_branches(eff))} UNION branches")
    wh = eff.args.get("where")
    if wh is not None:
        conds = list(wh.this.flatten()) if isinstance(wh.this, exp.And) else [wh.this]
        parts += [_cond_text(c) for c in conds]
    return "; ".join(parts) + "."
