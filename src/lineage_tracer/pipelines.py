"""Pipeline evidence that lives outside the databases: the code repository (SQL fingerprints), the PostgreSQL server
csvlog (literal statements, time, user, application) and Informatica PowerCenter mapping exports (column lineage with
expressions). Everything is read-only; nothing here needs a connection except `server_log`."""

from __future__ import annotations

import csv
import io
import os
import re
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

import sqlglot
from lxml import etree
from sqlglot import exp

REPO = Path(__file__).resolve().parents[2]
EXTS = (".sql", ".sh", ".py", ".xml")


# ---------------------------------------------------------------------------------------------- fingerprint
_FP = [(re.compile(r"--[^\n]*"), " "), (re.compile(r"/\*.*?\*/", re.S), " "),
       (re.compile(r"\$(\w*)\$.*?\$\1\$", re.S), "?"), (re.compile(r"'(?:[^']|'')*'"), "?"),
       (re.compile(r"\$\d+"), "?"), (re.compile(r"(?<![:\w]):\??[a-z_]\w*", re.I), "?"), (re.compile(r"(?<!:):\?"), "?"),
       (re.compile(r"\b\d+(?:\.\d+)?(?:e[+-]?\d+)?\b", re.I), "?"), (re.compile(r'"'), ""), (re.compile(r"\s+"), " "),
       (re.compile(r"\s*([(),;=<>+*/-])\s*"), r"\1"), (re.compile(r"\?(?:,\?)+"), "?")]


def fingerprint(sql: str) -> str:
    """Lowercase, comments/whitespace stripped, literals and $n parameters -> ?  (so pg_stat_statements text, the
    literal text in the server log and the statement in a .sql file all compare equal)."""
    for rx, rep in _FP:
        sql = rx.sub(rep, sql)
    return sql.strip(" ;").lower()


# ---------------------------------------------------------------------------------------------- code repository
def code_roots() -> list[Path]:
    """LINEAGE_CODE_ROOTS (os.pathsep separated; relative paths are relative to the repository), default sandbox/pipelines."""
    raw = os.environ.get("LINEAGE_CODE_ROOTS") or "sandbox/pipelines"
    return [p if p.is_absolute() else REPO / p for p in (Path(x) for x in raw.split(os.pathsep) if x.strip())]


def files(roots: list[Path] | None = None) -> list[tuple[Path, str]]:
    """[(absolute path, display path 'pipelines/lcr/20_core.sql')] for every indexable file."""
    out = []
    for r in roots or code_roots():
        for p in sorted(r.rglob("*")) if r.is_dir() else []:
            if p.suffix.lower() in EXTS and p.is_file() and "__pycache__" not in p.parts:
                out.append((p, f"{r.name}/{p.relative_to(r).as_posix()}"))
    return out


def split_statements(text: str) -> list[tuple[str, int, int]]:
    """SQL text -> [(statement, first line, last line)]. Respects quotes, comments and $$ bodies; psql meta-commands
    (\\set ...) are blanked. A statement's lines start right after the previous ';' (header comments included)."""
    text = re.sub(r"(?m)^\\.*$", "", text)
    out, i, n, start, q = [], 0, len(text), 0, None
    while i < n:
        c = text[i]
        if q:
            if text.startswith(q, i):
                i += len(q) - 1
                q = None
        elif text.startswith("--", i):
            i = text.find("\n", i) if "\n" in text[i:] else n
            continue
        elif text.startswith("/*", i):
            q = "*/"
            i += 1
        elif c in "'\"":
            q = c
        elif c == "$" and (m := re.match(r"\$\w*\$", text[i:])):
            q = m.group()
            i += len(q) - 1
        elif c == ";":
            _add(out, text, start, i)
            start = i + 1
        i += 1
    _add(out, text, start, n)
    return out


