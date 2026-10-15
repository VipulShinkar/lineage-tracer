"""Parse an uploaded regulatory report (PDF, XBRL/XML, CSV, XLSX) into the tracer-api.md report shape."""

from __future__ import annotations

import csv
import io
import re
from datetime import datetime
from pathlib import Path

C0700_LABELS = {"0010": "Original exposure", "0040": "Net of value adjustments", "0200": "Exposure value", "0220": "of which rated"}
NUM = re.compile(r"^\(?[-−–]?[\d,]+(\.\d+)?\)?$")


def to_number(s) -> float | None:
    if isinstance(s, (int, float)):
        return float(s)
    s = str(s).strip()
    if not s or not NUM.match(s) or not any(ch.isdigit() for ch in s):
        return None
    neg = s.startswith("(") or s[0] in "-−–"
    v = float(re.sub(r"[^\d.]", "", s))
    return -v if neg else v


def _iso(s: str) -> str | None:
    s = s.strip().rstrip(".,;")
    for f in ("%d %b %Y", "%d %B %Y", "%Y-%m-%d", "%d/%m/%Y", "%d-%b-%Y"):
        try:
            return datetime.strptime(s, f).date().isoformat()
        except ValueError:
            pass
    return None


def _unit(*texts: str) -> str | None:
    t = " ".join(texts)
    if re.search(r"EUR\s*m|€\s*m", t, re.I):
        return "EUR m"
    m = re.search(r"(?<![a-z])(USD|EUR|GBP|CHF|JPY)(?![a-z])(\s*(?:m|mn)\b)?", t, re.I)
    return None if not m else m.group(1).upper() + (" m" if m.group(2) else "")


def _template(*texts: str) -> str | None:
    m = re.search(r"\bC\s?(\d{2})(?:\.(\d{2}))?\b", " ".join(texts))
    return None if not m else f"C {m.group(1)}.{m.group(2)}" if m.group(2) else f"C{m.group(1)}"


def build_table(tid: str, title: str, header: list[str], data: list[list[str]], unit: str | None = None) -> dict:
    """Numeric columns -> value_columns, the rest -> key_columns."""
    is_val = [bool(data) and all(to_number(r[i]) is not None or not str(r[i]).strip() for r in data)
              and any(to_number(r[i]) is not None for r in data) for i in range(len(header))]
    keys = [h for h, v in zip(header, is_val) if not v]
    vals = [h for h, v in zip(header, is_val) if v]
    rows = [{"index": i, "key": {h: str(r[j]).strip() for j, h in enumerate(header) if not is_val[j]},
             "values": {h: to_number(r[j]) for j, h in enumerate(header) if is_val[j]}} for i, r in enumerate(data)]
    t = {"id": tid, "title": title, "key_columns": keys, "value_columns": vals, "rows": rows}
    if unit or _unit(*header):
        t["unit"] = unit or _unit(*header)
    return t


def read_report(name: str, data: bytes) -> dict:
    ext = Path(name).suffix.lower()
    if ext == ".pdf":
        meta, tables = _pdf(data)
    elif ext in (".xbrl", ".xml"):
        meta, tables = _xbrl(data)
    elif ext == ".csv":
        meta, tables = _grid(Path(name).stem, list(csv.reader(io.StringIO(data.decode("utf-8-sig")))))
    elif ext in (".xlsx", ".xlsm"):
        meta, tables = _xlsx(name, data)
    else:
        raise ValueError(f"unsupported report type {ext or name}")
    v = re.search(r"v(\d+)", Path(name).stem, re.I)
    if v and "version" not in meta:
        meta["version"] = f"v{v.group(1)}"
    if not tables:
        raise ValueError("no table found in the report")
    return {"file_name": name, "meta": meta, "tables": tables}


# ---------------------------------------------------------------- PDF
def _lines(page) -> list[list[tuple]]:
    words = sorted(page.get_text("words"), key=lambda w: ((w[1] + w[3]) / 2, w[0]))
    lines: list[list[tuple]] = []
    for w in words:
        if lines and abs((lines[-1][0][1] + lines[-1][0][3]) / 2 - (w[1] + w[3]) / 2) < 3:
            lines[-1].append(w)
        else:
            lines.append([w])
    return [sorted(ln, key=lambda w: w[0]) for ln in lines]


def _cells(line: list[tuple], gap: float = 8.0) -> list[list]:
    """Group words of one line into cells -> [x0, x1, text]."""
    out: list[list] = []
    for w in line:
        if out and w[0] - out[-1][1] < gap:
            out[-1][1], out[-1][2] = w[2], out[-1][2] + " " + w[4]
        else:
            out.append([w[0], w[2], w[4]])
    return out


def _pdf(data: bytes) -> tuple[dict, list[dict]]:
    import pymupdf

    doc = pymupdf.open(stream=data, filetype="pdf")
    lines = [ln for p in doc for ln in _lines(p)]
    text = [" ".join(w[4] for w in ln) for ln in lines]
    numeric = [bool(len(ln) >= 3 and to_number(ln[-1][4]) is not None and ":" not in t) for ln, t in zip(lines, text)]
    first = next((i for i, n in enumerate(numeric) if n), None)
    if first is None or first == 0:
        raise ValueError("no table found in the PDF")
    head, hdr = lines[:first - 1], _cells(lines[first - 1])
    meta = _pdf_meta([" ".join(w[4] for w in ln) for ln in head])
    cols = [(c[0], c[1], c[2]) for c in hdr]
    data_rows = []
    for ln, n in zip(lines[first:], numeric[first:]):
        if not n and len(ln) < 2:
            break
        cells = [""] * len(cols)
        for w in ln:  # nearest header column by overlap, else by centre distance
            cx = (w[0] + w[2]) / 2
            j = min(range(len(cols)), key=lambda k: 0 if cols[k][0] - 4 <= cx <= cols[k][1] + 4
                    else min(abs(cx - cols[k][0]), abs(cx - cols[k][1])))
            cells[j] = (cells[j] + " " + w[4]).strip()
        data_rows.append(cells)
    title = meta.get("title", "Report")
    tid = meta.get("template") or "t1"
    return meta, [build_table(tid, f"{tid} · {title}" if meta.get("template") and tid not in title else title,
                              [c[2] for c in cols], data_rows, _unit(" ".join(text[:first])) or None)]


