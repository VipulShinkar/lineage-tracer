#!/bin/bash
# Idempotent Apache Superset install in WSL (/opt/superset), SQLite metadata DB, systemd service on :8088.
set -e
export PIP_CACHE_DIR=/opt/superset/pipcache
mkdir -p /opt/superset/home
cd /opt/superset
if [ ! -x venv/bin/python ] || ! venv/bin/python -c "import rich, psycopg2, cachetools, superset; import importlib.metadata as m; assert m.version(\"flask-caching\")==\"2.3.0\"" 2>/dev/null; then
  if ! python3 -m venv venv 2>/dev/null; then
    apt-get update -qq && apt-get install -y -qq python3-venv python3-dev build-essential libpq-dev libssl-dev libffi-dev
    python3 -m venv venv
  fi
  venv/bin/pip install -q --upgrade pip setuptools wheel
  venv/bin/pip install -q apache-superset psycopg2-binary rich cachetools
  venv/bin/pip install -q "flask-caching==2.3.0"   # 2.5 breaks SupersetMetastoreCache (ignore_delete_many_errors)
fi
cat > /opt/superset/home/superset_config.py <<'EOF'
SECRET_KEY = "sandbox-secret-key-0123456789-abcdefghijklmnopqrstuvwxyz"
SQLALCHEMY_DATABASE_URI = "sqlite:////opt/superset/home/superset.db"
WTF_CSRF_ENABLED = True
TALISMAN_ENABLED = False
SQLALCHEMY_ENGINE_OPTIONS = {}
PREVENT_UNSAFE_DB_CONNECTIONS = False
EOF
export SUPERSET_CONFIG_PATH=/opt/superset/home/superset_config.py FLASK_APP=superset
venv/bin/superset db upgrade
venv/bin/superset fab create-admin --username admin --firstname Admin --lastname User --email admin@example.com --password admin || true
venv/bin/superset init
cat > /etc/systemd/system/superset.service <<'EOF'
[Unit]
Description=Apache Superset (sandbox)
After=network.target postgresql.service

[Service]
Environment=SUPERSET_CONFIG_PATH=/opt/superset/home/superset_config.py
Environment=FLASK_APP=superset
WorkingDirectory=/opt/superset
ExecStart=/opt/superset/venv/bin/gunicorn -w 2 --timeout 120 -b 0.0.0.0:8088 "superset.app:create_app()"
Restart=on-failure

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable superset >/dev/null 2>&1
systemctl restart superset
for i in $(seq 1 60); do curl -fs http://127.0.0.1:8088/health >/dev/null && break; sleep 2; done
curl -s http://127.0.0.1:8088/health; echo