def _add(out: list, text: str, a: int, b: int) -> None:
    body = text[a:b]
    if not re.sub(r"--[^\n]*|/\*.*?\*/", "", body, flags=re.S).strip():
        return
    lead = len(body) - len(body.lstrip())
    first = text.count("\n", 0, a + lead) + 1
    out.append((body.strip(), first, text.count("\n", 0, b) + 1))


# ponytail: embedded SQL in .py/.sh/.xml is found by keyword up to ';' or a closing quote; no real parsing
_EMBED = re.compile(r"\b(?:insert\s+into|merge\s+into|update\s+[\w.\"]+\s+set)\b.*?(?=;|\"\"\"|'''|\Z)", re.I | re.S)
_idx: dict = {"sig": None, "fp": {}}


def index(roots: list[Path] | None = None) -> dict[str, tuple[str, int, int]]:
    """fingerprint -> (display path, first line, last line); cached until a file changes."""
    fl = files(roots)
    sig = tuple((str(p), p.stat().st_mtime_ns) for p, _ in fl)
    if _idx["sig"] == sig:
        return _idx["fp"]
    fp: dict = {}
    for p, disp in fl:
        text = p.read_text(encoding="utf-8", errors="replace")
        if p.suffix.lower() == ".sql":
            stmts = split_statements(text)
        else:
            stmts = [(m.group().strip(), text.count("\n", 0, m.start()) + 1, text.count("\n", 0, m.end()) + 1)
                     for m in _EMBED.finditer(text)]
        for s, a, b in stmts:
            fp.setdefault(fingerprint(s), (disp, a, b))
    _idx["sig"], _idx["fp"] = sig, fp
    return fp


def code_match(sql: str, roots: list[Path] | None = None) -> str | None:
    """'pipelines/lcr/20_core_outflow.sql lines 3–28' for the file holding this statement, else None."""
    hit = index(roots).get(fingerprint(sql))
    return f"{hit[0]} lines {hit[1]}–{hit[2]}" if hit else None


def find_load(job: str, loc: str | None, table: str | None = None, roots: list[Path] | None = None) -> dict | None:
    """Source file of an OpenLineage / Spark job: its sourceCodeLocation path, else a .py/.sql whose name is in the job
    name or whose text quotes the job's application name (first dotted segment). With `table` ('schema.table') the lines
    of the load that writes it: {file, lines:(a,b)|None, text}."""
    fl = [x for x in files(roots) if x[0].suffix.lower() in (".py", ".sql", ".sh", ".scala")]
    base = os.path.basename(urlparse(loc).path) if loc else None
    app = job.split(".")[0].lower()
    cand = [x for x in fl if base and x[0].name == base] or            [x for x in fl if len(x[0].stem) >= 4 and x[0].stem.lower() in job.lower()] or            [x for x in fl if app and len(app) >= 4 and re.search(rf"[\"']{re.escape(app)}[\"']", x[0].read_text("utf-8", "replace"), re.I)]
    if not cand:
        return None
    p, disp = cand[0]
    lines = p.read_text("utf-8", "replace").splitlines()
    if table:
        a = next((k for k, ln in enumerate(lines) if re.search(rf"[\"']{re.escape(table)}[\"']", ln)), None)
        if a is not None:
            b = next((k for k in range(a, min(a + 80, len(lines))) if '""")' in lines[k]), a)
            return {"file": disp, "lines": (a + 1, b + 1), "text": chr(10).join(lines[a:b + 1])}
    return {"file": disp, "lines": None, "text": ""}


def find_job_file(job: str, loc: str | None, table: str | None = None, roots: list[Path] | None = None) -> str | None:
    r = find_load(job, loc, table, roots)
    return r and (f"{r['file']} lines {r['lines'][0]}–{r['lines'][1]}" if r["lines"] else r["file"])


