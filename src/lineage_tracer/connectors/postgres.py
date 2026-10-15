"""Read-only PostgreSQL metadata scanner (the approach of OpenMetadata's postgres lineage / DataHub's sql parsing).
Every session is read-only with a 10 s statement timeout; only catalog queries and SELECTs are ever issued."""

from __future__ import annotations

import hashlib
import re
from datetime import date

import psycopg
from psycopg import sql

from lineage_tracer import vault

SYSTEM = ("pg_catalog", "information_schema", "pg_toast")
NUMERIC = ("numeric", "double", "real", "integer", "bigint", "smallint", "decimal", "money")
TEXTISH = ("text", "character", "varchar", "bpchar", "name")


def connect(host: str, database: str, user: str, password: str) -> psycopg.Connection:
    h, _, port = vault.norm_host(host).partition(":")
    conn = psycopg.connect(host=h, port=int(port), dbname=database, user=user, password=password,
                           connect_timeout=5, autocommit=True)
    conn.execute("SET default_transaction_read_only = on")
    conn.execute("SET statement_timeout = '10s'")
    return conn


def columns(conn, schema: str, table: str) -> list[tuple[str, str]]:
    return conn.execute(
        "SELECT a.attname, format_type(a.atttypid, a.atttypmod) FROM pg_attribute a JOIN pg_class c ON c.oid = a.attrelid "
        "JOIN pg_namespace n ON n.oid = c.relnamespace WHERE n.nspname = %s AND c.relname = %s AND a.attnum > 0 "
        "AND NOT a.attisdropped ORDER BY a.attnum", (schema, table)).fetchall()


def descriptions(conn, schema: str, table: str) -> tuple[str | None, dict[str, str]]:
    """Glossary: COMMENT ON TABLE / COLUMN text -> (table description, {column: description})."""
    q = f'"{schema}"."{table}"'
    t = conn.execute("SELECT obj_description(to_regclass(%s), 'pg_class')", (q,)).fetchone()[0]
    cols = conn.execute("SELECT a.attname, col_description(a.attrelid, a.attnum) FROM pg_attribute a "
                        "WHERE a.attrelid = to_regclass(%s) AND a.attnum > 0 AND NOT a.attisdropped", (q,)).fetchall()
    return t, {n: d for n, d in cols if d}


def entity_type(conn, schema: str, table: str) -> str:
    r = conn.execute("SELECT c.relkind FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
                     "WHERE n.nspname = %s AND c.relname = %s", (schema, table)).fetchone()
    return "view" if r and r[0] in ("v", "m") else "table"


def resolve(conn, name: str, default_schema: str | None = None) -> tuple[str, str] | None:
    """'schema.table' or bare 'table' -> (schema, table) if it exists in this database."""
    if "." in name:
        s, _, t = name.rpartition(".")
        cands = [(s.strip('"'), t.strip('"'))]
    else:
        t = name.strip('"')
        found = conn.execute(
            "SELECT n.nspname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace WHERE c.relname = %s "
            "AND c.relkind IN ('r','v','m','f','p') AND n.nspname <> ALL(%s) ORDER BY (n.nspname = %s) DESC, n.nspname",
            (t, list(SYSTEM), default_schema or "public")).fetchall()
        cands = [(r[0], t) for r in found]
    for s, t in cands:
        if columns(conn, s, t):
            return s, t
    return None


def _pat(schema: str, table: str, pg: bool = False) -> str:
    """Optionally schema-qualified table name. pg=True ends with PostgreSQL's word boundary (\\y), else Python's \\b."""
    return rf"(?:\"?{re.escape(schema)}\"?\.)?\"?{re.escape(table)}\"?" + (r"\y" if pg else r"\b")


def _statements(src: str, schema: str, table: str) -> list[tuple[str, int, int]]:
    """Write statements for the table inside a function body: (text, first line, last line)."""
    clean = re.sub(r"--[^\n]*", lambda m: " " * len(m.group()), src)
    out = []
    for m in re.finditer(rf"\b(?:insert\s+into|merge\s+into|update)\s+(?:only\s+)?{_pat(schema, table)}", clean, re.I):
        depth, i, q = 0, m.start(), None
        while i < len(clean):
            ch = clean[i]
            if q:
                q = None if ch == q else q
            elif ch in "'\"":
                q = ch
            elif ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
            elif ch == ";" and depth <= 0:
                break
            i += 1
        out.append((src[m.start():i].strip(), clean.count("\n", 0, m.start()) + 1, clean.count("\n", 0, i) + 1))
    return out


def _version(text: str) -> str:
    return f"definition sha256 {hashlib.sha256(text.encode()).hexdigest()[:12]}… · captured {date.today().isoformat()}"


