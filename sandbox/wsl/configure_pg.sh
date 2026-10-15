#!/bin/bash
# Idempotent: preload pg_stat_statements next to age; restart only when the setting changes.
set -e
CONF=/etc/postgresql/18/main/conf.d/lineage.conf
if ! grep -q pg_stat_statements "$CONF"; then
  sed -i "/^shared_preload_libraries/d;/^pg_stat_statements/d" "$CONF"
  cat >> "$CONF" <<'EOF'
shared_preload_libraries = 'age,pg_stat_statements'
pg_stat_statements.track = 'all'
pg_stat_statements.max = 10000
track_activity_query_size = 8192
EOF
  pg_ctlcluster 18 main restart
  for i in $(seq 1 30); do pg_isready -q && break; sleep 1; done
fi
pg_isready
