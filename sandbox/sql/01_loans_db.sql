-- loans_db: Loan Origination System (system of record for facilities)
CREATE SCHEMA los;
CREATE TABLE los.facility (
    facility_id       text PRIMARY KEY,
    counterparty_id   text NOT NULL,
    counterparty_type text NOT NULL,          -- CORP / RETAIL / INST / SOV
    product_code      text NOT NULL,          -- TERM / GUAR / COMMIT / MORT ...
    currency          char(3) NOT NULL,
    drawn_balance     numeric(20,2) NOT NULL,
    undrawn_limit     numeric(20,2) NOT NULL,
    provision_pct     numeric(9,6) NOT NULL,  -- value adjustments as a fraction of the exposure
    rating_status     text NOT NULL,          -- RATED / UNRATED
    intragroup_flag   boolean NOT NULL,
    origination_date  date NOT NULL,
    maturity_date     date NOT NULL
);
COMMENT ON TABLE los.facility IS 'Credit facilities booked in the loan origination system';
