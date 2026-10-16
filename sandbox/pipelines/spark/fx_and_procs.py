"""fin_lake housekeeping around the Spark job. Usage: fx_and_procs.py reset|post
reset: raw GBP/INR 30-Jun rates back to the original values (so reruns are idempotent).
post : drop etl.sp_* procedures (Spark replaced them) and restate the GBP/INR 30-Jun rates x1.015 in raw WITHOUT reloading stg."""
import sys

import psycopg

with psycopg.connect("host=127.0.0.1 port=5433 user=etl_owner password=etl_owner dbname=fin_lake", autocommit=True) as c:
    if sys.argv[1] == "reset":
        c.execute("UPDATE raw.fx_rate SET rate_to_usd = CASE ccy WHEN 'GBP' THEN '1.270000' ELSE '0.012000' END "
                  "WHERE ccy IN ('GBP', 'INR') AND rate_date = '2026-06-30'")
    else:
        c.execute("DO $$ DECLARE p regprocedure; BEGIN FOR p IN SELECT oid::regprocedure FROM pg_proc WHERE pronamespace = 'etl'::regnamespace "
                  "AND prokind = 'p' LOOP EXECUTE 'DROP PROCEDURE ' || p; END LOOP; END $$")
        c.execute("UPDATE raw.fx_rate SET rate_to_usd = ROUND(rate_to_usd::numeric * 1.015, 6)::text "
                  "WHERE ccy IN ('GBP', 'INR') AND rate_date = '2026-06-30'")
print("fx_and_procs", sys.argv[1], "ok")
