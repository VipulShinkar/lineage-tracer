-- Business glossary as catalog comments. build.py applies each "@@DB" section to its database before the ETL runs.
-- @@DB loans_db
COMMENT ON TABLE los.facility IS 'Credit facilities booked in the loan origination system; system of record for drawn balances, undrawn limits and intragroup status.';
COMMENT ON COLUMN los.facility.drawn_balance IS 'Drawn balance: Amount drawn by the borrower, in facility currency.';
COMMENT ON COLUMN los.facility.undrawn_limit IS 'Undrawn limit: Committed amount not yet drawn, in facility currency.';
COMMENT ON COLUMN los.facility.intragroup_flag IS 'Intragroup flag: TRUE when the counterparty is a group company; excluded from regulatory exposure.';
COMMENT ON COLUMN los.facility.provision_pct IS 'Provision rate: Value adjustments (provisions) as a fraction of the exposure.';
COMMENT ON COLUMN los.facility.rating_status IS 'Rating status: RATED when an external rating exists, otherwise UNRATED.';
-- @@DB collateral_db
COMMENT ON TABLE col.collateral IS 'Collateral pledged against facilities; system of record for collateral values.';
COMMENT ON COLUMN col.collateral.market_value IS 'Market value: Current market value of the collateral in EUR.';
COMMENT ON COLUMN col.collateral.haircut_pct IS 'Haircut: Supervisory haircut applied to the market value (fraction).';
-- @@DB trading_db
COMMENT ON TABLE trd.trade_sensitivity IS 'Trade-level FRTB sensitivities in native currency; system of record for market risk inputs (C90).';
COMMENT ON COLUMN trd.trade_sensitivity.sensitivity_amount IS 'Sensitivity: Sensitivity of the trade to the risk factor, in the trade currency.';
COMMENT ON COLUMN trd.trade_sensitivity.risk_class IS 'Risk class: FRTB risk class: GIRR, FX, EQ, COM, CSR_NS.';
COMMENT ON COLUMN trd.trade_sensitivity.sensitivity_type IS 'Sensitivity type: FRTB sensitivity type: DELTA, VEGA or CURVATURE.';
-- @@DB staging
COMMENT ON TABLE public.stg_facilities IS 'Landed copy of facilities from the loan origination system.';
COMMENT ON TABLE public.stg_collateral IS 'Landed copy of collateral from the collateral management system.';
COMMENT ON TABLE public.stg_sensitivity IS 'Landed copy of trade sensitivities from the trading risk system.';
COMMENT ON TABLE public.ref_fx_rates IS 'FX rates feed loaded from the market data SQLite file; used for EUR and USD conversion.';
COMMENT ON COLUMN public.ref_fx_rates.rate_to_eur IS 'FX rate to EUR: EUR per one unit of the currency on the rate date.';
COMMENT ON COLUMN public.ref_fx_rates.rate_to_usd IS 'FX rate to USD: USD per one unit of the currency on the rate date.';
COMMENT ON PROCEDURE etl.sp_load_stg_facilities() IS 'Lands facilities from the loan origination system.';
COMMENT ON PROCEDURE etl.sp_load_stg_collateral() IS 'Lands collateral from the collateral management system.';
COMMENT ON PROCEDURE etl.sp_load_stg_sensitivity() IS 'Lands trade sensitivities from the trading risk system.';
-- @@DB dwh
COMMENT ON TABLE public.dw_exposure IS 'Facility exposure in EUR at the 30-Jun-2026 FX rate; intragroup facilities excluded.';
COMMENT ON TABLE public.dw_collateral_alloc IS 'Collateral value after supervisory haircut, per collateral item, in EUR.';
COMMENT ON TABLE public.mart_sa_exposure IS 'Standardised-approach data mart: on- and off-balance exposure per facility with its exposure class.';
COMMENT ON TABLE public.dw_sensitivity_usd IS 'Trade sensitivities converted to USD at the as-of-date rate.';
COMMENT ON COLUMN public.dw_exposure.drawn_eur IS 'Drawn (EUR): Drawn balance converted to EUR at the reporting-date rate.';
COMMENT ON COLUMN public.dw_exposure.undrawn_eur IS 'Undrawn (EUR): Undrawn limit converted to EUR at the reporting-date rate.';
COMMENT ON COLUMN public.dw_collateral_alloc.allocated_value_eur IS 'Allocated collateral (EUR): Market value net of haircut available as credit risk mitigation, in EUR.';
COMMENT ON COLUMN public.mart_sa_exposure.exposure_class IS 'Exposure class: Standardised-approach exposure class derived from the counterparty type.';
COMMENT ON COLUMN public.mart_sa_exposure.on_bal_eur IS 'On-balance exposure (EUR): On-balance-sheet exposure in EUR.';
COMMENT ON COLUMN public.mart_sa_exposure.off_bal_eur IS 'Off-balance exposure (EUR): Off-balance-sheet exposure (undrawn commitments) in EUR.';
COMMENT ON COLUMN public.dw_sensitivity_usd.sensitivity_usd IS 'Sensitivity (USD): Sensitivity in USD: native amount multiplied by the USD rate.';
COMMENT ON PROCEDURE etl.sp_load_exposure() IS 'Converts facilities to EUR and excludes intragroup facilities.';
COMMENT ON PROCEDURE etl.sp_load_collateral_alloc() IS 'Applies supervisory haircuts to collateral.';
COMMENT ON PROCEDURE etl.sp_load_mart_sa_exposure() IS 'Maps exposures to standardised-approach exposure classes.';
COMMENT ON PROCEDURE etl.sp_load_sensitivity_usd() IS 'Converts trade sensitivities to USD.';
-- @@DB sa_engine
COMMENT ON TABLE public.calc_sa_exposure IS 'Standardised-approach exposure value per facility after value adjustments, credit conversion factor and collateral.';
COMMENT ON COLUMN public.calc_sa_exposure.ev_on_eur IS 'On-balance exposure value (EUR): On-balance exposure value in EUR: balance less value adjustments less eligible collateral.';
COMMENT ON COLUMN public.calc_sa_exposure.ev_off_eur IS 'Off-balance exposure value (EUR): Off-balance exposure value in EUR: undrawn limit less value adjustments, times the CCF.';
COMMENT ON COLUMN public.calc_sa_exposure.ccf IS 'CCF: Credit conversion factor applied to the off-balance exposure.';
COMMENT ON COLUMN public.calc_sa_exposure.crm_eur IS 'CRM (EUR): Credit risk mitigation (collateral) deducted from the on-balance exposure, in EUR.';
COMMENT ON PROCEDURE etl.sp_calc_sa_exposure() IS 'Calculates standardised-approach exposure values with CCF and collateral.';
-- @@DB frtb_engine
COMMENT ON TABLE public.ref_risk_weight IS 'Supervisory risk weights per FRTB risk class and sensitivity type.';
COMMENT ON TABLE public.calc_sbm_charge IS 'FRTB sensitivities-based-method charge per group, risk class and sensitivity type.';
COMMENT ON COLUMN public.calc_sbm_charge.sbm_charge_usd IS 'SBM charge (USD): Capital charge in USD: sum of USD sensitivities multiplied by the risk weight.';
COMMENT ON COLUMN public.ref_risk_weight.risk_weight IS 'Risk weight: Supervisory risk weight for the risk class and sensitivity type.';
COMMENT ON PROCEDURE etl.sp_calc_sbm_charge() IS 'Calculates the FRTB sensitivities-based-method charge.';
-- @@DB reporting_db
COMMENT ON TABLE rpt.c0700_facts IS 'COREP C 07.00 credit risk SA cells per exposure class sheet, row and column, in EUR millions.';
COMMENT ON TABLE rpt.c90_facts IS 'COREP C90 sensitivities-based charge per consolidation group, risk class and sensitivity type, in USD.';
COMMENT ON VIEW rpt.v_corep_c90 IS 'COREP C90 report as published: charge rows plus the ALL / ALL total row.';
COMMENT ON COLUMN rpt.c0700_facts.value IS 'Reported value: Reported cell value in EUR millions, one decimal.';
COMMENT ON COLUMN rpt.c0700_facts.col_code IS 'C 07.00 column: C 07.00 column: 0010 original exposure, 0040 net of value adjustments, 0200 exposure value, 0220 of which rated.';
COMMENT ON COLUMN rpt.c90_facts.reported_value_usd IS 'Reported charge (USD): Reported SBM charge in USD.';
COMMENT ON COLUMN rpt.v_corep_c90.reported_value_usd IS 'Reported charge (USD): Reported SBM charge in USD; the ALL / ALL row is the sum of all rows.';
COMMENT ON PROCEDURE etl.sp_load_c0700_facts() IS 'Aggregates SA exposure values into the C 07.00 cells.';
COMMENT ON PROCEDURE etl.sp_load_c90_facts() IS 'Publishes the SBM charge into the C90 report table.';
