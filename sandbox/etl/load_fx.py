"""FX rates feed ETL: SQLite market_data.db -> staging.public.ref_fx_rates, then emit an OpenLineage RunEvent
(saved under sandbox/openlineage/ and posted to the lineage store via lineage_store.ingest_ol)."""
import json
import sqlite3
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

import psycopg

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from lineage_store import db, ingest_ol  # noqa: E402

SQLITE = ROOT / "sandbox" / "data" / "market_data.db"
STAGING = "host=127.0.0.1 port=5432 user=etl_owner password=etl_owner dbname=staging"
COLS = ["ccy", "rate_date", "rate_to_eur", "rate_to_usd"]


def main() -> None:
    src = sqlite3.connect(SQLITE)
    rows = src.execute("SELECT ccy, rate_date, rate_to_eur, rate_to_usd FROM fx_rates ORDER BY rate_date, ccy").fetchall()
    with psycopg.connect(STAGING) as conn:
        conn.execute("DELETE FROM public.ref_fx_rates")
        with conn.cursor() as cur:
            cur.executemany("INSERT INTO public.ref_fx_rates (ccy, rate_date, rate_to_eur, rate_to_usd) VALUES (%s,%s,%s,%s)", rows)
    ns_in = f"sqlite://{SQLITE.as_posix()}"
    ns_out = "postgres://127.0.0.1:5432"
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    event = {
        "eventType": "COMPLETE", "eventTime": now,
        "producer": "https://sandbox.local/etl/load_fx.py",
        "schemaURL": "https://openlineage.io/spec/1-0-5/OpenLineage.json#/definitions/RunEvent",
        "run": {"runId": str(uuid.uuid5(uuid.NAMESPACE_URL, "sandbox/load_fx/2026-06-30"))},
        "job": {"namespace": "sandbox-etl", "name": "load_fx_rates"},
        "inputs": [{"namespace": ns_in, "name": "fx_rates"}],
        "outputs": [{
            "namespace": ns_out, "name": "staging.public.ref_fx_rates",
            "facets": {"columnLineage": {"fields": {
                c: {"inputFields": [{"namespace": ns_in, "name": "fx_rates", "field": c,
                                  "transformations": [{"type": "DIRECT", "subtype": "IDENTITY", "description": "copied unchanged"}]}]}
                for c in COLS}}},
        }],
    }
    out = ROOT / "sandbox" / "openlineage"
    out.mkdir(exist_ok=True)
    (out / "load_fx_rates.json").write_text(json.dumps(event, indent=2))
    try:
        with db.connect() as lc:
            print("openlineage:", ingest_ol.ingest_event(lc, event))
    except Exception as e:  # lineage store optional for the sandbox itself
        print("WARNING: could not ingest OpenLineage event:", e)
    print(f"loaded {len(rows)} fx rows")


if __name__ == "__main__":
    main()
