-- frtb_engine: FRTB sensitivities-based-method engine
CREATE SERVER srv_dwh FOREIGN DATA WRAPPER postgres_fdw OPTIONS (host '127.0.0.1', port '5432', dbname 'dwh');
CREATE USER MAPPING FOR etl_owner  SERVER srv_dwh OPTIONS (user 'etl_owner', password 'etl_owner');
CREATE USER MAPPING FOR lineage_ro SERVER srv_dwh OPTIONS (user 'lineage_ro', password 'lineage_ro');
CREATE SCHEMA fdw_dwh; CREATE SCHEMA etl;
IMPORT FOREIGN SCHEMA public LIMIT TO (dw_sensitivity_usd) FROM SERVER srv_dwh INTO fdw_dwh;

-- supervisory parameter table (maintained by the methodology team; no loader)
CREATE TABLE public.ref_risk_weight (risk_class text, sensitivity_type text, risk_weight numeric(9,6), PRIMARY KEY (risk_class, sensitivity_type));
INSERT INTO public.ref_risk_weight VALUES
 ('COM','DELTA',0.30),('CSR_NS','DELTA',0.50),('EQ','CURVATURE',1.00),('EQ','DELTA',0.25),('EQ','VEGA',0.55),
 ('FX','CURVATURE',1.00),('FX','DELTA',0.15),('FX','VEGA',0.55),('GIRR','DELTA',0.02);

CREATE TABLE public.calc_sbm_charge (
    consolidation_group text, risk_class text, sensitivity_type text,
    sensitivity_usd_total numeric(20,6), risk_weight numeric(9,6), sbm_charge_usd numeric(20,2), as_of_date date);

CREATE PROCEDURE etl.sp_calc_sbm_charge() LANGUAGE plpgsql AS $$
BEGIN
    DELETE FROM public.calc_sbm_charge;
    -- Sum of (USD sensitivity x supervisory risk weight) per group, risk class and sensitivity type
    INSERT INTO public.calc_sbm_charge (
        consolidation_group, risk_class, sensitivity_type,
        sensitivity_usd_total, risk_weight, sbm_charge_usd, as_of_date)
    SELECT
        s.consolidation_group,
        s.risk_class,
        s.sensitivity_type,
        SUM(s.sensitivity_usd)                           AS sensitivity_usd_total,
        w.risk_weight,
        ROUND(SUM(s.sensitivity_usd * w.risk_weight), 2) AS sbm_charge_usd,
        MAX(s.as_of_date)                                AS as_of_date
    FROM fdw_dwh.dw_sensitivity_usd AS s
    JOIN public.ref_risk_weight     AS w
      ON w.risk_class = s.risk_class
     AND w.sensitivity_type = s.sensitivity_type
    GROUP BY s.consolidation_group, s.risk_class, s.sensitivity_type, w.risk_weight;
END $$;
