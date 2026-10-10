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
    & $python -m pip install --require-hashes -r (Join-Path $PSScriptRoot 'requirements-desktop.lock')
    if ($LASTEXITCODE -ne 0) { throw 'Locked runtime dependencies could not be installed' }
    & $python -m pip install --no-deps -e "${root}"
    if ($LASTEXITCODE -ne 0) { throw 'Project install failed' }
    & $python -m pip install 'pyinstaller>=6,<7'
    if ($LASTEXITCODE -ne 0) { throw 'Worker dependencies could not be installed' }

    $modelConfig = Join-Path $root 'config.toml'
    $persona = Join-Path $root 'config/LUNA.md'
    if (-not (Test-Path $modelConfig) -or -not (Test-Path $persona)) {
        throw 'Bundled default configuration is missing'
    }
    $arguments = @(
        '-m','PyInstaller','--clean','--noconfirm','--onefile','--noconsole',
        '--collect-all','llama_cpp',
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

    $source = Join-Path $buildPath 'dist/aurix-worker.exe'
    if (-not (Test-Path $source)) { throw 'PyInstaller output is missing' }

    # Real frozen worker startup/authenticated API smoke check.
# Checks the actual frozen EXE before packaging it. A successful Rust/React
# compilation alone does not prove that the Python sidecar can start.
$token = '0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef'
$oldToken = $env:AURIX_BRIDGE_TOKEN
$env:AURIX_BRIDGE_TOKEN = $token
$proc = $null
try {
    $proc = Start-Process -FilePath $source -WorkingDirectory $root -WindowStyle Hidden -PassThru
    $ready = $false
    $deadline = (Get-Date).AddSeconds(75)
    $headers = @{ Authorization = "Bearer $token" }
    do {
        Start-Sleep -Milliseconds 750
        if ($proc.HasExited) { throw "Packaged worker exited early with code $($proc.ExitCode)" }
        try {
            $health = Invoke-RestMethod -Uri 'http://127.0.0.1:9721/health' -Headers $headers -TimeoutSec 4
            if ($health.status -eq 'ok') {
                $settings = Invoke-RestMethod -Uri 'http://127.0.0.1:9721/settings' -Headers $headers -TimeoutSec 4
                $models = Invoke-RestMethod -Uri 'http://127.0.0.1:9721/models' -Headers $headers -TimeoutSec 8
                $account = Invoke-RestMethod -Uri 'http://127.0.0.1:9721/email/configure' -Headers $headers -TimeoutSec 8
                $wakeState = Invoke-RestMethod -Uri 'http://127.0.0.1:9721/voice/wake' -Headers $headers -TimeoutSec 8
                if ($null -eq $settings.offline -or $null -eq $models.recommendations -or
                    $null -eq $account.configured -or $null -eq $wakeState.enabled) {
                    throw 'Worker API is incomplete'
                }
                # Wake phrase tests dispatch initialization without needing a model download.
                $wake = Invoke-RestMethod -Uri 'http://127.0.0.1:9721/dispatch' -Method Post -Headers $headers -ContentType 'application/json' -Body '{"text":"hey luna"}' -TimeoutSec 15
                if ($wake.reply -notlike '*online*') { throw 'Packaged dispatcher failed its wake-phrase smoke test' }
                $ready = $true
                break
            }
        } catch {
            # PyInstaller onefile may still be extracting, retry until deadline.
        }
    } while ((Get-Date) -lt $deadline)
    if (-not $ready) { throw 'Packaged worker did not become ready within 75 seconds' }
    Write-Host 'Frozen worker smoke test passed: /health /settings /models'
} catch {
    $logPath = Join-Path $env:LOCALAPPDATA 'AURIX/logs/worker.log'
    if (Test-Path $logPath) {
        Get-Content $logPath -Tail 60 | ForEach-Object { Write-Host $_ }
    }
    throw
} finally {
    if ($null -ne $proc -and -not $proc.HasExited) {
        Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
    }
    $env:AURIX_BRIDGE_TOKEN = $oldToken
}

    $target = ((& rustc -vV) | Where-Object { $_ -match '^host: ' }) -replace '^host: ', ''
    if (-not $target) { throw 'Could not detect Rust build target' }
    New-Item -ItemType Directory -Force $binaryDir | Out-Null
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
        npm ci
        if ($LASTEXITCODE -ne 0) { throw 'npm dependency installation failed' }
        npm run tauri build
        if ($LASTEXITCODE -ne 0) { throw 'Tauri installer build failed' }
    } finally {
        Pop-Location
    }
    Write-Host 'Output: target/release/bundle (Cargo workspace target directory)'
    Write-Warning 'This is an UNSIGNED preview. Test on a clean Windows VM before distribution.'
} finally {
    [System.IO.File]::WriteAllText($configFile, $originalConfig)
}
