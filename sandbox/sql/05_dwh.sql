-- dwh: warehouse + data mart. Reads staging through postgres_fdw.
CREATE SERVER srv_staging FOREIGN DATA WRAPPER postgres_fdw OPTIONS (host '127.0.0.1', port '5432', dbname 'staging');
CREATE USER MAPPING FOR etl_owner  SERVER srv_staging OPTIONS (user 'etl_owner', password 'etl_owner');
CREATE USER MAPPING FOR lineage_ro SERVER srv_staging OPTIONS (user 'lineage_ro', password 'lineage_ro');
CREATE SCHEMA fdw_stg; CREATE SCHEMA etl;
IMPORT FOREIGN SCHEMA public LIMIT TO (stg_facilities, stg_collateral, stg_sensitivity, ref_fx_rates) FROM SERVER srv_staging INTO fdw_stg;

CREATE TABLE public.dw_exposure (
    facility_id text, counterparty_id text, counterparty_type text, product_code text, currency char(3),
    fx_rate_to_eur numeric(18,8), drawn_eur numeric(20,2), undrawn_eur numeric(20,2),
    provision_pct numeric(9,6), rating_status text, as_of_date date);
CREATE TABLE public.dw_collateral_alloc (
    collateral_id text, facility_id text, collateral_type text, market_value_eur numeric(20,2),
    haircut_pct numeric(6,4), allocated_value_eur numeric(20,2), as_of_date date);
CREATE TABLE public.mart_sa_exposure (
    facility_id text, exposure_class text, product_code text, rating_status text, provision_pct numeric(9,6),
    on_bal_eur numeric(20,2), off_bal_eur numeric(20,2), as_of_date date);
CREATE TABLE public.dw_sensitivity_usd (
    trade_id text, consolidation_group text, risk_class text, sensitivity_type text, risk_factor text,
    currency char(3), sensitivity_amount numeric(20,4), fx_rate_to_usd numeric(18,8), sensitivity_usd numeric(20,6), as_of_date date);

CREATE PROCEDURE etl.sp_load_exposure() LANGUAGE plpgsql AS $$
BEGIN
    DELETE FROM public.dw_exposure;
    -- Convert to EUR at the 30-Jun-2026 rate; intragroup facilities are excluded
    INSERT INTO public.dw_exposure (
        facility_id, counterparty_id, counterparty_type, product_code, currency,
        fx_rate_to_eur, drawn_eur, undrawn_eur, provision_pct, rating_status, as_of_date)
    SELECT
        f.facility_id,
        f.counterparty_id,
        f.counterparty_type,
        f.product_code,
        f.currency,
        fx.rate_to_eur                              AS fx_rate_to_eur,
        ROUND(f.drawn_balance * fx.rate_to_eur, 2)  AS drawn_eur,
        ROUND(f.undrawn_limit * fx.rate_to_eur, 2)  AS undrawn_eur,
        f.provision_pct,
        f.rating_status,
        f.as_of_date
    FROM fdw_stg.stg_facilities AS f
    JOIN fdw_stg.ref_fx_rates   AS fx
      ON fx.ccy = f.currency
     AND fx.rate_date = DATE '2026-06-30'
    WHERE f.intragroup_flag = FALSE;
END $$;

CREATE PROCEDURE etl.sp_load_collateral_alloc() LANGUAGE plpgsql AS $$
BEGIN
    DELETE FROM public.dw_collateral_alloc;
    -- Collateral is valued in EUR; supervisory haircut applied
    INSERT INTO public.dw_collateral_alloc (
        collateral_id, facility_id, collateral_type, market_value_eur,
        haircut_pct, allocated_value_eur, as_of_date)
    SELECT
        c.collateral_id,
        c.facility_id,
        c.collateral_type,
        c.market_value                                   AS market_value_eur,
        c.haircut_pct,
        ROUND(c.market_value * (1 - c.haircut_pct), 2)   AS allocated_value_eur,
        c.as_of_date
    FROM fdw_stg.stg_collateral AS c;
END $$;

CREATE PROCEDURE etl.sp_load_mart_sa_exposure() LANGUAGE plpgsql AS $$
BEGIN
    DELETE FROM public.mart_sa_exposure;
    INSERT INTO public.mart_sa_exposure (
        facility_id, exposure_class, product_code, rating_status, provision_pct,
        on_bal_eur, off_bal_eur, as_of_date)
    SELECT
        e.facility_id,
        CASE e.counterparty_type
            WHEN 'CORP'   THEN 'Corporates'
            WHEN 'RETAIL' THEN 'Retail'
            WHEN 'INST'   THEN 'Institutions'
            WHEN 'SOV'    THEN 'Central governments'
            ELSE 'Other'
        END                 AS exposure_class,
        e.product_code,
        e.rating_status,
        e.provision_pct,
        e.drawn_eur         AS on_bal_eur,
        e.undrawn_eur       AS off_bal_eur,
        e.as_of_date
    FROM public.dw_exposure AS e;
END $$;

CREATE PROCEDURE etl.sp_load_sensitivity_usd() LANGUAGE plpgsql AS $$
BEGIN
    DELETE FROM public.dw_sensitivity_usd;
    -- Convert native-currency sensitivities to USD at the as-of-date rate
    INSERT INTO public.dw_sensitivity_usd (
        trade_id, consolidation_group, risk_class, sensitivity_type, risk_factor,
        currency, sensitivity_amount, fx_rate_to_usd, sensitivity_usd, as_of_date)
    SELECT
        s.trade_id,
        s.consolidation_group,
        s.risk_class,
        s.sensitivity_type,
        s.risk_factor,
        s.currency,
        s.sensitivity_amount,
        fx.rate_to_usd                                        AS fx_rate_to_usd,
        ROUND(s.sensitivity_amount * fx.rate_to_usd, 6)       AS sensitivity_usd,
        s.as_of_date
    FROM fdw_stg.stg_sensitivity AS s
    JOIN fdw_stg.ref_fx_rates    AS fx
      ON fx.ccy = s.currency
     AND fx.rate_date = s.as_of_date;
END $$;
