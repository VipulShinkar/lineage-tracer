-- Lineage Tracer state. Idempotent.
CREATE TABLE IF NOT EXISTS tracer_report (
  report_id text PRIMARY KEY, file_name text NOT NULL, payload json NOT NULL, created_at timestamptz DEFAULT now());
CREATE TABLE IF NOT EXISTS trace (
  trace_id text PRIMARY KEY, report_id text NOT NULL, label text, status text NOT NULL, error text,
  header jsonb, state jsonb NOT NULL, created_at timestamptz DEFAULT now());
CREATE TABLE IF NOT EXISTS trace_step (trace_id text, n int, data jsonb NOT NULL, PRIMARY KEY (trace_id, n));
CREATE TABLE IF NOT EXISTS trace_hop (trace_id text, n int, data jsonb NOT NULL, PRIMARY KEY (trace_id, n));
CREATE TABLE IF NOT EXISTS vault_credential (
  type text, host text, database text, system text NOT NULL, secret bytea NOT NULL, created_at timestamptz DEFAULT now(),
  PRIMARY KEY (type, host, database));
CREATE TABLE IF NOT EXISTS query_history (
  db_host text, db_port int, dbname text, queryid text, userid text, query text NOT NULL, calls bigint,
  first_seen timestamptz DEFAULT now(), last_seen timestamptz DEFAULT now(),
  PRIMARY KEY (db_host, db_port, dbname, queryid, userid));