def spark_insert(text: str, schema: str, table: str, schemas: list[str]) -> str | None:
    """The Spark SQL string of a PySpark load region -> 'INSERT INTO schema.table <PostgreSQL select>' so the usual SQL
    column lineage, business rules and replay apply. JDBC-backed temp views are named schema_table (FROM stg_loan)."""
    m = re.search(r'"""(.*?)"""', text, re.S)
    if not m:
        return None
    sch = "|".join(re.escape(x) for x in schemas)
    q = re.sub(rf"(?i)\b(from|join)\s+({sch})_(\w+)", lambda g: f"{g.group(1)} {g.group(2)}.{g.group(3)}", m.group(1))
    # ponytail: Spark SQL is mostly ANSI, so it is used as PostgreSQL text; Spark-only functions fail the parse and
    # the load falls back to the OpenLineage columnLineage facet. Upgrade: sqlglot.transpile(read="spark") per function.
    return f"INSERT INTO {schema}.{table} " + q.strip()


# ---------------------------------------------------------------------------------------------- server csvlog
def _bind(sql: str, detail: str) -> str:
    """Substitute `parameters: $1 = 'x', $2 = NULL` (extended protocol 'execute' entries) into the statement."""
    vals = dict(re.findall(r"\$(\d+) = ('(?:[^']|'')*'|NULL)", detail or ""))
    return re.sub(r"\$(\d+)", lambda m: vals.get(m.group(1), m.group(0)), sql)


def parse_csvlog(text: str) -> list[dict]:
    """Postgres csvlog -> [{time, user, db, app, sql}] for logged statements (log_statement / duration entries)."""
    out = []
    for r in csv.reader(io.StringIO(text)):
        if len(r) < 14:
            continue
        m = re.match(r"(?:duration: [\d.]+ ms\s+)?(statement|execute [^:]*): (.*)", r[13], re.S)
        if not m:
            continue
        sql = m.group(2) if m.group(1) == "statement" else _bind(m.group(2), r[14] if len(r) > 14 else "")
        out.append({"time": r[0], "user": r[1], "db": r[2], "app": r[22] if len(r) > 22 else "", "sql": sql.strip()})
    return out


def fmt_log(e: dict, width: int = 110) -> str:
    """'30-Jun 23:42:07 · app lcr_shell · user etl_owner · INSERT INTO …'"""
    try:
        t = datetime.strptime(e["time"][:19], "%Y-%m-%d %H:%M:%S").strftime("%d-%b %H:%M:%S")
    except ValueError:
        t = e["time"][:19]
    return f"{t} · app {e['app'] or '-'} · user {e['user'] or '-'} · {' '.join(e['sql'].split())[:width]}"


_LOG: dict = {}
_LOGF: dict = {}  # (server, file, size) -> distinct statements of a finished log file
FILES = 8


def server_log(conn, ttl: float = 30) -> list[dict]:
    """Statements from the newest csvlog files of the server, read through pg_read_file (needs superuser or the role
    pg_read_server_files). Not permitted / no csvlog -> []. Cached per server for `ttl` seconds."""
    k = (conn.info.host, conn.info.port)
    if k in _LOG and time.time() - _LOG[k][0] < ttl:
        return _LOG[k][1]
    names: list[str] = []
    sizes: dict[str, int] = {}
    try:
        cur = conn.execute("SELECT pg_read_file('current_logfiles')").fetchone()[0]
        names = [ln.split(" ", 1)[1].strip() for ln in cur.splitlines() if ln.startswith("csvlog ")]
    except Exception:  # noqa: BLE001 - not permitted or logging_collector off
        pass
    try:  # rotated files too (pg_ls_logdir needs pg_monitor / pg_read_server_files)
        ld = conn.execute("SHOW log_directory").fetchone()[0]
        listing = sorted((n, z) for n, z in conn.execute("SELECT name, size FROM pg_ls_logdir()").fetchall() if n.endswith(".csv"))
        sizes = {f"{ld}/{n}": z for n, z in listing}
        names = list(dict.fromkeys([f"{ld}/{n}" for n, _ in listing[-FILES:]] + names))
    except Exception:  # noqa: BLE001
        pass
    ents: list[dict] = []
    for nme in names[-FILES:]:  # oldest -> newest, so a later execution of the same statement wins
        fk = (k, nme, sizes.get(nme))
        if fk not in _LOGF or sizes.get(nme) is None:
            try:  # one entry per distinct statement (a 20 MB log of row inserts collapses to a few dozen)
                latest = {fingerprint(e["sql"]): e for e in parse_csvlog(conn.execute("SELECT pg_read_file(%s)", (nme,)).fetchone()[0])}
            except Exception:  # noqa: BLE001
                continue
            _LOGF[fk] = list(latest.values())
        ents += _LOGF[fk]
    _LOG[k] = (time.time(), ents)
    return ents


