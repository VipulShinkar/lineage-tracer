-- Hop 4: warehouse -> regulatory data mart (product mapping T4)
INSERT INTO mart_sa_exposure (exposure_id, counterparty_id, exposure_class, product_code, drawn_amount_eur, undrawn_amount_eur, exposure_value_eur)
SELECT e.exposure_id AS exposure_id,
       e.counterparty_id AS counterparty_id,
       m.exposure_class AS exposure_class,
       e.product_code AS product_code,
       e.drawn_amount_eur AS drawn_amount_eur,
       e.undrawn_amount_eur AS undrawn_amount_eur,
       e.drawn_amount_eur + e.undrawn_amount_eur AS exposure_value_eur
FROM dw_exposure e
JOIN ref_product_class m ON m.product_code = e.product_code;
