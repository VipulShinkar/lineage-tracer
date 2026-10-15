import argparse

from lineage_store.seed import run

ap = argparse.ArgumentParser(description="Seed the Lineage Explorer database")
ap.add_argument("--reset", action="store_true", help="drop the lineage graph and all tables first")
ap.add_argument("--dsn", help="Postgres DSN (default: $LINEAGE_DSN or the local lineage DB)")
a = ap.parse_args()
print(run(a.dsn, a.reset))