# ---------------------------------------------------------------------------------------------- external-pipeline totals
def totals_factor(type_: str | None, subtype: str | None, text: str | None) -> float | None:
    """Factor f such that  sum(target) = f * sum(source)  holds for an identity, a SUM, or a linear scaling
    (x * k, x / k); None when the logic is anything else (so it cannot be reconciled by totals)."""
    sub, t = (subtype or "").upper(), re.sub(r"\s+", "", text or "")
    if (type_ or "").upper() == "INDIRECT":
        return None
    if sub == "IDENTITY":
        return 1.0
    prev = None
    while prev != t:  # peel ROUND(x,n) and SUM(x) wrappers
        prev = t
        t = re.sub(r"^(?:round|sum)\((.*?)(?:,\d+)?\)$", r"\1", t, flags=re.I)
    if re.fullmatch(r"[\w.]+", t):
        return 1.0
    m = re.fullmatch(r"\(?([\w.]+)\)?([*/])\(?(\d+(?:\.\d+)?(?:e\d+)?)\)?", t, re.I) or \
        re.fullmatch(r"(\d+(?:\.\d+)?(?:e\d+)?)(\*)\(?([\w.]+)\)?", t, re.I)
    if m:
        a, op, b = m.groups()
        k = float(b if re.match(r"[\d.]", b) else a)
        return k if op == "*" else 1 / k
    if sub == "AGGREGATION" and not re.search(r"\b(avg|min|max|count|median|stddev)", t, re.I) and not text:
        return 1.0  # Spark reports AGGREGATION without the function; the totals check decides
    return None


# ---------------------------------------------------------------------------------------------- business rules
def rule_text(expr: str | None, kind: str = "value") -> str | None:
    """Plain-English rule for a PowerCenter / lineage expression (IIF -> condition, lookup, aggregation, filter)."""
    e = (expr or "").strip()
    if not e:
        return None
    if m := re.match(r"LOOKUP (\S+) ON (.*)$", e, re.S):
        return f"Looked up from {m.group(1).rsplit('.', 1)[0]} (matched on {m.group(2)})"
    if kind == "filter":
        return f"Used to filter / match / group rows: {e}"
    try:
        t = sqlglot.parse_one(e, read="tsql")
    except Exception:  # noqa: BLE001
        return f"Calculated as {e}"
    parts = [f"If {n.this.sql()} then {n.args['true'].sql()}" + (f" otherwise {n.args['false'].sql()}" if n.args.get("false") else "")
             for n in t.find_all(exp.If)]
    aggs = sorted({type(n).__name__.upper() for n in t.find_all(exp.AggFunc)})
    if aggs:
        parts.append(f"Aggregated ({', '.join(aggs)}) per group")
    return "; ".join(parts) if parts else (None if re.fullmatch(r"[\w.]+", e) else f"Calculated as {e}")


# ---------------------------------------------------------------------------------------------- Informatica
_CONN_KEYS = {"host": ("HOST", "SERVER", "DBHOST", "HOSTNAME"), "port": ("PORT", "DBPORT"),
              "database": ("DBNAME", "DATABASE", "DATABASENAME", "DB")}


