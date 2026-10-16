"""Ingest the Spark OpenLineage events (COMPLETE events carry the columnLineage facet) into the lineage DB (5432)."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))
from lineage_store import db, ingest_ol  # noqa: E402

EVENTS = ROOT / "sandbox" / "openlineage" / "spark" / "efr_events.ndjson"


def main() -> int:
    evs = [json.loads(line) for line in EVENTS.read_text().splitlines() if line.strip()]
    done = [e for e in evs if e.get("eventType") == "COMPLETE" and e.get("outputs")]
    with db.connect() as conn:
        res = [ingest_ol.ingest_event(conn, e) for e in done]
    print(f"ingested {len(res)} of {len(evs)} events: {sum(r['nodes_upserted'] for r in res)} nodes, {sum(r['edges_upserted'] for r in res)} edges")
    return 0


if __name__ == "__main__":
    sys.exit(main())
