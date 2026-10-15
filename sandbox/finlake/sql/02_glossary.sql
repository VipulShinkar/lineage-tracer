-- Business glossary (BCBS 239 style definitions) as catalog comments; part of the model, applied by build.py after 01_model.sql.

-- ================= raw
COMMENT ON TABLE raw.entity IS 'Legal entities of the reporting group as delivered by the entity master; starting point (source of record) for entity attributes.';
COMMENT ON TABLE raw.counterparty IS 'Counterparty master as delivered by the client onboarding system; may contain several deliveries per counterparty.';
COMMENT ON TABLE raw.rating IS 'External/internal credit rating history per counterparty as delivered by the rating source.';
COMMENT ON TABLE raw.loan_contract IS 'Loan and commitment contracts as booked in the lending system; source of drawn and undrawn amounts. Amounts are text as delivered.';
COMMENT ON TABLE raw.collateral IS 'Collateral pledged against loan contracts, valued in the contract currency.';
COMMENT ON TABLE raw.credit_limit IS 'Approved credit risk appetite limits per legal entity and counterparty sector, in the entity currency.';
COMMENT ON TABLE raw.fx_rate IS 'Daily foreign exchange rates to USD from the market data feed; source of record for currency conversion.';
COMMENT ON TABLE raw.gl_balance IS 'General ledger balances per entity, account and currency; used for the completeness check against loan principal.';
COMMENT ON COLUMN raw.loan_contract.principal IS 'Principal: Outstanding principal drawn by the borrower, in contract currency.';
COMMENT ON COLUMN raw.loan_contract.undrawn_limit IS 'Undrawn limit: Committed but undrawn amount available to the borrower, in contract currency.';
COMMENT ON COLUMN raw.loan_contract.accrued_int IS 'Accrued interest: Interest accrued and not yet paid, in contract currency.';
COMMENT ON COLUMN raw.loan_contract.impairment IS 'Impairment: Specific impairment (value adjustment) recognised against the contract, in contract currency.';
COMMENT ON COLUMN raw.loan_contract.product_code IS 'Product type: Product type: TERM loan, RCF revolving facility, GUAR guarantee, TRADE trade finance.';
COMMENT ON COLUMN raw.loan_contract.ccy IS 'Contract currency: ISO currency of the contract.';
COMMENT ON COLUMN raw.fx_rate.rate_to_usd IS 'FX rate to USD: Units of USD per one unit of the currency on the rate date.';
COMMENT ON COLUMN raw.counterparty.sector_code IS 'Counterparty sector: Counterparty sector: SOV sovereign, BNK bank, CORP corporate, RET retail.';
COMMENT ON COLUMN raw.counterparty.is_intragroup IS 'Intragroup flag: Y when the counterparty belongs to the same consolidation group.';
COMMENT ON COLUMN raw.credit_limit.limit_amount IS 'Approved limit: Approved limit in the currency given in ccy.';

-- ================= stg
COMMENT ON TABLE stg.entity IS 'Cleaned legal entity list (codes standardised to upper case).';
COMMENT ON TABLE stg.counterparty IS 'Deduplicated counterparty master (latest delivery wins) with the intragroup indicator as a boolean.';
COMMENT ON TABLE stg.rating IS 'Latest rating per counterparty, typed and upper-cased.';
COMMENT ON TABLE stg.loan IS 'Typed loan contracts with drawn and undrawn amounts in transaction currency.';
COMMENT ON TABLE stg.collateral IS 'Typed collateral valuations in transaction currency.';
COMMENT ON TABLE stg.credit_limit IS 'Typed credit limits per entity and sector in the entity currency.';
COMMENT ON TABLE stg.fx_rate IS 'Typed daily FX rates to USD used for all currency conversion in the warehouse.';
COMMENT ON COLUMN stg.loan.drawn_amt IS 'Drawn balance: Drawn balance in transaction currency: principal plus accrued interest minus impairment.';
COMMENT ON COLUMN stg.loan.undrawn_amt IS 'Undrawn commitment: Undrawn commitment in transaction currency.';
COMMENT ON COLUMN stg.loan.product_code IS 'Product type: Standardised product type used to look up the credit conversion factor and risk weight.';
COMMENT ON COLUMN stg.fx_rate.rate_to_usd IS 'FX rate to USD: Units of USD per one unit of the currency on the rate date.';
COMMENT ON COLUMN stg.counterparty.sector_code IS 'Counterparty sector: Counterparty sector code used to derive the regulatory portfolio.';
COMMENT ON COLUMN stg.counterparty.is_intragroup IS 'Intragroup flag: TRUE when the counterparty is a group company; such exposures are excluded from external credit risk reporting.';
COMMENT ON COLUMN stg.credit_limit.limit_amount IS 'Approved limit: Approved limit in the entity currency.';

