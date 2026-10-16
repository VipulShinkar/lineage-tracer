DELETE FROM stg.deposit_account;

INSERT INTO stg.deposit_account (account_id, entity_code, cpty_type, is_operational, insured, balance_usd)
SELECT d.account_id,
       UPPER(d.entity_code),
       UPPER(d.cpty_type),
       d.is_operational = 'Y',
       d.insured = 'Y',
       ROUND(d.balance * fx.rate_to_usd, 2)
FROM raw.deposit_account d
JOIN raw.fx_rate fx
  ON fx.ccy = d.ccy
 AND fx.rate_date = DATE '2026-06-30';
