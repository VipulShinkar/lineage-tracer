#!/bin/bash
# runs the PySpark job inside WSL; Spark's noisy stderr goes to a log so PowerShell does not treat it as an error
R=$(cd "$(dirname "$0")/../../.." && pwd)
L=$R/sandbox/openlineage/spark; mkdir -p $L
/opt/spark-venv/bin/python $R/sandbox/pipelines/spark/efr_job.py > $L/job.log 2>&1 || { tail -30 $L/job.log; exit 1; }
grep '^loaded' $L/job.log | wc -l
