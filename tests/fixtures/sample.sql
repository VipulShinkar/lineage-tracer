CREATE TABLE stg.customers AS
SELECT
    c.customer_id,
    c.customer_name,
    c.email
FROM raw.customers c;

WITH active_orders AS (
    SELECT
        o.order_id,
        o.customer_id,
        o.order_total
    FROM raw.orders o
    WHERE o.status = 'ACTIVE'
)
INSERT INTO mart.customer_orders (customer_id, customer_name, order_id, order_total)
SELECT
    stg.customer_id,
    stg.customer_name,
    ao.order_id,
    ao.order_total
FROM stg.customers stg
JOIN active_orders ao
    ON ao.customer_id = stg.customer_id;

MERGE INTO mart.customer_dim AS tgt
USING stg.customers AS src
ON tgt.customer_id = src.customer_id
WHEN MATCHED THEN UPDATE SET tgt.customer_name = src.customer_name
WHEN NOT MATCHED THEN INSERT (customer_id, customer_name) VALUES (src.customer_id, src.customer_name);

UPDATE mart.customer_dim
SET customer_name = raw.customers.customer_name
FROM raw.customers
WHERE mart.customer_dim.customer_id = raw.customers.customer_id;
