# LUNA Desktop Executive Launch Script (PowerShell)
Write-Host "🌙 Launching LUNA Autonomous Executive GUI..." -ForegroundColor Cyan

# Use $PSScriptRoot to resolve paths regardless of CWD
$projectRoot = Split-Path $PSScriptRoot -Parent

$python = Join-Path $projectRoot ".venv\Scripts\python.exe"
$runUi   = Join-Path $projectRoot "native_ui\run_ui.py"

if (-not (Test-Path $python)) {
    Write-Host "❌ Python venv not found at: $python" -ForegroundColor Red
    Write-Host "   Run: python -m venv .venv  (from $projectRoot)" -ForegroundColor Yellow
    exit 1
}

if (-not (Test-Path $runUi)) {
    Write-Host "❌ run_ui.py not found at: $runUi" -ForegroundColor Red
    exit 1
}

Write-Host "Python : $python" -ForegroundColor DarkGray
Write-Host "Script : $runUi"  -ForegroundColor DarkGray

Set-Location $projectRoot
& $python $runUi
