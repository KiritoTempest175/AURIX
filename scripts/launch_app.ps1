param([string]$target)
if (-not $target) { exit 1 }
$clean = $target.Trim()

# Common app alias resolution
$aliases = @{
    "vscode" = "visual studio code"
    "vs code" = "visual studio code"
    "code" = "visual studio code"
    "visual studio" = "visual studio 2022"
    "vs" = "visual studio 2022"
    "word" = "word 2016"
    "excel" = "excel 2016"
    "ppt" = "powerpoint 2016"
    "powerpoint" = "powerpoint 2016"
    "chrome" = "google chrome"
    "opera" = "opera gx browser"
    "discord" = "discord"
    "steam" = "steam"
    "spotify" = "spotify"
    "epic" = "epic games launcher"
    "epic games" = "epic games launcher"
}
$lookup = $clean.ToLower()
if ($aliases.ContainsKey($lookup)) {
    $clean = $aliases[$lookup]
}

# 1. Direct URLs
if ($clean -match '^(https?://|www\.)') {
    Start-Process $clean
    Write-Output "Opened URL $clean"
    exit 0
}

# 2. Search Start Menu shortcuts
$dirs = @(
    "$env:ProgramData\Microsoft\Windows\Start Menu\Programs",
    "$env:APPDATA\Microsoft\Windows\Start Menu\Programs"
)
$words = $clean.ToLower() -split '\s+' | Where-Object { $_ }

$shortcuts = Get-ChildItem -Path $dirs -Filter "*.lnk" -Recurse -ErrorAction SilentlyContinue
foreach ($sc in $shortcuts) {
    $stem = $sc.BaseName.ToLower()
    $allMatch = $true
    foreach ($w in $words) {
        if ($stem -notmatch [regex]::Escape($w)) {
            $allMatch = $false
            break
        }
    }
    if ($allMatch) {
        Start-Process -FilePath $sc.FullName
        Write-Output "Launched $($sc.BaseName)"
        exit 0
    }
}

# 3. Search Windows Universal Apps via Get-StartApps
try {
    $apps = Get-StartApps -ErrorAction SilentlyContinue
    foreach ($app in $apps) {
        $n = $app.Name.ToLower()
        $allMatch = $true
        foreach ($w in $words) {
            if ($n -notmatch [regex]::Escape($w)) {
                $allMatch = $false
                break
            }
        }
        if ($allMatch) {
            Start-Process -FilePath "shell:AppsFolder\$($app.AppID)"
            Write-Output "Launched $($app.Name)"
            exit 0
        }
    }
} catch {}

# 4. Common Windows Built-ins
$builtins = @{
    "notepad" = "notepad.exe"
    "calc" = "calc.exe"
    "calculator" = "calc.exe"
    "explorer" = "explorer.exe"
    "files" = "explorer.exe"
    "paint" = "mspaint.exe"
    "taskmgr" = "taskmgr.exe"
    "task manager" = "taskmgr.exe"
    "terminal" = "wt.exe"
    "cmd" = "cmd.exe"
    "powershell" = "powershell.exe"
    "settings" = "ms-settings:"
}

if ($builtins.ContainsKey($clean.ToLower())) {
    Start-Process $builtins[$clean.ToLower()]
    Write-Output "Launched $($builtins[$clean.ToLower()])"
    exit 0
}

# 5. Direct Process Fallback
try {
    Start-Process $clean -ErrorAction Stop
    Write-Output "Launched $clean"
    exit 0
} catch {
    Write-Output "NOT_FOUND"
    exit 1
}
