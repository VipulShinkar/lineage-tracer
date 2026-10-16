CREATE OR REPLACE VIEW rpt.v_lcr_summary AS
SELECT entity, hqla_usd, outflows_usd, inflows_usd, net_outflows_usd, lcr_pct
FROM rpt.lcr_summary
UNION ALL
SELECT 'GROUP',
       SUM(hqla_usd),
       SUM(outflows_usd),
       SUM(inflows_usd),
       SUM(net_outflows_usd),
       ROUND(SUM(hqla_usd) / SUM(net_outflows_usd) * 100, 2)
FROM rpt.lcr_summary;

COMMENT ON VIEW rpt.v_lcr_summary IS 'LCR per entity plus GROUP total row (sums of entity amounts; group LCR from summed HQLA and net outflows).';
GRANT SELECT ON rpt.v_lcr_summary TO lineage_ro;
