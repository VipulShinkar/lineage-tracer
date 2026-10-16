# EFR lake ETL as PySpark + OpenLineage. Standalone, idempotent. Needs fin_lake built (sandbox/finlake/setup.ps1) and the lineage DB up.
#   powershell -File sandbox/pipelines/spark/setup.ps1
$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $PSScriptRoot))
Set-Location $repo
$py = Join-Path $repo '.venv\Scripts\python.exe'
function Step($m) { Write-Host "`n=== $m" -ForegroundColor Cyan }
function Run($exe, $argList) { & $exe @argList; if ($LASTEXITCODE -ne 0) { throw "failed: $exe $argList" } }
$wslDir = '/mnt/d/' + ($PSScriptRoot.Substring(3).Replace([string][char]92, '/'))

Step 'distro up'
& powershell -File scripts/db.ps1
Step 'install Spark in WSL if missing'
wsl.exe -d Ubuntu-AGE -u root -- bash -c 'test -x /opt/spark-venv/bin/python && command -v java >/dev/null && ls /opt/spark-jars/openlineage-spark_2.12-*.jar >/dev/null 2>&1'
if ($LASTEXITCODE -ne 0) { Run wsl.exe @('-d', 'Ubuntu-AGE', '-u', 'root', '--', 'bash', "$wslDir/install_spark.sh") }
Step 'reset raw FX (idempotent rerun)'
Run $py @("$PSScriptRoot\fx_and_procs.py", 'reset')
Step 'run PySpark job (local[2], 1g) -> events'
Run wsl.exe @('-d', 'Ubuntu-AGE', '-u', 'root', '--', 'bash', "$wslDir/run_job.sh")
Step 'drop etl procedures, restate FX in raw (stg not reloaded)'
Run $py @("$PSScriptRoot\fx_and_procs.py", 'post')
Step 'ingest OpenLineage events into the lineage DB'
Run $py @("$PSScriptRoot\ingest_events.py")
Write-Host "`nSpark EFR pipeline ready." -ForegroundColor Green
