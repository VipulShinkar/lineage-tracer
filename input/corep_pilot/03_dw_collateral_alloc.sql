-- Hop 3: collateral staging -> warehouse allocation
INSERT INTO dw_collateral_alloc (exposure_id, collateral_id, collateral_type, allocated_value_eur)
SELECT c.facility_id AS exposure_id,
       c.collateral_id AS collateral_id,
       c.collateral_type AS collateral_type,
       c.market_value_eur AS allocated_value_eur
FROM stg_collateral c;
