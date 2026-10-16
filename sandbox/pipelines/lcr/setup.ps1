# Rebuilds the LCR mart (db lcr_mart on 5432). Idempotent, standalone.
#   powershell -File sandbox/pipelines/lcr/setup.ps1 [-SkipSuperset]
param([switch]$SkipSuperset)
$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $PSScriptRoot))
Set-Location $repo
$env:UV_CACHE_DIR = 'D:\Tools\uv-cache'; $env:TEMP = 'D:\Tools\tmp'; $env:TMP = 'D:\Tools\tmp'
$py = Join-Path $repo '.venv\Scripts\python.exe'
$lcr = 'sandbox/pipelines/lcr'
function Step($m) { Write-Host "`n=== $m" -ForegroundColor Cyan }
function Run($exe, $argList) { & $exe @argList; if ($LASTEXITCODE -ne 0) { throw "failed: $exe $argList" } }
$wslLcr = '/mnt/d/' + ($repo.Substring(3) -replace '\\', '/') + "/$lcr"

Step 'distro up'
& powershell -File scripts/db.ps1
Step 'server csvlog (restarts only if changed)'
Run wsl.exe @('-d', 'Ubuntu-AGE', '-u', 'root', '--', 'bash', "$wslLcr/configure_log.sh")
Step 'create lcr_mart + raw seed'
Run $py @("$lcr/create_db.py")
Run $py @("$lcr/seed_raw.py")
Step 'run pipeline (psql, application_name=lcr_shell)'
Run wsl.exe @('-d', 'Ubuntu-AGE', '-u', 'root', '--', 'bash', "$wslLcr/run_lcr.sh")
if (-not $SkipSuperset) {
    Step 'superset objects'
    Run $py @("$lcr/bootstrap_superset.py")
}
Step 'report file'
Run $py @("$lcr/make_report.py")
Step 'verify'
Run $py @("$lcr/verify.py")
Write-Host "`nlcr_mart ready." -ForegroundColor Green
