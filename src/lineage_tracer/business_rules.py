"""Deterministic business-rule sentences from the SQL AST (no LLM). Business terms come from the database glossary
(COMMENT ON ... / Superset descriptions) when present, else the column name is used as written."""

from __future__ import annotations

import re
from datetime import date

from sqlglot import exp

from lineage_tracer import sql_lineage as sl

SCALES = {1000: "thousands", 1_000_000: "millions", 1_000_000_000: "billions"}
AGG = {"SUM": "Sum of", "AVG": "Average of", "COUNT": "Count of", "MAX": "Maximum of", "MIN": "Minimum of"}


def short(desc: str | None) -> str | None:
    """Business term of a column comment 'Term: definition' -> 'Term'; None (use the column name) without a colon."""
    if not desc or ":" not in desc:
        return None
    return desc.split(":", 1)[0].strip() or None


def join_and(xs: list[str]) -> str:
    xs = xs[:1] + [x[0].lower() + x[1:] if x[1:2].islower() else x for x in xs[1:]]  # 'Base risk weight' -> 'base risk weight', 'CCF' stays
    return "" if not xs else xs[0] if len(xs) < 2 else ", ".join(xs[:-1]) + " and " + xs[-1]


def _iso(v: str) -> str | None:
    try:
        d = date.fromisoformat(v[:10])
    except ValueError:
        return None
    return f"{d.day}-{d.strftime('%b')}-{d.year}"


class Terms:
    def __init__(self, gloss: dict[str, str] | None = None):
        self.gloss = gloss or {}

    def __call__(self, name: str) -> str:
        return self.gloss.get(name, name)

    def render(self, e: exp.Expression) -> str:
        """Expression text with glossary terms for columns and × / ÷ operators."""
        e = e.transform(lambda n: exp.Identifier(this=self(n.name), quoted=False) if isinstance(n, exp.Column) else n)
        return " ".join(e.sql(dialect="postgres").split()).replace(" * ", " × ").replace(" / ", " ÷ ")


def _case(e: exp.Case, t: Terms) -> str:
    pairs = []
    for i in e.args.get("ifs") or []:
        cond = i.this
        key = cond.expression.sql() if isinstance(cond, exp.EQ) else cond.sql()
        pairs.append(f"{key} → {i.args['true'].sql()}")
    more = " …" if len(pairs) > 4 else ""
    src = next((t(c.name) for c in e.find_all(exp.Column)), "value")
    return f"{src} mapped by lookup: " + ", ".join(pairs[:4]) + more


def column_rule(w: sl.Writer, col: str, filters: dict | None, t: Terms) -> str | None:
    """How one target column is produced, in business words; None for a plain copy."""
    if w.kind in ("update", "merge"):
        return None
    q = sl.composed(w, col, filters)
    if q is None or isinstance(q, exp.Column):
        return None
    rnd = scale = None
    e = q
    if isinstance(e, exp.Round):
        rnd, e = e.args.get("decimals"), e.this
    if isinstance(e, exp.Div) and isinstance(e.expression, exp.Literal) and e.expression.is_number \
            and float(e.expression.name) in SCALES:
        scale, e = float(e.expression.name), e.this
    if isinstance(e, exp.Paren):
        e = e.this
    wrap = []
    while isinstance(e, (exp.Upper, exp.Lower, exp.Trim)):  # cleansing wrappers around one column
        wrap.append({"Upper": "upper-cased", "Lower": "lower-cased", "Trim": "trimmed"}[type(e).__name__])
        e = e.this
    if wrap and isinstance(e, exp.Column):
        return f"{t(col)} = {t(e.name)} cleansed ({', '.join(reversed(wrap))})"
    if isinstance(e, exp.AggFunc):
        base = f"{AGG.get(e.key.upper(), e.key.title() + ' of')} {t.render(e.this) if e.this is not None else 'rows'}"
    elif isinstance(e, exp.Case):
        base = _case(e, t)
    elif isinstance(e, exp.Coalesce):
        base = f"{t.render(e.this)}, defaulting to {t.render(e.expressions[0])} when missing"
    elif isinstance(e, exp.Binary):
        base = f"{t(col)} = {t.render(e)}"
    else:
        base = t.render(e)
    extra = []
    if scale:
        extra.append(f"expressed in {SCALES[scale]} (÷{int(scale):,})")
    if rnd is not None:
        extra.append(f"rounded to {rnd.name} dp")
    return ", ".join([base] + extra)


def _conds(node: exp.Expression) -> list[exp.Expression]:
    return list(node.flatten()) if isinstance(node, exp.And) else [node]


