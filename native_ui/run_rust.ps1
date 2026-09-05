# Resolve cargo from PATH or well-known install locations
$cargoCmd = (Get-Command cargo -ErrorAction SilentlyContinue)?.Source
if (-not $cargoCmd) {
    # Common locations: USERPROFILE\.cargo\bin or well-known rustup paths
    $candidates = @(
        "$env:USERPROFILE\.cargo\bin\cargo.exe",
        "C:\Users\msaaa\.cargo\bin\cargo.exe",
        "C:\Users\Zain\.cargo\bin\cargo.exe"
    )
    foreach ($c in $candidates) {
        if (Test-Path $c) {
            $cargoCmd = $c
            break
        }
    }
}

if (-not $cargoCmd) {
    Write-Error "cargo not found. Install Rust from https://rustup.rs/ and re-open your terminal."
    exit 1
}

Write-Host "Using cargo: $cargoCmd" -ForegroundColor DarkGray

# Add the containing bin dir to PATH for this session (handles rustc, etc.)
$cargoBin = Split-Path $cargoCmd -Parent
if ($env:PATH -notlike "*$cargoBin*") {
    $env:PATH = "$cargoBin;$env:PATH"
}

& $cargoCmd @args
