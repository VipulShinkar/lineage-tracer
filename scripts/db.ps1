# Starts the Postgres 18 + Apache AGE database that lives in the Ubuntu-AGE WSL distro (D:\WSL\Ubuntu).
# WSL stops an idle distro, so a hidden `sleep infinity` keeps it (and systemd-managed Postgres) running.
# Connect from Windows with host=127.0.0.1 (not "localhost": ::1 is not forwarded by WSL and hangs).
$running = Get-CimInstance Win32_Process -Filter "Name='wsl.exe'" | Where-Object { $_.CommandLine -like '*Ubuntu-AGE*sleep infinity*' }
if (-not $running) {
    Start-Process wsl.exe -ArgumentList '-d', 'Ubuntu-AGE', '-u', 'root', '--exec', 'sleep', 'infinity' -WindowStyle Hidden
}
foreach ($i in 1..30) {
    if ((Test-NetConnection 127.0.0.1 -Port 5432 -WarningAction SilentlyContinue).TcpTestSucceeded) { "Postgres ready on 127.0.0.1:5432"; exit 0 }
    Start-Sleep -Seconds 1
}
Write-Error "Postgres did not come up on 127.0.0.1:5432"; exit 1
