"""Drops/recreates lcr_mart (owner etl_owner), grants lineage_ro read + log access, applies 00_ddl.sql and 01_glossary.sql."""
from pathlib import Path

import psycopg

HERE = Path(__file__).resolve().parent
HOST = "host=127.0.0.1 port=5432"

with psycopg.connect(f"{HOST} user=lineage password=lineage dbname=postgres", autocommit=True) as c:
    c.execute("DROP DATABASE IF EXISTS lcr_mart WITH (FORCE)")
    c.execute("CREATE DATABASE lcr_mart OWNER etl_owner")
    # lineage_ro reads the csvlog through pg_read_file (pg_read_server_files) and lists it with pg_ls_logdir (pg_monitor)
    c.execute("GRANT pg_read_server_files, pg_monitor TO lineage_ro")
    c.execute("REVOKE CONNECT ON DATABASE lcr_mart FROM PUBLIC")
    c.execute("GRANT CONNECT ON DATABASE lcr_mart TO lineage_ro, etl_owner")
with psycopg.connect(f"{HOST} user=lineage password=lineage dbname=lcr_mart", autocommit=True) as c:
    c.execute("CREATE EXTENSION IF NOT EXISTS pg_stat_statements")
    # function ACLs are per database: let lineage_ro call pg_read_file here (read-only file access, no write functions)
    c.execute("GRANT EXECUTE ON FUNCTION pg_read_file(text), pg_read_file(text, bigint, bigint) TO lineage_ro")
with psycopg.connect(f"{HOST} user=etl_owner password=etl_owner dbname=lcr_mart", autocommit=True) as c:
    for f in ("00_ddl.sql", "01_glossary.sql"):
        c.execute((HERE / f).read_text(encoding="utf-8"))
print("lcr_mart created")
