-- sa_engine: standardised-approach calculation engine
CREATE SERVER srv_dwh FOREIGN DATA WRAPPER postgres_fdw OPTIONS (host '127.0.0.1', port '5432', dbname 'dwh');
CREATE USER MAPPING FOR etl_owner  SERVER srv_dwh OPTIONS (user 'etl_owner', password 'etl_owner');
CREATE USER MAPPING FOR lineage_ro SERVER srv_dwh OPTIONS (user 'lineage_ro', password 'lineage_ro');
CREATE SCHEMA fdw_dwh; CREATE SCHEMA etl;
IMPORT FOREIGN SCHEMA public LIMIT TO (mart_sa_exposure, dw_collateral_alloc) FROM SERVER srv_dwh INTO fdw_dwh;

CREATE TABLE public.calc_sa_exposure (
    facility_id text, exposure_class text, rating_status text,
    orig_on_eur numeric(20,2), orig_off_eur numeric(20,2),
    adj_on_eur numeric(20,2), adj_off_eur numeric(20,2),
    crm_eur numeric(20,2), ccf numeric(9,6),
    ev_on_eur numeric(20,2), ev_off_eur numeric(20,2), as_of_date date);

CREATE PROCEDURE etl.sp_calc_sa_exposure() LANGUAGE plpgsql AS $$
BEGIN
    DELETE FROM public.calc_sa_exposure;
    -- exposure value = (balance - value adjustments - eligible collateral) on-balance,
    --                  (limit - value adjustments) x CCF off-balance
    INSERT INTO public.calc_sa_exposure (
        facility_id, exposure_class, rating_status,
        orig_on_eur, orig_off_eur, adj_on_eur, adj_off_eur,
        crm_eur, ccf, ev_on_eur, ev_off_eur, as_of_date)
    SELECT
        m.facility_id,
        m.exposure_class,
        m.rating_status,
        m.on_bal_eur                                                     AS orig_on_eur,
        m.off_bal_eur                                                    AS orig_off_eur,
        ROUND(m.on_bal_eur  * (1 - m.provision_pct), 2)                  AS adj_on_eur,
        ROUND(m.off_bal_eur * (1 - m.provision_pct), 2)                  AS adj_off_eur,
        LEAST(COALESCE(a.crm_eur, 0), ROUND(m.on_bal_eur * (1 - m.provision_pct), 2)) AS crm_eur,
        CASE m.product_code WHEN 'COMMIT' THEN 0.939866 ELSE 1.0 END     AS ccf,
        ROUND(m.on_bal_eur * (1 - m.provision_pct), 2)
            - LEAST(COALESCE(a.crm_eur, 0), ROUND(m.on_bal_eur * (1 - m.provision_pct), 2)) AS ev_on_eur,
        ROUND(m.off_bal_eur * (1 - m.provision_pct)
            * CASE m.product_code WHEN 'COMMIT' THEN 0.939866 ELSE 1.0 END, 2) AS ev_off_eur,
        m.as_of_date
    FROM fdw_dwh.mart_sa_exposure AS m
    LEFT JOIN (
        SELECT c.facility_id, SUM(c.allocated_value_eur) AS crm_eur
        FROM fdw_dwh.dw_collateral_alloc AS c
        GROUP BY c.facility_id
    ) AS a
      ON a.facility_id = m.facility_id;
END $$;
