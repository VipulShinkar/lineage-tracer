import os

import pytest

TEST_DSN = os.environ.get("LINEAGE_TEST_DSN", "host=127.0.0.1 port=5432 user=lineage password=lineage dbname=lineage_test")


@pytest.fixture(scope="session")
def lineage_dsn():
    """Seed the lineage_test database once per session (skips if Postgres is not reachable)."""
    from lineage_store import seed

    try:
        seed.run(TEST_DSN, do_reset=True)
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"lineage_test database unavailable: {exc}")
    os.environ["LINEAGE_DSN"] = TEST_DSN
    return TEST_DSN


@pytest.fixture()
def conn(lineage_dsn):
    from lineage_store import db

    c = db.connect(lineage_dsn)
    yield c
    c.close()
