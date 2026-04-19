# Wait for the main Phase A run to finish, then launch the reasoning sweep.
# Detached helper so we can leave it unattended.
param(
    [int]$WaitForPid = 9972,
    [string]$WorkDir = 'E:\MASE-demo'
)

Set-Location $WorkDir
$env:PYTHONPATH = "$WorkDir;$WorkDir\src"
$env:PYTHONIOENCODING = "utf-8"

Write-Host "[wrapper] waiting for PID $WaitForPid to exit..."
while ($true) {
    $proc = Get-Process -Id $WaitForPid -ErrorAction SilentlyContinue
    if (-not $proc) { break }
    Start-Sleep -Seconds 30
}
Write-Host "[wrapper] PID $WaitForPid exited at $(Get-Date -Format o); launching reasoning sweep"

python scripts\run_external_phase_a_reasoning.py *>&1 |
    Tee-Object -FilePath scripts\_external_logs\phase_a_reasoning.log
