DELETE FROM core.fact_inflow;

INSERT INTO core.fact_inflow (entity, category, balance_usd, inflow_rate, inflow_usd)
SELECT c.entity_code,
       c.flow_type AS category,
       SUM(c.amount_usd) AS balance_usd,
       p.factor AS inflow_rate,
       SUM(c.amount_usd) * p.factor AS inflow_usd
FROM stg.cashflow c
JOIN stg.lcr_param p
  ON p.item_code = c.flow_type
WHERE c.flow_type LIKE 'IN%'
  AND c.maturity_date > DATE '2026-06-30'
  AND c.maturity_date <= DATE '2026-07-30'
GROUP BY c.entity_code, c.flow_type, p.factor;
