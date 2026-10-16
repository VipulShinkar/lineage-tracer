-- LCR mart model (Basel III LCR, simplified, 30-Jun-2026, USD m in rpt). Run as etl_owner in lcr_mart.
CREATE SCHEMA raw; CREATE SCHEMA stg; CREATE SCHEMA core; CREATE SCHEMA rpt;

CREATE TABLE raw.deposit_account (account_id text PRIMARY KEY, entity_code text, cpty_type text, product text, ccy text, balance numeric, is_operational text, insured text);
CREATE TABLE raw.security_holding (isin text PRIMARY KEY, entity_code text, asset_class text, ccy text, market_value numeric, is_encumbered text);
CREATE TABLE raw.cashflow (entity_code text, flow_type text, ccy text, amount numeric, maturity_date date);
CREATE TABLE raw.fx_rate (ccy text, rate_date date, rate_to_usd numeric, PRIMARY KEY (ccy, rate_date));
CREATE TABLE raw.lcr_param (item_code text PRIMARY KEY, factor numeric);

CREATE TABLE stg.deposit_account (account_id text, entity_code text, cpty_type text, is_operational boolean, insured boolean, balance_usd numeric);
CREATE TABLE stg.security_holding (isin text, entity_code text, asset_class text, is_encumbered boolean, mv_usd numeric);
CREATE TABLE stg.cashflow (entity_code text, flow_type text, amount_usd numeric, maturity_date date);
CREATE TABLE stg.lcr_param (item_code text, factor numeric);

CREATE TABLE core.fact_hqla (entity text, hqla_level text, mv_usd numeric, haircut numeric, weighted_usd numeric);
CREATE TABLE core.fact_outflow (entity text, category text, balance_usd numeric, runoff_rate numeric, outflow_usd numeric);
CREATE TABLE core.fact_inflow (entity text, category text, balance_usd numeric, inflow_rate numeric, inflow_usd numeric);

CREATE TABLE rpt.lcr_summary (entity text, hqla_usd numeric, outflows_usd numeric, inflows_usd numeric, net_outflows_usd numeric, lcr_pct numeric);
