# Rebuilds the EFR financial lake (cluster finlake, port 5433, db fin_lake). Idempotent; leaves the 5432 sandbox untouched.
#   powershell -File sandbox/finlake/setup.ps1 [-SkipSuperset]
param([switch]$SkipSuperset)
$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
Set-Location $repo
$env:UV_CACHE_DIR = 'D:\Tools\uv-cache'; $env:TEMP = 'D:\Tools\tmp'; $env:TMP = 'D:\Tools\tmp'
$py = Join-Path $repo '.venv\Scripts\python.exe'
function Step($m) { Write-Host "`n=== $m" -ForegroundColor Cyan }
function Run($exe, $argList) { & $exe @argList; if ($LASTEXITCODE -ne 0) { throw "failed: $exe $argList" } }
$wslRepo = '/mnt/d/' + ($repo.Substring(3) -replace '\\', '/')

Step 'distro up'
& powershell -File scripts/db.ps1
Step 'finlake cluster (port 5433, shared_buffers 128MB)'
Run wsl.exe @('-d', 'Ubuntu-AGE', '-u', 'root', '--', 'bash', "$wslRepo/sandbox/finlake/create_cluster.sh")
Step 'build fin_lake'
Run $py @('sandbox/finlake/build.py')
Step 'verify as lineage_ro'
Run $py @('sandbox/finlake/verify.py')
if (-not $SkipSuperset) {
    Step 'superset objects'
    Run $py @('sandbox/finlake/bootstrap_superset.py')
}
Step 'report file'
Run $py @('sandbox/finlake/make_report.py')
Write-Host "`nfin_lake ready." -ForegroundColor Green
