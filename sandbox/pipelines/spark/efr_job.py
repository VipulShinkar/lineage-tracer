"""EFR credit-risk lake load as a PySpark job (replaces the etl.sp_load_* procedures).
raw -> stg -> core (dims + facts) -> rpt over JDBC; one Spark write (= one OpenLineage job/run) per target table.
Run inside WSL:  /opt/spark-venv/bin/python efr_job.py   (events: sandbox/openlineage/spark/efr_events.ndjson)"""
import glob
from pathlib import Path

from pyspark.sql import SparkSession

REPO = str(Path(__file__).resolve().parents[3])
EVENTS = f"{REPO}/sandbox/openlineage/spark/efr_events.ndjson"
URL = "jdbc:postgresql://127.0.0.1:5433/fin_lake?ApplicationName=spark_efr"
DB = {"user": "etl_owner", "password": "etl_owner", "driver": "org.postgresql.Driver"}

Path(EVENTS).parent.mkdir(parents=True, exist_ok=True)
Path(EVENTS).unlink(missing_ok=True)
spark = (SparkSession.builder.master("local[2]").appName("efr_credit_risk")
         .config("spark.driver.memory", "1g").config("spark.sql.shuffle.partitions", "2").config("spark.ui.enabled", "false")
         .config("spark.jars", ",".join(glob.glob("/opt/spark-jars/*.jar")))
         .config("spark.extraListeners", "io.openlineage.spark.agent.OpenLineageSparkListener")
         .config("spark.openlineage.transport.type", "file")
         .config("spark.openlineage.transport.location", EVENTS)
         .config("spark.openlineage.namespace", "efr_spark")
         .getOrCreate())
spark.sparkContext.setLogLevel("ERROR")

