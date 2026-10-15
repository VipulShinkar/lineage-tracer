-- collateral_db: collateral management system (system of record for collateral)
CREATE SCHEMA col;
CREATE TABLE col.collateral (
    collateral_id   text PRIMARY KEY,
    facility_id     text NOT NULL,
    collateral_type text NOT NULL,            -- CASH / SECURITIES / REAL_ESTATE / GUARANTEE
    currency        char(3) NOT NULL,         -- all collateral is valued in EUR in this estate
    market_value    numeric(20,2) NOT NULL,
    haircut_pct     numeric(6,4) NOT NULL,    -- fraction, e.g. 0.0800
    valuation_date  date NOT NULL
);
COMMENT ON TABLE col.collateral IS 'Collateral pledged against facilities';