def cond_rule(c: exp.Expression, t: Terms) -> str | None:
    txt = c.sql()
    if re.search(r"intra_?group", txt, re.I):
        neg = isinstance(c, exp.Not) or re.search(r"(=\s*(false|'N'|'no'|0)\b|<>\s*'?(Y|true|1)|is not true|is false)", txt, re.I)
        return "Intragroup counterparties excluded" if neg else "Only intragroup counterparties included"
    lits = [x for x in c.find_all(exp.Literal) if x.is_string and _iso(x.name)]
    if lits and isinstance(c, (exp.EQ, exp.LTE, exp.GTE, exp.LT, exp.GT, exp.Between)):
        return f"Restricted to {_iso(lits[0].name)}" if isinstance(c, exp.EQ) else f"Date condition {t.render(c)}"
    if isinstance(c, exp.Not):
        return f"Excludes rows where {t.render(c.this)}"
    if isinstance(c, exp.Column):
        return f"Only rows where {t(c.name)}"
    if isinstance(c, exp.EQ) and isinstance(c.this, exp.Column) and re.match(r"(rn|rnk|rank|row_?num)\w*$", c.this.name, re.I)             and c.expression.sql() == "1":
        return "Deduplicated: keeps the first-ranked row per key (latest delivery)"
    if isinstance(c, exp.EQ) and isinstance(c.this, exp.Column) and isinstance(c.expression, exp.Literal):
        return f"Only {t(c.this.name)} = {c.expression.sql()}"
    if isinstance(c, exp.EQ) and all(isinstance(x, exp.Column) for x in (c.this, c.expression)):
        return None  # a join key, reported as the lookup
    return f"Filtered to {t.render(c)}"


Item = tuple[str, frozenset]   # (rule text, source tables it involves; empty = the whole statement)


