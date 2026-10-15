-- Hop 3: staging -> warehouse (FX conversion T2, intragroup scope filter T3)
INSERT INTO dw_exposure (exposure_id, drawn_amount_eur, undrawn_amount_eur, orig_currency, counterparty_id, product_code)
SELECT f.facility_id AS exposure_id,
       f.drawn_balance * fx.rate_to_eur AS drawn_amount_eur,
       f.undrawn_limit * fx.rate_to_eur AS undrawn_amount_eur,
       f.currency_code AS orig_currency,
       f.counterparty_id AS counterparty_id,
       f.product_code AS product_code
FROM stg_credit_facilities f
JOIN ref_fx_rates fx ON fx.currency_code = f.currency_code
WHERE f.intragroup_flag = 'N';