def _pdf_meta(head: list[str]) -> dict:
    meta: dict = {}
    head = [h.strip() for h in head if h.strip()]
    if head:
        meta["title"] = head[0].rstrip(";, ")
        if "COREP" in head[0].upper():
            meta["return_type"] = "COREP"
        t = _template(head[0])
        if t:
            meta["template"] = t
    for h in head[1:]:
        m = re.match(r"(?i)(date|as at|reference date)\s*:\s*(.+)", h)
        d = re.match(r"(?i)delivered to\s*:\s*(.+)", h)
        if m:
            meta["ref_date"] = _iso(m.group(2)) or m.group(2)
        elif d:
            meta["delivered_to"] = d.group(1).strip()
        elif ":" not in h and "entity" not in meta:
            meta["entity"] = h.rstrip(";, ")
    return meta


# ---------------------------------------------------------------- CSV / XLSX
def _grid(title: str, rows: list[list]) -> tuple[dict, list[dict]]:
    rows = [[("" if c is None else str(c)) for c in r] for r in rows if any(c not in (None, "") for c in r)]
    tid = _template(title) or "t1"
    return {"title": title, **({"template": tid} if tid != "t1" else {})}, [build_table(tid, title, rows[0], rows[1:])]


def _xlsx(name: str, data: bytes) -> tuple[dict, list[dict]]:
    from openpyxl import load_workbook

    wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    meta, tables = {}, []
    for ws in wb.worksheets:
        m, t = _grid(ws.title if len(wb.worksheets) > 1 else Path(name).stem, [list(r) for r in ws.iter_rows(values_only=True)])
        meta = meta or m
        t[0]["id"] = f"t{len(tables) + 1}"
        tables += t
    return meta, tables


# ---------------------------------------------------------------- XBRL instance
def _xbrl(data: bytes) -> tuple[dict, list[dict]]:
    """Contexts (period, entity, dimension members) + numeric facts. The fact's code (r0010c0200 in the concept name,
    or row/col attributes) selects row and column; dimension members become key columns."""
    from lxml import etree

    root = etree.fromstring(data)
    local = lambda e: etree.QName(e).localname  # noqa: E731
    ctx = {}
    for c in root.iter("{*}context"):
        dims = {d.get("dimension").split(":")[-1]: (d.text or "").strip().split(":")[-1]
                for d in c.iter("{*}explicitMember", "{*}typedMember")}
        ent = c.find(".//{*}identifier")
        per = c.find(".//{*}instant")
        ctx[c.get("id")] = (dims, (ent.text or "").strip() if ent is not None else None,
                            (per.text or "").strip() if per is not None else None)
    unit = None
    rows: dict[tuple, dict] = {}
    cols: list[str] = []
    ref_date = entity = None
    for f in root.iter():
        cr = f.get("contextRef")
        v = to_number(f.text) if cr and f.text else None
        if cr is None or v is None or cr not in ctx:
            continue
        dims, ent, per = ctx[cr]
        entity, ref_date = entity or ent, ref_date or per
        dims = dict(dims)
        rd = dims.pop(next((k for k in dims if k.lower() in ("row", "rowcode")), None), None)
        cd = dims.pop(next((k for k in dims if k.lower() in ("column", "col", "columncode")), None), None)
        m = re.search(r"r(\d{4}).*?c(\d{4})", local(f), re.I)
        row = rd or (f"r{m.group(1)}" if m else f.get("row") or f.get("rowCode") or "r0")
        col = (cd or (m.group(2) if m else f.get("col") or f.get("column") or f.get("colCode") or local(f))).lstrip("c")
        unit = unit or (f.get("unitRef") or "").upper().replace("EURO", "EUR") or None
        key = (tuple(dims.values()) or ("",), row)
        rows.setdefault(key, {"dims": dims, "row": row, "values": {}})["values"][col] = v
        if col not in cols:
            cols.append(col)
    if not rows:
        raise ValueError("no numeric facts found in the XBRL instance")
    dim_names = list(next(iter(rows.values()))["dims"]) or ["dimension"]
    out_rows = [{"index": i, "key": {**{n: r["dims"].get(n, "") for n in dim_names}, "row": r["row"]},
                 "values": {c: r["values"].get(c) for c in sorted(cols)}} for i, r in enumerate(rows.values())]
    m = re.search(r"C\s?0?7[._ ]?00", data[:4000].decode("utf-8", "ignore"), re.I)
    tmpl = "C 07.00" if m else None
    title = "C 07.00 · Credit risk SA" if tmpl else "XBRL report"
    meta = {"title": f"COREP {title}" if tmpl else title, "return_type": "COREP", "template": tmpl,
            "entity": entity, "ref_date": ref_date}
    t = {"id": "t1", "title": title, "key_columns": dim_names + ["row"], "value_columns": sorted(cols), "rows": out_rows}
    if tmpl:  # simplified C 07.00 column meanings
        t["column_labels"] = {c: C0700_LABELS[c] for c in cols if c in C0700_LABELS}
    if unit:
        t["unit"] = "EUR m" if unit.startswith("EUR") else unit
    return {k: v for k, v in meta.items() if v}, [t]
