"""Superset REST (as OpenMetadata dashboard/superset/api_source.py and DataHub superset.py): chart -> dataset -> database."""

from __future__ import annotations

import re
from urllib.parse import urlparse

import httpx


def login(url: str, user: str, password: str) -> httpx.Client:
    c = httpx.Client(base_url=url.rstrip("/"), timeout=20)
    r = c.post("/api/v1/security/login", json={"username": user, "password": password, "provider": "db", "refresh": False})
    if r.status_code != 200:
        raise ValueError(f"Superset login failed ({r.status_code})")
    c.headers["Authorization"] = f"Bearer {r.json()['access_token']}"
    return c


def find_chart(c: httpx.Client, title: str) -> dict:
    """First chart whose name contains `title` (exact name preferred)."""
    q = f"(filters:!((col:slice_name,opr:ct,value:'{title.replace(chr(39), '')}')),page_size:50)"
    res = c.get("/api/v1/chart/", params={"q": q}).json().get("result", [])
    if not res:
        raise ValueError(f"no Superset chart matching '{title}'")
    return sorted(res, key=lambda r: r["slice_name"] != title)[0]


def chart_source(c: httpx.Client, chart_id: int) -> dict:
    """-> {chart, dataset, sql?, schema, table, database:{backend, host, port, name}}"""
    ch = c.get(f"/api/v1/chart/{chart_id}").json()["result"]
    ds = c.get(f"/api/v1/dataset/{ch['datasource_id']}").json()["result"]
    db = c.get(f"/api/v1/database/{ds['database']['id']}/connection").json()["result"]  # password masked by Superset
    p = db.get("parameters") or {}
    u = urlparse(re.sub(r"\+\w+://", "://", db.get("sqlalchemy_uri") or ""))
    return {"chart": ch["slice_name"], "chart_id": chart_id, "dataset": ds["table_name"], "sql": ds.get("sql") or None,
            "schema": ds.get("schema"), "table": ds["table_name"],
            "columns": [{"name": x["column_name"], "data_type": x.get("type"), **({"description": x["description"]} if x.get("description") else {})}
                        for x in ds.get("columns", [])], "description": ch.get("description") or ds.get("description"),
            "database": {"backend": db.get("backend") or u.scheme, "host": p.get("host") or u.hostname or "127.0.0.1",
                         "port": p.get("port") or u.port or 5432,
                         "name": p.get("database") or (u.path or "/").lstrip("/") or db.get("database_name")}}


def chart_rows(c: httpx.Client, chart_id: int) -> list[dict]:
    """Re-run the chart with its saved query context."""
    r = c.get(f"/api/v1/chart/{chart_id}/data/")  # runs the query context saved with the chart
    if r.status_code != 200:
        raise ValueError(f"chart data returned {r.status_code}")
    return r.json()["result"][0].get("data", [])


def confirm(rows: list[dict], keys: dict, value: float, tol: float) -> bool:
    """A row that carries every key value and a number equal to the selected data point."""
    for r in rows:
        vals = {str(v).lower() for v in r.values()}
        if all(k.lower() in vals for k in keys.values()) and any(
                isinstance(v, (int, float)) and abs(v - value) <= tol for v in r.values()):
            return True
    return False
