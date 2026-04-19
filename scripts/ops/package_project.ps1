param(
    [string]$OutputDir = "E:\MASE-demo\dist"
)

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = (Resolve-Path (Join-Path $scriptDir "..\\..")).Path
$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$stagingDir = Join-Path $env:TEMP "mase-package-$timestamp"
$zipPath = Join-Path $OutputDir "MASE-demo-benchmark-ready-$timestamp.zip"

$excludeNames = @("__pycache__", ".pytest_cache", "memory_runs", "dist", "archives")
$excludeExtensions = @(".pyc")

if (Test-Path $stagingDir) {
    Remove-Item $stagingDir -Recurse -Force
}
New-Item -ItemType Directory -Path $stagingDir | Out-Null
New-Item -ItemType Directory -Path $OutputDir -Force | Out-Null

Get-ChildItem $projectRoot -Force | Where-Object {
    $excludeNames -notcontains $_.Name
} | ForEach-Object {
    Copy-Item $_.FullName -Destination (Join-Path $stagingDir $_.Name) -Recurse -Force
}

Get-ChildItem $stagingDir -Recurse -File | Where-Object {
    $excludeExtensions -contains $_.Extension
} | Remove-Item -Force

if (Test-Path $zipPath) {
    Remove-Item $zipPath -Force
}

Compress-Archive -Path (Join-Path $stagingDir "*") -DestinationPath $zipPath -Force
Remove-Item $stagingDir -Recurse -Force

Write-Output $zipPath
