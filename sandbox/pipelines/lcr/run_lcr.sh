#!/bin/bash
# Loads the LCR mart: runs the numbered SQL files in order (inside WSL). No procedures.
set -e
cd "$(dirname "$0")"
export PGPASSWORD=etl_owner PGAPPNAME=lcr_shell
for f in 1?_*.sql 2?_*.sql 3?_*.sql; do
  echo "== $f"
  psql -v ON_ERROR_STOP=1 -h 127.0.0.1 -U etl_owner -d lcr_mart -f "$f"
done
