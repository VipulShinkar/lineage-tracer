# Rebuilds the whole sandbox estate from scratch (drops/recreates only the sandbox databases). Idempotent.
#   powershell -File sandbox/setup.ps1 [-SkipSuperset]
param([switch]$SkipSuperset)
$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
Set-Location $repo
$env:UV_CACHE_DIR = 'D:\Tools\uv-cache'; $env:TEMP = 'D:\Tools\tmp'; $env:TMP = 'D:\Tools\tmp'
$py = Join-Path $repo '.venv\Scripts\python.exe'
function Step($m) { Write-Host "`n=== $m" -ForegroundColor Cyan }
function Run($exe, $argList) { & $exe @argList; if ($LASTEXITCODE -ne 0) { throw "failed: $exe $argList" } }
$wslRepo = '/mnt/d/' + ($repo.Substring(3) -replace '\\', '/')

Step 'database up'
& powershell -File scripts/db.ps1
Step 'postgres config (pg_stat_statements)'
Run wsl.exe @('-d', 'Ubuntu-AGE', '-u', 'root', '--', 'bash', "$wslRepo/sandbox/wsl/configure_pg.sh")
Step 'build estate (roles, DBs, seed, ETL, late collateral reload)'
Run $py @('sandbox/build.py')
Step 'EFR financial lake (port 5433: cluster, build, verify, report)'
Run powershell @('-File', 'sandbox/finlake/setup.ps1', '-SkipSuperset')
if (-not $SkipSuperset) {
    Step 'superset install / service'
    Run wsl.exe @('-d', 'Ubuntu-AGE', '-u', 'root', '--', 'bash', "$wslRepo/sandbox/wsl/install_superset.sh")
    Step 'superset bootstrap'
    Run $py @('sandbox/superset/bootstrap.py')
    Run $py @('sandbox/finlake/bootstrap_superset.py')
}
Step 'C90 as Informatica-style mappings (drops C90 procedures + foreign tables)'
Run powershell @('-File', 'sandbox/pipelines/informatica/setup.ps1')
Step 'EFR lake ETL as PySpark + OpenLineage (drops etl procedures)'
Run powershell @('-File', 'sandbox/pipelines/spark/setup.ps1')
Step 'LCR mart (shell scripts)'
$lcrArgs = @('-File', 'sandbox/pipelines/lcr/setup.ps1'); if ($SkipSuperset) { $lcrArgs += '-SkipSuperset' }
Run powershell $lcrArgs
Step 'verify as lineage_ro (all pipelines)'
Run $py @('sandbox/verify.py')
Step 'report files'
Run $py @('sandbox/reports/make_reports.py')
Write-Host "`nSandbox ready." -ForegroundColor Green
