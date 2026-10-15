-- trading_db: trading book risk system (system of record for FRTB sensitivities)
CREATE SCHEMA trd;
CREATE TABLE trd.trade_sensitivity (
    trade_id            text PRIMARY KEY,
    book                text NOT NULL,
    desk                text NOT NULL,
    consolidation_group text NOT NULL,
    risk_class          text NOT NULL,        -- GIRR / FX / EQ / COM / CSR_NS
    sensitivity_type    text NOT NULL,        -- DELTA / VEGA / CURVATURE
    risk_factor         text NOT NULL,
    currency            char(3) NOT NULL,
    sensitivity_amount  numeric(20,4) NOT NULL,   -- native currency
    as_of_date          date NOT NULL
);
COMMENT ON TABLE trd.trade_sensitivity IS 'Trade-level FRTB SBM sensitivities in native currency';