def _log(conn, schema: str, table: str, extra: str | None = None) -> str | None:
    """pg_stat_statements evidence (needs the extension and pg_read_all_stats)."""
    rx = rf"(insert\s+into|update|merge\s+into)\s+{_pat(schema, table, True)}" + (rf"|{re.escape(extra)}" if extra else "")
    try:
        r = conn.execute("SELECT query, calls FROM pg_stat_statements WHERE query ~* %s "
                         "AND dbid = (SELECT oid FROM pg_database WHERE datname = current_database()) "
                         "ORDER BY calls DESC LIMIT 1", (rx,)).fetchone()
    except psycopg.Error:
        return None
    return f"pg_stat_statements · {r[1]} call{'s' if r[1] != 1 else ''} · {' '.join(r[0].split())[:110]}" if r else None


def writers(conn, schema: str, table: str) -> list[dict]:
    """What populates schema.table. Strategies in order: foreign table, view/matview, function, query log.
    Each: {kind, sql?, ref, version?, log?, foreign?, dialect}."""
    db = conn.execute("SELECT current_database()").fetchone()[0]
    ft = conn.execute(
        "SELECT s.srvname, s.srvoptions, ft.ftoptions FROM pg_foreign_table ft JOIN pg_class c ON c.oid = ft.ftrelid "
        "JOIN pg_namespace n ON n.oid = c.relnamespace JOIN pg_foreign_server s ON s.oid = ft.ftserver "
        "WHERE n.nspname = %s AND c.relname = %s", (schema, table)).fetchone()
    if ft:
        o = dict(x.split("=", 1) for x in (ft[1] or []) + (ft[2] or []))
        f = {"host": o.get("host", "127.0.0.1"), "port": o.get("port", "5432"), "database": o.get("dbname", db),
             "schema": o.get("schema_name", "public"), "table": o.get("table_name", table), "server": ft[0]}
        return [{"kind": "foreign", "foreign": f, "dialect": "postgres",
                 "ref": f"{db}: foreign table {schema}.{table} via server {ft[0]} → "
                        f"{f['database']}.{f['schema']}.{f['table']} ({f['host']}:{f['port']})",
                 "version": _version(str(sorted(o.items())))}]
    out: list[dict] = []
    purpose = conn.execute("SELECT obj_description(to_regclass(%s), 'pg_class')", (f'"{schema}"."{table}"',)).fetchone()[0]
    v = conn.execute("SELECT definition FROM pg_views WHERE schemaname = %s AND viewname = %s UNION ALL "
                     "SELECT definition FROM pg_matviews WHERE schemaname = %s AND matviewname = %s",
                     (schema, table, schema, table)).fetchone()
    if v:
        return [{"kind": "view", "dialect": "postgres", "sql": f'CREATE VIEW "{schema}"."{table}" AS {v[0].strip().rstrip(";")}',
                 "ref": f"{db}: view {schema}.{table}", "version": _version(v[0]), "log": _log(conn, schema, table),
                 "purpose": purpose}]
    for ns, fn, src, comment in conn.execute(
            "SELECT n.nspname, p.proname, p.prosrc, obj_description(p.oid, 'pg_proc') FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace "
            "WHERE n.nspname <> ALL(%s) AND p.prosrc ~* %s", (list(SYSTEM), rf"(insert\s+into|merge\s+into|update)\s+{_pat(schema, table, True)}")):
        for text, a, b in _statements(src, schema, table):
            out.append({"kind": "function", "dialect": "postgres", "sql": text,
                        "ref": f"{db}: function {ns}.{fn} lines {a}–{b}", "version": _version(src), "purpose": comment,
                        "log": _log(conn, schema, table, f"{fn}(")})
    if out:
        return out
    try:  # ad-hoc loads that only exist in the query log
        for q, calls in conn.execute("SELECT query, calls FROM pg_stat_statements WHERE query ~* %s ORDER BY calls DESC LIMIT 3",
                                     (rf"^\s*(insert\s+into|merge\s+into)\s+{_pat(schema, table, True)}",)):
            out.append({"kind": "log", "dialect": "postgres", "sql": q, "ref": f"{db}: query log entry",
                        "log": f"pg_stat_statements · {calls} calls · {' '.join(q.split())[:110]}", "version": _version(q)})
    except psycopg.Error:
        pass
    return out


def consumers(conn, schema: str, table: str) -> list[str]:
    """Views and functions reading schema.table (names only)."""
    rx = rf"\y{_pat(schema, table, True)}"
    names = [f"{s}.{n}" for s, n in conn.execute(
        "SELECT schemaname, viewname FROM pg_views WHERE definition ~* %s AND schemaname <> ALL(%s) UNION ALL "
        "SELECT schemaname, matviewname FROM pg_matviews WHERE definition ~* %s", (rx, list(SYSTEM), rx))
        if (s, n) != (schema, table)]
    for ns, fn, src in conn.execute("SELECT n.nspname, p.proname, p.prosrc FROM pg_proc p JOIN pg_namespace n "
                                    "ON n.oid = p.pronamespace WHERE n.nspname <> ALL(%s) AND p.prosrc ~* %s",
                                    (list(SYSTEM), rf"(from|join)\s+{_pat(schema, table, True)}")):
        tg = re.findall(r"insert\s+into\s+([\w.\"]+)", src, re.I)
        names += [t.replace('"', "") for t in tg] or [f"function {ns}.{fn}"]
    return list(dict.fromkeys(names))


