DELETE FROM core.fact_hqla;

INSERT INTO core.fact_hqla (entity, hqla_level, mv_usd, haircut, weighted_usd)
SELECT s.entity_code,
       CASE
         WHEN s.asset_class IN ('L1_SOVEREIGN', 'L1_CENTRAL_BANK') THEN '1'
         WHEN s.asset_class IN ('L2A_GOV', 'L2A_COVERED') THEN '2A'
         ELSE '2B'
       END AS hqla_level,
       SUM(s.mv_usd) AS mv_usd,
       p.factor AS haircut,
       SUM(s.mv_usd) * (1 - p.factor) AS weighted_usd
FROM stg.security_holding s
JOIN stg.lcr_param p
  ON p.item_code = 'HQLA_L' || CASE
         WHEN s.asset_class IN ('L1_SOVEREIGN', 'L1_CENTRAL_BANK') THEN '1'
         WHEN s.asset_class IN ('L2A_GOV', 'L2A_COVERED') THEN '2A'
         ELSE '2B'
       END
WHERE NOT s.is_encumbered
  AND s.asset_class IN ('L1_SOVEREIGN', 'L1_CENTRAL_BANK', 'L2A_GOV', 'L2A_COVERED', 'L2B_RMBS', 'L2B_CORP_BOND')
GROUP BY s.entity_code, 2, p.factor;
