-- fin_lake: raw -> stg -> core (star) -> rpt, procedures in etl. Owner: etl_owner.
CREATE SCHEMA raw; CREATE SCHEMA stg; CREATE SCHEMA core; CREATE SCHEMA rpt; CREATE SCHEMA etl;

-- ===================================================== raw (source-shaped; starting point of every trace)
CREATE TABLE raw.entity (entity_code text, entity_name text, country text, consolidation_group text, _batch_id text, _loaded_at timestamptz);
CREATE TABLE raw.counterparty (cpty_id text, cpty_name text, country text, sector_code text, is_intragroup text, _batch_id text, _loaded_at timestamptz);
CREATE TABLE raw.rating (cpty_id text, rating_grade text, rating_date text, agency text, _batch_id text, _loaded_at timestamptz);
CREATE TABLE raw.loan_contract (contract_id text, entity_code text, cpty_id text, product_code text, ccy text, principal text,
    undrawn_limit text, accrued_int text, impairment text, start_date text, maturity_date text, _batch_id text, _loaded_at timestamptz);
CREATE TABLE raw.collateral (collateral_id text, contract_id text, collateral_type text, ccy text, market_value text, _batch_id text, _loaded_at timestamptz);
CREATE TABLE raw.credit_limit (entity_code text, sector_code text, limit_amount text, ccy text, _batch_id text, _loaded_at timestamptz);
CREATE TABLE raw.fx_rate (ccy text, rate_date text, rate_to_usd text, _batch_id text, _loaded_at timestamptz);
CREATE TABLE raw.gl_balance (entity_code text, account_code text, ccy text, balance text, as_of text, _batch_id text, _loaded_at timestamptz);

-- ===================================================== stg (typed, cleaned, deduped, intragroup flagged)
CREATE TABLE stg.entity (entity_code text, entity_name text, country text, consolidation_group text);
CREATE TABLE stg.counterparty (cpty_id text, cpty_name text, country text, sector_code text, is_intragroup boolean);
CREATE TABLE stg.rating (cpty_id text, rating_grade text, rating_date date, agency text);
CREATE TABLE stg.loan (contract_id text, entity_code text, cpty_id text, product_code text, ccy char(3),
    drawn_amt numeric(20,2), undrawn_amt numeric(20,2), start_date date, maturity_date date);
CREATE TABLE stg.collateral (collateral_id text, contract_id text, collateral_type text, ccy char(3), market_value numeric(20,2));
CREATE TABLE stg.credit_limit (entity_code text, sector_code text, limit_amount numeric(20,2), ccy char(3));
CREATE TABLE stg.fx_rate (ccy char(3), rate_date date, rate_to_usd numeric(18,8));

-- ===================================================== core (star)
CREATE TABLE core.dim_date (date_key date, year int, quarter int, month int, is_month_end boolean);
CREATE TABLE core.dim_entity (entity_key int, entity_code text, entity_name text, country text, consolidation_group text);
CREATE TABLE core.dim_counterparty (cpty_key int, cpty_id text, cpty_name text, country text, sector_code text, portfolio text, is_intragroup boolean);
CREATE TABLE core.dim_rating (rating_key int, rating_grade text, pd numeric(9,6), lgd numeric(9,6));
CREATE TABLE core.dim_product (product_key int, product_code text, ccf numeric(9,4), risk_weight_base numeric(9,4));
CREATE TABLE core.fact_exposure (as_of date, entity_key int, cpty_key int, product_key int, rating_key int,
    drawn_usd numeric(20,2), undrawn_usd numeric(20,2), ccf numeric(9,4), ead_usd numeric(20,2), risk_weight numeric(9,4),
    rwa_usd numeric(20,2), pd numeric(9,6), lgd numeric(9,6), el_usd numeric(20,2), collateral_usd numeric(20,2));
CREATE TABLE core.fact_limit (as_of date, entity_key int, portfolio text, limit_usd numeric(20,2));

-- ===================================================== rpt
CREATE TABLE rpt.efr_credit_risk_summary (entity text, risk_type text, portfolio text, exposure_ead numeric(18,2),
    rwa numeric(18,2), expected_loss numeric(18,2), limit_amount numeric(18,2), as_of date);

