-- Business glossary as catalog comments ("Term: definition" on columns).
COMMENT ON TABLE raw.deposit_account IS 'Customer deposit accounts as booked in the deposit system, balances in account currency.';
COMMENT ON TABLE raw.security_holding IS 'Securities held in the liquidity portfolio, market value in security currency.';
COMMENT ON TABLE raw.cashflow IS 'Contractual cash flows (inflows and wholesale funding outflows) with maturity date, in flow currency.';
COMMENT ON TABLE raw.fx_rate IS 'Daily FX rates to USD from the market data feed; source of record for conversion.';
COMMENT ON TABLE raw.lcr_param IS 'LCR parameters: run-off rates, inflow rates and HQLA haircuts per item code.';
COMMENT ON COLUMN raw.deposit_account.balance IS 'Deposit balance: Outstanding balance of the deposit account in account currency.';
COMMENT ON COLUMN raw.deposit_account.insured IS 'Insured: Y when the deposit is covered by a deposit guarantee scheme.';
COMMENT ON COLUMN raw.deposit_account.is_operational IS 'Operational deposit: Y when the deposit is held for clearing, custody or cash management.';
COMMENT ON COLUMN raw.deposit_account.cpty_type IS 'Counterparty type: RETAIL, SME, CORP corporate or FIN financial institution.';
COMMENT ON COLUMN raw.security_holding.market_value IS 'Market value: Market value of the security holding in security currency.';
COMMENT ON COLUMN raw.security_holding.asset_class IS 'Asset class: L1_SOVEREIGN, L1_CENTRAL_BANK, L2A_GOV, L2A_COVERED, L2B_RMBS, L2B_CORP_BOND or non-HQLA classes.';
COMMENT ON COLUMN raw.security_holding.is_encumbered IS 'Encumbered: Y when pledged and therefore not available as liquidity buffer.';
COMMENT ON COLUMN raw.fx_rate.rate_to_usd IS 'FX rate to USD: Units of USD per one unit of the currency on the rate date.';
COMMENT ON COLUMN raw.lcr_param.factor IS 'Factor: Run-off rate, inflow rate or haircut (0 to 1) for the item code.';

COMMENT ON TABLE stg.deposit_account IS 'Typed deposits with balance converted to USD at the reporting date.';
COMMENT ON TABLE stg.security_holding IS 'Typed security holdings with market value converted to USD.';
COMMENT ON TABLE stg.cashflow IS 'Typed contractual cash flows converted to USD.';
COMMENT ON TABLE stg.lcr_param IS 'Typed LCR parameters.';
COMMENT ON COLUMN stg.deposit_account.balance_usd IS 'Deposit balance USD: Deposit balance converted to USD at the 30-Jun-2026 rate.';
COMMENT ON COLUMN stg.security_holding.mv_usd IS 'Market value USD: Security market value converted to USD at the 30-Jun-2026 rate.';
COMMENT ON COLUMN stg.cashflow.amount_usd IS 'Cash flow USD: Contractual cash flow converted to USD at the 30-Jun-2026 rate.';

COMMENT ON TABLE core.fact_hqla IS 'High quality liquid assets per entity and HQLA level after haircut; encumbered assets excluded.';
COMMENT ON TABLE core.fact_outflow IS 'Stressed 30-day cash outflows per entity and category (deposit run-off and wholesale funding maturing).';
COMMENT ON TABLE core.fact_inflow IS 'Contractual 30-day cash inflows per entity and category after inflow rates.';
COMMENT ON COLUMN core.fact_hqla.weighted_usd IS 'HQLA after haircut: Market value in USD multiplied by (1 - haircut).';
COMMENT ON COLUMN core.fact_hqla.haircut IS 'Haircut: Regulatory valuation haircut for the HQLA level (L1 0%, L2A 15%, L2B 50%).';
COMMENT ON COLUMN core.fact_outflow.outflow_usd IS 'Stressed outflow: Balance in USD multiplied by the run-off rate of the category.';
COMMENT ON COLUMN core.fact_outflow.runoff_rate IS 'Run-off rate: Share of the balance assumed to leave within 30 days under stress.';
COMMENT ON COLUMN core.fact_inflow.inflow_usd IS 'Inflow: Contractual inflow in USD multiplied by the inflow rate of the category.';

COMMENT ON TABLE rpt.lcr_summary IS 'Liquidity Coverage Ratio per entity in USD m, loaded from core facts.';
COMMENT ON COLUMN rpt.lcr_summary.hqla_usd IS 'HQLA: Stock of high quality liquid assets after haircuts, USD m.';
COMMENT ON COLUMN rpt.lcr_summary.outflows_usd IS 'Total outflows: Stressed cash outflows over 30 days, USD m.';
COMMENT ON COLUMN rpt.lcr_summary.inflows_usd IS 'Total inflows: Cash inflows over 30 days before the cap, USD m.';
COMMENT ON COLUMN rpt.lcr_summary.net_outflows_usd IS 'Net cash outflows: Outflows minus inflows capped at 75% of outflows, USD m.';
COMMENT ON COLUMN rpt.lcr_summary.lcr_pct IS 'LCR: HQLA divided by net cash outflows over 30 days, in percent.';
