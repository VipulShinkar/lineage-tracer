#!/bin/bash
# Idempotent: second Postgres 18 cluster "finlake" on port 5433 (data on the D:-backed WSL disk), small memory footprint.
set -e
if ! pg_lsclusters -h | awk '{print $2}' | grep -qx finlake; then
  pg_createcluster 18 finlake --port 5433
fi
CONF=/etc/postgresql/18/finlake/conf.d/finlake.conf
mkdir -p /etc/postgresql/18/finlake/conf.d
cat > "$CONF" <<'EOF'
listen_addresses = '*'
port = 5433
shared_buffers = 128MB
max_connections = 30
work_mem = 4MB
maintenance_work_mem = 32MB
shared_preload_libraries = 'pg_stat_statements'
pg_stat_statements.track = 'all'
pg_stat_statements.max = 10000
track_activity_query_size = 8192
password_encryption = 'scram-sha-256'
EOF
HBA=/etc/postgresql/18/finlake/pg_hba.conf
grep -q '^host all all 0.0.0.0/0' "$HBA" || echo 'host all all 0.0.0.0/0 scram-sha-256' >> "$HBA"
systemctl enable postgresql@18-finlake >/dev/null 2>&1 || true
pg_lsclusters -h | grep finlake | grep -q online && pg_ctlcluster 18 finlake restart || pg_ctlcluster 18 finlake start
for i in $(seq 1 30); do pg_isready -q -p 5433 && break; sleep 1; done
# admin superuser used only by the build (same convention as the 5432 cluster)
runuser -u postgres -- psql -p 5433 -qAt <<'EOF'
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='lineage') THEN CREATE ROLE lineage LOGIN SUPERUSER PASSWORD 'lineage'; END IF;
END $$;
EOF
pg_isready -p 5433
