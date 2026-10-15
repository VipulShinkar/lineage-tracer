-- Hop 2: collateral system -> staging
INSERT INTO stg_collateral (collateral_id, facility_id, collateral_type, market_value_eur, valuation_date)
SELECT c.collateral_id AS collateral_id,
       c.facility_id AS facility_id,
       c.collateral_type AS collateral_type,
       c.collateral_value AS market_value_eur,
       c.valuation_date AS valuation_date
FROM collateral_master c;
