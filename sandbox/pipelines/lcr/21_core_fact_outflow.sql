DELETE FROM core.fact_outflow;

INSERT INTO core.fact_outflow (entity, category, balance_usd, runoff_rate, outflow_usd)
SELECT d.entity_code,
       CASE
         WHEN d.cpty_type = 'RETAIL' AND d.insured THEN 'RET_STABLE'
         WHEN d.cpty_type = 'RETAIL' THEN 'RET_LESS_STABLE'
         WHEN d.is_operational THEN 'WHOLESALE_OPERATIONAL'
         WHEN d.cpty_type = 'FIN' THEN 'FIN_NON_OPERATIONAL'
         ELSE 'CORP_NON_OPERATIONAL'
       END AS category,
       SUM(d.balance_usd) AS balance_usd,
       p.factor AS runoff_rate,
       SUM(d.balance_usd) * p.factor AS outflow_usd
FROM stg.deposit_account d
JOIN stg.lcr_param p
  ON p.item_code = CASE
         WHEN d.cpty_type = 'RETAIL' AND d.insured THEN 'RET_STABLE'
         WHEN d.cpty_type = 'RETAIL' THEN 'RET_LESS_STABLE'
         WHEN d.is_operational THEN 'WHOLESALE_OPERATIONAL'
         WHEN d.cpty_type = 'FIN' THEN 'FIN_NON_OPERATIONAL'
         ELSE 'CORP_NON_OPERATIONAL'
       END
GROUP BY d.entity_code, 2, p.factor;

INSERT INTO core.fact_outflow (entity, category, balance_usd, runoff_rate, outflow_usd)
SELECT c.entity_code,
       c.flow_type AS category,
       SUM(c.amount_usd) AS balance_usd,
       p.factor AS runoff_rate,
       SUM(c.amount_usd) * p.factor AS outflow_usd
FROM stg.cashflow c
JOIN stg.lcr_param p
  ON p.item_code = c.flow_type
WHERE c.flow_type LIKE 'OUT%'
  AND c.maturity_date > DATE '2026-06-30'
  AND c.maturity_date <= DATE '2026-07-30'
GROUP BY c.entity_code, c.flow_type, p.factor;
