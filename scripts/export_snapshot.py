"""Export read-only demo snapshot from the local API into web/public/snapshot/.

Usage: python scripts/export_snapshot.py [api_base]
"""
import json, re, sys
from pathlib import Path
import httpx

API = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000").rstrip("/")
OUT = Path(__file__).resolve().parent.parent / "web" / "public" / "snapshot"
PICKS = [  # (key, predicate on label)
    ("EFR data point", lambda l: "EFR" in l and "whole report" not in l),
    ("EFR whole report", lambda l: "EFR" in l and "whole report" in l),
    ("LCR", lambda l: "LCR" in l),
    ("C90", lambda l: l.startswith("C90")),
    ("C 07.00", lambda l: l.startswith("C 07.00")),
]
BAD_KEY = re.compile(r"password|secret|token|key", re.I)
HOST = re.compile(r"\b(127\.0\.0\.1|localhost)\b")


def scrub(o):
    if isinstance(o, dict):
        # "key" fields such as report key_columns/row key are data, not credentials: only drop credential-like names
        return {k: scrub(v) for k, v in o.items() if not (BAD_KEY.search(k) and k not in ("key", "key_columns"))}
    if isinstance(o, list):
        return [scrub(v) for v in o]
    return HOST.sub("sandbox-host", o) if isinstance(o, str) else o


def main():
    c = httpx.Client(base_url=API, timeout=120, headers={"X-Role": "analyst"})
    traces = c.get("/api/tracer/traces").json()
    (OUT / "packs").mkdir(parents=True, exist_ok=True)
    index = []
    for name, pred in PICKS:
        cand = [t for t in traces if t["status"] == "complete" and pred(t["label"])]
        if not cand:
            sys.exit(f"no complete trace for {name}")
        t = max(cand, key=lambda t: t["created_at"])
        tid = t["trace_id"]
        tr = c.get(f"/api/tracer/traces/{tid}").json()
        li = c.get(f"/api/tracer/traces/{tid}/lineage").json()
        rid = tr.get("report_id") or li.get("report_id")
        files = {"trace": tr, "lineage": li}
        if rid:
            files["report"] = c.get(f"/api/tracer/reports/{rid}").json()
        for k, v in files.items():
            (OUT / f"{tid}.{k}.json").write_text(json.dumps(scrub(v), indent=1), encoding="utf-8")
        p = c.post(f"/api/tracer/traces/{tid}/evidence-pack", json={"format": "pdf"}).json()
        pdf = c.get(p["download_url"] if p["download_url"].startswith("/") else f"/api/evidence-packs/{p['ref']}")
        pdf.raise_for_status()
        (OUT / "packs" / f"{tid}.pdf").write_bytes(pdf.content)
        s = li["summary"]
        index.append({
            "trace_id": tid, "title": s["title"], "label": t["label"], "kind": name,
            "report": t["label"].split(" · ")[0], "captured": t["created_at"][:10],
            "pipeline_types": sorted({h["pipeline_type"] for h in li["hops"] if h.get("pipeline_type")}),
            "hops": s["hops"], "proven": s["proven"], "code_derived": s["code_derived"],
        })
        print(name, tid, t["label"])
    (OUT / "index.json").write_text(json.dumps(scrub(index), indent=1), encoding="utf-8")
    bad = [f.name for f in OUT.glob("*.json") if re.search(r"password|secret|BEGIN .*PRIVATE", f.read_text(encoding="utf-8"), re.I)]
    if bad:
        sys.exit(f"sensitive words found in {bad}; check manually")


if __name__ == "__main__":
    main()
