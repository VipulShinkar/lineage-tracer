"""Bootstraps Superset through its REST API (idempotent): database, datasets and the two table charts.
Usage: .venv\\Scripts\\python sandbox\\superset\\bootstrap.py [http://127.0.0.1:8088]"""
import json
import sys

import httpx

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8088"
DB_NAME = "reporting_db"
DB_URI = "postgresql+psycopg2://lineage_ro:lineage_ro@127.0.0.1:5432/reporting_db"
C90_SQL = ("SELECT consolidation_group AS consolidation_group, risk_class AS risk_class, sensitivity_type AS sensitivity_type, "
           "reported_value_usd AS reported_value_usd FROM rpt.v_corep_c90 "
           "ORDER BY (risk_class = 'ALL'), risk_class, sensitivity_type LIMIT 1000")
C90_COLS = ["consolidation_group", "risk_class", "sensitivity_type", "reported_value_usd"]
C07_COLS = ["row_code", "col_code", "value"]

c = httpx.Client(base_url=BASE, timeout=120)
tok = c.post("/api/v1/security/login", json={"username": "admin", "password": "admin", "provider": "db", "refresh": True}).json()["access_token"]
c.headers["Authorization"] = f"Bearer {tok}"
c.headers["X-CSRFToken"] = c.get("/api/v1/security/csrf_token/").json()["result"]
c.headers["Referer"] = BASE


def find(kind, col, val):
    q = json.dumps({"filters": [{"col": col, "opr": "eq", "value": val}]})
    r = c.get(f"/api/v1/{kind}/", params={"q": q}).json()
    return [x["id"] for x in r.get("result", [])]


def ok(r):
    if r.status_code >= 300:
        raise SystemExit(f"{r.request.method} {r.request.url} -> {r.status_code} {r.text[:500]}")
    return r.json()


# database
ids = find("database", "database_name", DB_NAME)
payload = {"database_name": DB_NAME, "sqlalchemy_uri": DB_URI, "expose_in_sqllab": True}
if ids:
    db_id = ids[0]
    ok(c.put(f"/api/v1/database/{db_id}", json=payload))
else:
    db_id = ok(c.post("/api/v1/database/", json=payload))["id"]

# recreate charts/datasets so reruns converge
for name in ("COREP C90 Report", "C 07.00 Corporates"):
    for i in find("chart", "slice_name", name):
        ok(c.delete(f"/api/v1/chart/{i}"))
for t in ("corep_c90_report", "c0700_facts"):
    for i in find("dataset", "table_name", t):
        ok(c.delete(f"/api/v1/dataset/{i}"))

ds90 = ok(c.post("/api/v1/dataset/", json={"database": db_id, "schema": "rpt", "table_name": "corep_c90_report", "sql": C90_SQL}))["id"]
ds07 = ok(c.post("/api/v1/dataset/", json={"database": db_id, "schema": "rpt", "table_name": "c0700_facts"}))["id"]


def chart(name, ds, cols, filters):
    form = {"datasource": f"{ds}__table", "viz_type": "table", "query_mode": "raw", "all_columns": cols, "row_limit": 1000,
            "adhoc_filters": [{"expressionType": "SIMPLE", "clause": "WHERE", "subject": f["col"], "operator": "==",
                               "comparator": f["val"]} for f in filters], "order_desc": False}
    qc = {"datasource": {"id": ds, "type": "table"}, "force": False, "result_format": "json", "result_type": "full",
          "form_data": form,
          "queries": [{"columns": cols, "metrics": [], "orderby": [], "row_limit": 1000, "filters": filters, "extras": {"having": "", "where": ""},
                       "annotation_layers": [], "series_limit": 0, "order_desc": False, "url_params": {}, "custom_params": {}, "custom_form_data": {}}]}
    return ok(c.post("/api/v1/chart/", json={"slice_name": name, "viz_type": "table", "datasource_id": ds, "datasource_type": "table",
                                              "params": json.dumps(form), "query_context": json.dumps(qc)}))["id"]


ch90 = chart("COREP C90 Report", ds90, C90_COLS, [])
ch07 = chart("C 07.00 Corporates", ds07, C07_COLS, [{"col": "sheet", "op": "==", "val": "Corporates"}])

for name, cid in (("COREP C90 Report", ch90), ("C 07.00 Corporates", ch07)):
    data = ok(c.get(f"/api/v1/chart/{cid}/data/"))["result"][0]["data"]
    print(f"chart {cid} '{name}': {len(data)} rows")
    for r in data[:12]:
        print("   ", r)
print("database", db_id, "datasets", ds90, ds07, "charts", ch90, ch07)