def read_connections(folder: Path) -> dict[str, dict]:
    """PowerCenter connection names -> {host, port, database}. Reads connections.xml (CONNECTION elements, attributes or
    ATTRIBUTE children) and parameter files (*.par/*.param/*.ini/*.properties) with lines  name=host:port/db  or
    name=postgresql://host:port/db  (an optional $DBConnection prefix is ignored)."""
    out: dict[str, dict] = {}
    for p in sorted(folder.glob("*")):
        low = p.name.lower()
        try:
            if low == "connections.xml" or (low.endswith(".xml") and "connection" in low):
                root = etree.fromstring(p.read_bytes(), etree.XMLParser(recover=True))
                for el in root.iter("CONNECTION") if root is not None else []:
                    a = {**{k.upper(): v for k, v in el.attrib.items()},
                         **{c.get("NAME", "").upper(): c.get("VALUE", "") for c in el.findall("ATTRIBUTE")}}
                    name = a.get("NAME") or a.get("CONNECTIONNAME")
                    pick = {k: next((a[x] for x in ks if a.get(x)), None) for k, ks in _CONN_KEYS.items()}
                    if name and pick["database"]:
                        out[name] = {"host": pick["host"] or "127.0.0.1", "port": int(pick["port"] or 5432), "database": pick["database"]}
            elif low.endswith((".par", ".param", ".ini", ".properties")):
                for ln in p.read_text("utf-8", "replace").splitlines():
                    m = re.match(r"\s*(?:\$+DBConnection_?)?([\w.-]+)\s*=\s*(?:\w+://)?([\w.-]+)(?::(\d+))?/([\w.-]+)", ln)
                    if m:
                        out[m.group(1)] = {"host": m.group(2), "port": int(m.group(3) or 5432), "database": m.group(4)}
        except (OSError, ValueError, etree.XMLSyntaxError):
            continue
    return out


def resolve_connection(name: str | None, conns: dict[str, dict]) -> dict:
    """Connection name -> {host, port, database}; unknown names are taken to be the database name on the local server."""
    c = conns.get(name or "") or next((v for k, v in conns.items() if k.lower() == (name or "").lower()), None)
    return c or {"host": "127.0.0.1", "port": 5432, "database": name or ""}


_ID = re.compile(r"[A-Za-z_][A-Za-z0-9_$]*")


def _refs(expr: str, ports: dict) -> list[str]:
    body = re.sub(r"'(?:[^']|'')*'", " ", expr or "")
    up = {k.upper(): k for k in ports}
    return list(dict.fromkeys(up[w.upper()] for w in _ID.findall(body) if w.upper() in up))


def _sub(text: str, ref: str, rep: str) -> str:
    rep = rep if re.fullmatch(r"[\w.]+|\w+\(.*\)", rep) else f"({rep})"
    return re.sub(rf"\b{re.escape(ref)}\b", lambda _m: rep, text, flags=re.I)


