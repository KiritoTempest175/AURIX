# LUNA Core Engine Build Script (PowerShell)
Write-Host "[*] Building LUNA Rust Core Engine in release mode..." -ForegroundColor Cyan

# Resolve cargo from PATH or well-known install locations
$cmd = Get-Command cargo -ErrorAction SilentlyContinue
$cargoCmd = if ($cmd) { $cmd.Source } else { $null }
if (-not $cargoCmd) {
    $candidates = @(
        "$env:USERPROFILE\.cargo\bin\cargo.exe",
        "C:\Users\msaaa\.cargo\bin\cargo.exe",
        "C:\Users\Zain\.cargo\bin\cargo.exe"
    )
    foreach ($c in $candidates) {
        if (Test-Path $c) { $cargoCmd = $c; break }
    }
}
if (-not $cargoCmd) {
    Write-Host "[ERROR] cargo not found. Install Rust from https://rustup.rs/" -ForegroundColor Red
    exit 1
}
Write-Host "Using cargo: $cargoCmd" -ForegroundColor DarkGray

& $cargoCmd build --manifest-path core_engine/Cargo.toml --release
if ($LASTEXITCODE -eq 0) {
    if (Test-Path "target/release/core_engine.dll") {
        Copy-Item "target/release/core_engine.dll" -Destination "core_engine.pyd" -Force
        Copy-Item "target/release/core_engine.dll" -Destination "luna_core.pyd" -Force
        Copy-Item "target/release/core_engine.dll" -Destination "core_engine/core_engine.pyd" -Force
        Write-Host "[SUCCESS] Successfully built and installed core_engine.pyd and luna_core.pyd!" -ForegroundColor Green
    }
} else {
    Write-Host "[ERROR] Failed to compile core_engine." -ForegroundColor Red
}
