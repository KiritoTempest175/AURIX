#Requires -Version 7.0
# Test a real NSIS installation without developer executables on PATH.
# GitHub-hosted Windows is not a fresh Windows VM.
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$installer = Get-ChildItem (Join-Path $root 'target/release/bundle/nsis') -Filter '*.exe' |
    Select-Object -First 1
if ($null -eq $installer) { throw 'Windows NSIS installer missing' }
$installDir = Join-Path $env:TEMP ('aurix-test-' + [guid]::NewGuid().ToString('N'))
$dataDir = Join-Path $env:TEMP ('aurix-data-' + [guid]::NewGuid().ToString('N'))
$oldPath = $env:PATH
$oldData = $env:AURIX_DATA_DIR
$oldRoot = $env:AURIX_ROOT
$app = $null
try {
    $installed = Start-Process $installer.FullName -ArgumentList @('/S', "/D=$installDir") -PassThru -Wait
    if ($installed.ExitCode -ne 0) { throw "Installer exited with $($installed.ExitCode)" }
    $exe = Join-Path $installDir 'AURIX.exe'
    $worker = Join-Path $installDir 'aurix-worker.exe'
    if (-not (Test-Path $exe)) { throw 'Installed AURIX.exe missing' }
    if (-not (Test-Path $worker)) { throw 'Installed Python sidecar missing' }
    $env:PATH = "$env:SystemRoot\System32;$env:SystemRoot;$env:SystemRoot\System32\WindowsPowerShell\v1.0"
    $env:AURIX_DATA_DIR = $dataDir
    $env:AURIX_ROOT = $null
    foreach ($tool in @('python', 'node', 'rustc', 'cargo')) {
        if (Get-Command $tool -ErrorAction SilentlyContinue) { throw "Developer executable is reachable: $tool" }
    }
    $app = Start-Process $exe -WorkingDirectory $env:TEMP -PassThru
    $ready = $false
    $deadline = (Get-Date).AddSeconds(90)
    do {
        Start-Sleep -Milliseconds 650
        if ($app.HasExited) { throw "AURIX executable exited early: $($app.ExitCode)" }
        $log = Join-Path $dataDir 'logs/worker.log'
        if ((Test-Path $log) -and (Get-Content $log -Raw) -match 'Private bridge running') {
            $ready = $true
            break
        }
    } while ((Get-Date) -lt $deadline)
    if (-not $ready) { throw 'Installed sidecar did not start within 90 seconds' }
    if (-not (Test-Path (Join-Path $dataDir 'config.toml'))) {
        throw 'First-run application configuration was not created'
    }
    @{
        actual_nsis_install = $true
        development_runtimes_not_on_path = $true
        packaged_worker_started = $true
        clean_windows_vm = $false
        real_microphone_test = $false
        real_ollama_inference = $false
        independent_security_audit = $false
    } | ConvertTo-Json | Set-Content (Join-Path $root 'installer-smoke.json')
    Write-Host 'Installed AURIX launched with no developer runtimes on PATH.'
} finally {
    if ($null -ne $app -and -not $app.HasExited) {
        & "$env:SystemRoot\System32\taskkill.exe" /PID $app.Id /T /F | Out-Null
    }
    $env:PATH = $oldPath
    $env:AURIX_DATA_DIR = $oldData
    $env:AURIX_ROOT = $oldRoot
}
