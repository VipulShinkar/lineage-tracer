# Runs the 4 C90 mappings in order (DTM-style). Usage: powershell -File run_c90.ps1
$ErrorActionPreference = 'Stop'
$here = $PSScriptRoot
$py = Join-Path $here '..\..\..\.venv\Scripts\python.exe'
foreach ($m in 'stg_sensitivity', 'dw_sensitivity_usd', 'calc_sbm_charge', 'rpt_c90_facts') {
    & $py (Join-Path $here 'pmrun.py') (Join-Path $here "m_C90_$m.xml")
    if ($LASTEXITCODE -ne 0) { throw "mapping m_C90_$m failed" }
}
