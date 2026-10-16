# Standalone + idempotent: drops the C90 procedures/foreign tables, runs the 4 PowerCenter-style mappings, verifies.
# Needs the sandbox DBs (sandbox/build.py) to exist. Usage: powershell -File sandbox/pipelines/informatica/setup.ps1
$ErrorActionPreference = 'Stop'
$here = $PSScriptRoot
$repo = (Resolve-Path (Join-Path $here '..\..\..')).Path
Set-Location $repo
$env:UV_CACHE_DIR = 'D:\Tools\uv-cache'; $env:TEMP = 'D:\Tools\tmp'; $env:TMP = 'D:\Tools\tmp'
$py = Join-Path $repo '.venv\Scripts\python.exe'
function Run($exe, $a) { & $exe @a; if ($LASTEXITCODE -ne 0) { throw "failed: $exe $a" } }
& powershell -File scripts/db.ps1
Run $py @("$here\prepare.py")
Run powershell @('-File', "$here\run_c90.ps1")
Run $py @("$here\verify.py")