CREATE VIEW rpt.v_efr_credit_risk_summary AS
SELECT u.entity, u.risk_type, u.portfolio, u.exposure_ead, u.rwa, u.expected_loss, u.limit_amount, u.utilisation_pct
FROM (
    SELECT s.entity, s.risk_type, s.portfolio, s.exposure_ead, s.rwa, s.expected_loss, s.limit_amount,
           ROUND(s.exposure_ead / NULLIF(s.limit_amount, 0) * 100, 2) AS utilisation_pct
    FROM rpt.efr_credit_risk_summary AS s
    UNION ALL
    SELECT 'GROUP' AS entity, 'CREDIT' AS risk_type, 'ALL' AS portfolio,
           SUM(s.exposure_ead), SUM(s.rwa), SUM(s.expected_loss), SUM(s.limit_amount),
           ROUND(SUM(s.exposure_ead) / NULLIF(SUM(s.limit_amount), 0) * 100, 2) AS utilisation_pct
    FROM rpt.efr_credit_risk_summary AS s
) AS u
ORDER BY (u.entity = 'GROUP'), u.entity, u.portfolio;

-- completeness check (BCBS 239): loan principal in the lake vs general ledger
CREATE VIEW rpt.v_gl_completeness AS
SELECT UPPER(l.entity_code) AS entity_code, l.ccy, SUM(l.principal::numeric) AS loan_principal, g.balance::numeric AS gl_balance,
       SUM(l.principal::numeric) - g.balance::numeric AS difference
FROM raw.loan_contract AS l
JOIN raw.gl_balance AS g ON g.entity_code = UPPER(l.entity_code) AND g.ccy = l.ccy AND g.account_code = '1100-LOANS'
GROUP BY UPPER(l.entity_code), l.ccy, g.balance;

-- ===================================================== etl: raw -> stg
CREATE PROCEDURE etl.sp_load_stg_entity() LANGUAGE plpgsql AS $$
BEGIN
    TRUNCATE TABLE stg.entity;
    INSERT INTO stg.entity (entity_code, entity_name, country, consolidation_group)
    SELECT
        UPPER(TRIM(e.entity_code)) AS entity_code,
        TRIM(e.entity_name)        AS entity_name,
        e.country,
        e.consolidation_group
    FROM raw.entity AS e;
END $$;

CREATE PROCEDURE etl.sp_load_stg_counterparty() LANGUAGE plpgsql AS $$
BEGIN
    TRUNCATE TABLE stg.counterparty;
    -- dedupe: keep the latest delivery per counterparty; flag intragroup
    INSERT INTO stg.counterparty (cpty_id, cpty_name, country, sector_code, is_intragroup)
    SELECT
        d.cpty_id,
        TRIM(d.cpty_name)               AS cpty_name,
        d.country,
        UPPER(d.sector_code)            AS sector_code,
        (d.is_intragroup = 'Y')         AS is_intragroup
    FROM (
        SELECT c.*, ROW_NUMBER() OVER (PARTITION BY c.cpty_id ORDER BY c._loaded_at DESC) AS rn
        FROM raw.counterparty AS c
    ) AS d
    WHERE d.rn = 1;
END $$;

CREATE PROCEDURE etl.sp_load_stg_rating() LANGUAGE plpgsql AS $$
BEGIN
    TRUNCATE TABLE stg.rating;
    -- latest rating per counterparty
    INSERT INTO stg.rating (cpty_id, rating_grade, rating_date, agency)
    SELECT
        d.cpty_id,
        UPPER(d.rating_grade)        AS rating_grade,
        d.rating_date::date          AS rating_date,
        d.agency
    FROM (
        SELECT r.*, ROW_NUMBER() OVER (PARTITION BY r.cpty_id ORDER BY r.rating_date DESC) AS rn
        FROM raw.rating AS r
    ) AS d
    WHERE d.rn = 1;
END $$;