-- ================= core
COMMENT ON TABLE core.dim_date IS 'Calendar dimension for the reporting year.';
COMMENT ON TABLE core.dim_entity IS 'Reporting legal entity dimension.';
COMMENT ON TABLE core.dim_counterparty IS 'Counterparty dimension with the regulatory portfolio (Sovereigns, Banks, Corporates, Retail) and the intragroup indicator.';
COMMENT ON TABLE core.dim_rating IS 'Rating grade dimension mapping each grade to a probability of default and a loss-given-default band; NR = not rated.';
COMMENT ON TABLE core.dim_product IS 'Product dimension carrying the credit conversion factor and base risk weight per product type.';
COMMENT ON TABLE core.fact_exposure IS 'Credit exposure fact at contract grain on the reporting date, in USD: drawn, undrawn, EAD, RWA and expected loss. Intragroup excluded.';
COMMENT ON TABLE core.fact_limit IS 'Approved credit limits per entity and portfolio on the reporting date, in USD.';
COMMENT ON COLUMN core.dim_counterparty.portfolio IS 'Portfolio: Regulatory portfolio derived from the sector code: SOV Sovereigns, BNK Banks, CORP Corporates, RET Retail.';
COMMENT ON COLUMN core.dim_counterparty.is_intragroup IS 'Intragroup flag: TRUE when the counterparty belongs to the group; excluded from exposure.';
COMMENT ON COLUMN core.dim_entity.entity_code IS 'Entity: Code of the reporting legal entity (e.g. ENT-UK).';
COMMENT ON COLUMN core.dim_rating.pd IS 'PD: Probability of default over one year for the rating grade.';
COMMENT ON COLUMN core.dim_rating.lgd IS 'LGD: Loss given default (fraction of exposure lost on default) for the rating grade band.';
COMMENT ON COLUMN core.dim_product.ccf IS 'CCF: Credit Conversion Factor applied to undrawn commitments (CRR Art. 111).';
COMMENT ON COLUMN core.dim_product.risk_weight_base IS 'Base risk weight: Base risk weight applied to EAD to derive risk-weighted assets.';
COMMENT ON COLUMN core.fact_exposure.drawn_usd IS 'Drawn (USD): Drawn balance in USD, converted at the reporting-date FX rate.';
COMMENT ON COLUMN core.fact_exposure.undrawn_usd IS 'Undrawn (USD): Undrawn commitment in USD, converted at the reporting-date FX rate.';
COMMENT ON COLUMN core.fact_exposure.ccf IS 'CCF: Credit conversion factor applied to the undrawn commitment.';
COMMENT ON COLUMN core.fact_exposure.ead_usd IS 'EAD (USD): Exposure at Default in USD: drawn balance plus CCF-weighted undrawn commitment, converted at the reporting-date FX rate; intragroup excluded.';
COMMENT ON COLUMN core.fact_exposure.risk_weight IS 'Risk weight: Risk weight applied to EAD.';
COMMENT ON COLUMN core.fact_exposure.rwa_usd IS 'RWA (USD): Risk-weighted assets in USD: EAD multiplied by the risk weight.';
COMMENT ON COLUMN core.fact_exposure.pd IS 'PD: Probability of default of the counterparty rating grade.';
COMMENT ON COLUMN core.fact_exposure.lgd IS 'LGD: Loss given default of the counterparty rating grade.';
COMMENT ON COLUMN core.fact_exposure.el_usd IS 'Expected loss (USD): Expected loss in USD: PD multiplied by LGD multiplied by EAD.';
COMMENT ON COLUMN core.fact_exposure.collateral_usd IS 'Collateral (USD): Market value of collateral pledged against the contract, in USD (informational, not deducted from EAD).';
COMMENT ON COLUMN core.fact_limit.limit_usd IS 'Limit (USD): Approved credit risk appetite limit in USD at the reporting-date FX rate.';

