#Requires -Version 7.0
# Build an unsigned Windows preview with a packaged Python sidecar.
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$venv = Join-Path $root '.build/venv'
$frontend = Join-Path $root 'frontend'
$tauri = Join-Path $frontend 'src-tauri'
$configFile = Join-Path $tauri 'tauri.conf.json'
$originalConfig = [System.IO.File]::ReadAllText($configFile)
$binaryDir = Join-Path $tauri 'binaries'
$buildPath = Join-Path $root '.build'

try {
    New-Item -ItemType Directory -Force $buildPath | Out-Null
    py -3.11 -m venv $venv
    $python = Join-Path $venv 'Scripts/python.exe'
    & $python -m pip install --upgrade pip setuptools wheel
    if ($LASTEXITCODE -ne 0) { throw 'pip bootstrap failed' }
    & $python -m pip install -e $root 'pyinstaller>=6,<7'
    if ($LASTEXITCODE -ne 0) { throw 'Worker dependencies could not be installed' }

    $modelConfig = Join-Path $root 'config.toml'
    $persona = Join-Path $root 'config/LUNA.md'
    if (-not (Test-Path $modelConfig) -or -not (Test-Path $persona)) {
        throw 'Bundled default configuration is missing'
    }
    $arguments = @(
        '-m','PyInstaller','--clean','--noconfirm','--onefile','--noconsole',
        '--name','aurix-worker','--paths',$root,
        '--distpath',(Join-Path $buildPath 'dist'),
        '--workpath',(Join-Path $buildPath 'pyinstaller'),
        '--specpath',(Join-Path $buildPath 'spec'),
        '--add-data',"$modelConfig;.",
        '--add-data',"$persona;config",
        (Join-Path $frontend 'bridge_server.py')
    )
    & $python @arguments
    if ($LASTEXITCODE -ne 0) { throw 'PyInstaller sidecar build failed' }

    $target = ((& rustc -vV) | Where-Object { $_ -match '^host: ' }) -replace '^host: ', ''
    if (-not $target) { throw 'Could not detect Rust build target' }
    New-Item -ItemType Directory -Force $binaryDir | Out-Null
    $source = Join-Path $buildPath 'dist/aurix-worker.exe'
    $bundled = Join-Path $binaryDir "aurix-worker-$target.exe"
    Copy-Item -Force $source $bundled

    # Tauri's externalBin is transient, so normal cargo check works without
    # a pre-built binary. Configuration is restored even if packaging fails.
    $configuration = Get-Content $configFile -Raw | ConvertFrom-Json
    $configuration.bundle | Add-Member -NotePropertyName externalBin -NotePropertyValue @('binaries/aurix-worker') -Force
    $configuration | ConvertTo-Json -Depth 40 | Set-Content -Encoding utf8 $configFile

    Push-Location $frontend
    try {
        npm install --global npm@11.6.0
        if ($LASTEXITCODE -ne 0) { throw 'Required npm toolchain installation failed' }
        npm install
        if ($LASTEXITCODE -ne 0) { throw 'npm dependency installation failed' }
        npm run tauri build
        if ($LASTEXITCODE -ne 0) { throw 'Tauri installer build failed' }
    } finally {
        Pop-Location
    }
    Write-Host 'Output: frontend/src-tauri/target/release/bundle'
    Write-Warning 'This is an UNSIGNED preview. Test on a clean Windows VM before distribution.'
} finally {
    [System.IO.File]::WriteAllText($configFile, $originalConfig)
}
