DELETE FROM rpt.lcr_summary;

INSERT INTO rpt.lcr_summary (entity, hqla_usd, outflows_usd, inflows_usd, net_outflows_usd, lcr_pct)
SELECT h.entity,
       ROUND(h.hqla / 1000000, 2) AS hqla_usd,
       ROUND(o.outflows / 1000000, 2) AS outflows_usd,
       ROUND(i.inflows / 1000000, 2) AS inflows_usd,
       ROUND((o.outflows - LEAST(i.inflows, 0.75 * o.outflows)) / 1000000, 2) AS net_outflows_usd,
       ROUND(h.hqla / (o.outflows - LEAST(i.inflows, 0.75 * o.outflows)) * 100, 2) AS lcr_pct
FROM (SELECT entity, SUM(weighted_usd) AS hqla FROM core.fact_hqla GROUP BY entity) h
JOIN (SELECT entity, SUM(outflow_usd) AS outflows FROM core.fact_outflow GROUP BY entity) o
  ON o.entity = h.entity
JOIN (SELECT entity, SUM(inflow_usd) AS inflows FROM core.fact_inflow GROUP BY entity) i
  ON i.entity = h.entity;
