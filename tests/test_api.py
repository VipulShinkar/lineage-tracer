import pytest
from fastapi.testclient import TestClient

from lineage_store import audit

CELL = "C07.00:Corporates:r0010:c0200"


@pytest.fixture()
def client(lineage_dsn):
    from lineage_api.app import app

    return TestClient(app)


def test_navigation_endpoints(client):
    ctx = client.get("/api/contexts").json()
    assert [s["label"] for s in ctx["submissions"]] == ["v1 · submitted 11-Aug-2026", "v1 · submitted 11-May-2026"]
    assert client.get("/api/templates").json()["pilot_scope"]["total"] == 10
    grid = client.get("/api/templates/C07.00/grid", params={"sheet": "Corporates"}).json()
    assert grid["rows"][1]["cells"][4]["value"] == 35.6
    c = client.get(f"/api/cells/{CELL}").json()
    assert (c["hops"], c["first_hop_systems"], c["transformations"]) == (7, 3, 8)
    assert c["manual_adjustments"] == {"count": 1, "total": -18.3}
    assert c["cell_header"]["value"] == 1240.5 and c["cell_header"]["coverage"] == "partial"
    assert client.get("/api/cells/nope").status_code == 404
    assert "gap:haircut_table" in [x["uid"] for x in client.get("/api/search", params={"q": "haircut"}).json()["results"]]


def test_lineage_hop_transformations_waterfall(client):
    lin = client.get(f"/api/cells/{CELL}/lineage", params={"level": "dataset"}).json()
    assert lin["summary"]["hops"] == 7 and len(lin["lanes"]) == 7
    assert client.get(f"/api/cells/{CELL}/lineage", params={"level": "bogus"}).status_code == 400
    assert client.get(f"/api/cells/{CELL}/hops/3").json()["records"]["out"] == 47960
    tr = client.get(f"/api/cells/{CELL}/transformations").json()
    assert [t["id"] for t in tr["transformations"]] == [f"T{i}" for i in range(1, 9)]
    assert tr["dependency"]["formula"] == "C 03.00 CET1 ratio = C 01.00 CET1 ÷ C 02.00 TREA"
    w = client.get(f"/api/cells/{CELL}/waterfall").json()
    assert w["residual"] == 0.0 and w["steps"][-1]["amount"] == 1240.5
    m = client.get("/api/mappings/mapping:product_to_class", params={"version": "3.2", "compare": "3.1"}).json()
    assert m["differs_in"] == 2
    old = client.get("/api/mappings/mapping:product_to_class", params={"sub": "2026-03-31.v1"}).json()
    assert old["version"] == "3.1"


def test_records_masked_for_supervisor_and_reveal_forbidden(client):
    r = client.get(f"/api/cells/{CELL}/records", params={"compare": "2026-03-31.v1"}, headers={"X-Role": "supervisor"}).json()
    assert r["contributing_records"] == 3418 and r["total"]["compare"] == 1184.3
    assert r["masking"] == {"masked": True, "can_reveal": False}
    assert [t["counterparty"] for t in r["top"]][4] == "CPTY-•••2764"
    assert all("•" in t["counterparty"] and "•" in t["source_key"] for t in r["top"])
    assert client.post("/api/records/REC-000005/reveal", json={"reason": "why"}, headers={"X-Role": "supervisor"}).status_code == 403
    t = client.get("/api/records/REC-000005/trace").json()
    assert t["title"] == "CPTY-•••2764 · term loan · Transport" and "00••••58" in t["steps"][0]["label"]


def test_reveal_for_analyst_is_audited(client, conn):
    before = conn.execute("SELECT count(*) FROM audit_log").fetchone()[0]
    r = client.post("/api/records/REC-000005/reveal", json={"reason": "supervisory request"})
    assert r.status_code == 200 and r.json() == {"counterparty": "CPTY-00012764", "source_key": "LOS-FAC-00123458"}
    assert client.post("/api/records/REC-000005/reveal", json={"reason": " "}).status_code == 422
    row = conn.execute("SELECT action, target, detail FROM audit_log ORDER BY seq DESC LIMIT 1").fetchone()
    assert conn.execute("SELECT count(*) FROM audit_log").fetchone()[0] == before + 1
    assert row == ("revealed an identifier", "REC-000005", "supervisory request")
    assert audit.verify(conn)


def test_unknown_role_rejected(client):
    assert client.get(f"/api/cells/{CELL}/records", headers={"X-Role": "hacker"}).status_code == 400