def parse_mappings(xml_text: str, conns: dict[str, dict]) -> list[dict]:
    """PowerCenter export -> one job per MAPPING: {mapping, tables, edges:[{target:(ds,ns,col), source:(ds,ns,col),
    type DIRECT|INDIRECT, subtype, description, via}]}. `ds` is database.schema.table, `ns` postgres://host:port.
    Source/target tables come from SOURCE/TARGET definitions (OWNERNAME = schema); their connection from the INSTANCE
    DBDNAME, the session CONNECTIONREFERENCE or the definition DBDNAME, resolved through `conns`."""
    root = etree.fromstring(xml_text.encode("utf-8"), etree.XMLParser(recover=True, resolve_entities=False))
    if root is None:
        return []
    defs = {(e.tag, e.get("NAME")): e for e in root.iter("SOURCE", "TARGET")}
    jobs = []
    for m in root.iter("MAPPING"):
        sess = {}
        for s in root.iter("SESSION"):
            if s.get("MAPPINGNAME") == m.get("NAME"):
                for st in s.iter("SESSTRANSFORMATIONINST"):
                    cr = st.find("CONNECTIONREFERENCE")
                    if cr is not None:
                        sess[st.get("SINSTANCENAME")] = cr.get("CONNECTIONNAME")
        ins = {i.get("NAME"): {"type": (i.get("TYPE") or "").upper(), "tname": i.get("TRANSFORMATION_NAME") or i.get("NAME"),
                               "ttype": i.get("TRANSFORMATION_TYPE") or "", "db": i.get("DBDNAME")} for i in m.findall("INSTANCE")}
        trans = {t.get("NAME"): t for t in m.findall("TRANSFORMATION")}
        ports = {n: {f.get("NAME"): f for f in t.findall("TRANSFORMFIELD")} for n, t in trans.items()}
        attr = lambda t, k: next((a.get("VALUE") or "" for a in t.findall("TABLEATTRIBUTE") if (a.get("NAME") or "").lower() == k.lower()), "")  # noqa: E731
        up: dict[tuple, list] = {}
        for c in m.findall("CONNECTOR"):
            up.setdefault((c.get("TOINSTANCE"), c.get("TOFIELD")), []).append((c.get("FROMINSTANCE"), c.get("FROMFIELD")))

        def dataset(inst: str | None, table: str | None = None, conn_name: str | None = None) -> tuple[str, str]:
            i = ins.get(inst) or {}
            kind = "SOURCE" if i.get("type") == "SOURCE" or (table and (("SOURCE", table) in defs)) else "TARGET"
            d = next((x for x in (defs.get((kind, i.get("tname") or table)), defs.get(("SOURCE", table)), defs.get(("TARGET", table))) if x is not None), None)
            tbl = (i.get("tname") if i else None) or table
            schema = (d.get("OWNERNAME") if d is not None and d.get("OWNERNAME") else "public")
            if "." in (table or "") and not i:
                schema, tbl = table.rsplit(".", 1)
            c = resolve_connection(conn_name or sess.get(inst) or i.get("db") or (d.get("DBDNAME") if d is not None else None), conns)
            return f"{c['database']}.{schema}.{tbl}", f"postgres://{c['host']}:{c['port']}"

        memo: dict = {}

        def conds(inst: str) -> list[tuple]:
            """Filter / Joiner / Lookup / Aggregator-group conditions of a transformation: [(text, [(inst, col, kind)...])]"""
            t = trans.get(ins[inst]["tname"])
            if t is None:
                return []
            tt, p, res = ins[inst]["ttype"].lower(), ports[ins[inst]["tname"]], []
            for key in ("Filter Condition", "Join Condition", "Lookup condition"):
                c = attr(t, key)
                if c:
                    srcs = [s for r in _refs(c, p) for s in trace(inst, r)[1]]
                    res.append((c, srcs))
            if tt == "aggregator":
                srcs = [s for f, fe in p.items() if fe.get("EXPRESSIONTYPE") == "GROUPBY" for s in trace(inst, f)[1]]
                res.append(("group by", srcs))
            return res

        def trace(inst: str, fld: str) -> tuple[str, list, list]:
            """-> (inline expression over source columns, [(source inst, column, 'value'|'filter')], [transformation names])"""
            k = (inst, fld)
            if k in memo:
                return memo[k]
            memo[k] = (fld, [], [])  # cycle guard
            i = ins.get(inst) or {}
            if i.get("type") == "SOURCE":
                memo[k] = res = (fld, [(inst, fld, "value")], [])
                return res
            tr, pt = trans.get(i.get("tname")), ports.get(i.get("tname"), {})
            tf = pt.get(fld)
            expr = ((tf.get("EXPRESSION") or "").strip() if tf is not None else "")
            ptype = ((tf.get("PORTTYPE") or "") if tf is not None else "").upper()
            ttype = (i.get("ttype") or "").lower()
            text, srcs, via = fld, [], []
            if "LOOKUP" in ptype and ttype.startswith("lookup") and not up.get(k):
                tbl = attr(tr, "Lookup table name")
                text = f"LOOKUP {tbl}.{fld}"
                srcs, via = [(("lookup", tbl, attr(tr, "Connection Information")), fld, "value")], [inst]
            elif expr and expr.upper() != fld.upper():
                text, via = expr, [inst]
                for r in _refs(expr, {n: 1 for n in pt if n.upper() != fld.upper()}):
                    t2, s2, v2 = trace(inst, r)
                    text, srcs, via = _sub(text, r, t2), srcs + s2, via + v2
            elif up.get(k):
                for fi, ff in up[k]:
                    t2, s2, v2 = trace(fi, ff)
                    text, srcs, via = t2, srcs + s2, via + v2
            for c, cs in conds(inst) if (tr is not None and not (ttype == "aggregator" and "GROUPBY" == (tf.get("EXPRESSIONTYPE") if tf is not None else ""))) else []:
                srcs += [(a, b, "filter") for a, b, _ in cs]
                via += [inst] if cs else []
            memo[k] = res = (text, srcs, list(dict.fromkeys(via)))
            return res

        edges, tables = [], set()
        for tn, inst in ins.items():
            if inst["type"] != "TARGET":
                continue
            tds, tns = dataset(tn)
            tables.add(tds)
            for (to, tofld), froms in up.items():
                if to != tn:
                    continue
                for fi, ff in froms:
                    text, srcs, via = trace(fi, ff)
                    seen: dict = {}
                    for si, sc, kind in srcs:
                        seen[(si if isinstance(si, str) else si, sc)] = seen.get((si, sc)) == "value" and "value" or kind
                    for (si, sc), kind in seen.items():
                        sds, sns = dataset(None, si[1], si[2]) if isinstance(si, tuple) else dataset(si)
                        value = kind == "value"
                        agg = bool(re.search(r"\b(SUM|MAX|MIN|AVG|COUNT)\s*\(", text, re.I))
                        edges.append({"target": (tds, tns, tofld), "source": (sds, sns, sc),
                                      "type": "DIRECT" if value else "INDIRECT",
                                      "subtype": ("IDENTITY" if text == sc else "AGGREGATION" if agg else "TRANSFORMATION") if value else "FILTER",
                                      "description": text if value else "; ".join(c for c, _ in conds(fi) if c) or "filter / join / group by",
                                      "via": ", ".join(via)})
        jobs.append({"mapping": m.get("NAME"), "tables": sorted(tables), "edges": edges})
    return jobs


_MAP: dict = {}


def sync_mappings(conn, roots: list[Path] | None = None) -> dict:
    """Ingest the PowerCenter mapping exports found in the code roots into the lineage graph as pipeline jobs
    (idempotent; files unchanged since the last call are skipped). -> {files, mappings, edges}"""
    from lineage_parser.xml import parse_xml_lineage
    from lineage_store import ingest_ol

    res = {"files": 0, "mappings": 0, "edges": 0}
    for p, disp in files(roots):
        if p.suffix.lower() != ".xml" or "connection" in p.name.lower():
            continue
        folder = p.parent
        sig = (p.stat().st_mtime_ns, tuple((c.name, c.stat().st_mtime_ns) for c in sorted(folder.glob("*")) if c.is_file()))
        if _MAP.get(str(p)) == sig:
            continue
        text = p.read_text(encoding="utf-8", errors="replace")
        if parse_xml_lineage(text).format_detected != "informatica":
            continue
        res["files"] += 1
        for job in parse_mappings(text, read_connections(folder)):
            res["mappings"] += 1
            res["edges"] += ingest_ol.ingest_job(conn, job["mapping"], "informatica", disp, job["edges"])
        _MAP[str(p)] = sig
    return res
