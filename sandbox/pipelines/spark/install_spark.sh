#!/bin/bash
# Idempotent: Java 17, venv with pyspark 3.5, JDBC + OpenLineage jars (all inside WSL, on D:). Run as root.
set -e
OL=1.49.0; PG=42.7.4
command -v java >/dev/null || { apt-get update -qq; DEBIAN_FRONTEND=noninteractive apt-get install -y -qq openjdk-17-jre-headless; }
[ -x /opt/spark-venv/bin/python ] || python3 -m venv /opt/spark-venv
/opt/spark-venv/bin/python -c "import pyspark" 2>/dev/null || /opt/spark-venv/bin/pip install -q "pyspark==3.5.*"
mkdir -p /opt/spark-jars; cd /opt/spark-jars
M=https://repo1.maven.org/maven2
[ -s postgresql-$PG.jar ] || curl -fsSL -o postgresql-$PG.jar $M/org/postgresql/postgresql/$PG/postgresql-$PG.jar
[ -s openlineage-spark_2.12-$OL.jar ] || curl -fsSL -o openlineage-spark_2.12-$OL.jar $M/io/openlineage/openlineage-spark_2.12/$OL/openlineage-spark_2.12-$OL.jar
/opt/spark-venv/bin/python -c "import pyspark;print('pyspark',pyspark.__version__)"; ls -la /opt/spark-jars; du -sh /opt/spark-venv /opt/spark-jars