CREATE PROCEDURE etl.sp_load_stg_loan() LANGUAGE plpgsql AS $$
BEGIN
    TRUNCATE TABLE stg.loan;
    -- drawn amount = principal + accrued interest - impairment (transaction currency)
    INSERT INTO stg.loan (
        contract_id, entity_code, cpty_id, product_code, ccy,
        drawn_amt, undrawn_amt, start_date, maturity_date)
    SELECT
        l.contract_id,
        UPPER(l.entity_code)                                                       AS entity_code,
        l.cpty_id,
        UPPER(l.product_code)                                                      AS product_code,
        l.ccy,
        l.principal::numeric + l.accrued_int::numeric - l.impairment::numeric      AS drawn_amt,
        l.undrawn_limit::numeric                                                   AS undrawn_amt,
        l.start_date::date                                                         AS start_date,
        l.maturity_date::date                                                      AS maturity_date
    FROM raw.loan_contract AS l;
END $$;

CREATE PROCEDURE etl.sp_load_stg_collateral() LANGUAGE plpgsql AS $$
BEGIN
    TRUNCATE TABLE stg.collateral;
    INSERT INTO stg.collateral (collateral_id, contract_id, collateral_type, ccy, market_value)
    SELECT
        c.collateral_id,
        c.contract_id,
        c.collateral_type,
        c.ccy,
        c.market_value::numeric AS market_value
    FROM raw.collateral AS c;
END $$;

CREATE PROCEDURE etl.sp_load_stg_credit_limit() LANGUAGE plpgsql AS $$
BEGIN
    TRUNCATE TABLE stg.credit_limit;
    INSERT INTO stg.credit_limit (entity_code, sector_code, limit_amount, ccy)
    SELECT
        UPPER(l.entity_code)      AS entity_code,
        UPPER(l.sector_code)      AS sector_code,
        l.limit_amount::numeric   AS limit_amount,
        l.ccy
    FROM raw.credit_limit AS l;
END $$;

CREATE PROCEDURE etl.sp_load_stg_fx_rate() LANGUAGE plpgsql AS $$
BEGIN
    TRUNCATE TABLE stg.fx_rate;
    INSERT INTO stg.fx_rate (ccy, rate_date, rate_to_usd)
    SELECT
        f.ccy,
        f.rate_date::date        AS rate_date,
        f.rate_to_usd::numeric   AS rate_to_usd
    FROM raw.fx_rate AS f;
END $$;

-- ===================================================== etl: stg -> core
CREATE PROCEDURE etl.sp_load_core_dim_date() LANGUAGE plpgsql AS $$
BEGIN
    TRUNCATE TABLE core.dim_date;
    INSERT INTO core.dim_date (date_key, year, quarter, month, is_month_end)
    SELECT
        d::date                                              AS date_key,
        EXTRACT(YEAR FROM d)::int                            AS year,
        EXTRACT(QUARTER FROM d)::int                         AS quarter,
        EXTRACT(MONTH FROM d)::int                           AS month,
        (d + INTERVAL '1 day')::date = DATE_TRUNC('month', d + INTERVAL '1 day')::date AS is_month_end
    FROM generate_series(DATE '2026-01-01', DATE '2026-12-31', INTERVAL '1 day') AS g(d);
END $$;

CREATE PROCEDURE etl.sp_load_core_dim_entity() LANGUAGE plpgsql AS $$
BEGIN
    TRUNCATE TABLE core.dim_entity;
    INSERT INTO core.dim_entity (entity_key, entity_code, entity_name, country, consolidation_group)
    SELECT
        ROW_NUMBER() OVER (ORDER BY e.entity_code)::int AS entity_key,
        e.entity_code,
        e.entity_name,
        e.country,
        e.consolidation_group
    FROM stg.entity AS e;
END $$;

CREATE PROCEDURE etl.sp_load_core_dim_counterparty() LANGUAGE plpgsql AS $$
BEGIN
    TRUNCATE TABLE core.dim_counterparty;
    -- portfolio derived from the sector code
    INSERT INTO core.dim_counterparty (cpty_key, cpty_id, cpty_name, country, sector_code, portfolio, is_intragroup)
    SELECT
        ROW_NUMBER() OVER (ORDER BY c.cpty_id)::int AS cpty_key,
        c.cpty_id,
        c.cpty_name,
        c.country,
        c.sector_code,
        CASE c.sector_code
            WHEN 'SOV'  THEN 'Sovereigns'
            WHEN 'BNK'  THEN 'Banks'
            WHEN 'CORP' THEN 'Corporates'
            WHEN 'RET'  THEN 'Retail'
            ELSE 'Other'
        END                                         AS portfolio,
        c.is_intragroup
    FROM stg.counterparty AS c;