def where(filters: dict, types: dict) -> tuple[sql.Composable, list]:
    """Equality conditions; date-like columns compare as dates."""
    parts, params = [], []
    for c, v in filters.items():
        t = types.get(c, "")
        parts.append(sql.SQL("{}::date = %s::date").format(sql.Identifier(c)) if t.startswith(("date", "timestamp"))
                     else sql.SQL("{}::text = %s").format(sql.Identifier(c)))
        params.append(v)
    return (sql.SQL(" AND ").join(parts) if parts else sql.SQL("true")), params


def sum_value(conn, schema: str, table: str, col: str, filters: dict) -> float | None:
    types = dict(columns(conn, schema, table))
    w, p = where(filters, types)
    agg = sql.SQL("count(*)") if col == "*" else sql.SQL("sum({})").format(sql.Identifier(col))  # "*" = row count
    q = sql.SQL("SELECT {} FROM {}.{} WHERE {}").format(agg, sql.Identifier(schema), sql.Identifier(table), w)
    r = conn.execute(q, p).fetchone()[0]
    return None if r is None else float(r)


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def locate(conn, schema: str, table: str, keys: dict, value_name: str, value: float, ref_date: str | None,
           tol: float) -> dict:
    """Find which columns of the table hold the report's keys and value.
    -> {filters, value_col, stored, tied, notes}"""
    cols = columns(conn, schema, table)
    types = dict(cols)
    filters: dict[str, str] = {}
    notes: list[str] = []
    nums = [c for c, t in cols if t.startswith(NUMERIC)]
    wide = any(_norm(c) in (_norm(value_name), "c" + _norm(value_name)) for c in nums)
    for kname, kval in {**keys, **({} if wide else {"col": value_name})}.items():  # long format: the column code is a key
        variants = list({_norm(kval), _norm(re.sub(r"^[rc](?=\d)", "", kval.lower()))})
        text_cols = [c for c, t in cols if t.startswith(TEXTISH) and c not in filters]
        text_cols.sort(key=lambda c: (_norm(c) != _norm(kname), _norm(kname) not in _norm(c) and _norm(c) not in _norm(kname)))
        for c in text_cols:
            w, p = where(filters, types)
            q = sql.SQL("SELECT {}::text FROM {}.{} WHERE regexp_replace(lower({}::text), '[^a-z0-9]', '', 'g') = ANY(%s) AND ").format(
                sql.Identifier(c), sql.Identifier(schema), sql.Identifier(table), sql.Identifier(c)) + w + sql.SQL(" LIMIT 1")
            r = conn.execute(q, [variants] + p).fetchone()
            if r:
                filters[c] = r[0]
                break
        else:
            notes.append(f"key {kname}={kval} not found in {schema}.{table}")
    nums = [c for c in nums if c not in filters]
    nums.sort(key=lambda c: _norm(c) not in (_norm(value_name), "c" + _norm(value_name)))
    date_cols = [c for c, t in cols if t.startswith(("date", "timestamp")) and re.search(r"date|as_?of|period|cob", c, re.I)]
    attempts = [{**filters, date_cols[0]: ref_date}] if ref_date and date_cols else []
    attempts.append(filters)
    best = None
    for f in attempts:
        w, p = where(f, types)
        q = sql.SQL("SELECT ") + sql.SQL(", ").join(sql.SQL("sum({})").format(sql.Identifier(c)) for c in nums) + \
            sql.SQL(" FROM {}.{} WHERE ").format(sql.Identifier(schema), sql.Identifier(table)) + w if nums else None
        if q is None:
            break
        sums = conn.execute(q, p).fetchone()
        hit = next(((c, float(s)) for c, s in zip(nums, sums) if s is not None and abs(float(s) - value) <= tol), None)
        if hit:
            return {"filters": f, "value_col": hit[0], "stored": hit[1], "tied": True, "notes": notes}
        best = best or (f, nums[0], float(sums[0]) if sums[0] is not None else None)
    if best is None:
        return {"filters": filters, "value_col": None, "stored": None, "tied": False,
                "notes": notes + [f"no numeric column in {schema}.{table}"]}
    f, c, s = best
    return {"filters": f, "value_col": c, "stored": s, "tied": False,
            "notes": notes + [f"{schema}.{table}.{c} sums to {s} for these keys, report shows {value}"]}
