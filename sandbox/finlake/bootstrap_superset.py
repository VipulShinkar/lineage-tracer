"""Superset objects for the EFR lake (idempotent): database fin_lake, virtual dataset, table chart "EFR Credit Risk Summary".
Usage: .venv\\Scripts\\python sandbox\\finlake\\bootstrap_superset.py [http://127.0.0.1:8088]"""
import json
import sys

import httpx

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8088"
DB_NAME, CHART, DATASET = "fin_lake", "EFR Credit Risk Summary", "efr_credit_risk_summary"
DB_URI = "postgresql+psycopg2://lineage_ro:lineage_ro@127.0.0.1:5433/fin_lake"
COLS = ["entity", "risk_type", "portfolio", "exposure_ead", "rwa", "expected_loss", "limit_amount", "utilisation_pct"]
SQL = f"SELECT {', '.join(COLS)} FROM rpt.v_efr_credit_risk_summary"

c = httpx.Client(base_url=BASE, timeout=120)
tok = c.post("/api/v1/security/login", json={"username": "admin", "password": "admin", "provider": "db", "refresh": True}).json()["access_token"]
c.headers.update({"Authorization": f"Bearer {tok}", "Referer": BASE})
c.headers["X-CSRFToken"] = c.get("/api/v1/security/csrf_token/").json()["result"]


def ok(r):
    if r.status_code >= 300:
        raise SystemExit(f"{r.request.method} {r.request.url} -> {r.status_code} {r.text[:500]}")
    return r.json()


def find(kind, col, val):
    q = json.dumps({"filters": [{"col": col, "opr": "eq", "value": val}]})
    return [x["id"] for x in c.get(f"/api/v1/{kind}/", params={"q": q}).json().get("result", [])]


payload = {"database_name": DB_NAME, "sqlalchemy_uri": DB_URI, "expose_in_sqllab": True}
ids = find("database", "database_name", DB_NAME)
if ids:
    db_id = ids[0]
    ok(c.put(f"/api/v1/database/{db_id}", json=payload))
else:
    db_id = ok(c.post("/api/v1/database/", json=payload))["id"]
for i in find("chart", "slice_name", CHART):
    ok(c.delete(f"/api/v1/chart/{i}"))
for i in find("dataset", "table_name", DATASET):
    ok(c.delete(f"/api/v1/dataset/{i}"))
ds = ok(c.post("/api/v1/dataset/", json={"database": db_id, "schema": "rpt", "table_name": DATASET, "sql": SQL}))["id"]
form = {"datasource": f"{ds}__table", "viz_type": "table", "query_mode": "raw", "all_columns": COLS, "row_limit": 1000, "adhoc_filters": [], "order_desc": False}
qc = {"datasource": {"id": ds, "type": "table"}, "force": False, "result_format": "json", "result_type": "full", "form_data": form,
      "queries": [{"columns": COLS, "metrics": [], "orderby": [], "row_limit": 1000, "filters": [], "extras": {"having": "", "where": ""},
                   "annotation_layers": [], "series_limit": 0, "order_desc": False, "url_params": {}, "custom_params": {}, "custom_form_data": {}}]}
ch = ok(c.post("/api/v1/chart/", json={"slice_name": CHART, "viz_type": "table", "datasource_id": ds, "datasource_type": "table",
                                        "params": json.dumps(form), "query_context": json.dumps(qc)}))["id"]
data = ok(c.get(f"/api/v1/chart/{ch}/data/"))["result"][0]["data"]
print(f"chart {ch} '{CHART}': {len(data)} rows")
for r in data:
    if r["entity"] == "ENT-UK" and r["portfolio"] == "Corporates" or r["entity"] == "GROUP":
        print("   ", r)
print("database", db_id, "dataset", ds, "chart", ch)
