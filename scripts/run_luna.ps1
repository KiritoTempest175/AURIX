# AURIX Desktop Executive Launch Script (PowerShell)
Write-Host "🚀 Launching AURIX Autonomous Executive GUI..." -ForegroundColor Cyan

# Use $PSScriptRoot to resolve paths regardless of CWD
$projectRoot = Split-Path $PSScriptRoot -Parent

$python = Join-Path $projectRoot ".venv\Scripts\python.exe"
$frontend = Join-Path $projectRoot "frontend.py"

if (-not (Test-Path $python)) {
    Write-Host "❌ Python venv not found at: $python" -ForegroundColor Red
    Write-Host "   Run: python -m venv .venv  (from $projectRoot)" -ForegroundColor Yellow
    exit 1
}

if (-not (Test-Path $frontend)) {
    Write-Host "❌ frontend.py not found at: $frontend" -ForegroundColor Red
    exit 1
}

Write-Host "Python : $python" -ForegroundColor DarkGray
Write-Host "Script : $frontend"  -ForegroundColor DarkGray

Set-Location $projectRoot
& $python $frontend