# LOADS = (target, SQL) in dependency order; upstream tables are read back over JDBC (view name = schema_table)
LOADS = [
# ------------------------------------------------------------------ raw -> stg
("stg.entity", """
SELECT UPPER(TRIM(e.entity_code)) AS entity_code, TRIM(e.entity_name) AS entity_name, e.country, e.consolidation_group
FROM raw_entity e"""),

("stg.counterparty", """
-- dedupe: keep the latest delivery per counterparty; flag intragroup
SELECT d.cpty_id, TRIM(d.cpty_name) AS cpty_name, d.country, UPPER(d.sector_code) AS sector_code,
       (d.is_intragroup = 'Y') AS is_intragroup
FROM (SELECT c.*, ROW_NUMBER() OVER (PARTITION BY c.cpty_id ORDER BY c._loaded_at DESC) AS rn FROM raw_counterparty c) d
WHERE d.rn = 1"""),

("stg.rating", """
-- latest rating per counterparty
SELECT d.cpty_id, UPPER(d.rating_grade) AS rating_grade, CAST(d.rating_date AS DATE) AS rating_date, d.agency
FROM (SELECT r.*, ROW_NUMBER() OVER (PARTITION BY r.cpty_id ORDER BY r.rating_date DESC) AS rn FROM raw_rating r) d
WHERE d.rn = 1"""),

("stg.loan", """
-- drawn amount = principal + accrued interest - impairment (transaction currency)
SELECT l.contract_id, UPPER(l.entity_code) AS entity_code, l.cpty_id, UPPER(l.product_code) AS product_code, l.ccy,
       CAST(l.principal AS DECIMAL(20,2)) + CAST(l.accrued_int AS DECIMAL(20,2)) - CAST(l.impairment AS DECIMAL(20,2)) AS drawn_amt,
       CAST(l.undrawn_limit AS DECIMAL(20,2)) AS undrawn_amt,
       CAST(l.start_date AS DATE) AS start_date, CAST(l.maturity_date AS DATE) AS maturity_date
FROM raw_loan_contract l"""),

("stg.collateral", """
SELECT c.collateral_id, c.contract_id, c.collateral_type, c.ccy, CAST(c.market_value AS DECIMAL(20,2)) AS market_value
FROM raw_collateral c"""),

("stg.credit_limit", """
SELECT UPPER(l.entity_code) AS entity_code, UPPER(l.sector_code) AS sector_code,
       CAST(l.limit_amount AS DECIMAL(20,2)) AS limit_amount, l.ccy
FROM raw_credit_limit l"""),

("stg.fx_rate", """
SELECT f.ccy, CAST(f.rate_date AS DATE) AS rate_date, CAST(f.rate_to_usd AS DECIMAL(18,8)) AS rate_to_usd
FROM raw_fx_rate f"""),

# ------------------------------------------------------------------ stg -> core
("core.dim_date", """
SELECT d AS date_key, YEAR(d) AS year, QUARTER(d) AS quarter, MONTH(d) AS month, (d = LAST_DAY(d)) AS is_month_end
FROM (SELECT EXPLODE(SEQUENCE(DATE '2026-01-01', DATE '2026-12-31', INTERVAL 1 DAY)) AS d)"""),

("core.dim_entity", """
SELECT CAST(ROW_NUMBER() OVER (ORDER BY e.entity_code) AS INT) AS entity_key,
       e.entity_code, e.entity_name, e.country, e.consolidation_group
FROM stg_entity e"""),

("core.dim_counterparty", """
-- portfolio derived from the sector code
SELECT CAST(ROW_NUMBER() OVER (ORDER BY c.cpty_id) AS INT) AS cpty_key,
       c.cpty_id, c.cpty_name, c.country, c.sector_code,
       CASE c.sector_code WHEN 'SOV' THEN 'Sovereigns' WHEN 'BNK' THEN 'Banks' WHEN 'CORP' THEN 'Corporates'
                          WHEN 'RET' THEN 'Retail' ELSE 'Other' END AS portfolio,
       c.is_intragroup
FROM stg_counterparty c"""),

("core.dim_rating", """
-- grade -> probability of default and loss-given-default band ('NR' = not rated)
SELECT CAST(ROW_NUMBER() OVER (ORDER BY g.rating_grade) AS INT) AS rating_key, g.rating_grade,
       CAST(CASE g.rating_grade WHEN 'AAA' THEN 0.0003 WHEN 'AA' THEN 0.0006 WHEN 'A' THEN 0.0015 WHEN 'BBB' THEN 0.0050
                                WHEN 'BB' THEN 0.0200 WHEN 'B' THEN 0.0600 WHEN 'CCC' THEN 0.2000 ELSE 0.0300 END AS DECIMAL(9,6)) AS pd,
       CAST(CASE WHEN g.rating_grade IN ('AAA', 'AA', 'A') THEN 0.35 WHEN g.rating_grade IN ('BBB', 'BB') THEN 0.45
                 ELSE 0.55 END AS DECIMAL(9,6)) AS lgd
FROM (SELECT r.rating_grade FROM stg_rating r UNION SELECT 'NR' AS rating_grade) g"""),

("core.dim_product", """
SELECT CAST(ROW_NUMBER() OVER (ORDER BY p.product_code) AS INT) AS product_key, p.product_code,
       CAST(CASE p.product_code WHEN 'RCF' THEN 0.50 WHEN 'TRADE' THEN 0.20 ELSE 1.00 END AS DECIMAL(9,4)) AS ccf,
       CAST(CASE p.product_code WHEN 'GUAR' THEN 1.00 WHEN 'TRADE' THEN 0.50 WHEN 'RCF' THEN 0.80 ELSE 0.90 END AS DECIMAL(9,4)) AS risk_weight_base
FROM (SELECT DISTINCT l.product_code FROM stg_loan l) p"""),

("core.fact_exposure", """
-- EAD = drawn + CCF x undrawn (USD at the 30-Jun-2026 rate); RWA = EAD x risk weight; EL = PD x LGD x EAD; intragroup excluded
WITH base AS (
    SELECT e.entity_key, c.cpty_key, p.product_key, dr.rating_key, l.contract_id,
           ROUND(l.drawn_amt   * fx.rate_to_usd, 2) AS drawn_usd,
           ROUND(l.undrawn_amt * fx.rate_to_usd, 2) AS undrawn_usd,
           p.ccf, p.risk_weight_base AS risk_weight, dr.pd, dr.lgd
    FROM stg_loan l
    JOIN stg_fx_rate fx          ON fx.ccy = l.ccy AND fx.rate_date = DATE '2026-06-30'
    JOIN core_dim_entity e       ON e.entity_code = l.entity_code
    JOIN core_dim_counterparty c ON c.cpty_id = l.cpty_id
    JOIN core_dim_product p      ON p.product_code = l.product_code
    LEFT JOIN stg_rating r       ON r.cpty_id = l.cpty_id
    JOIN core_dim_rating dr      ON dr.rating_grade = COALESCE(r.rating_grade, 'NR')
    WHERE c.is_intragroup = FALSE
),
coll AS (
    SELECT k.contract_id, SUM(ROUND(k.market_value * fx.rate_to_usd, 2)) AS collateral_usd
    FROM stg_collateral k
    JOIN stg_fx_rate fx ON fx.ccy = k.ccy AND fx.rate_date = DATE '2026-06-30'
    GROUP BY k.contract_id
)
SELECT DATE '2026-06-30' AS as_of, b.entity_key, b.cpty_key, b.product_key, b.rating_key,
       b.drawn_usd, b.undrawn_usd, b.ccf,
       ROUND(b.drawn_usd + b.ccf * b.undrawn_usd, 2) AS ead_usd,
       b.risk_weight,
       ROUND((b.drawn_usd + b.ccf * b.undrawn_usd) * b.risk_weight, 2) AS rwa_usd,
       b.pd, b.lgd,
       ROUND(b.pd * b.lgd * (b.drawn_usd + b.ccf * b.undrawn_usd), 2) AS el_usd,
       COALESCE(k.collateral_usd, 0) AS collateral_usd
FROM base b LEFT JOIN coll k ON k.contract_id = b.contract_id"""),

("core.fact_limit", """
SELECT DATE '2026-06-30' AS as_of, e.entity_key,
       CASE l.sector_code WHEN 'SOV' THEN 'Sovereigns' WHEN 'BNK' THEN 'Banks' WHEN 'CORP' THEN 'Corporates'
                          WHEN 'RET' THEN 'Retail' ELSE 'Other' END AS portfolio,
       ROUND(l.limit_amount * fx.rate_to_usd, 2) AS limit_usd
FROM stg_credit_limit l
JOIN core_dim_entity e ON e.entity_code = l.entity_code
JOIN stg_fx_rate fx    ON fx.ccy = l.ccy AND fx.rate_date = DATE '2026-06-30'"""),

# ------------------------------------------------------------------ core -> rpt
("rpt.efr_credit_risk_summary", """
-- USD millions, 2 dp
WITH expo AS (
    SELECT f.entity_key, c.portfolio, SUM(f.ead_usd) AS ead_usd, SUM(f.rwa_usd) AS rwa_usd, SUM(f.el_usd) AS el_usd
    FROM core_fact_exposure f JOIN core_dim_counterparty c ON c.cpty_key = f.cpty_key
    GROUP BY f.entity_key, c.portfolio
),
lim AS (
    SELECT l.entity_key, l.portfolio, SUM(l.limit_usd) AS limit_usd FROM core_fact_limit l GROUP BY l.entity_key, l.portfolio
)
SELECT e.entity_code AS entity, 'CREDIT' AS risk_type, x.portfolio,
       ROUND(x.ead_usd / 1000000, 2) AS exposure_ead, ROUND(x.rwa_usd / 1000000, 2) AS rwa,
       ROUND(x.el_usd / 1000000, 2) AS expected_loss, ROUND(l.limit_usd / 1000000, 2) AS limit_amount,
       DATE '2026-06-30' AS as_of
FROM expo x
JOIN core_dim_entity e ON e.entity_key = x.entity_key
LEFT JOIN lim l        ON l.entity_key = x.entity_key AND l.portfolio = x.portfolio"""),
]

TABLES = ("raw.entity raw.counterparty raw.rating raw.loan_contract raw.collateral raw.credit_limit raw.fx_rate "
          "stg.entity stg.counterparty stg.rating stg.loan stg.collateral stg.credit_limit stg.fx_rate "
          "core.dim_entity core.dim_counterparty core.dim_rating core.dim_product core.fact_exposure core.fact_limit").split()

for target, sql in LOADS:
    for t in TABLES:  # (re)register JDBC-backed views so each load reads its upstream from the database
        if t.replace(".", "_") + " " in sql.replace("\n", " ") + " ":
            spark.read.jdbc(URL, t, properties=DB).createOrReplaceTempView(t.replace(".", "_"))
    df = spark.sql(sql)
    df.write.jdbc(URL, target, mode="overwrite", properties={**DB, "truncate": "true"})  # one action = one OL run
    print("loaded", target, flush=True)
spark.stop()
