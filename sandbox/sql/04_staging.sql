-- staging: landing area. Reads source systems through postgres_fdw; FX rates arrive via the Python/OpenLineage job.
CREATE SERVER srv_loans_db      FOREIGN DATA WRAPPER postgres_fdw OPTIONS (host '127.0.0.1', port '5432', dbname 'loans_db');
CREATE SERVER srv_collateral_db FOREIGN DATA WRAPPER postgres_fdw OPTIONS (host '127.0.0.1', port '5432', dbname 'collateral_db');
CREATE SERVER srv_trading_db    FOREIGN DATA WRAPPER postgres_fdw OPTIONS (host '127.0.0.1', port '5432', dbname 'trading_db');
CREATE USER MAPPING FOR etl_owner  SERVER srv_loans_db      OPTIONS (user 'etl_owner', password 'etl_owner');
CREATE USER MAPPING FOR etl_owner  SERVER srv_collateral_db OPTIONS (user 'etl_owner', password 'etl_owner');
CREATE USER MAPPING FOR etl_owner  SERVER srv_trading_db    OPTIONS (user 'etl_owner', password 'etl_owner');
CREATE USER MAPPING FOR lineage_ro SERVER srv_loans_db      OPTIONS (user 'loans_ro', password 'loans_ro');
CREATE USER MAPPING FOR lineage_ro SERVER srv_collateral_db OPTIONS (user 'lineage_ro', password 'lineage_ro');
CREATE USER MAPPING FOR lineage_ro SERVER srv_trading_db    OPTIONS (user 'lineage_ro', password 'lineage_ro');
CREATE SCHEMA fdw_los; CREATE SCHEMA fdw_col; CREATE SCHEMA fdw_trd; CREATE SCHEMA etl;
IMPORT FOREIGN SCHEMA los FROM SERVER srv_loans_db      INTO fdw_los;
IMPORT FOREIGN SCHEMA col FROM SERVER srv_collateral_db INTO fdw_col;
IMPORT FOREIGN SCHEMA trd FROM SERVER srv_trading_db    INTO fdw_trd;

CREATE TABLE public.stg_facilities (
    facility_id text, counterparty_id text, counterparty_type text, product_code text, currency char(3),
    drawn_balance numeric(20,2), undrawn_limit numeric(20,2), provision_pct numeric(9,6), rating_status text,
    intragroup_flag boolean, as_of_date date, loaded_at timestamptz DEFAULT now());
CREATE TABLE public.stg_collateral (
    collateral_id text, facility_id text, collateral_type text, currency char(3),
    market_value numeric(20,2), haircut_pct numeric(6,4), valuation_date date, as_of_date date, loaded_at timestamptz DEFAULT now());
CREATE TABLE public.stg_sensitivity (
    trade_id text, book text, desk text, consolidation_group text, risk_class text, sensitivity_type text,
    risk_factor text, currency char(3), sensitivity_amount numeric(20,4), as_of_date date, loaded_at timestamptz DEFAULT now());
CREATE TABLE public.ref_fx_rates (
    ccy char(3), rate_date date, rate_to_eur numeric(18,8), rate_to_usd numeric(18,8), loaded_at timestamptz DEFAULT now());

CREATE PROCEDURE etl.sp_load_stg_facilities() LANGUAGE plpgsql AS $$
BEGIN
    DELETE FROM public.stg_facilities;
    INSERT INTO public.stg_facilities (
        facility_id, counterparty_id, counterparty_type, product_code, currency,
        drawn_balance, undrawn_limit, provision_pct, rating_status, intragroup_flag, as_of_date)
    SELECT
        f.facility_id,
        f.counterparty_id,
        f.counterparty_type,
        f.product_code,
        f.currency,
        f.drawn_balance,
        f.undrawn_limit,
        f.provision_pct,
        f.rating_status,
        f.intragroup_flag,
        DATE '2026-06-30' AS as_of_date
    FROM fdw_los.facility AS f;
END $$;

CREATE PROCEDURE etl.sp_load_stg_collateral() LANGUAGE plpgsql AS $$
BEGIN
    DELETE FROM public.stg_collateral;
    INSERT INTO public.stg_collateral (
        collateral_id, facility_id, collateral_type, currency,
        market_value, haircut_pct, valuation_date, as_of_date)
    SELECT
        c.collateral_id,
        c.facility_id,
        c.collateral_type,
        c.currency,
        c.market_value,
        c.haircut_pct,
        c.valuation_date,
        DATE '2026-06-30' AS as_of_date
    FROM fdw_col.collateral AS c;
END $$;

CREATE PROCEDURE etl.sp_load_stg_sensitivity() LANGUAGE plpgsql AS $$
BEGIN
    DELETE FROM public.stg_sensitivity;
    INSERT INTO public.stg_sensitivity (
        trade_id, book, desk, consolidation_group, risk_class, sensitivity_type,
        risk_factor, currency, sensitivity_amount, as_of_date)
    SELECT
        t.trade_id,
        t.book,
        t.desk,
        t.consolidation_group,
        t.risk_class,
        t.sensitivity_type,
        t.risk_factor,
        t.currency,
        t.sensitivity_amount,
        t.as_of_date
    FROM fdw_trd.trade_sensitivity AS t;
END $$;