-- ================= rpt
COMMENT ON TABLE rpt.efr_credit_risk_summary IS 'Enterprise Financial Risk credit risk summary per entity and portfolio in USD millions (BCBS 239 report data).';
COMMENT ON VIEW rpt.v_efr_credit_risk_summary IS 'EFR Credit Risk Summary as published: entity/portfolio rows plus the GROUP total row, with limit utilisation.';
COMMENT ON VIEW rpt.v_gl_completeness IS 'Completeness check: loan principal in the lake compared with the general ledger loan balance per entity and currency.';
COMMENT ON COLUMN rpt.efr_credit_risk_summary.entity IS 'Entity: Reporting legal entity code.';
COMMENT ON COLUMN rpt.efr_credit_risk_summary.portfolio IS 'Portfolio: Regulatory portfolio of the counterparties.';
COMMENT ON COLUMN rpt.efr_credit_risk_summary.exposure_ead IS 'EAD (USD m): Exposure at Default in USD millions: sum of EAD, intragroup excluded.';
COMMENT ON COLUMN rpt.efr_credit_risk_summary.rwa IS 'RWA (USD m): Risk-weighted assets in USD millions.';
COMMENT ON COLUMN rpt.efr_credit_risk_summary.expected_loss IS 'Expected loss (USD m): Expected loss in USD millions (PD x LGD x EAD).';
COMMENT ON COLUMN rpt.efr_credit_risk_summary.limit_amount IS 'Limit (USD m): Approved credit risk appetite limit in USD millions.';
COMMENT ON COLUMN rpt.v_efr_credit_risk_summary.exposure_ead IS 'EAD (USD m): Exposure at Default in USD millions; the GROUP row is the sum over all entities and portfolios.';
COMMENT ON COLUMN rpt.v_efr_credit_risk_summary.rwa IS 'RWA (USD m): Risk-weighted assets in USD millions.';
COMMENT ON COLUMN rpt.v_efr_credit_risk_summary.expected_loss IS 'Expected loss (USD m): Expected loss in USD millions (PD x LGD x EAD).';
COMMENT ON COLUMN rpt.v_efr_credit_risk_summary.limit_amount IS 'Limit (USD m): Approved credit risk appetite limit in USD millions.';
COMMENT ON COLUMN rpt.v_efr_credit_risk_summary.utilisation_pct IS 'Limit utilisation: Limit utilisation: exposure at default divided by the approved limit, in percent.';

-- ================= etl procedures
COMMENT ON PROCEDURE etl.sp_load_stg_entity() IS 'Standardises the legal entity master for downstream use.';
COMMENT ON PROCEDURE etl.sp_load_stg_counterparty() IS 'Deduplicates counterparties (latest delivery wins) and flags intragroup counterparties.';
COMMENT ON PROCEDURE etl.sp_load_stg_rating() IS 'Selects the latest rating per counterparty.';
COMMENT ON PROCEDURE etl.sp_load_stg_loan() IS 'Types loan contracts and derives the drawn amount net of impairment and including accrued interest.';
COMMENT ON PROCEDURE etl.sp_load_stg_collateral() IS 'Types collateral valuations.';
COMMENT ON PROCEDURE etl.sp_load_stg_credit_limit() IS 'Types approved credit limits.';
COMMENT ON PROCEDURE etl.sp_load_stg_fx_rate() IS 'Types FX rates used for USD conversion.';
COMMENT ON PROCEDURE etl.sp_load_core_dim_date() IS 'Generates the calendar dimension.';
COMMENT ON PROCEDURE etl.sp_load_core_dim_entity() IS 'Builds the reporting entity dimension.';
COMMENT ON PROCEDURE etl.sp_load_core_dim_counterparty() IS 'Builds the counterparty dimension and derives the regulatory portfolio from the sector.';
COMMENT ON PROCEDURE etl.sp_load_core_dim_rating() IS 'Maps rating grades to probability of default and loss-given-default bands.';
COMMENT ON PROCEDURE etl.sp_load_core_dim_product() IS 'Assigns credit conversion factors and base risk weights per product type.';
COMMENT ON PROCEDURE etl.sp_load_core_fact_exposure() IS 'Computes EAD, RWA and expected loss per contract in USD at the reporting-date FX rate, excluding intragroup.';
COMMENT ON PROCEDURE etl.sp_load_core_fact_limit() IS 'Converts approved limits to USD per entity and portfolio.';
COMMENT ON PROCEDURE etl.sp_load_rpt_efr() IS 'Aggregates exposure, RWA, expected loss and limits per entity and portfolio into USD millions for the EFR report.';
