# LUNA Unified Test Suite Runner (PowerShell)
Write-Host "🧪 Running Python and Rust Test Suites for LUNA..." -ForegroundColor Cyan

Write-Host "`n--- [1/2] Running Python Subsystems Unit & Integration Tests ---" -ForegroundColor Yellow
python tests/run_all_tests.py

Write-Host "`n--- [2/2] Running Rust Workspace Tests ---" -ForegroundColor Yellow
cargo test --workspace

Write-Host "`n✅ All LUNA test suites completed!" -ForegroundColor Green
