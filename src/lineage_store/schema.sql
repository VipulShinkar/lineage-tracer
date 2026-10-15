-- Lineage Explorer schema: relational facts + AGE graph "lineage". Idempotent.

DO $$
DECLARE l text;
BEGIN
  IF NOT EXISTS (SELECT 1 FROM ag_catalog.ag_graph WHERE name = 'lineage') THEN
    EXECUTE format('SELECT ag_catalog.create_graph(%L)', 'lineage');
  END IF;
  FOREACH l IN ARRAY ARRAY['System','Dataset','Field','Job','Rule','Mapping','Control','Adjustment',
                           'ReportTemplate','ReportCell','Gap','Owner'] LOOP
    IF NOT EXISTS (SELECT 1 FROM ag_catalog.ag_label WHERE name = l AND graph =
                   (SELECT graphid FROM ag_catalog.ag_graph WHERE name = 'lineage')) THEN
      EXECUTE format('SELECT ag_catalog.create_vlabel(%L, %L)', 'lineage', l);
    END IF;
  END LOOP;
  FOREACH l IN ARRAY ARRAY['CONTAINS','READS','WRITES','DERIVES','APPLIES','GUARDED_BY','ADJUSTED_BY',
                           'DEPENDS_ON','OWNED_BY','HAS_GAP'] LOOP
    IF NOT EXISTS (SELECT 1 FROM ag_catalog.ag_label WHERE name = l AND graph =
                   (SELECT graphid FROM ag_catalog.ag_graph WHERE name = 'lineage')) THEN
      EXECUTE format('SELECT ag_catalog.create_elabel(%L, %L)', 'lineage', l);
    END IF;
  END LOOP;
END $$;

-- uid lookups on the graph label tables
DO $$
DECLARE l text;
BEGIN
  FOREACH l IN ARRAY ARRAY['System','Dataset','Field','Job','Rule','Mapping','Control','Adjustment',
                           'ReportTemplate','ReportCell','Gap','Owner','DERIVES','DEPENDS_ON'] LOOP
    EXECUTE format('CREATE INDEX IF NOT EXISTS %I ON lineage.%I USING btree (ag_catalog.agtype_access_operator(properties, ''"uid"''::agtype))',
                   'ix_uid_' || lower(l), l);
  END LOOP;
END $$;

-- reporting context / navigation
CREATE TABLE IF NOT EXISTS submission (
  id text PRIMARY KEY, ref_date date NOT NULL, version text NOT NULL, submitted_on date,
  family text NOT NULL, entity text NOT NULL, basis text NOT NULL, prior_id text);
CREATE TABLE IF NOT EXISTS template (
  id text PRIMARY KEY, code text NOT NULL, name text NOT NULL, short_name text NOT NULL, pos int NOT NULL,
  in_scope boolean NOT NULL, scope_note text, coverage_label text);
CREATE TABLE IF NOT EXISTS col_def (template text, code text, label text, pos int, PRIMARY KEY (template, code));
CREATE TABLE IF NOT EXISTS row_def (template text, code text, label text, bold boolean DEFAULT false, pos int,
  PRIMARY KEY (template, code));
CREATE TABLE IF NOT EXISTS sheet_def (template text, name text, pos int, PRIMARY KEY (template, name));
CREATE TABLE IF NOT EXISTS cell_def (
  cell_id text PRIMARY KEY, template text NOT NULL, sheet text NOT NULL, row_code text NOT NULL, col_code text NOT NULL,
  coverage text NOT NULL, coverage_note text NOT NULL DEFAULT '', dpm_id text, definition text, gap_summary text, dependency_text text,
  unit text NOT NULL DEFAULT 'EUR m');
CREATE TABLE IF NOT EXISTS cell_value (
  cell_id text, submission_id text, value numeric NOT NULL, PRIMARY KEY (cell_id, submission_id));
CREATE TABLE IF NOT EXISTS recent_query (pos int PRIMARY KEY, cell_id text, label text);

-- run-time facts
CREATE TABLE IF NOT EXISTS hop (
  n int PRIMARY KEY, chip text NOT NULL, manual boolean DEFAULT false, from_label text, to_label text,
  mechanism text, frequency text, data_owner text, system_owner text, certified text,
  open_dq text, waterfall_step text, records_note text);
CREATE TABLE IF NOT EXISTS hop_mapping (
  hop int, pos int, source_field text, target_field text, what_happens text, PRIMARY KEY (hop, pos));
CREATE TABLE IF NOT EXISTS run (
  run_id text PRIMARY KEY, hop int NOT NULL, job_id text, submission_id text, cutoff timestamp, started timestamp,
  ended timestamp, rerun boolean DEFAULT false, records_in int, records_out int);
CREATE TABLE IF NOT EXISTS hop_value (
  cell_id text, submission_id text, seq int, step text, rule_uid text, hop int, amount numeric NOT NULL,
  kind text NOT NULL CHECK (kind IN ('source','delta','manual','pass')), PRIMARY KEY (cell_id, submission_id, seq));
CREATE TABLE IF NOT EXISTS control (
  control_id text PRIMARY KEY, seq int, code text, hop int, name text, hop_name text, guards_uid text, also_hop int, also_name text);
CREATE TABLE IF NOT EXISTS control_result (
  control_id text, submission_id text, run_id text, status text NOT NULL CHECK (status IN ('pass','fail','waived')),
  detail text, PRIMARY KEY (control_id, submission_id));
CREATE TABLE IF NOT EXISTS adjustment (
  id text PRIMARY KEY, submission_id text, cell_id text, amount numeric, description text, reason text,
  maker text, maker_at timestamp, checker text, checker_at timestamp, euc text, source text,
  evidence_label text, evidence_url text, approved_on date);