def rule_items(w: sl.Writer, col: str, filters: dict | None, t: Terms, ref_date: str | None, extra_cols: list[str]) -> list[Item]:
    """Business rules of one statement for the traced column, each tagged with the source tables it involves."""
    if w.select is None:
        return []
    cte = {c.alias_or_name for c in w.stmt.find_all(exp.CTE)}
    tabs = {x.alias_or_name: sl._qname(x) for x in w.stmt.find_all(exp.Table) if x.name not in cte}
    one = w.sources[0] if len(w.sources) == 1 else None

    def tables_of(node: exp.Expression) -> frozenset:
        return frozenset(x for x in (tabs.get(c.table, one if not c.table else None) for c in node.find_all(exp.Column)) if x)

    def leaf_tables(c_: str) -> frozenset:
        return frozenset(x for x, _ in sl.leaf_columns(w, c_, None, filters))

    fx_tables = frozenset(x for x in w.sources if re.search(r"rate|fx", x, re.I))
    frm = w.select.args.get("from_") or w.select.args.get("from")
    base = sl._qname(frm.this) if frm is not None and isinstance(frm.this, exp.Table) else None
    out: list[Item] = []
    r = column_rule(w, col, filters, t)
    if r:
        lt = leaf_tables(col) - fx_tables
        looked_up = frozenset(sl._qname(j.this) for j in w.stmt.find_all(exp.Join)
                              if isinstance(j.this, exp.Table) and j.this.name not in cte and j.args.get("on") is not None)
        out.append((r, frozenset({base}) if base in lt else (lt - looked_up) or lt))
    q = sl.composed(w, col, filters)
    names = {c.name for c in q.find_all(exp.Column)} if q is not None else set()
    if any(re.search(r"rate|fx", n, re.I) for n in names):
        ccy = re.search(r"_(usd|eur|gbp|chf|jpy)$", col, re.I)
        dates = [_iso(x.name) for x in w.stmt.find_all(exp.Literal) if x.is_string and _iso(x.name)]
        when = dates[0] if dates else _iso(ref_date or "")
        fxj = next((j for j in w.stmt.find_all(exp.Join) if isinstance(j.this, exp.Table) and re.search(r"rate|fx", j.this.name, re.I)), None)
        rate = next((n for n in names if re.search(r"rate|fx", n, re.I)), "rate")
        keys = " and ".join(sorted({t(c.this.name) for c in _conds(fxj.args["on"]) if isinstance(c, exp.EQ)
                                    and isinstance(c.this, exp.Column)})) if fxj is not None and fxj.args.get("on") is not None else ""
        out.append((f"Converted to {ccy.group(1).upper() if ccy else 'the reporting currency'}"
                    + (f" at the {when} FX rate" if when else " using the FX rate")
                    + (f" ({rate} matched on {keys})" if keys else ""), fx_tables))
    for j in w.stmt.find_all(exp.Join):
        tb = j.this if isinstance(j.this, exp.Table) else None
        if tb is None or j.args.get("on") is None or re.search(r"rate|fx", tb.name, re.I):
            continue
        if tb.name in cte:  # join to a CTE: a lookup from the table(s) the CTE reads
            body = next(c for c in w.stmt.find_all(exp.CTE) if c.alias_or_name == tb.name)
            inner = [sl._qname(x) for x in body.find_all(exp.Table) if x.name not in cte]
            if not inner:
                continue
            qn, tb_name, ref = frozenset(inner), inner[0].split(".")[-1], tb.alias_or_name
        else:
            qn, tb_name, ref = sl._qname(tb), tb.name, tabs.get(tb.alias_or_name)
        qs = qn if isinstance(qn, frozenset) else frozenset({qn})
        on = [c for c in _conds(j.args["on"]) if not _iso_cond(c)]
        keys = " and ".join(re.sub(r"_key$", "", c.this.name)
                            if isinstance(c.this, exp.Column) and isinstance(c.expression, exp.Column)
                            and c.this.name == c.expression.name else t.render(c) for c in on if isinstance(c, exp.EQ))
        keycols = {c.name for k in on for c in k.find_all(exp.Column)}
        used = list(dict.fromkeys(t(c.name) for c in w.stmt.find_all(exp.Column)  # used for values, not as join/filter keys
                                  if (c.table == ref if tb.name in cte else tabs.get(c.table) == qn) and not c.find_ancestor(exp.Join, exp.Where)
                                  and c.name not in keycols and not re.search(r"_(key|id|sk)$", c.name)))
        what = join_and(used[:3])
        out.append((f"{what} looked up from {tb_name} by {keys}" if what and keys else
                    f"Looks up {tb_name} (matched on {keys})" if keys else f"Joined to {tb_name}", qs))
        out += [(cond_rule(c, t), qs) for c in _conds(j.args["on"]) if _iso_cond(c)]
    for wh in w.stmt.find_all(exp.Where):
        out += [(x, tables_of(c)) for c in _conds(wh.this) if (x := cond_rule(c, t))]
    for g in w.stmt.find_all(exp.Group):
        names_ = [sl._group_name(w, x) if isinstance(x, exp.Literal) else t(x.name) if isinstance(x, exp.Column) else x.sql()
                  for x in g.expressions]
        if names_:
            out.append(("Summed by " + " and ".join(t(n) for n in names_), frozenset().union(*(tables_of(x) for x in g.expressions))))
    for c2 in extra_cols:
        if c2 != col:
            r2 = column_rule(w, c2, filters, t)
            if r2 and ("mapped" in r2 or "defaulting" in r2):
                out.append((r2, leaf_tables(c2)))
    for u in w.stmt.find_all(exp.SetOperation):  # also unions inside subqueries
        for b in sl._branches(u):
            uncast = lambda x: x.this if isinstance(x, exp.Cast) else x  # noqa: E731  ('GROUP'::text)
            lits = [uncast(p.this).name for p in b.selects if isinstance(p, exp.Alias) and isinstance(uncast(p.this), exp.Literal)
                    and uncast(p.this).is_string and uncast(p.this).name.upper() in ("ALL", "GROUP", "TOTAL")]
            if lits and any(True for _ in b.find_all(exp.AggFunc)):
                out.append((f"Total row {'/'.join(dict.fromkeys(lits))} = sum of the detail rows", frozenset()))
    seen, uniq = set(), []
    for txt, ts in out:
        if txt and txt not in seen:
            seen.add(txt)
            uniq.append((txt, ts))
    return uniq[:12]


def hop_rules(*a, **k) -> list[str]:
    """All rules of the statement (statement_rules)."""
    return [x for x, _ in rule_items(*a, **k)]


def rules_for(items: list[Item], source: str) -> list[str]:
    """Rules that involve this hop's source table (rules with no table attribution apply to every hop)."""
    return [x for x, ts in items if not ts or source in ts]


def _iso_cond(c: exp.Expression) -> bool:
    return any(x.is_string and _iso(x.name) for x in c.find_all(exp.Literal))


def filter_edge_rule(w: sl.Writer, src_col: str, t: Terms) -> str:
    """Why a column that only filters/joins matters."""
    if w.select is not None:
        for wh in w.stmt.find_all(exp.Where):
            for c in _conds(wh.this):
                if src_col in {x.name for x in c.find_all(exp.Column)}:
                    r = cond_rule(c, t)
                    if r:
                        return r
        for g in w.stmt.find_all(exp.Group):
            if any(src_col == x.name for x in g.find_all(exp.Column)):
                return f"Grouping key: {t(src_col)}"
    return f"{t(src_col)} used to match rows to the lookup"