END $$;

CREATE PROCEDURE etl.sp_load_core_dim_rating() LANGUAGE plpgsql AS $$
BEGIN
    TRUNCATE TABLE core.dim_rating;
    -- grade -> probability of default and loss-given-default band ('NR' = not rated)
    INSERT INTO core.dim_rating (rating_key, rating_grade, pd, lgd)
    SELECT
        ROW_NUMBER() OVER (ORDER BY g.rating_grade)::int AS rating_key,
        g.rating_grade,
        CASE g.rating_grade
            WHEN 'AAA' THEN 0.0003 WHEN 'AA' THEN 0.0006 WHEN 'A' THEN 0.0015 WHEN 'BBB' THEN 0.0050
            WHEN 'BB'  THEN 0.0200 WHEN 'B'  THEN 0.0600 WHEN 'CCC' THEN 0.2000 ELSE 0.0300
        END                                              AS pd,
        CASE WHEN g.rating_grade IN ('AAA', 'AA', 'A') THEN 0.35
             WHEN g.rating_grade IN ('BBB', 'BB')      THEN 0.45
             ELSE 0.55
        END                                              AS lgd
    FROM (
        SELECT r.rating_grade FROM stg.rating AS r
        UNION
        SELECT 'NR' AS rating_grade
    ) AS g;
END $$;

CREATE PROCEDURE etl.sp_load_core_dim_product() LANGUAGE plpgsql AS $$
BEGIN
    TRUNCATE TABLE core.dim_product;
    INSERT INTO core.dim_product (product_key, product_code, ccf, risk_weight_base)
    SELECT
        ROW_NUMBER() OVER (ORDER BY p.product_code)::int AS product_key,
        p.product_code,
        CASE p.product_code WHEN 'RCF' THEN 0.50 WHEN 'TRADE' THEN 0.20 ELSE 1.00 END AS ccf,
        CASE p.product_code WHEN 'GUAR' THEN 1.00 WHEN 'TRADE' THEN 0.50 WHEN 'RCF' THEN 0.80 ELSE 0.90 END AS risk_weight_base
    FROM (SELECT DISTINCT l.product_code FROM stg.loan AS l) AS p;
END $$;

CREATE PROCEDURE etl.sp_load_core_fact_exposure() LANGUAGE plpgsql AS $$
BEGIN
    TRUNCATE TABLE core.fact_exposure;
    -- EAD = drawn + CCF x undrawn (USD at the 30-Jun-2026 rate); RWA = EAD x risk weight; EL = PD x LGD x EAD; intragroup excluded
    INSERT INTO core.fact_exposure (
        as_of, entity_key, cpty_key, product_key, rating_key,
        drawn_usd, undrawn_usd, ccf, ead_usd, risk_weight,
        rwa_usd, pd, lgd, el_usd, collateral_usd)
    WITH base AS (
        SELECT
            e.entity_key,
            c.cpty_key,
            p.product_key,
            dr.rating_key,
            l.contract_id,
            ROUND(l.drawn_amt   * fx.rate_to_usd, 2)                      AS drawn_usd,
            ROUND(l.undrawn_amt * fx.rate_to_usd, 2)                      AS undrawn_usd,
            p.ccf,
            p.risk_weight_base                                            AS risk_weight,
            dr.pd,
            dr.lgd
        FROM stg.loan AS l
        JOIN stg.fx_rate          AS fx ON fx.ccy = l.ccy AND fx.rate_date = DATE '2026-06-30'
        JOIN core.dim_entity      AS e  ON e.entity_code = l.entity_code
        JOIN core.dim_counterparty AS c ON c.cpty_id = l.cpty_id
        JOIN core.dim_product     AS p  ON p.product_code = l.product_code
        LEFT JOIN stg.rating      AS r  ON r.cpty_id = l.cpty_id
        JOIN core.dim_rating      AS dr ON dr.rating_grade = COALESCE(r.rating_grade, 'NR')
        WHERE c.is_intragroup = FALSE
    ),
    coll AS (
        SELECT k.contract_id, SUM(ROUND(k.market_value * fx.rate_to_usd, 2)) AS collateral_usd
        FROM stg.collateral AS k
        JOIN stg.fx_rate AS fx ON fx.ccy = k.ccy AND fx.rate_date = DATE '2026-06-30'
        GROUP BY k.contract_id
    )
    SELECT
        DATE '2026-06-30'                                         AS as_of,
        b.entity_key,
        b.cpty_key,
        b.product_key,
        b.rating_key,
        b.drawn_usd,
        b.undrawn_usd,
        b.ccf,
        ROUND(b.drawn_usd + b.ccf * b.undrawn_usd, 2)             AS ead_usd,
        b.risk_weight,
        ROUND((b.drawn_usd + b.ccf * b.undrawn_usd) * b.risk_weight, 2) AS rwa_usd,
        b.pd,
        b.lgd,
        ROUND(b.pd * b.lgd * (b.drawn_usd + b.ccf * b.undrawn_usd), 2)  AS el_usd,
        COALESCE(k.collateral_usd, 0)                             AS collateral_usd
    FROM base AS b
    LEFT JOIN coll AS k ON k.contract_id = b.contract_id;
