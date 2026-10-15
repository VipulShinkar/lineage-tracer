-- reporting_db: reporting layer read by Superset. Reads engines through postgres_fdw.
CREATE SERVER srv_sa_engine   FOREIGN DATA WRAPPER postgres_fdw OPTIONS (host '127.0.0.1', port '5432', dbname 'sa_engine');
CREATE SERVER srv_frtb_engine FOREIGN DATA WRAPPER postgres_fdw OPTIONS (host '127.0.0.1', port '5432', dbname 'frtb_engine');
CREATE USER MAPPING FOR etl_owner  SERVER srv_sa_engine   OPTIONS (user 'etl_owner', password 'etl_owner');
CREATE USER MAPPING FOR etl_owner  SERVER srv_frtb_engine OPTIONS (user 'etl_owner', password 'etl_owner');
CREATE USER MAPPING FOR lineage_ro SERVER srv_sa_engine   OPTIONS (user 'lineage_ro', password 'lineage_ro');
CREATE USER MAPPING FOR lineage_ro SERVER srv_frtb_engine OPTIONS (user 'lineage_ro', password 'lineage_ro');
CREATE SCHEMA rpt; CREATE SCHEMA fdw_sa; CREATE SCHEMA fdw_frtb; CREATE SCHEMA etl;
IMPORT FOREIGN SCHEMA public LIMIT TO (calc_sa_exposure) FROM SERVER srv_sa_engine INTO fdw_sa;
IMPORT FOREIGN SCHEMA public LIMIT TO (calc_sbm_charge)  FROM SERVER srv_frtb_engine INTO fdw_frtb;

CREATE TABLE rpt.c0700_facts (template text, sheet text, row_code text, col_code text, value numeric(18,1), unit text DEFAULT 'EUR m', as_of_date date);
CREATE TABLE rpt.c90_facts (consolidation_group text, risk_class text, sensitivity_type text, reported_value_usd numeric(18,2), as_of_date date);

CREATE VIEW rpt.v_corep_c90 AS
SELECT u.consolidation_group, u.risk_class, u.sensitivity_type, u.reported_value_usd
FROM (
    SELECT f.consolidation_group, f.risk_class, f.sensitivity_type, f.reported_value_usd
    FROM rpt.c90_facts AS f
    UNION ALL
    SELECT f.consolidation_group, 'ALL' AS risk_class, 'ALL' AS sensitivity_type, SUM(f.reported_value_usd) AS reported_value_usd
    FROM rpt.c90_facts AS f
    GROUP BY f.consolidation_group
) AS u
ORDER BY u.consolidation_group, (u.risk_class = 'ALL'), u.risk_class, u.sensitivity_type;

CREATE PROCEDURE etl.sp_load_c0700_facts() LANGUAGE plpgsql AS $$
BEGIN
    DELETE FROM rpt.c0700_facts;
    INSERT INTO rpt.c0700_facts (template, sheet, row_code, col_code, value, as_of_date)
    WITH g AS (
        SELECT
            c.exposure_class,
            SUM(c.orig_on_eur)  AS orig_on,
            SUM(c.orig_off_eur) AS orig_off,
            SUM(c.adj_on_eur)   AS adj_on,
            SUM(c.adj_off_eur)  AS adj_off,
            SUM(c.ev_on_eur)    AS ev_on,
            SUM(c.ev_off_eur)   AS ev_off,
            SUM(CASE WHEN c.rating_status = 'RATED' THEN c.ev_on_eur  ELSE 0 END) AS ev_on_rated,
            SUM(CASE WHEN c.rating_status = 'RATED' THEN c.ev_off_eur ELSE 0 END) AS ev_off_rated,
            MAX(c.as_of_date)   AS as_of_date
        FROM fdw_sa.calc_sa_exposure AS c
        GROUP BY c.exposure_class
    )
-- @@FACTS@@
    ;
END $$;

CREATE PROCEDURE etl.sp_load_c90_facts() LANGUAGE plpgsql AS $$
BEGIN
    DELETE FROM rpt.c90_facts;
    INSERT INTO rpt.c90_facts (consolidation_group, risk_class, sensitivity_type, reported_value_usd, as_of_date)
    SELECT
        k.consolidation_group,
        k.risk_class,
        k.sensitivity_type,
        k.sbm_charge_usd AS reported_value_usd,
        k.as_of_date
    FROM fdw_frtb.calc_sbm_charge AS k;
END $$;
