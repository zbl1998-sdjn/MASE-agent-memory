param(
    [int]$Port = $(if ($env:MASE_PLATFORM_PORT) { [int]$env:MASE_PLATFORM_PORT } else { 8765 }),
    [string]$HostName = "127.0.0.1",
    [switch]$ReadOnly
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$root = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
$frontend = Join-Path $root "frontend"
$packageJson = Join-Path $frontend "package.json"
$serverEntry = Join-Path $root "integrations\openai_compat\server.py"
$platformUrl = "http://${HostName}:$Port"

if (-not (Test-Path -LiteralPath $packageJson -PathType Leaf)) {
    throw "Frontend package.json not found: $packageJson"
}

if (-not (Test-Path -LiteralPath $serverEntry -PathType Leaf)) {
    throw "Backend server entry not found: $serverEntry"
}

Write-Host "Installing frontend dependencies in $frontend"
npm --prefix $frontend install

Write-Host "Building frontend"
npm --prefix $frontend run build

Write-Host "Starting MASE platform at $platformUrl"
Write-Host "Backend binds to ${HostName}:$Port via integrations.openai_compat.server"
$env:MASE_PLATFORM_PORT = [string]$Port
$env:MASE_PLATFORM_HOST = $HostName
if ($ReadOnly) {
    $env:MASE_READ_ONLY = "1"
}
Push-Location -LiteralPath $root
try {
    python -m integrations.openai_compat.server
}
finally {
    Pop-Location
}
