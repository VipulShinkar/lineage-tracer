DELETE FROM stg.security_holding;

INSERT INTO stg.security_holding (isin, entity_code, asset_class, is_encumbered, mv_usd)
SELECT s.isin,
       UPPER(s.entity_code),
       s.asset_class,
       s.is_encumbered = 'Y',
       ROUND(s.market_value * fx.rate_to_usd, 2)
FROM raw.security_holding s
JOIN raw.fx_rate fx
  ON fx.ccy = s.ccy
 AND fx.rate_date = DATE '2026-06-30';
