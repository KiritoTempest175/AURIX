# LUNA Core Engine Build Script (PowerShell)
Write-Host "🔨 Building LUNA Rust Core Engine in release mode..." -ForegroundColor Cyan

cargo build --manifest-path core_engine/Cargo.toml --release
if ($LASTEXITCODE -eq 0) {
    if (Test-Path "target/release/core_engine.dll") {
        Copy-Item "target/release/core_engine.dll" -Destination "core_engine.pyd" -Force
        Copy-Item "target/release/core_engine.dll" -Destination "luna_core.pyd" -Force
        Write-Host "✅ Successfully built and installed core_engine.pyd and luna_core.pyd!" -ForegroundColor Green
    }
} else {
    Write-Host "❌ Failed to compile core_engine." -ForegroundColor Red
}