END $$;

CREATE PROCEDURE etl.sp_load_core_fact_limit() LANGUAGE plpgsql AS $$
BEGIN
    TRUNCATE TABLE core.fact_limit;
    INSERT INTO core.fact_limit (as_of, entity_key, portfolio, limit_usd)
    SELECT
        DATE '2026-06-30'                                  AS as_of,
        e.entity_key,
        CASE l.sector_code
            WHEN 'SOV'  THEN 'Sovereigns'
            WHEN 'BNK'  THEN 'Banks'
            WHEN 'CORP' THEN 'Corporates'
            WHEN 'RET'  THEN 'Retail'
            ELSE 'Other'
        END                                                AS portfolio,
        ROUND(l.limit_amount * fx.rate_to_usd, 2)          AS limit_usd
    FROM stg.credit_limit AS l
    JOIN core.dim_entity  AS e  ON e.entity_code = l.entity_code
    JOIN stg.fx_rate      AS fx ON fx.ccy = l.ccy AND fx.rate_date = DATE '2026-06-30';
END $$;

-- ===================================================== etl: core -> rpt
CREATE PROCEDURE etl.sp_load_rpt_efr() LANGUAGE plpgsql AS $$
BEGIN
    TRUNCATE TABLE rpt.efr_credit_risk_summary;
    -- USD millions, 2 dp
    INSERT INTO rpt.efr_credit_risk_summary (entity, risk_type, portfolio, exposure_ead, rwa, expected_loss, limit_amount, as_of)
    WITH expo AS (
        SELECT
            f.entity_key,
            c.portfolio,
            SUM(f.ead_usd) AS ead_usd,
            SUM(f.rwa_usd) AS rwa_usd,
            SUM(f.el_usd)  AS el_usd
        FROM core.fact_exposure AS f
        JOIN core.dim_counterparty AS c ON c.cpty_key = f.cpty_key
        GROUP BY f.entity_key, c.portfolio
    ),
    lim AS (
        SELECT l.entity_key, l.portfolio, SUM(l.limit_usd) AS limit_usd
        FROM core.fact_limit AS l
        GROUP BY l.entity_key, l.portfolio
    )
    SELECT
        e.entity_code                          AS entity,
        'CREDIT'                               AS risk_type,
        x.portfolio,
        ROUND(x.ead_usd / 1000000, 2)          AS exposure_ead,
        ROUND(x.rwa_usd / 1000000, 2)          AS rwa,
        ROUND(x.el_usd  / 1000000, 2)          AS expected_loss,
        ROUND(l.limit_usd / 1000000, 2)        AS limit_amount,
        DATE '2026-06-30'                      AS as_of
    FROM expo AS x
    JOIN core.dim_entity AS e ON e.entity_key = x.entity_key
    LEFT JOIN lim        AS l ON l.entity_key = x.entity_key AND l.portfolio = x.portfolio;
END $$;
