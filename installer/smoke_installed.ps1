#Requires -Version 7.0
# CI runtime-isolation smoke. This is not a substitute for a clean-VM test.
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$installer = Get-ChildItem "$root/target/release/bundle/nsis/*.exe" | Select-Object -First 1
if ($null -eq $installer) { throw 'NSIS installer missing' }
$installDir = Join-Path $env:TEMP ('aurix-installed-' + [guid]::NewGuid().ToString('N'))
$dataDir = Join-Path $env:TEMP ('aurix-smoke-data-' + [guid]::NewGuid().ToString('N'))
$originalPath = $env:PATH
$originalData = $env:AURIX_DATA_DIR
$originalRoot = $env:AURIX_ROOT
$app = $null
try {
    $setup = Start-Process $installer.FullName -ArgumentList @('/S', "/D=$installDir") -PassThru -Wait
    if ($setup.ExitCode -ne 0) { throw "Installer failed: $($setup.ExitCode)" }
    $exe = Get-ChildItem $installDir -Filter '*.exe' | Where-Object { $_.Name -ieq 'aurix.exe' } | Select-Object -First 1
    if ($null -eq $exe) { throw 'Installed AURIX.exe missing' }
    if (-not (Test-Path "$installDir/aurix-worker.exe")) { throw 'Installed worker missing' }
    $env:PATH = "$env:SystemRoot\System32;$env:SystemRoot;$env:SystemRoot\System32\WindowsPowerShell\v1.0"
    $env:AURIX_DATA_DIR = $dataDir
    $env:AURIX_ROOT = $null
    foreach ($tool in @('python','node','rustc','cargo')) {
        if (Get-Command $tool -ErrorAction SilentlyContinue) { throw "$tool is unexpectedly reachable" }
    }
    # Launch outside the checkout; release code must use the installed worker.
    $app = Start-Process $exe.FullName -WorkingDirectory $env:TEMP -PassThru
    $deadline = (Get-Date).AddSeconds(90)
    $ready = $false
    do {
        Start-Sleep -Milliseconds 500
        if ($app.HasExited) { throw "Installed app exited: $($app.ExitCode)" }
        $log = Join-Path $dataDir 'logs/worker.log'
        if ((Test-Path $log) -and (Get-Content $log -Raw) -match 'Private bridge running') {
            $ready = $true
            break
        }
    } while ((Get-Date) -lt $deadline)
    if (-not $ready) { throw 'Installed worker never became ready' }
    if (-not (Test-Path (Join-Path $dataDir 'config.toml'))) { throw 'First-run configuration missing' }
    @{
        installed_app = $exe.Name
        runtime_path_isolated = $true
        worker_started = $ready
        clean_vm_verified = $false
        microphone_verified = $false
        model_inference_verified = $false
    } | ConvertTo-Json | Set-Content "$root/installer-smoke.json"
} finally {
    if ($null -ne $app -and -not $app.HasExited) {
        & "$env:SystemRoot/System32/taskkill.exe" /PID $app.Id /T /F | Out-Null
    }
    $env:PATH = $originalPath
    $env:AURIX_DATA_DIR = $originalData
    $env:AURIX_ROOT = $originalRoot
    # Test directories are isolated; preserve evidence as CI artifacts.
}
