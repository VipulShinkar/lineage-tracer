DELETE FROM stg.lcr_param;

INSERT INTO stg.lcr_param (item_code, factor)
SELECT p.item_code,
       p.factor::numeric
FROM raw.lcr_param p;
