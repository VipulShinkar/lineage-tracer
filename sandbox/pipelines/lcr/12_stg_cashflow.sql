DELETE FROM stg.cashflow;

INSERT INTO stg.cashflow (entity_code, flow_type, amount_usd, maturity_date)
SELECT UPPER(c.entity_code),
       c.flow_type,
       ROUND(c.amount * fx.rate_to_usd, 2),
       c.maturity_date
FROM raw.cashflow c
JOIN raw.fx_rate fx
  ON fx.ccy = c.ccy
 AND fx.rate_date = DATE '2026-06-30';