CREATE TABLE IF NOT EXISTS rule_version (
  rule_uid text, version text, effective_from date, effective_to date NOT NULL DEFAULT '9999-12-31', seq int,
  type text, hop_label text, description text, owner text, ref_label text, ref_url text, manual boolean DEFAULT false,
  adjustment_id text, approved_on date, PRIMARY KEY (rule_uid, version));
CREATE TABLE IF NOT EXISTS mapping_version (
  mapping_uid text, version text, effective_from date, effective_to date NOT NULL DEFAULT '9999-12-31', name text,
  PRIMARY KEY (mapping_uid, version));
CREATE TABLE IF NOT EXISTS mapping_row (
  mapping_uid text, version text, code text, label text, target text, pos int, PRIMARY KEY (mapping_uid, version, code));

-- records
CREATE TABLE IF NOT EXISTS record_contribution (
  submission_id text, cell_id text, record_key text, counterparty text, sector text, product text,
  source_system text, source_key text, value numeric NOT NULL, prior_value numeric,
  PRIMARY KEY (submission_id, cell_id, record_key));
CREATE INDEX IF NOT EXISTS ix_record_key ON record_contribution (record_key);
CREATE TABLE IF NOT EXISTS record_trace (
  record_key text, seq int, hop text, label text, sublabel text, amount numeric, ccy text, PRIMARY KEY (record_key, seq));

-- governance
CREATE TABLE IF NOT EXISTS gap (
  uid text PRIMARY KEY, title text, description text, owner text, target_date date, status text DEFAULT 'opened');
CREATE TABLE IF NOT EXISTS certification (pos int, owner text PRIMARY KEY, nodes int, pct int, status text);
CREATE TABLE IF NOT EXISTS lineage_snapshot (
  submission_id text, cell_id text, payload jsonb NOT NULL, hash text NOT NULL, PRIMARY KEY (submission_id, cell_id));
CREATE TABLE IF NOT EXISTS evidence_pack (
  ref text PRIMARY KEY, cell text, format text, file_path text, sha256 text, watermark text, created_by text,
  created_at timestamptz DEFAULT now());
CREATE TABLE IF NOT EXISTS audit_log (
  seq bigserial PRIMARY KEY, ts text NOT NULL, actor text NOT NULL, role text NOT NULL, action text NOT NULL,
  target text NOT NULL, detail text, prev_hash text NOT NULL, hash text NOT NULL);

CREATE OR REPLACE FUNCTION audit_log_readonly() RETURNS trigger AS $$
BEGIN RAISE EXCEPTION 'audit_log is append-only'; END $$ LANGUAGE plpgsql;
DROP TRIGGER IF EXISTS audit_log_no_change ON audit_log;
CREATE TRIGGER audit_log_no_change BEFORE UPDATE OR DELETE ON audit_log
  FOR EACH ROW EXECUTE FUNCTION audit_log_readonly();

CREATE TABLE IF NOT EXISTS setting (key text PRIMARY KEY, value text);
CREATE TABLE IF NOT EXISTS cde_footprint (pos int PRIMARY KEY, field text, cells int);
CREATE SEQUENCE IF NOT EXISTS evidence_pack_seq START 42;

-- snapshots are immutable
CREATE OR REPLACE FUNCTION lineage_snapshot_readonly() RETURNS trigger AS $$
BEGIN RAISE EXCEPTION 'lineage_snapshot is immutable'; END $$ LANGUAGE plpgsql;
DROP TRIGGER IF EXISTS lineage_snapshot_no_change ON lineage_snapshot;
CREATE TRIGGER lineage_snapshot_no_change BEFORE UPDATE OR DELETE ON lineage_snapshot
  FOR EACH ROW EXECUTE FUNCTION lineage_snapshot_readonly();

-- masking helpers + masked views for the (future) read-only agent role
CREATE OR REPLACE FUNCTION mask_cpty(v text) RETURNS text LANGUAGE sql IMMUTABLE AS
$$ SELECT regexp_replace(v, '[^-]*$', '') || '•••' || right(v, 4) $$;
CREATE OR REPLACE FUNCTION mask_key(v text) RETURNS text LANGUAGE sql IMMUTABLE AS
$$ SELECT m[1] || left(m[2], k) || repeat('•', length(m[2]) - k - 2) || right(m[2], 2)
   FROM (SELECT regexp_match(v, '^(.*-)([^-]+)$') AS m) x,
        LATERAL (SELECT GREATEST(length(m[2]) - length(ltrim(m[2], '0')), 1) AS k) y $$;

CREATE OR REPLACE VIEW v_record_contribution_masked AS
  SELECT submission_id, cell_id, record_key, mask_cpty(counterparty) AS counterparty, sector, product,
         source_system, mask_key(source_key) AS source_key, value, prior_value
  FROM record_contribution;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'lineage_agent') THEN
    CREATE ROLE lineage_agent LOGIN PASSWORD 'lineage_agent' NOSUPERUSER NOCREATEDB NOCREATEROLE;
  END IF;
END $$;
ALTER ROLE lineage_agent SET default_transaction_read_only = on;
REVOKE ALL ON ALL TABLES IN SCHEMA public FROM lineage_agent;
GRANT SELECT ON v_record_contribution_masked, submission, template, cell_def, cell_value, hop, hop_mapping, run,
  hop_value, control, control_result, rule_version, mapping_version, mapping_row, gap, adjustment TO lineage_agent;
GRANT USAGE ON SCHEMA ag_catalog, lineage TO lineage_agent;
GRANT SELECT ON ALL TABLES IN SCHEMA ag_catalog, lineage TO lineage_agent;
