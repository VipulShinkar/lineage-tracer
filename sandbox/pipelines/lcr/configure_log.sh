#!/bin/bash
# Idempotent: csvlog for the 5432 cluster; restart only if the file changed. Run as root in WSL.
set -e
CONF=/etc/postgresql/18/main/conf.d/lcr_log.conf
NEW=$(mktemp)
cat > "$NEW" <<'EOC'
logging_collector = on
log_destination = 'csvlog'
log_statement = 'mod'
log_filename = 'postgresql-%Y-%m-%d_%H%M%S.log'
log_rotation_age = 1d
log_rotation_size = 20MB
EOC
if ! cmp -s "$NEW" "$CONF" 2>/dev/null; then
  install -m 644 "$NEW" "$CONF"
  pg_ctlcluster 18 main restart
  for i in $(seq 1 30); do pg_isready -q && break; sleep 1; done
fi
rm -f "$NEW"
pg_isready
su postgres -c "psql -Atc \"SELECT current_setting('data_directory')||'/'||current_setting('log_directory')\""
